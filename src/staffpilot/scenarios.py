"""Scenario definitions shared by the planner and the language model.

`ScenarioParams` is the structured output the assistant asks the model for when a
manager describes a what if question in words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class ScenarioParams(BaseModel):
    """A change to the planning inputs. Fields left at their default mean no change."""

    model_config = ConfigDict(extra="forbid")

    countries: list[str] = Field(
        default_factory=list, description="Countries the change applies to. Empty means every country."
    )
    months: list[int] = Field(
        default_factory=list,
        description="Calendar months (1 to 12) the demand change applies to. Empty means all.",
    )
    demand_multiplier: float = Field(
        1.0, ge=0.1, le=3.0, description="Scale on eligible sign ups, for example 0.7 for a 30 percent drop."
    )
    threshold_multiplier: float = Field(
        1.0,
        ge=0.1,
        le=3.0,
        description="Scale on the eligibility threshold, for example 0.8 to lower it by 20 percent.",
    )
    salary_multiplier: float = Field(1.0, ge=0.1, le=3.0, description="Scale on annual agent salary.")
    expected_uplift: float | None = Field(
        None, ge=0.0, le=1.0, description="Replace the expected ad spend uplift (default 0.135)."
    )
    capacity_per_agent: int | None = Field(
        None, ge=1, le=50, description="Advertisers one agent can hold at once."
    )
    max_hires_per_month: int | None = Field(None, ge=0, description="Cap on hires decided in any month.")
    service_target: float | None = Field(
        None, ge=0.0, le=1.0, description="Minimum share of eligible advertisers to serve, for example 0.98."
    )
    queue_policy: Literal["fifo", "budget_priority"] | None = Field(
        None, description="Order of assignment from the waiting pool."
    )
    initial_pool: Literal["empty", "carryover"] | None = Field(
        None,
        description="Whether advertisers from the last 60 days of history wait in the pool on 1 January.",
    )
    replan: bool = Field(
        True, description="True to reoptimize under the scenario, False to stress the current plan."
    )

    def plain(self) -> str:
        """The scenario as a manager would say it, for answers and the app."""
        when = _month_phrase(self.months)
        changes = []
        if self.demand_multiplier != 1.0:
            changes.append(f"sign ups {_move(self.demand_multiplier, 'rise', 'fall')}{when}")
        if self.threshold_multiplier != 1.0:
            changes.append(
                f"the eligibility threshold is {_move(self.threshold_multiplier, 'raised', 'lowered', 'by ')}"
            )
        if self.salary_multiplier != 1.0:
            changes.append(f"salaries {_move(self.salary_multiplier, 'rise', 'fall')}")
        if self.expected_uplift is not None:
            changes.append(f"support lifts ad spend by {self.expected_uplift:.0%} on average")
        if self.capacity_per_agent:
            changes.append(f"each agent can hold {self.capacity_per_agent} advertisers")
        if self.max_hires_per_month is not None:
            changes.append(f"hiring is capped at {self.max_hires_per_month} a month")
        if self.service_target is not None:
            changes.append(f"at least {self.service_target:.0%} of eligible advertisers must be served")
        if self.queue_policy == "budget_priority":
            changes.append("the largest budgets are served first")
        if self.initial_pool == "carryover":
            changes.append("late December sign ups are still waiting on 1 January")
        where = " in " + _join(self.countries) if self.countries else " in every country"
        mode = "and we rebuild the plan" if self.replan else "and we keep the current plan"
        if not changes:
            return f"Nothing changes{where}"
        return f"If {_join(changes)}{where}, {mode}"

    def describe(self) -> str:
        parts = []
        if self.demand_multiplier != 1.0:
            months = f" in months {self.months}" if self.months else ""
            parts.append(f"demand x{self.demand_multiplier:g}{months}")
        if self.threshold_multiplier != 1.0:
            parts.append(f"threshold x{self.threshold_multiplier:g}")
        if self.salary_multiplier != 1.0:
            parts.append(f"salary x{self.salary_multiplier:g}")
        for name in (
            "expected_uplift",
            "capacity_per_agent",
            "max_hires_per_month",
            "service_target",
            "queue_policy",
            "initial_pool",
        ):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name} = {value}")
        scope = ", ".join(self.countries) if self.countries else "all countries"
        mode = "replanned" if self.replan else "current plan stressed"
        return f"{'; '.join(parts) or 'no change'} for {scope} ({mode})"


_MONTH_NAMES = [
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


def _join(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _move(multiplier: float, up: str, down: str, by: str = "") -> str:
    percent = abs(multiplier - 1) * 100
    return f"{up if multiplier > 1 else down} {by}{percent:.0f}%"


def _month_phrase(months: list[int]) -> str:
    if not months:
        return ""
    months = sorted(set(months))
    names = [_MONTH_NAMES[m - 1] for m in months]
    if len(months) > 2 and months == list(range(months[0], months[-1] + 1)):
        return f" from {names[0]} to {names[-1]}"
    return " in " + _join(names)


@dataclass
class ScenarioResult:
    params: ScenarioParams
    comparison: pd.DataFrame  # one row per country with base, scenario and change columns
    plan: pd.DataFrame  # scenario plan for the affected countries

    def totals(self) -> dict[str, float]:
        frame = self.comparison
        out: dict[str, float] = {}
        for metric in ("net_value", "total_cost", "uplift_value", "served", "dropped", "avg_active"):
            base, new = frame[f"{metric}_base"].sum(), frame[f"{metric}_scenario"].sum()
            out[f"{metric}_base"] = float(base)
            out[f"{metric}_scenario"] = float(new)
            out[f"{metric}_change"] = float(new - base)
        served_b, arrivals_b = frame["served_base"].sum(), frame["arrivals_base"].sum()
        served_s, arrivals_s = frame["served_scenario"].sum(), frame["arrivals_scenario"].sum()
        out["service_rate_base"] = float(served_b / arrivals_b) if arrivals_b else 1.0
        out["service_rate_scenario"] = float(served_s / arrivals_s) if arrivals_s else 1.0
        return out
