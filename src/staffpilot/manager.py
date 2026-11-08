"""Manager tools that need no language model.

Four views for a manager who wants to choose rather than type:

* the staffing policies side by side, with the trade offs in plain words,
* how the plan holds up when sign ups come in 30 percent below or above the forecast,
* a step by step scenario: countries, months, a change in sign ups and a policy,
* the country inputs and the assumptions behind every plan, read only.

Every number comes from the planner (`Planner.compare_policies`, `Planner.sensitivity`,
`Planner.scenario`) or straight from the dataset. This module only picks what to show
and says it in a manager's words; it adds no calculation of its own.
"""

from __future__ import annotations

import pandas as pd

from staffpilot import cache, charts
from staffpilot.eda import profile
from staffpilot.monthly import MONTH_NAMES
from staffpilot.planner import POLICIES, RECOMMENDED_POLICY, Planner
from staffpilot.scenarios import DemandChange, ScenarioParams


# Policy comparison


def policy_name(policy: str) -> str:
    return charts.POLICY_NAMES.get(policy, policy)


def policy_comparison(p: Planner, countries: list[str] | None = None) -> pd.DataFrame:
    """Totals of each staffing policy for the chosen countries (all when empty), from the planner."""
    frame = p.compare_policies(countries or None, POLICIES)
    frame["name"] = frame["policy"].map(policy_name)
    return frame


def policy_table(frame: pd.DataFrame) -> pd.DataFrame:
    """The comparison in a manager's words, best net value first."""
    frame = frame.sort_values("net_value", ascending=False)
    shown = pd.DataFrame(
        {
            "Policy": frame["name"],
            "Net value": frame["net_value"].map(charts.money),
            "vs January team": frame.get("net_value_vs_hold", pd.Series(0.0, frame.index)).map(
                _signed_money
            ),
            "Cost": frame["total_cost"].map(charts.money),
            "Avg agents": frame["avg_active"].map(_count),
            "Hires": frame["hires"].map(_count),
            "Notices": frame["notices"].map(_count),
            "Served": frame["service_rate"].map(lambda v: f"{v:.1%}"),
            "Avg wait (days)": frame["mean_wait_days"].map(lambda v: f"{v:.1f}"),
        }
    )
    return shown.reset_index(drop=True)


def policy_takeaways(frame: pd.DataFrame) -> list[str]:
    """The trade offs that matter to a manager, each worked out from the comparison."""
    rows = frame.set_index("policy")
    best = frame.loc[frame["net_value"].idxmax()]
    lines = []
    if "hold" in rows.index and best["policy"] != "hold":
        lines.append(
            f"**Most value:** {best['name']} earns {charts.money(best['net_value'])}, "
            f"{charts.money(best['net_value'] - rows.loc['hold', 'net_value'])} more than keeping the January team."
        )
    else:
        lines.append(f"**Most value:** {best['name']} earns {charts.money(best['net_value'])}.")
    if RECOMMENDED_POLICY not in rows.index:
        return lines
    rec = rows.loc[RECOMMENDED_POLICY]
    if "optimized" in rows.index:
        opt = rows.loc["optimized"]
        price = opt["net_value"] - rec["net_value"]
        if abs(price) < 0.0005 * max(abs(opt["net_value"]), 1):
            cost = "costs almost nothing"
        else:
            cost = f"{'costs' if price > 0 else 'adds'} {charts.money(abs(price))} of net value"
        served, opt_served = f"{rec['service_rate']:.1%}", f"{opt['service_rate']:.1%}"
        if served == opt_served:
            service = f"both serve {served}, so here the promise is a guarantee rather than a change"
        else:
            service = f"it serves {served} instead of {opt_served}. This is why it is recommended"
        lines.append(
            f"**The service promise:** serving at least 98% of eligible advertisers {cost} against profit only; "
            f"{service}."
        )
    if "hold" in rows.index:
        hold = rows.loc["hold"]
        ratio = hold["avg_active"] / rec["avg_active"] if rec["avg_active"] else 0.0
        lines.append(
            f"**Keeping the January team** pays for {hold['avg_active']:,.0f} agents on average"
            + (f", {ratio:.1f} times the recommended plan" if ratio >= 1.05 else "")
            + f". It gives no notices, but earns {_gap(hold['net_value'] - rec['net_value'])}."
        )
    if "reactive" in rows.index:
        react = rows.loc["reactive"]
        lines.append(
            f"**Following last month's demand** makes {react['hires']:,.0f} hires and {react['notices']:,.0f} "
            f"notices in the year, against {rec['hires']:,.0f} and {rec['notices']:,.0f} for the recommended plan. "
            f"It earns {_gap(react['net_value'] - rec['net_value'])}, and the churn is hard on teams."
        )
    if "peak_cover" in rows.index:
        peak = rows.loc["peak_cover"]
        extra = peak["avg_active"] - rec["avg_active"]
        lines.append(
            f"**One cut to the yearly peak** is the simplest to run, but carries {abs(extra):,.0f} "
            f"{'more' if extra >= 0 else 'fewer'} agents on average than the recommended plan "
            f"and earns {_gap(peak['net_value'] - rec['net_value'])}."
        )
    return lines


def _count(value: float) -> str:
    return f"{value:,.0f}"


def _signed_money(value: float) -> str:
    if abs(value) < 0.5:
        return "same"
    return ("+" if value > 0 else "-") + charts.money(abs(value))


def _years(years: list[int]) -> str:
    names = [str(y) for y in years]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _gap(diff: float) -> str:
    """How much more or less a policy earns than the recommended plan."""
    if abs(diff) < 0.5:
        return "the same as the recommended plan"
    return f"{charts.money(abs(diff))} {'more' if diff > 0 else 'less'} than the recommended plan"


# Sensitivity to sign up volume

SENSITIVITY_SCALES = (0.7, 1.0, 1.3)


def sensitivity(
    p: Planner, countries: list[str] | None = None, policy: str = RECOMMENDED_POLICY
) -> pd.DataFrame:
    """`Planner.sensitivity` at 30 percent fewer, as forecast and 30 percent more sign ups.

    Rebuilding the plan for every volume solves each country again, about a minute for
    all countries, so the result is kept in the planner's disk cache.
    """
    countries = countries or None
    key = cache.digest(
        "sensitivity",
        policy,
        ",".join(countries or []),
        SENSITIVITY_SCALES,
        p.dataset.fingerprint(),
        p.settings.model_dump_json(),
        cache.code_version(),
    )
    return cache.cached(
        "sensitivity", key, lambda: p.sensitivity(SENSITIVITY_SCALES, countries, policy)
    )


def volume_label(scale: float) -> str:
    change = round((scale - 1) * 100)
    if change == 0:
        return "As forecast"
    return f"{abs(change)}% {'more' if change > 0 else 'fewer'} sign ups"


def sensitivity_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per volume: the approved plan kept as it is, against a plan rebuilt for that volume."""
    kept = frame[frame["plan"] == "current plan"].set_index("demand_scale")
    rebuilt = frame[frame["plan"] == "replanned"].set_index("demand_scale")
    rows = []
    for scale in kept.index:
        k, r = kept.loc[scale], rebuilt.loc[scale]
        rows.append(
            {
                "Sign ups": volume_label(scale),
                "Kept: net value": charts.money(k["net_value"]),
                "Rebuilt: net value": charts.money(r["net_value"]),
                "Gain from rebuilding": _signed_money(r["net_value"] - k["net_value"]),
                "Kept: served": f"{k['service_rate']:.1%}",
                "Rebuilt: served": f"{r['service_rate']:.1%}",
                "Kept: wait (days)": f"{k['mean_wait_days']:.1f}",
                "Rebuilt: agents": _count(r["avg_active"]),
            }
        )
    return pd.DataFrame(rows)


def sensitivity_takeaways(frame: pd.DataFrame) -> list[str]:
    """What a manager should take from the volume test, worked out from it."""
    kept = frame[frame["plan"] == "current plan"].set_index("demand_scale")
    rebuilt = frame[frame["plan"] == "replanned"].set_index("demand_scale")
    lines = []
    for scale in kept.index:
        if scale == 1.0:
            continue
        k, r = kept.loc[scale], rebuilt.loc[scale]
        gain = r["net_value"] - k["net_value"]
        wait = k["mean_wait_days"]
        waiting = f"wait {wait:.1f} days on average" if wait >= 0.05 else "barely wait"
        lines.append(
            f"**{volume_label(scale)}:** keeping the plan earns {charts.money(k['net_value'])}, serves "
            f"{k['service_rate']:.1%} and advertisers {waiting}. Rebuilding it with "
            f"{r['avg_active']:,.0f} agents on average serves {r['service_rate']:.1%} and "
            + (f"adds {charts.money(gain)}." if gain >= 0.5 else "changes little.")
        )
    low, high = min(kept.index), max(kept.index)
    if high > 1 and low < 1:
        service_loss = rebuilt.loc[high, "service_rate"] - kept.loc[high, "service_rate"]
        if service_loss > 0.005:
            lines.append(
                "**What it means:** fewer sign ups cost money (idle agents), more sign ups cost service "
                "(advertisers wait or are lost). Watch actual sign ups each month and plan again on the "
                "Monthly update page when they run above the forecast."
            )
        else:
            lines.append(
                "**What it means:** service holds across the range, so the risk is money, not service. "
                "Plan again on the Monthly update page when actual sign ups move away from the forecast."
            )
    return lines


# Step by step scenario

CUSTOM = "Choose months"
PERIODS = {
    "All year": [],
    "Q1 (January to March)": [1, 2, 3],
    "Q2 (April to June)": [4, 5, 6],
    "Q3 (July to September)": [7, 8, 9],
    "Q4 (October to December)": [10, 11, 12],
    CUSTOM: [],
}
REBUILD = "Rebuild the plan for the change"
KEEP = "Keep the current plan and see the impact"


class ScenarioChoiceError(ValueError):
    """A choice in the scenario builder that cannot be run, with a message for the manager."""


def chosen_months(period: str, months: list[str] | None = None) -> list[int]:
    """Calendar months (1 to 12) for a period; empty means all year."""
    if period not in PERIODS:
        raise ScenarioChoiceError(f"Pick a period from the list, not {period!r}.")
    if period != CUSTOM:
        return PERIODS[period]
    picked = sorted({MONTH_NAMES.index(m) + 1 for m in months or [] if m in MONTH_NAMES})
    if not picked:
        raise ScenarioChoiceError("Pick at least one month, or choose a period such as Q3.")
    return picked


def demand_change(
    countries: list[str] | None, period: str, months: list[str] | None, percent: float
) -> DemandChange:
    """One change to eligible sign ups, from the builder's controls."""
    percent = float(percent or 0)
    if not -90 <= percent <= 200:
        raise ScenarioChoiceError("A change in sign ups runs from 90% fewer to 200% more.")
    return DemandChange(
        countries=list(countries or []),
        months=chosen_months(period, months),
        multiplier=round(1 + percent / 100, 4),
    )


def build_params(
    first: DemandChange, second: DemandChange | None = None, rebuild: bool = True
) -> ScenarioParams:
    """The scenario the planner runs. One change uses its plain fields; two use `adjustments`."""
    changes = [c for c in (first, second) if c is not None and c.multiplier != 1.0]
    if not changes:
        raise ScenarioChoiceError("Set a change in sign ups first: the slider is at 0%.")
    if len(changes) == 1:
        (only,) = changes
        return ScenarioParams(
            countries=only.countries, months=only.months, demand_multiplier=only.multiplier, replan=rebuild
        )
    return ScenarioParams(adjustments=changes, replan=rebuild)


# Country inputs and assumptions


def country_inputs(p: Planner) -> pd.DataFrame:
    """One row per country: the dataset's inputs and the measures the Data page already computes."""
    report = profile(p.dataset, p.settings.rules.capacity_per_agent)
    by_country = report.countries.set_index("country")
    eligible = p.dataset.eligible()
    per_year = eligible.groupby([eligible["country"], eligible["signup_date"].dt.year]).size().unstack(
        fill_value=0
    )
    frame = pd.DataFrame(
        {
            "Country": by_country.index,
            "Salary": by_country["salary"].to_numpy(),
            "Threshold": by_country["threshold"].to_numpy(),
            "January agents": by_country["agents"].astype(int).to_numpy(),
        }
    )
    for year in per_year.columns:
        frame[f"Eligible {year}"] = per_year[year].reindex(by_country.index, fill_value=0).to_numpy()
    frame["Share eligible"] = by_country["eligible_rate"].to_numpy()
    frame["Median budget"] = by_country["median_eligible_budget"].to_numpy()
    frame["Peak need"] = by_country["peak_need"].round().astype(int).to_numpy()
    frame["Team vs need"] = by_country["staff_to_need"].to_numpy()
    return frame.sort_values("Country").reset_index(drop=True)


def country_summary(frame: pd.DataFrame) -> str:
    agents = int(frame["January agents"].sum())
    need = int(frame["Peak need"].sum())
    short = frame.loc[frame["Team vs need"] < 1, "Country"].tolist()
    text = (
        f"**{len(frame)} countries** start the year with **{agents:,} agents**, while the busiest 60 days of "
        f"eligible sign ups need about **{need:,}**."
    )
    if short:
        text += f" Short of that need on 1 January: **{', '.join(short)}** (in amber)."
    return text


def assumptions(p: Planner) -> pd.DataFrame:
    """The rules and assumptions every plan uses, read from the settings, with what each one changes."""
    rules, chosen = p.settings.rules, p.settings.assumptions
    boundary = "strictly greater than" if rules.eligibility == "greater" else "at least"
    rows = [
        (
            "Who gets support",
            f"Budget {boundary} the country threshold",
            "Only eligible advertisers count as demand. A lower threshold means more demand and more agents.",
        ),
        (
            "Advertisers per agent",
            f"At most {rules.capacity_per_agent} at a time",
            "Sets how many agents a month of sign ups needs. Every reported day respects it.",
        ),
        (
            "Support length",
            f"{rules.support_days} days per advertiser",
            "An agent's slot stays busy this long, so a peak keeps agents busy for two months.",
        ),
        (
            "Longest wait in the pool",
            f"{rules.max_wait_days} days",
            "Past this an advertiser is lost and brings no uplift, so too few agents costs value as well as speed.",
        ),
        (
            "Hiring lead time",
            f"{rules.ramp_months} month of ramp up, {'paid' if chosen.pay_during_ramp else 'unpaid'}",
            "A hire decided in one month works from the next, so the plan hires before a peak, not during it.",
        ),
        (
            "Cost of a notice",
            f"{rules.notice_months} month, {rules.fire_cost_share:.0%} of annual salary",
            "Cuts are not free; small dips in demand are cheaper to ride out than to cut for.",
        ),
        (
            "Value of support",
            f"{rules.expected_uplift:.1%} expected ad spend uplift",
            "The expected value of the brief's 0 to 25% spread. Higher uplift makes more agents worth paying for.",
        ),
        (
            "Uplift counted on",
            "Projected annual budget" if chosen.uplift_base == "annual_budget" else "The 60 day support window",
            (
                "Counting only the support window would cut the value of support several times over; "
                "the decision to cut the January team stays the same."
            ),
        ),
        (
            "Pool on 1 January",
            "Empty" if chosen.initial_pool == "empty" else "Late December sign ups still waiting",
            "Starting empty is the cautious choice; a carried over pool would need more agents in January.",
        ),
        (
            "Order of service",
            "First come, first served" if chosen.queue_policy == "fifo" else "Largest budgets first",
            (
                "Tested on the course data: largest budgets first earns about $1.0M less, serves fewer "
                "advertisers and makes small advertisers wait longer."
            ),
        ),
        (
            "Forecast",
            f"{p.forecast.method.replace('_', ' ')}, chosen by a backtest on the last year",
            (
                f"Plans {p.year} from sign ups in {_years(p.dataset.history_years)}. "
                "If real sign ups differ, the Monthly update page plans the rest of the year again."
            ),
        ),
    ]
    return pd.DataFrame(rows, columns=["Assumption", "Used in the plan", "Why it matters"])
