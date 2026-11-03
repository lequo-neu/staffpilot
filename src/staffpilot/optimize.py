"""Mixed integer program that chooses monthly hires and notices for one country.

Headcount decisions are monthly, as the brief asks. Advertiser flows are tracked in
weeks: an advertiser started in week w holds a slot for `occupancy_weeks` weeks and
may wait at most `wait_weeks` weeks. A purely monthly flow model treats 60 days as
two calendar months and, when headcount is cut, lets the plan exceed the ten
advertiser limit by hundreds of slots once checked day by day. The weekly flow and
the "every month a week touches" capacity constraint remove that gap; a short
repair loop driven by the simulator closes what rounding leaves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time

import numpy as np
import pandas as pd
import pulp

from staffpilot.config import AssumptionSettings, PlanningSettings, RuleSettings


log = logging.getLogger(__name__)


@dataclass
class CountryPlan:
    """Monthly staffing decisions for one country.

    `active[t]` agents can take advertisers in month t. `hires[t]` are decided in
    month t and become active after the ramp up; `notices[t]` are given in month t
    and leave after the notice period.
    """

    country: str
    active: np.ndarray
    hires: np.ndarray
    notices: np.ndarray
    salary: float
    rules: RuleSettings
    assumptions: AssumptionSettings
    policy: str = "optimized"
    solver_status: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def months(self) -> int:
        return len(self.active)

    def in_ramp(self) -> np.ndarray:
        ramp = self.rules.ramp_months
        trainees = np.zeros(self.months)
        for t in range(self.months):
            start = max(0, t - ramp + 1)
            trainees[t] = self.hires[start : t + 1].sum() if ramp > 0 else 0
        return trainees

    def payroll(self) -> np.ndarray:
        extra = self.in_ramp() if self.assumptions.pay_during_ramp else 0
        return self.active + extra

    def salary_cost(self) -> np.ndarray:
        return self.payroll() * self.salary / 12.0

    def fire_cost(self) -> np.ndarray:
        return self.notices * self.salary * self.rules.fire_cost_share

    def table(self, year: int, months: int = 12) -> pd.DataFrame:
        labels = [f"{year + (t // 12)}-{t % 12 + 1:02d}" for t in range(months)]
        return pd.DataFrame(
            {
                "country": self.country,
                "month": labels,
                "active_agents": self.active[:months].astype(int),
                "hires_decided": self.hires[:months].astype(int),
                "notices_given": self.notices[:months].astype(int),
                "agents_in_ramp": self.in_ramp()[:months].astype(int),
                "agents_in_notice": self.notices[:months].astype(int),
                "payroll_agents": self.payroll()[:months].astype(int),
                "salary_cost": self.salary_cost()[:months].round(0),
                "fire_cost": self.fire_cost()[:months].round(0),
            }
        )


def _project(start: int, hires: np.ndarray, notices: np.ndarray, rules: RuleSettings) -> np.ndarray:
    active = np.zeros(len(hires))
    active[0] = start
    for t in range(1, len(hires)):
        joined = hires[t - rules.ramp_months] if t >= rules.ramp_months else 0.0
        left = notices[t - rules.notice_months] if t >= rules.notice_months else 0.0
        active[t] = active[t - 1] + joined - left
    return active


def path_from_targets(
    country: str,
    start: int,
    targets: np.ndarray,
    salary: float,
    rules: RuleSettings,
    assumptions: AssumptionSettings,
    policy: str,
) -> CountryPlan:
    """Build a feasible plan that reaches each monthly target as early as the lead times allow."""
    months = len(targets)
    hires = np.zeros(months)
    notices = np.zeros(months)
    for month in range(1, months):
        projected = _project(start, hires, notices, rules)
        gap = float(np.ceil(targets[month]) - projected[month])
        if gap > 0 and month - rules.ramp_months >= 0:
            hires[month - rules.ramp_months] += gap
        elif gap < 0 and month - rules.notice_months >= 0:
            notices[month - rules.notice_months] += min(-gap, projected[month])
    active = _project(start, hires, notices, rules)
    return CountryPlan(country, active, hires, notices, salary, rules, assumptions, policy=policy)


def _periods(month_by_day: np.ndarray, flow_period: str) -> tuple[list[range], list[set[int]]]:
    """Day ranges of each flow period and the months each period touches."""
    n_days = len(month_by_day)
    if flow_period == "month":
        starts = [0, *list(np.flatnonzero(np.diff(month_by_day)) + 1)]
        spans = [range(a, b) for a, b in zip(starts, [*starts[1:], n_days], strict=True)]
    else:
        spans = [range(start, min(start + 7, n_days)) for start in range(0, n_days, 7)]
    touched = [{int(month_by_day[d]) for d in span} for span in spans]
    return spans, touched


def optimize_country(
    country: str,
    daily_demand: np.ndarray,
    month_by_day: np.ndarray,
    mean_budget_by_month: np.ndarray,
    start_agents: int,
    salary: float,
    rules: RuleSettings,
    assumptions: AssumptionSettings,
    planning: PlanningSettings,
    service_target: float | None = None,
    min_active: np.ndarray | None = None,
    max_hires_per_month: int | None = None,
    initial_pool: float = 0.0,
    flow_period: str = "week",
) -> CountryPlan:
    """Solve the staffing program over the planning year plus the lookahead months.

    `flow_period="month"` gives the simpler model that treats 60 days as two months;
    it is kept only to show why the weekly model is needed.
    """
    months = int(month_by_day.max()) + 1
    spans, touched = _periods(month_by_day, flow_period)
    if flow_period == "month":
        occupancy_periods, wait_periods, weeks_per_period = 2, 2, 30.4 / 7
    else:
        occupancy_periods, wait_periods, weeks_per_period = planning.occupancy_weeks, planning.wait_weeks, 1.0
    n_weeks = len(spans)
    buffer = 1.0 + planning.safety_buffer
    weekly_demand = [float(daily_demand[list(span)].sum()) * buffer for span in spans]
    if initial_pool:
        weekly_demand[0] += float(initial_pool)
    value_factor = 1.0 if assumptions.uplift_base == "annual_budget" else rules.support_days / 365.0
    week_value = [
        rules.expected_uplift * value_factor * float(mean_budget_by_month[int(month_by_day[span[-1]])])
        for span in spans
    ]

    problem = pulp.LpProblem(f"staffing_{country.replace(' ', '_')}", pulp.LpMaximize)
    active = [pulp.LpVariable(f"active_{t}", lowBound=0, cat="Integer") for t in range(months)]
    hires = [pulp.LpVariable(f"hires_{t}", lowBound=0, cat="Integer") for t in range(months)]
    notices = [pulp.LpVariable(f"notices_{t}", lowBound=0, cat="Integer") for t in range(months)]
    flow = {
        (u, w): pulp.LpVariable(f"serve_{u}_{w}", lowBound=0)
        for u in range(n_weeks)
        for w in range(u, min(n_weeks, u + wait_periods + 1))
    }

    problem += active[0] == int(start_agents)
    for t in range(1, months):
        joined = hires[t - rules.ramp_months] if t >= rules.ramp_months else 0
        left = notices[t - rules.notice_months] if t >= rules.notice_months else 0
        problem += active[t] == active[t - 1] + joined - left
    for t in range(months):
        problem += notices[t] <= active[t]
        if max_hires_per_month is not None:
            problem += hires[t] <= int(max_hires_per_month)
        if min_active is not None and t < len(min_active):
            problem += active[t] >= float(min_active[t])
    for u in range(n_weeks):
        problem += (
            pulp.lpSum(flow[u, w] for w in range(u, min(n_weeks, u + wait_periods + 1))) <= weekly_demand[u]
        )
    started_in = {w: [] for w in range(n_weeks)}
    for (_, w), var in flow.items():
        started_in[w].append(var)
    for w in range(n_weeks):
        occupancy = pulp.lpSum(
            var for ww in range(max(0, w - occupancy_periods + 1), w + 1) for var in started_in[ww]
        )
        for m in touched[w]:
            problem += occupancy <= rules.capacity_per_agent * active[m]

    trainees = [
        pulp.lpSum(hires[k] for k in range(max(0, t - rules.ramp_months + 1), t + 1))
        if rules.ramp_months
        else 0
        for t in range(months)
    ]
    payroll = [active[t] + (trainees[t] if assumptions.pay_during_ramp else 0) for t in range(months)]
    # The brief gives no price for waiting, so a small penalty per week only breaks ties in favour of
    # serving earlier (the brief asks for timely support). Reported value comes from the simulator.
    revenue = pulp.lpSum(
        week_value[w] * max(0.0, 1.0 - planning.wait_penalty_per_week * weeks_per_period * (w - u)) * var
        for (u, w), var in flow.items()
    )
    cost = pulp.lpSum(
        salary / 12.0 * payroll[t] + rules.fire_cost_share * salary * notices[t] for t in range(months)
    )
    problem += revenue - cost

    if service_target:
        planning_weeks = [w for w in range(n_weeks) if max(touched[w]) < 12]
        demand_in_year = sum(weekly_demand[u] for u in planning_weeks) / buffer
        problem += (
            pulp.lpSum(var for (u, w), var in flow.items() if u in planning_weeks)
            >= service_target * demand_in_year
        )

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=planning.solver_time_limit)
    started = time.perf_counter()
    problem.solve(solver)
    status = pulp.LpStatus[problem.status]
    log.debug("%s: %s flows, solver %s in %.2fs", country, flow_period, status, time.perf_counter() - started)
    if status not in {"Optimal", "Not Solved"} and problem.status != 1:
        raise RuntimeError(f"Staffing model for {country} ended with status {status}")

    def values(variables: list[pulp.LpVariable]) -> np.ndarray:
        return np.array([round(v.value() or 0.0) for v in variables], dtype=float)

    return CountryPlan(
        country,
        values(active),
        values(hires),
        values(notices),
        salary,
        rules,
        assumptions,
        policy="optimized" if not service_target else f"service_{int(round(service_target * 100))}",
        solver_status=status,
    )
