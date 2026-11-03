"""Backtest: plan the last history year from the years before it, then score the plan on what really happened.

The real data has two years, so the plan for the second year is built from the first
year only and simulated on the actual daily sign ups of the second year. The January
headcount table is reused for that earlier year, which is an assumption.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from staffpilot.config import Settings
from staffpilot.data import Dataset
from staffpilot.forecast import DemandStream, month_of_day
from staffpilot.optimize import optimize_country
from staffpilot.planner import Planner
from staffpilot.simulate import simulate


def actual_stream(dataset: Dataset, country: str, year: int, months: int) -> DemandStream:
    """Real eligible sign ups of `year`, padded with the following months when available."""
    start = pd.Timestamp(year=year, month=1, day=1)
    days = pd.date_range(start, start + pd.DateOffset(months=months) - pd.Timedelta(days=1), freq="D")
    eligible = dataset.eligible(country)
    by_day = eligible.groupby("signup_date")["budget"].apply(lambda s: s.to_numpy(dtype=float))
    return DemandStream([by_day.get(day, np.empty(0)) for day in days], [])


def run_backtest(settings: Settings, dataset: Dataset) -> pd.DataFrame:
    years = dataset.history_years
    if len(years) < 2:
        raise ValueError("A backtest needs at least two years of sign ups")
    target = years[-1]
    train = replace(dataset, signups=dataset.signups[dataset.signups["signup_date"].dt.year < target])
    planner = Planner(settings.with_updates(planning={"planning_year": target}), train)
    rules, assumptions = settings.rules, settings.assumptions
    month_by_day = month_of_day(target, 12)
    rows = []
    for country in planner.countries:
        row = dataset.countries.loc[country]
        stream = actual_stream(dataset, country, target, 12)
        # Hindsight: the same optimizer given the real daily sign ups. It is a reference point, not a
        # strict bound, because its horizon ends in December.
        hindsight = optimize_country(
            country,
            stream.daily_counts,
            month_by_day,
            np.full(12, float(dataset.eligible(country, target)["budget"].mean())),
            int(row["agents"]),
            float(row["salary"]),
            rules,
            assumptions,
            settings.planning,
        )
        plans = {
            "hold": planner.plan_country(country, "hold"),
            "optimized from forecast": planner.plan_country(country, "optimized"),
            "hindsight": hindsight,
        }
        for label, plan in plans.items():
            totals = simulate(stream, plan.active, month_by_day, rules, assumptions).totals(12)
            cost = float(plan.salary_cost()[:12].sum() + plan.fire_cost()[:12].sum())
            rows.append(
                {
                    "country": country,
                    "plan": label,
                    "net_value": totals["uplift_value"] - cost,
                    "served": totals["served"],
                    "arrivals": totals["arrivals"],
                    "max_overflow": totals["max_overflow"],
                    "avg_active": float(np.mean(plan.active[:12])),
                }
            )
    return pd.DataFrame(rows)


def summarize_backtest(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.groupby("plan").agg(
        net_value=("net_value", "sum"),
        avg_active=("avg_active", "sum"),
        served=("served", "sum"),
        arrivals=("arrivals", "sum"),
        worst_overflow=("max_overflow", "max"),
    )
    out["service_rate"] = out["served"] / out["arrivals"]
    out["share_of_hindsight"] = out["net_value"] / float(out.loc["hindsight", "net_value"])
    return out.drop(columns=["served", "arrivals"]).sort_values("net_value", ascending=False).reset_index()
