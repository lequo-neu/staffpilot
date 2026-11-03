"""Swapping in the official file (other years, same structure) must only change the year labels."""

from __future__ import annotations

import pandas as pd
import pytest

from staffpilot.data import Dataset
from staffpilot.planner import Planner
from tests.conftest import COUNTRIES, STAFFING


def test_shifting_every_date_one_year_back_gives_the_same_plan(settings, signups, planner):
    shifted = signups.copy()
    shifted["Sign_Up_Date"] = shifted["Sign_Up_Date"] - pd.DateOffset(years=1)
    earlier = Planner(settings, Dataset.from_frames(COUNTRIES, STAFFING, shifted))
    assert earlier.year == planner.year - 1

    original, moved = planner.run("optimized").totals(), earlier.run("optimized").totals()
    # Week boundaries move with the calendar (2032 is a leap year), so allow small differences.
    for key in ("net_value", "avg_active", "service_rate", "hires", "notices"):
        assert moved[key] == pytest.approx(original[key], rel=0.03, abs=3), key
    labels = earlier.run("optimized").plan_table()["month"]
    assert labels.iloc[0] == f"{earlier.year}-01"
