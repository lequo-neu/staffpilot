"""Monthly update: plan again during the year when actual sign ups differ from the forecast.

At the start of a month the manager knows the real sign ups of the months before it,
and how many agents are really on staff. `Planner.monthly_update` keeps the decisions
already carried out, scales the rest of the forecast by what the recent months showed
and solves the remaining months again. This module holds the result and its read out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd


if TYPE_CHECKING:
    from staffpilot.optimize import CountryPlan
    from staffpilot.planner import CountryOutcome

MONTH_NAMES = [
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
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e6:
        return f"{sign}${value / 1e6:,.1f}M"
    return f"{sign}${value / 1e3:,.0f}k" if value >= 1e3 else f"{sign}${value:,.0f}"


def _count(value: float, word: str) -> str:
    n = round(value)
    return f"{n} {word}{'' if n == 1 else 's'}"


@dataclass
class MonthlyUpdate:
    """The approved plan against the plan made again with the actual numbers so far."""

    country: str
    year: int
    as_of: int  # calendar month the update is made in; the months before it are done
    forecast: np.ndarray  # monthly eligible sign ups the approved plan was built on
    demand: np.ndarray  # actual counts for the months done, the adjusted forecast after them
    actual: np.ndarray
    ratio: float  # actual against forecast in the recent months, applied to the rest of the year
    headcount_change: int  # agents on staff now minus the plan
    original: CountryPlan
    kept: CountryOutcome  # the approved decisions, run on what really happened
    updated: CountryOutcome

    @property
    def done(self) -> int:
        return self.as_of - 1

    def table(self) -> pd.DataFrame:
        """One row per month of the planning year: sign ups and decisions, before and after the update."""
        months = range(12)
        old, new = self.original, self.updated.plan

        def status(t: int) -> str:
            if t < self.done:
                return "carried out"
            return "decide now" if t == self.done else "planned"

        return pd.DataFrame(
            {
                "month": [f"{self.year}-{t + 1:02d}" for t in months],
                "status": [status(t) for t in months],
                "forecast_signups": np.round(self.forecast[:12]).astype(int),
                "signups_used": np.round(self.demand[:12]).astype(int),
                "agents_planned": old.active[:12].astype(int),
                "agents_updated": new.active[:12].astype(int),
                "agents_change": (new.active[:12] - old.active[:12]).astype(int),
                "hires_planned": old.hires[:12].astype(int),
                "hires_updated": new.hires[:12].astype(int),
                "notices_planned": old.notices[:12].astype(int),
                "notices_updated": new.notices[:12].astype(int),
            }
        )

    def facts(self) -> dict[str, float]:
        k, u = self.kept.kpis, self.updated.kpis
        now, old, new = self.done, self.original, self.updated.plan
        return {
            "ratio": self.ratio,
            "kept_net_value": k["net_value"],
            "updated_net_value": u["net_value"],
            "net_value_change": u["net_value"] - k["net_value"],
            "kept_service_rate": k["service_rate"],
            "updated_service_rate": u["service_rate"],
            "kept_dropped": k["dropped"],
            "updated_dropped": u["dropped"],
            "kept_mean_wait_days": k["mean_wait_days"],
            "updated_mean_wait_days": u["mean_wait_days"],
            "hires_now_planned": float(old.hires[now]),
            "hires_now_updated": float(new.hires[now]),
            "notices_now_planned": float(old.notices[now]),
            "notices_now_updated": float(new.notices[now]),
        }

    def changes(self) -> list[tuple[int, int, int]]:
        """(calendar month, planned agents, updated agents) for every month whose headcount moved."""
        old, new = self.original.active[:12], self.updated.plan.active[:12]
        return [(t + 1, int(old[t]), int(new[t])) for t in range(self.done, 12) if old[t] != new[t]]

    def summary(self) -> str:
        """The update as a manager reads it, in Markdown bullets."""
        f = self.facts()
        if self.done <= 2:
            seen = "in " + " and ".join(MONTH_NAMES[: self.done])
        else:
            seen = f"from {MONTH_NAMES[0]} to {MONTH_NAMES[self.done - 1]}"
        rest = f"{MONTH_NAMES[self.done]} to December"
        gap = self.ratio - 1
        if abs(gap) < 0.005:
            demand = f"Sign ups {seen} were on forecast, so {rest} keeps its forecast."
        else:
            direction = "above" if gap > 0 else "below"
            demand = (
                f"Sign ups {seen} came in {abs(gap):.0%} {direction} the forecast, so the forecast for "
                f"{rest} is {'raised' if gap > 0 else 'lowered'} by the same share."
            )
        if self.headcount_change:
            n = abs(self.headcount_change)
            more = "more" if self.headcount_change > 0 else "fewer"
            demand += f" {_count(n, 'agent')} {more} than planned are on staff now."

        def outcome(prefix: str) -> str:
            return (
                f"serves {f[prefix + '_service_rate']:.1%} of eligible advertisers after "
                f"{f[prefix + '_mean_wait_days']:.1f} days on average; net value {_money(f[prefix + '_net_value'])}"
            )

        change = f["net_value_change"]
        if change >= 0:
            worth = f"The update adds {_money(change)} of net value."
        elif f["updated_mean_wait_days"] < f["kept_mean_wait_days"] - 0.05:
            worth = (
                f"The update costs {_money(-change)} to bring the average wait back from "
                f"{f['kept_mean_wait_days']:.1f} to {f['updated_mean_wait_days']:.1f} days."
            )
        else:
            worth = f"The update costs {_money(-change)} to serve more advertisers."
        month = MONTH_NAMES[self.done]
        decide = (
            f"hire {f['hires_now_updated']:.0f} (the plan said {f['hires_now_planned']:.0f}) and give notice to "
            f"{f['notices_now_updated']:.0f} (the plan said {f['notices_now_planned']:.0f})."
        )
        moved = self.changes()
        if moved:
            when, before, after = moved[0]
            decide += (
                f" Headcount first moves in {MONTH_NAMES[when - 1]}: {after} agents at work instead of "
                f"{before} ({after - before:+d})."
            )
        else:
            decide += " Headcount stays as planned for the rest of the year."
        return "\n".join(
            [
                f"* **What changed.** {demand}",
                f"* **Keep the approved plan:** {outcome('kept')}.",
                f"* **Updated plan:** {outcome('updated')}. {worth}",
                f"* **Decide in {month}:** {decide}",
            ]
        )
