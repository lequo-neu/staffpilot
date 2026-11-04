"""Day by day simulation of one country, following the brief rules exactly.

Order of events on each day:

1. advertisers whose 60 day support ends today graduate and free their slot,
2. today's eligible sign ups join the waiting pool,
3. advertisers who have waited longer than the limit leave the pool,
4. free slots are filled from the pool.

A slot counts as free only if it exists for the whole 60 day support period under the
plan. An agent who has been given notice therefore stops taking new advertisers, so
the ten advertiser limit holds on every day even when headcount is cut.

Every KPI in the reports comes from this simulator, not from the optimizer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import heapq

import numpy as np
import pandas as pd

from staffpilot.config import AssumptionSettings, RuleSettings
from staffpilot.forecast import DemandStream


WAITING, SERVED, DROPPED = 0, 1, 2


@dataclass
class SimulationResult:
    """Monthly flows plus the fate of every advertiser grouped by arrival month."""

    monthly: pd.DataFrame
    cohorts: pd.DataFrame  # arrival month: arrivals, served (at any time), dropped, pending at the end
    waits: np.ndarray
    wait_months: np.ndarray

    def totals(self, months: int = 12) -> dict[str, float]:
        """Totals for the first `months` months.

        Service and uplift follow the arrival cohort: an advertiser who signs up in
        December and is served in January counts, with its uplift, in this year. Costs
        follow the month they are paid. Counting uplift by service month instead would
        push value out of the year whenever a plan lets late December sign ups wait,
        which the optimizer (with its lookahead) rightly does not penalize.
        """
        m = self.monthly[self.monthly["month_index"] <= months]
        c = self.cohorts[self.cohorts["arrival_month"] <= months]
        arrivals = float(c["arrivals"].sum())
        served = float(c["served"].sum())
        waits = self.waits[self.wait_months <= months]
        capacity = float(m["capacity_slot_days"].sum())
        return {
            "arrivals": arrivals,
            "served": served,
            "dropped": float(c["dropped"].sum()),
            "waiting_at_end": float(c["pending"].sum()),
            "service_rate": served / arrivals if arrivals else 1.0,
            "uplift_value": float(c["uplift_value"].sum()),
            "mean_wait_days": float(waits.mean()) if waits.size else 0.0,
            "p90_wait_days": float(np.percentile(waits, 90)) if waits.size else 0.0,
            "max_wait_days": float(waits.max()) if waits.size else 0.0,
            "utilization": float(m["occupied_slot_days"].sum() / capacity) if capacity else 0.0,
            "max_overflow": float(m["max_overflow"].max()),
            "peak_load": float(m["peak_load"].max()),
        }


def simulate(
    demand: DemandStream,
    active_by_month: np.ndarray,
    month_by_day: np.ndarray,
    rules: RuleSettings,
    assumptions: AssumptionSettings,
    rng: np.random.Generator | None = None,
    sample_uplift: bool = False,
    dispatch: str = "notice_aware",
) -> SimulationResult:
    """Run the pool and capacity rules for one country over the days in `demand`."""
    n_days = len(demand.budgets_by_day)
    n_months = int(month_by_day[:n_days].max()) + 1
    support = rules.support_days
    capacity_by_day = (
        rules.capacity_per_agent * np.asarray(active_by_month, dtype=float)[month_by_day[:n_days]]
    )
    capacity_by_day = np.round(capacity_by_day).astype(int)
    # Beyond the simulated days the last planned headcount is assumed to continue.
    future_capacity = np.concatenate([capacity_by_day, np.full(support, capacity_by_day[-1])])
    value_factor = 1.0 if assumptions.uplift_base == "annual_budget" else rules.support_days / 365.0
    levels = np.asarray(rules.uplift_levels)
    probabilities = np.asarray(rules.uplift_probabilities)
    rng = rng or np.random.default_rng(0)

    arrival_day: list[int] = []
    budget: list[float] = []
    state: list[int] = []
    earned: list[float] = []
    order: deque[int] = deque()
    priority: list[tuple[float, int]] = []
    use_priority = assumptions.queue_policy == "budget_priority"

    def enqueue(day: int, amount: float) -> None:
        idx = len(arrival_day)
        arrival_day.append(day)
        budget.append(amount)
        state.append(WAITING)
        earned.append(0.0)
        order.append(idx)
        if use_priority:
            heapq.heappush(priority, (-amount, idx))

    for day, amount in sorted(demand.initial_pool):
        enqueue(day, amount)
    carried = len(arrival_day)

    occupancy = np.zeros(n_days + support, dtype=int)  # advertisers in support on each day, as booked so far
    stats = {
        key: np.zeros(n_months)
        for key in (
            "arrivals",
            "served",
            "dropped",
            "uplift_value",
            "occupied_slot_days",
            "capacity_slot_days",
            "max_overflow",
            "peak_load",
            "waiting_end",
            "uplift_wait_days",
        )
    }
    waits: list[int] = []
    wait_months: list[int] = []
    waiting = carried

    for day in range(n_days):
        month = month_by_day[day]
        for amount in demand.budgets_by_day[day]:
            enqueue(day, float(amount))
        stats["arrivals"][month] += len(demand.budgets_by_day[day])
        waiting += len(demand.budgets_by_day[day])

        while order and day - arrival_day[order[0]] > rules.max_wait_days:
            idx = order.popleft()
            if state[idx] == WAITING:
                state[idx] = DROPPED
                stats["dropped"][month] += 1
                waiting -= 1

        capacity = int(capacity_by_day[day])
        window = slice(day, day + support)
        if dispatch == "greedy":
            # Fill today's free slots without looking at planned cuts; used to show what goes wrong.
            free = capacity - int(occupancy[day])
        else:
            free = int((future_capacity[window] - occupancy[window]).min())
        while free > 0 and waiting > 0:
            if use_priority:
                _, idx = heapq.heappop(priority)
            else:
                idx = order.popleft()
            if state[idx] != WAITING:
                continue
            state[idx] = SERVED
            waiting -= 1
            free -= 1
            occupancy[window] += 1
            waits.append(day - arrival_day[idx])
            wait_months.append(int(month) + 1)
            uplift = rng.choice(levels, p=probabilities) if sample_uplift else rules.expected_uplift
            earned[idx] = uplift * budget[idx] * value_factor
            stats["uplift_value"][month] += earned[idx]
            # Uplift weighted by the days waited; the optimizer's preference for early service is priced on it.
            stats["uplift_wait_days"][month] += earned[idx] * (day - arrival_day[idx])
            stats["served"][month] += 1

        occupied = int(occupancy[day])
        stats["occupied_slot_days"][month] += occupied
        stats["capacity_slot_days"][month] += capacity
        stats["max_overflow"][month] = max(stats["max_overflow"][month], occupied - capacity)
        # Advertisers per agent on the day, which the brief caps at ten.
        if capacity:
            load = occupied * rules.capacity_per_agent / capacity
            stats["peak_load"][month] = max(stats["peak_load"][month], load)
        stats["waiting_end"][month] = waiting

    monthly = pd.DataFrame(stats)
    monthly.insert(0, "month_index", np.arange(1, n_months + 1))
    days_in_month = np.bincount(month_by_day[:n_days], minlength=n_months)
    monthly["active_agents"] = np.asarray(active_by_month, dtype=float)[:n_months]
    monthly["utilization"] = np.where(
        monthly["capacity_slot_days"] > 0, monthly["occupied_slot_days"] / monthly["capacity_slot_days"], 0.0
    )
    monthly["idle_agents"] = (monthly["capacity_slot_days"] - monthly["occupied_slot_days"]) / (
        rules.capacity_per_agent * days_in_month
    )

    arrivals_at = np.asarray(arrival_day, dtype=int)
    cohort = np.where(arrivals_at >= 0, month_by_day[np.clip(arrivals_at, 0, n_days - 1)] + 1, 1)
    outcome = np.asarray(state, dtype=int)
    cohorts = pd.DataFrame({"arrival_month": cohort, "state": outcome, "uplift_value": earned})
    cohorts = (
        cohorts.assign(
            arrivals=1,
            served=(cohorts["state"] == SERVED).astype(int),
            dropped=(cohorts["state"] == DROPPED).astype(int),
            pending=(cohorts["state"] == WAITING).astype(int),
        )
        .groupby("arrival_month")[["arrivals", "served", "dropped", "pending", "uplift_value"]]
        .sum()
        .reindex(range(1, n_months + 1), fill_value=0)
        .reset_index()
    )
    cohorts["carried_in"] = 0
    cohorts.loc[0, "carried_in"] = carried
    return SimulationResult(
        monthly, cohorts, np.asarray(waits, dtype=float), np.asarray(wait_months, dtype=int)
    )
