"""Descriptive analysis of the sign up data, used by the notebook and the assistant."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from staffpilot.data import Dataset


INSIGHT_KINDS: tuple[str, ...] = ("volatility", "seasonality", "eligibility", "budget", "growth")


@dataclass
class Insight:
    kind: str
    table: pd.DataFrame
    headline: str
    facts: dict[str, float]


def _daily(dataset: Dataset) -> pd.DataFrame:
    eligible = dataset.eligible()
    counts = eligible.groupby(["country", "signup_date"]).size().rename("signups").reset_index()
    days = pd.date_range(eligible["signup_date"].min(), eligible["signup_date"].max(), freq="D")
    full = pd.MultiIndex.from_product([dataset.country_names, days], names=["country", "signup_date"])
    return counts.set_index(["country", "signup_date"]).reindex(full, fill_value=0).reset_index()


def volatility(dataset: Dataset) -> Insight:
    daily = _daily(dataset)
    monthly = (
        daily.groupby(["country", daily["signup_date"].dt.to_period("M")])["signups"].sum().reset_index()
    )
    table = (
        pd.DataFrame(
            {
                "daily_cv": daily.groupby("country")["signups"].agg(
                    lambda s: s.std() / s.mean() if s.mean() else 0
                ),
                "monthly_cv": monthly.groupby("country")["signups"].agg(
                    lambda s: s.std() / s.mean() if s.mean() else 0
                ),
                "mean_daily_eligible": daily.groupby("country")["signups"].mean(),
            }
        )
        .sort_values("monthly_cv", ascending=False)
        .round(3)
    )
    top = table.index[0]
    return Insight(
        "volatility",
        table.reset_index(),
        f"{top} has the most volatile monthly demand; day to day noise is high everywhere.",
        {
            "top_monthly_cv": float(table["monthly_cv"].iloc[0]),
            "median_daily_cv": float(table["daily_cv"].median()),
        },
    )


def seasonality(dataset: Dataset) -> Insight:
    eligible = dataset.eligible()
    monthly = eligible.groupby(eligible["signup_date"].dt.month).size()
    index = (monthly / monthly.mean()).round(3)
    table = pd.DataFrame(
        {"month": index.index, "seasonal_index": index.to_numpy(), "eligible_signups": monthly.to_numpy()}
    )
    peak, low = int(index.idxmax()), int(index.idxmin())
    return Insight(
        "seasonality",
        table,
        f"Demand peaks in month {peak} and is lowest in month {low}.",
        {
            "peak_month": peak,
            "peak_index": float(index.max()),
            "low_month": low,
            "low_index": float(index.min()),
        },
    )


def eligibility(dataset: Dataset) -> Insight:
    frame = dataset.signups.groupby("country").agg(signups=("eligible", "size"), eligible=("eligible", "sum"))
    frame["eligible_rate"] = (frame["eligible"] / frame["signups"]).round(3)
    frame = frame.join(dataset.countries["threshold"]).sort_values("eligible_rate", ascending=False)
    overall = float(dataset.signups["eligible"].mean())
    return Insight(
        "eligibility",
        frame.reset_index(),
        f"{overall:.1%} of sign ups clear their country threshold.",
        {
            "overall_eligible_rate": overall,
            "highest_rate": float(frame["eligible_rate"].max()),
            "lowest_rate": float(frame["eligible_rate"].min()),
        },
    )


def budget(dataset: Dataset) -> Insight:
    eligible = dataset.eligible()
    table = (
        eligible.groupby("country")["budget"]
        .agg(["median", "mean", "count"])
        .round(0)
        .sort_values("mean", ascending=False)
    )
    return Insight(
        "budget",
        table.reset_index(),
        f"{table.index[0]} has the largest eligible budgets on average.",
        {
            "top_mean_budget": float(table["mean"].iloc[0]),
            "overall_mean_budget": float(eligible["budget"].mean()),
        },
    )


def growth(dataset: Dataset) -> Insight:
    years = dataset.history_years
    eligible = dataset.eligible()
    table = eligible.groupby(["country", eligible["signup_date"].dt.year]).size().unstack(fill_value=0)
    if len(years) > 1:
        table["change"] = ((table[years[-1]] / table[years[-2]]) - 1).round(3)
    else:
        table["change"] = 0.0
    total_change = float(table[years[-1]].sum() / table[years[-2]].sum() - 1) if len(years) > 1 else 0.0
    table.columns = [str(c) for c in table.columns]
    return Insight(
        "growth",
        table.sort_values("change").reset_index(),
        f"Eligible sign ups changed by {total_change:.1%} between the last two years.",
        {"total_change": total_change},
    )


_BUILDERS = {
    "volatility": volatility,
    "seasonality": seasonality,
    "eligibility": eligibility,
    "budget": budget,
    "growth": growth,
}


def insight(dataset: Dataset, kind: str, country: str | None = None) -> Insight:
    if kind not in _BUILDERS:
        raise ValueError(f"Unknown insight {kind!r}; choose one of {INSIGHT_KINDS}")
    result = _BUILDERS[kind](dataset)
    if country and "country" in result.table.columns:
        row = result.table[result.table["country"] == country]
        if not row.empty:
            for column in row.columns:
                if column != "country" and pd.api.types.is_numeric_dtype(row[column]):
                    result.facts[f"{country}_{column}"] = float(row[column].iloc[0])
    return result
