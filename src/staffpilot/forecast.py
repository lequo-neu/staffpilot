"""Monthly demand forecasts and daily arrival streams for the planning year.

Three simple seasonal methods are compared on the last history year (train on the
earlier years, predict the last one) and the most accurate one is used. With only
two years of data a heavier model would not be identifiable, and the brief asks for
expected values first.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import zlib

import numpy as np
import pandas as pd

from staffpilot.data import Dataset


METHODS = ("last_year", "seasonal_mean", "seasonal_trend")
log = logging.getLogger(__name__)


def monthly_history(dataset: Dataset) -> pd.DataFrame:
    """Eligible sign ups and mean budget by country, year and month."""
    eligible = dataset.eligible()
    grouped = eligible.groupby(
        [
            eligible["country"],
            eligible["signup_date"].dt.year.rename("year"),
            eligible["signup_date"].dt.month.rename("month"),
        ]
    )
    table = grouped.agg(eligible=("budget", "size"), mean_budget=("budget", "mean")).reset_index()
    full = pd.MultiIndex.from_product(
        [dataset.country_names, dataset.history_years, range(1, 13)], names=["country", "year", "month"]
    )
    table = table.set_index(["country", "year", "month"]).reindex(full)
    table["eligible"] = table["eligible"].fillna(0).astype(int)
    table["mean_budget"] = table.groupby(level="country")["mean_budget"].transform(
        lambda s: s.fillna(s.mean())
    )
    # A country with no eligible sign up at all still needs a finite value for the optimizer.
    table["mean_budget"] = table["mean_budget"].fillna(
        float(eligible["budget"].mean()) if len(eligible) else 0.0
    )
    return table.reset_index()


def _predict(history: pd.DataFrame, method: str) -> pd.Series:
    """Predict the twelve months after the last year in `history` for one country."""
    by_year = history.pivot(index="month", columns="year", values="eligible").sort_index(axis=1)
    if method == "last_year" or by_year.shape[1] == 1:
        return by_year.iloc[:, -1].astype(float)
    if method == "seasonal_mean":
        return by_year.mean(axis=1)
    totals = by_year.sum(axis=0)
    growth = float(totals.iloc[-1] / totals.iloc[-2]) if totals.iloc[-2] > 0 else 1.0
    return by_year.mean(axis=1) * growth ** ((by_year.shape[1] + 1) / 2)


def _mape(actual: pd.Series, predicted: pd.Series) -> float:
    mask = actual > 0
    return float((abs(actual[mask] - predicted[mask]) / actual[mask]).mean() * 100) if mask.any() else 0.0


def backtest(dataset: Dataset) -> pd.DataFrame:
    """Mean absolute percentage error of each method on the last history year."""
    years = dataset.history_years
    history = monthly_history(dataset)
    rows = []
    for country, frame in history.groupby("country"):
        train = frame[frame["year"] < years[-1]]
        actual = frame[frame["year"] == years[-1]].set_index("month")["eligible"].astype(float)
        for method in METHODS:
            if train["year"].nunique() < 1:
                continue
            rows.append(
                {"country": country, "method": method, "mape": _mape(actual, _predict(train, method))}
            )
    return pd.DataFrame(rows)


def _pick_method(scores: pd.DataFrame) -> str:
    """Lowest mean error wins; near ties go to the method that uses the most history."""
    if scores.empty:
        return "last_year"
    error = scores.groupby("method")["mape"].mean()
    best = error.min()
    for method in ("seasonal_mean", "last_year", "seasonal_trend"):
        if method in error and error[method] <= best + 0.5:
            return method
    return str(error.idxmin())


@dataclass
class Forecast:
    """Monthly eligible demand for the planning year plus lookahead months."""

    year: int
    method: str
    monthly: pd.DataFrame  # country, month_index (1 based, may exceed 12), demand, mean_budget
    backtest: pd.DataFrame

    def demand(self, country: str) -> np.ndarray:
        frame = self.monthly[self.monthly["country"] == country].sort_values("month_index")
        return frame["demand"].to_numpy(dtype=float)

    def mean_budget(self, country: str) -> np.ndarray:
        frame = self.monthly[self.monthly["country"] == country].sort_values("month_index")
        return frame["mean_budget"].to_numpy(dtype=float)


def build_forecast(dataset: Dataset, year: int, lookahead_months: int = 3, method: str = "auto") -> Forecast:
    scores = (
        backtest(dataset)
        if len(dataset.history_years) > 1
        else pd.DataFrame(columns=["country", "method", "mape"])
    )
    if method == "auto":
        method = _pick_method(scores)
        if not scores.empty:
            log.info(
                "Forecast method %s (mean backtest error %.1f%%)",
                method,
                float(scores[scores["method"] == method]["mape"].mean()),
            )
    history = monthly_history(dataset)
    rows = []
    for country, frame in history.groupby("country"):
        prediction = _predict(frame, method)
        budget = frame.groupby("month")["mean_budget"].mean()
        for index in range(1, 13 + lookahead_months):
            month = (index - 1) % 12 + 1
            rows.append(
                {
                    "country": country,
                    "month_index": index,
                    "demand": max(float(prediction.loc[month]), 0.0),
                    "mean_budget": float(budget.loc[month]),
                }
            )
    return Forecast(year=year, method=method, monthly=pd.DataFrame(rows), backtest=scores)


def horizon_days(year: int, months: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(year=year, month=1, day=1)
    return pd.date_range(start, start + pd.DateOffset(months=months) - pd.Timedelta(days=1), freq="D")


def month_of_day(year: int, months: int) -> np.ndarray:
    """Zero based month index for each day of the horizon."""
    days = horizon_days(year, months)
    return ((days.year - year) * 12 + days.month - 1).to_numpy()


@dataclass
class DemandStream:
    """Advertisers arriving each day, as an array of projected budgets per day."""

    budgets_by_day: list[np.ndarray]
    initial_pool: list[tuple[int, float]]  # (arrival day relative to 1 January, budget)

    @property
    def daily_counts(self) -> np.ndarray:
        return np.array([len(day) for day in self.budgets_by_day], dtype=int)


def _round_preserving_total(values: np.ndarray, rng: np.random.Generator | None) -> np.ndarray:
    floor = np.floor(values)
    remainder = values - floor
    missing = int(round(values.sum() - floor.sum()))
    if missing > 0:
        if rng is None:
            order = np.argsort(-remainder, kind="stable")[:missing]
        else:
            order = rng.choice(len(values), size=missing, replace=False, p=remainder / remainder.sum())
        floor[order] += 1
    return floor.astype(int)


def demand_stream(
    dataset: Dataset,
    forecast: Forecast,
    country: str,
    months: int = 12,
    multipliers: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
    bootstrap: bool = False,
    carryover_days: int = 0,
) -> DemandStream:
    """Turn monthly totals into daily arrivals with budgets drawn from history.

    Without `bootstrap` the daily shape of the last history year is reused and the
    result is deterministic. With `bootstrap` each day count is resampled from the
    same calendar month in any history year, which keeps the heavy day to day noise
    seen in the data (coefficient of variation near 0.7).
    """
    rng = rng or np.random.default_rng(0)
    totals = forecast.demand(country)[:months].copy()
    if multipliers is not None:
        totals = totals * multipliers[:months]
    days = horizon_days(forecast.year, months)
    month_index = month_of_day(forecast.year, months)
    history = dataset.eligible(country)
    budgets_pool = history["budget"].to_numpy(dtype=float)
    last_year = dataset.history_years[-1]
    reference = dataset.daily_eligible_counts(country, last_year).astype(float)
    reference_days = pd.date_range(f"{last_year}-01-01", f"{last_year}-12-31", freq="D")
    counts = np.zeros(len(days), dtype=int)
    for m in range(months):
        day_slots = np.flatnonzero(month_index == m)
        calendar_month = days[day_slots[0]].month
        if bootstrap:
            pool = [
                dataset.daily_eligible_counts(country, y)[
                    pd.date_range(f"{y}-01-01", f"{y}-12-31").month == calendar_month
                ]
                for y in dataset.history_years
            ]
            shape = rng.choice(np.concatenate(pool), size=len(day_slots), replace=True).astype(float)
        else:
            ref = reference[reference_days.month == calendar_month]
            positions = np.linspace(0, len(ref) - 1, len(day_slots)).round().astype(int)
            shape = ref[positions]
        shape = shape if shape.sum() > 0 else np.ones(len(day_slots))
        expected = totals[m] * shape / shape.sum()
        counts[day_slots] = _round_preserving_total(expected, rng if bootstrap else None)
    if budgets_pool.size == 0:
        budgets_pool = np.array([0.0])
    budget_rng = rng if bootstrap else np.random.default_rng(zlib.crc32(country.encode("utf-8")))
    budgets = [budget_rng.choice(budgets_pool, size=c, replace=True) if c else np.empty(0) for c in counts]
    initial: list[tuple[int, float]] = []
    if carryover_days:
        tail = history[
            history["signup_date"] > pd.Timestamp(f"{last_year}-12-31") - pd.Timedelta(days=carryover_days)
        ]
        start = pd.Timestamp(f"{forecast.year}-01-01")
        offset = (start - pd.Timestamp(f"{last_year + 1}-01-01")).days
        initial = [
            (int((d - pd.Timestamp(f"{last_year + 1}-01-01")).days) - offset, float(b))
            for d, b in zip(tail["signup_date"], tail["budget"], strict=True)
        ]
    return DemandStream(budgets, initial)
