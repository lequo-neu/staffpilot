"""Alerts a staffing manager should see before acting on a plan.

They come from the data and the simulated plan, not from a monitoring server: each
rule is a plain check with a threshold, so the reason for every alert is visible.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from staffpilot.planner import RECOMMENDED_POLICY, Planner


log = logging.getLogger(__name__)
LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    level: str  # critical, warning or info
    topic: str
    message: str
    countries: tuple[str, ...] = ()
    page: str = ""  # the app page where the manager acts on it, if any


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _money(value: float) -> str:
    return f"${value / 1e6:,.1f}M" if abs(value) >= 1e6 else f"${value / 1e3:,.0f}k"


def _names(countries: list[str], limit: int = 6) -> str:
    shown = ", ".join(countries[:limit])
    return shown + (f" and {len(countries) - limit} more" if len(countries) > limit else "")


def plan_alerts(planner: Planner, policy: str = RECOMMENDED_POLICY) -> list[Alert]:
    s = planner.settings
    alerts: list[Alert] = []
    expected = s.planning.expected_year
    if expected and planner.year != expected:
        alerts.append(
            Alert(
                "critical",
                "year",
                f"This file plans {planner.year}, but the brief asks for {expected}. Load the official course file before "
                "using these numbers.",
            )
        )
    if planner.dataset.repaired_dates:
        alerts.append(
            Alert(
                "info",
                "data",
                f"{planner.dataset.repaired_dates} sign ups had impossible dates (such as 29 February in a normal year) and "
                "were moved to the end of their month.",
            )
        )

    kpis = planner.run(policy).kpi_table().set_index("country")
    value_only = planner.run("optimized").kpi_table().set_index("country")

    low_service = kpis.index[kpis["service_rate"] < 0.98].tolist()
    if low_service:
        alerts.append(
            Alert(
                "critical",
                "service",
                f"Fewer than 98% of eligible advertisers are served in {_names(low_service)}.",
                tuple(low_service),
            )
        )
    overflow = kpis.index[kpis["max_overflow"] > 0].tolist()
    if overflow:
        alerts.append(
            Alert(
                "critical",
                "capacity",
                f"The ten advertiser limit is broken in {_names(overflow)}.",
                tuple(overflow),
            )
        )
    bundle = planner.run(policy)
    for country in kpis.index[kpis["p90_wait_days"] > 14]:
        sim = bundle.outcomes[country].simulation
        in_year = sim.wait_months <= 12
        waits, months = sim.waits[in_year], sim.wait_months[in_year]
        late = waits > 14
        busy = sorted({int(m) for m in months[late]})
        named = (
            " and ".join(MONTHS[m - 1] for m in busy[-2:])
            if len(busy) <= 2
            else f"{MONTHS[busy[0] - 1]} to {MONTHS[busy[-1] - 1]}"
        )
        alerts.append(
            Alert(
                "warning",
                "waiting",
                f"In {country}, {int(late.sum()):,} of {len(waits):,} advertisers wait more than two weeks: those who "
                f"sign up in {named}, when {int(bundle.outcomes[country].plan.active[busy[-1] - 1]):,} agents meet "
                f"the year's peak. The longest wait is {int(waits.max())} days, within the 60 day limit.",
                (country,),
                "Plan",
            )
        )
    for country in kpis.index[kpis["end_agents"] > kpis["start_agents"]]:
        row = kpis.loc[country]
        peak = int(bundle.outcomes[country].plan.active[:12].max())
        alerts.append(
            Alert(
                "warning",
                "hiring",
                f"{country} has {row['start_agents']:,.0f} agents and the plan needs up to {peak:,} by "
                f"{MONTHS[int(bundle.outcomes[country].plan.active[:12].argmax())]}: hire {row['hires']:,.0f}. "
                "Hires decided in January start in February, so approve them first.",
                (country,),
                "Plan",
            )
        )
    deep_cuts = kpis[kpis["notices"] > 0.5 * kpis["start_agents"]]
    if len(deep_cuts):
        biggest = deep_cuts["notices"].idxmax()
        alerts.append(
            Alert(
                "warning",
                "people",
                f"In {len(deep_cuts)} countries more than half of the January team gets notice: "
                f"{deep_cuts['notices'].sum():,.0f} of {deep_cuts['start_agents'].sum():,.0f} agents, for example "
                f"{deep_cuts.loc[biggest, 'notices']:,.0f} of {deep_cuts.loc[biggest, 'start_agents']:,.0f} in "
                f"{biggest}. Check local notice rules before notices are sent.",
                tuple(deep_cuts.index),
            )
        )
    # Salary only: the one time firing cost says nothing about whether ongoing support pays.
    for country in value_only.index[value_only["uplift_value"] < value_only["salary_cost"]]:
        row = kpis.loc[country]
        alerts.append(
            Alert(
                "warning",
                "value",
                f"In {country} support brings {_money(row['uplift_value'])} of uplift, but its agents cost "
                f"{_money(row['salary_cost'])} in salary. The service goal keeps it; Profit only would stop it. "
                "Choose the goal on Plan.",
                (country,),
                "Plan",
            )
        )
    alerts.append(
        Alert(
            "info",
            "assumption",
            "The plan assumes uplift applies to the projected annual budget. If it only counts during the 60 days of "
            "support, every policy loses money; confirm this with Google before giving notice.",
        )
    )
    alerts.sort(key=lambda a: LEVEL_ORDER[a.level])
    for alert in alerts:
        if alert.level != "info":
            log.warning("%s alert (%s): %s", alert.level, alert.topic, alert.message)
    return alerts
