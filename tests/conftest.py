"""Synthetic data so the tests run anywhere, without the teaching team file.

The years are deliberately unusual (2031 and 2032) to prove nothing depends on the
real calendar years.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from staffpilot.config import load_settings
from staffpilot.data import Dataset


@pytest.fixture(autouse=True, scope="session")
def _logs_outside_the_repository(tmp_path_factory):
    # Tests must not add their runs (on synthetic countries) to the real logs/ folder.
    mp = pytest.MonkeyPatch()
    mp.setenv("STAFFPILOT_LOG_DIR", str(tmp_path_factory.mktemp("logs")))
    mp.setenv("STAFFPILOT_OFFLINE", "1")
    mp.setenv("STAFFPILOT_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
    yield
    mp.undo()


COUNTRIES = pd.DataFrame(
    {
        "Country": ["Alpha", "Beta", "Gamma"],
        "Annual_Agent_Salary_USD": [60000, 30000, 45000],
        "Advertiser_Eligibility_Threshold_USD": [20000, 8000, 15000],
    }
)
STAFFING = pd.DataFrame({"Country": ["Alpha", "Beta", "Gamma"], "Existing_Agent_Count": [40, 5, 25]})


def make_signups(years: tuple[int, ...] = (2031, 2032), seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    rates = {"Alpha": 18, "Beta": 9, "Gamma": 6}
    for year in years:
        for day in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"):
            season = 1.0 + 0.4 * (day.month >= 10)
            for country, rate in rates.items():
                count = rng.poisson(rate * season)
                rows.extend((country, day, float(b)) for b in rng.lognormal(9.8, 0.8, size=count))
    frame = pd.DataFrame(rows, columns=["Country", "Sign_Up_Date", "Projected_Annual_Budget"])
    frame.insert(0, "Advertiser_ID", [f"A{i:06d}" for i in range(len(frame))])
    return frame


@pytest.fixture(scope="session")
def signups() -> pd.DataFrame:
    return make_signups()


@pytest.fixture(scope="session")
def dataset(signups: pd.DataFrame) -> Dataset:
    return Dataset.from_frames(COUNTRIES, STAFFING, signups)


@pytest.fixture(scope="session")
def settings():
    return load_settings().with_updates(planning={"monte_carlo_runs": 3, "lookahead_months": 2})


@pytest.fixture(scope="session")
def planner(settings, dataset):
    from staffpilot.planner import Planner

    return Planner(settings, dataset)
