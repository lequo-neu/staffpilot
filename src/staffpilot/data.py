"""Load the advertiser sign up dataset and apply the eligibility rule.

Nothing here assumes particular years. The planning year is derived from the data,
so the course dataset (2024 to 2025) and a file with the brief's years (2023 to 2024)
both work without code changes.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field, replace
import hashlib
import logging
from pathlib import Path
import re

import numpy as np
import pandas as pd

from staffpilot.config import Settings


log = logging.getLogger(__name__)


COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "country": ("country", "market"),
    "salary": ("annualagentsalaryusd", "annualsalary", "salary", "agentsalary"),
    "threshold": ("advertisereligibilitythresholdusd", "eligibilitythreshold", "threshold"),
    "agents": ("existingagentcount", "agentcount", "agents", "headcount"),
    "advertiser_id": ("advertiserid", "id"),
    "signup_date": ("signupdate", "dateofsignup", "date"),
    "budget": ("projectedannualbudget", "projectedbudget", "budget"),
}
COUNTRY_TABLE = ("country", "salary", "threshold")
STAFFING_TABLE = ("country", "agents")
SIGNUP_TABLE = ("advertiser_id", "country", "signup_date", "budget")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


class DatasetError(ValueError):
    """Raised when the input file does not contain the tables the brief describes."""


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    lookup = {_normalise(col): col for col in frame.columns}
    mapping = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup and lookup[alias] not in mapping:
                mapping[lookup[alias]] = canonical
                break
    return frame.rename(columns=mapping)


def _has(frame: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    return all(col in frame.columns for col in columns)


def parse_signup_dates(values: pd.Series) -> pd.Series:
    """Parse sign up dates and repair impossible calendar days.

    The course dataset has 920 sign ups dated 2025-02-29, a day that does not exist,
    so they arrive as text. Such a day is moved to the last valid day of its month so
    the sign up still counts in the right month.
    """

    repaired = 0

    def repair(value: object) -> object:
        nonlocal repaired
        if isinstance(value, str):
            match = _ISO_DATE.match(value.strip())
            if match:
                year, month, day = (int(part) for part in match.groups())
                last = calendar.monthrange(year, month)[1]
                if day > last:
                    repaired += 1
                return pd.Timestamp(year=year, month=month, day=min(day, last))
        return value

    parsed = pd.to_datetime(values.map(repair), errors="coerce")
    if parsed.isna().any():
        bad = values[parsed.isna()].head(3).tolist()
        raise DatasetError(f"Unreadable sign up dates, for example {bad}")
    if repaired:
        # INFO, not WARNING: the data alert and the EDA report already show this to the user.
        log.info(
            "Moved %d impossible sign up dates (such as 29 February in a normal year) to the end of the month",
            repaired,
        )
    parsed = parsed.dt.normalize()
    parsed.attrs["repaired_dates"] = repaired
    return parsed


@dataclass
class Dataset:
    """Country table and sign ups, with eligibility already applied."""

    countries: pd.DataFrame
    signups: pd.DataFrame
    source: str = "in memory"
    eligibility: str = "greater"
    threshold_multipliers: dict[str, float] = field(default_factory=dict)
    repaired_dates: int = 0

    def fingerprint(self) -> str:
        """A short hash of the content, used to key cached plans."""
        cached = getattr(self, "_fingerprint", None)
        if cached is None:
            parts = [
                pd.util.hash_pandas_object(self.signups, index=True).sum(),
                pd.util.hash_pandas_object(self.countries, index=True).sum(),
                self.eligibility,
            ]
            cached = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:20]
            object.__setattr__(self, "_fingerprint", cached)
        return cached

    @property
    def country_names(self) -> list[str]:
        return list(self.countries.index)

    @property
    def history_years(self) -> list[int]:
        return sorted(int(y) for y in self.signups["signup_date"].dt.year.unique())

    def planning_year(self, configured: int = 0) -> int:
        return configured or self.history_years[-1] + 1

    def eligible(self, country: str | None = None, year: int | None = None) -> pd.DataFrame:
        frame = self.signups[self.signups["eligible"]]
        if country is not None:
            frame = frame[frame["country"] == country]
        if year is not None:
            frame = frame[frame["signup_date"].dt.year == year]
        return frame

    def daily_eligible_counts(self, country: str, year: int) -> np.ndarray:
        days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        counts = self.eligible(country, year).groupby("signup_date").size()
        return counts.reindex(days, fill_value=0).to_numpy(dtype=int)

    def with_thresholds(self, multipliers: dict[str, float]) -> Dataset:
        """Return a copy where some country thresholds are scaled (used by scenarios)."""
        countries = self.countries.copy()
        for country, factor in multipliers.items():
            countries.loc[country, "threshold"] = countries.loc[country, "threshold"] * factor
        signups = self.signups.drop(columns=["eligible"])
        return replace(
            self,
            countries=countries,
            signups=_flag_eligible(signups, countries, self.eligibility),
            threshold_multipliers={**self.threshold_multipliers, **multipliers},
        )

    @classmethod
    def from_frames(
        cls,
        countries: pd.DataFrame,
        staffing: pd.DataFrame,
        signups: pd.DataFrame,
        eligibility: str = "greater",
        source: str = "in memory",
    ) -> Dataset:
        countries = _rename_columns(countries)
        staffing = _rename_columns(staffing)
        signups = _rename_columns(signups)
        for frame, columns, label in (
            (countries, COUNTRY_TABLE, "salary and threshold"),
            (staffing, STAFFING_TABLE, "existing staffing"),
            (signups, SIGNUP_TABLE, "advertiser sign ups"),
        ):
            if not _has(frame, columns):
                raise DatasetError(f"The {label} table needs columns {columns}, found {list(frame.columns)}")
        table = countries[list(COUNTRY_TABLE)].merge(staffing[list(STAFFING_TABLE)], on="country", how="left")
        if table["agents"].isna().any():
            missing = table.loc[table["agents"].isna(), "country"].tolist()
            raise DatasetError(f"No January headcount for {missing}")
        table = table.astype({"salary": float, "threshold": float, "agents": int}).set_index("country")
        clean = signups[list(SIGNUP_TABLE)].copy()
        clean["advertiser_id"] = clean["advertiser_id"].astype(str)
        clean["country"] = clean["country"].astype(str).str.strip()
        dates = parse_signup_dates(clean["signup_date"])
        repaired = int(dates.attrs.get("repaired_dates", 0))
        clean["signup_date"] = dates
        clean["budget"] = clean["budget"].astype(float)
        unknown = sorted(set(clean["country"]) - set(table.index))
        if unknown:
            raise DatasetError(f"Sign ups reference countries without salary data: {unknown}")
        flagged = _flag_eligible(clean, table, eligibility)
        log.info(
            "Loaded %d sign ups for %d countries from %s; %d eligible",
            len(flagged),
            len(table),
            Path(source).name,
            int(flagged["eligible"].sum()),
        )
        return cls(table, flagged, source=source, eligibility=eligibility, repaired_dates=repaired)


def _flag_eligible(signups: pd.DataFrame, countries: pd.DataFrame, rule: str) -> pd.DataFrame:
    threshold = signups["country"].map(countries["threshold"])
    out = signups.copy()
    out["eligible"] = out["budget"] > threshold if rule == "greater" else out["budget"] >= threshold
    return out


def _find_table(tables: dict[str, pd.DataFrame], preferred: str, columns: tuple[str, ...]) -> pd.DataFrame:
    if preferred in tables and _has(_rename_columns(tables[preferred]), columns):
        return tables[preferred]
    for frame in tables.values():
        if _has(_rename_columns(frame), columns) and len(frame.columns) <= len(columns) + 2:
            return frame
    raise DatasetError(f"No sheet or file with columns {columns}")


def load_dataset(settings: Settings, path: str | Path | None = None) -> Dataset:
    """Read the workbook or CSV folder named in the settings."""
    source = Path(path) if path else settings.data_path()
    if not source.exists():
        raise DatasetError(
            f"Dataset not found at {source}. Put the teaching team file there or set [data] path in config/staffpilot.toml."
        )
    if source.is_dir():
        tables = {p.stem: pd.read_csv(p) for p in sorted(source.glob("*.csv"))}
    else:
        # Reading the workbook is the slowest step of a start, so its sheets are cached
        # until the file changes (its path, size or modification time).
        from staffpilot import cache

        tables = cache.cached(
            "workbook", cache.file_key(source), lambda: pd.read_excel(source, sheet_name=None)
        )
    signups = _find_table(tables, settings.data.signup_sheet, SIGNUP_TABLE)
    countries = _find_table(tables, settings.data.salary_sheet, ("country", "salary", "threshold"))
    staffing = _find_table(tables, settings.data.staffing_sheet, STAFFING_TABLE)
    return Dataset.from_frames(countries, staffing, signups, settings.rules.eligibility, source=str(source))
