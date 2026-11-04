"""Evidence a manager can check: is the plan right, how is each number built, is it the best.

* `plan_checks` tests the plan against every rule of the brief and against the
  alternatives (simple rules, the solver's proof, the backtest), with the numbers.
* `value_breakdown` and `monthly_detail` rebuild net value from its inputs, so a
  manager can redo the arithmetic with a calculator or a spreadsheet.
* `compare_manual` scores a headcount the manager typed in with the same simulator,
  so any change to the plan shows what it costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from staffpilot import cache


if TYPE_CHECKING:
    from staffpilot.planner import CountryOutcome, Planner

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Check:
    title: str
    passed: bool | None  # None: information a manager should weigh, not a pass or a fail
    detail: str


def wait_penalty(planner: Planner, outcome: CountryOutcome) -> float:
    """The optimizer's price on waiting (assumption A9), measured on the simulated year."""
    weekly = planner.settings.planning.wait_penalty_per_week
    return weekly * float(outcome.simulation.monthly["uplift_wait_days"].iloc[:12].sum()) / 7


def margin(planner: Planner, policy: str, country: str | None = None, cut: float = 0.05) -> dict[str, float]:
    """What `cut` fewer agents from February would do, scored day by day with the same simulator."""
    rows = []
    for name, outcome in _outcomes(planner, policy, country).items():
        targets = outcome.plan.active[:12].copy()
        targets[1:] = np.floor(targets[1:] * (1 - cut))
        lean, _ = planner.score_plan(name, targets, policy)
        rows.append((outcome, lean))
    arrivals = sum(o.kpis["arrivals"] for o, _ in rows)

    def mean_wait(index: int) -> float:
        waits = np.concatenate(
            [pair[index].simulation.waits[pair[index].simulation.wait_months <= 12] for pair in rows]
        )
        return float(waits.mean()) if waits.size else 0.0

    return {
        "net_value": sum(o.kpis["net_value"] for o, _ in rows),
        "lean_net_value": sum(lean.kpis["net_value"] for _, lean in rows),
        "service_rate": sum(o.kpis["served"] for o, _ in rows) / arrivals if arrivals else 1.0,
        "lean_service_rate": sum(lean.kpis["served"] for _, lean in rows) / arrivals if arrivals else 1.0,
        "mean_wait_days": mean_wait(0),
        "lean_mean_wait_days": mean_wait(1),
        "lean_overflow": max(lean.kpis["max_overflow"] for _, lean in rows),
        "cut": cut,
    }


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e6:
        return f"{sign}${value / 1e6:,.1f}M"
    return f"{sign}${value / 1e3:,.0f}k" if value >= 1e3 else f"{sign}${value:,.0f}"


def _outcomes(planner: Planner, policy: str, country: str | None) -> dict[str, CountryOutcome]:
    bundle = planner.run(policy)
    return {country: bundle.outcomes[country]} if country else dict(bundle.outcomes)


def _net(planner: Planner, policy: str, country: str | None) -> float:
    return float(sum(o.kpis["net_value"] for o in _outcomes(planner, policy, country).values()))


def backtest_share(planner: Planner) -> float | None:
    """Share of the hindsight value reached by a plan built from the earlier history years only."""
    if len(planner.dataset.history_years) < 2:
        return None
    from staffpilot.backtest import run_backtest, summarize_backtest

    key = cache.digest(
        planner.dataset.fingerprint(), planner.settings.model_dump_json(), cache.code_version()
    )

    def compute() -> float:
        frame = summarize_backtest(run_backtest(planner.settings, planner.dataset)).set_index("plan")
        return float(frame.loc["optimized from forecast", "share_of_hindsight"])

    return cache.cached("backtest", key, compute)


def plan_checks(
    planner: Planner, policy: str, country: str | None = None, with_backtest: bool = True
) -> list[Check]:
    """The brief's rules and the evidence that the plan is the best one, each with its numbers."""
    from staffpilot.planner import POLICY_LABELS, service_goal

    rules = planner.settings.rules
    outcomes = _outcomes(planner, policy, country)
    where = country or f"all {len(outcomes)} countries"
    checks: list[Check] = []

    overflow = max(o.kpis["max_overflow"] for o in outcomes.values())
    busiest = max(float(o.simulation.monthly["utilization"].iloc[:12].max()) for o in outcomes.values())
    checks.append(
        Check(
            f"No agent holds more than {rules.capacity_per_agent} advertisers on any day",
            overflow <= 0,
            f"Checked day by day for {where}; the busiest month uses {busiest:.0%} of the slots.",
        )
    )

    waits = np.concatenate([o.simulation.waits[o.simulation.wait_months <= 12] for o in outcomes.values()])
    longest = float(waits.max()) if waits.size else 0.0
    dropped = sum(o.kpis["dropped"] for o in outcomes.values())
    checks.append(
        Check(
            f"Nobody is served after more than {rules.max_wait_days} days in the pool",
            longest <= rules.max_wait_days,
            f"The longest wait is {longest:.0f} days; {dropped:,.0f} advertisers left the pool unserved.",
        )
    )

    timing_ok = True
    for o in outcomes.values():
        plan = o.plan
        for t in range(1, plan.months):
            joined = plan.hires[t - rules.ramp_months] if t >= rules.ramp_months else 0
            left = plan.notices[t - rules.notice_months] if t >= rules.notice_months else 0
            if abs(plan.active[t] - (plan.active[t - 1] + joined - left)) > 1e-6:
                timing_ok = False
    checks.append(
        Check(
            f"Hires start after {rules.ramp_months} month of ramp up; notices end after {rules.notice_months} month",
            timing_ok,
            "Every month's headcount equals the month before, plus hires that finished ramp up, "
            "minus notices that ended.",
        )
    )

    costs_ok = True
    for o in outcomes.values():
        plan = o.plan
        salary = float((plan.payroll()[:12] * plan.salary / 12).sum())
        notice = float((plan.notices[:12] * plan.salary * rules.fire_cost_share).sum())
        costs_ok &= abs(salary - o.kpis["salary_cost"]) < 1 and abs(notice - o.kpis["fire_cost"]) < 1
    checks.append(
        Check(
            f"Costs follow the brief: salary while employed, {rules.fire_cost_share:.0%} of salary per notice",
            costs_ok,
            "Agents in ramp up and under notice are paid; recomputed from the plan, the totals match to the dollar.",
        )
    )

    floor, days = service_goal(policy)
    if floor:
        arrivals = sum(o.kpis["arrivals"] for o in outcomes.values())
        limit = days or rules.max_wait_days
        if days:
            on_time = float((waits <= limit).sum() / arrivals) if arrivals else 1.0
        else:
            # Within the 60 day window this is the service rate of the planning year's sign ups.
            on_time = sum(o.kpis["served"] for o in outcomes.values()) / arrivals if arrivals else 1.0
        checks.append(
            Check(
                f"Service goal: at least {floor:.0%} served within {limit} days",
                on_time >= floor - 0.005,
                f"{on_time:.1%} of eligible advertisers get an agent within {limit} days.",
            )
        )

    optimal = sum(o.plan.solver_status == "Optimal" for o in outcomes.values())
    repaired = sum(any(n == "repair round applied" for n in o.plan.notes) for o in outcomes.values())
    raised = (
        f"; the simulator check had to raise the headcount in {repaired} of them"
        if repaired
        else "; the simulator check found nothing to raise"
    )
    checks.append(
        Check(
            "The solver proved the plan optimal for the planning model",
            optimal == len(outcomes),
            f"CBC proved optimality for {optimal} of {len(outcomes)} countries{raised}.",
        )
    )

    lean = margin(planner, policy, country)
    gain = lean["lean_net_value"] - lean["net_value"]
    holds = lean["lean_overflow"] <= 0 and (floor is None or lean["lean_service_rate"] >= floor - 0.005)
    if gain > 0 and holds:
        detail = (
            f"With {lean['cut']:.0%} fewer agents from February every rule still holds and net value rises by "
            f"{_money(gain)} ({gain / abs(lean['net_value']):.1%}), but the average wait goes from "
            f"{lean['mean_wait_days']:.1f} to {lean['lean_mean_wait_days']:.1f} days. The model plans advertiser "
            "flows week by week and prefers early service (assumption A9), so it keeps this margin; "
            "score your own numbers in Try your own plan."
        )
    else:
        detail = (
            f"{lean['cut']:.0%} fewer agents from February would {'lose ' + _money(-gain) if gain <= 0 else 'break a rule'}"
            f"{'' if holds else ' (a rule or the service goal fails)'}, so the plan has no cheaper margin to give up."
        )
    checks.append(Check("How lean is it, by the exact daily rules?", None, detail))

    net = _net(planner, policy, country)
    rivals = {p: _net(planner, p, country) for p in ("hold", "reactive", "peak_cover")}
    best_rule = max(("reactive", "peak_cover"), key=lambda p: rivals[p])
    checks.append(
        Check(
            "It beats every simple staffing rule",
            net >= max(rivals.values()) - 1,
            f"{_money(net - rivals['hold'])} more than keeping the January team and "
            f"{_money(net - rivals[best_rule])} more than the best simple rule "
            f"({POLICY_LABELS[best_rule].lower()}).",
        )
    )

    if with_backtest and country is None:
        share = backtest_share(planner)
        if share is not None:
            years = planner.dataset.history_years
            checks.append(
                Check(
                    "It holds up on real sign ups it never saw",
                    share >= 0.95,
                    f"Planned from {years[0]} alone and scored on what really happened in {years[-1]}, "
                    f"it reaches {share:.1%} of the value of a plan made with hindsight.",
                )
            )
    return checks


def value_breakdown(planner: Planner, policy: str, country: str | None = None) -> dict[str, float]:
    """Net value rebuilt from its inputs: uplift minus salaries minus notice cost."""
    rules = planner.settings.rules
    outcomes = _outcomes(planner, policy, country)
    served = sum(o.kpis["served"] for o in outcomes.values())
    uplift = sum(o.kpis["uplift_value"] for o in outcomes.values())
    factor = 1.0 if planner.settings.assumptions.uplift_base == "annual_budget" else rules.support_days / 365
    rate = rules.expected_uplift * factor
    payroll = sum(float(o.plan.payroll()[:12].sum()) for o in outcomes.values())
    salary_cost = sum(o.kpis["salary_cost"] for o in outcomes.values())
    notices = sum(o.kpis["notices"] for o in outcomes.values())
    notice_cost = sum(o.kpis["fire_cost"] for o in outcomes.values())
    return {
        "served": served,
        "mean_budget": uplift / (served * rate) if served and rate else 0.0,
        "uplift_rate": rate,
        "uplift": uplift,
        "payroll_agent_months": payroll,
        "salary_per_agent_month": salary_cost / payroll if payroll else 0.0,
        "salary_cost": salary_cost,
        "notices": notices,
        "salary_per_notice": notice_cost / notices / rules.fire_cost_share if notices else 0.0,
        "fire_cost_share": rules.fire_cost_share,
        "notice_cost": notice_cost,
        "net_value": uplift - salary_cost - notice_cost,
    }


def monthly_detail(planner: Planner, policy: str, country: str | None = None) -> pd.DataFrame:
    """Each month: sign ups, service, waiting pool, capacity in use and cost, summed over the countries."""
    rules = planner.settings.rules
    frames = []
    for o in _outcomes(planner, policy, country).values():
        m = o.simulation.monthly.iloc[:12].copy()
        m["salary_cost"] = o.plan.salary_cost()[:12]
        m["notice_cost"] = o.plan.fire_cost()[:12]
        m["hires_decided"] = o.plan.hires[:12]
        m["notices_given"] = o.plan.notices[:12]
        frames.append(m)
    total = pd.concat(frames).groupby("month_index").sum(numeric_only=True)
    days = pd.Series(
        [pd.Period(f"{planner.year}-{i:02d}").days_in_month for i in total.index], index=total.index
    )
    return pd.DataFrame(
        {
            "month": [MONTHS[i - 1] for i in total.index],
            "sign_ups": total["arrivals"].astype(int),
            "served": total["served"].astype(int),
            "left_unserved": total["dropped"].astype(int),
            "waiting_at_month_end": total["waiting_end"].astype(int),
            "agents_at_work": total["active_agents"].astype(int),
            "slots": (total["active_agents"] * rules.capacity_per_agent).astype(int),
            "advertisers_in_support": (total["occupied_slot_days"] / days).round(0).astype(int),
            "utilization": total["occupied_slot_days"]
            / total["capacity_slot_days"].where(total["capacity_slot_days"] > 0),
            "hires_decided": total["hires_decided"].astype(int),
            "notices_given": total["notices_given"].astype(int),
            "salary_cost": total["salary_cost"],
            "notice_cost": total["notice_cost"],
            "uplift_value": total["uplift_value"],
        }
    ).reset_index(drop=True)


@dataclass
class ManualComparison:
    country: str
    targets: np.ndarray
    manual: CountryOutcome
    optimized: CountryOutcome

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "month": MONTHS,
                "optimized": self.optimized.plan.active[:12].astype(int),
                "yours_asked": self.targets.astype(int),
                "yours_possible": self.manual.plan.active[:12].astype(int),
            }
        )

    def moved_by_lead_times(self) -> list[str]:
        """Months whose typed headcount the ramp up and notice periods do not allow."""
        possible = self.manual.plan.active[:12]
        return [MONTHS[t] for t in range(12) if abs(possible[t] - self.targets[t]) > 0.5]

    def summary(self) -> str:
        m, o = self.manual.kpis, self.optimized.kpis
        change = m["net_value"] - o["net_value"]
        if abs(change) < 1:
            verdict = "Your plan is the optimized plan."
        elif change < 0:
            verdict = f"Your plan earns **{_money(-change)} less** than the optimized plan."
        elif (
            m["mean_wait_days"] > o["mean_wait_days"] + 0.05 or m["service_rate"] < o["service_rate"] - 0.0005
        ):
            verdict = (
                f"Your plan earns **{_money(change)} more** by making advertisers wait longer: the optimized plan "
                "prefers early service (assumption A9) and pays for it. Whether the saving is worth the wait "
                "is a business choice."
            )
        else:
            verdict = f"Your plan earns **{_money(change)} more** with the same service."
        lines = [
            f"* {verdict}",
            f"* **Net value**: yours {_money(m['net_value'])}, optimized {_money(o['net_value'])}.",
            f"* **Cost**: yours {_money(m['total_cost'])}, optimized {_money(o['total_cost'])}.",
            (
                f"* **Served**: yours {m['service_rate']:.1%} after {m['mean_wait_days']:.1f} days on average "
                f"({m['dropped']:,.0f} left unserved); optimized {o['service_rate']:.1%} after "
                f"{o['mean_wait_days']:.1f} days ({o['dropped']:,.0f} left unserved)."
            ),
        ]
        moved = self.moved_by_lead_times()
        if moved:
            lines.append(
                f"* **Not possible as typed** in {', '.join(moved)}: January keeps the January team, and a "
                "change takes a month of ramp up or notice, so those months were set as close as the rules allow."
            )
        return "\n".join(lines)


def compare_manual(
    planner: Planner, country: str, targets: list[float] | np.ndarray, policy: str
) -> ManualComparison:
    manual, optimized = planner.score_plan(country, targets, policy)
    return ManualComparison(
        manual.plan.country, np.round(np.asarray(targets, dtype=float)), manual, optimized
    )
