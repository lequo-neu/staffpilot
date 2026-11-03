from __future__ import annotations

import pandas as pd
import pytest

from staffpilot.config import load_settings
from staffpilot.data import Dataset, DatasetError, load_dataset, parse_signup_dates
from tests.conftest import COUNTRIES, STAFFING


def _tiny(budgets: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Advertiser_ID": [f"x{i}" for i in range(len(budgets))],
            "Country": "Alpha",
            "Sign_Up_Date": "2031-03-01",
            "Projected_Annual_Budget": budgets,
        }
    )


def test_eligibility_is_strictly_greater_than_threshold():
    data = Dataset.from_frames(COUNTRIES, STAFFING, _tiny([19999, 20000, 20001]))
    assert data.signups["eligible"].tolist() == [False, False, True]


def test_eligibility_can_include_the_threshold():
    data = Dataset.from_frames(
        COUNTRIES, STAFFING, _tiny([19999, 20000, 20001]), eligibility="greater_or_equal"
    )
    assert data.signups["eligible"].tolist() == [False, True, True]


def test_impossible_leap_day_moves_to_end_of_month():
    parsed = parse_signup_dates(pd.Series(["2027-02-29", "2028-02-29", pd.Timestamp("2027-03-01")]))
    assert [d.strftime("%Y-%m-%d") for d in parsed] == ["2027-02-28", "2028-02-29", "2027-03-01"]


def test_planning_year_follows_the_data(dataset):
    assert dataset.history_years == [2031, 2032]
    assert dataset.planning_year() == 2033


def test_workbook_and_csv_folder_load_the_same(tmp_path, signups):
    workbook = tmp_path / "data.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        COUNTRIES.to_excel(writer, sheet_name="Agent Salary and Threshold", index=False)
        signups.head(500).to_excel(writer, sheet_name="Advertiser Sign-ups", index=False)
        STAFFING.to_excel(writer, sheet_name="Existing Agent Staffing", index=False)
    folder = tmp_path / "csv"
    folder.mkdir()
    COUNTRIES.to_csv(folder / "salary.csv", index=False)
    signups.head(500).to_csv(folder / "signups.csv", index=False)
    STAFFING.to_csv(folder / "staffing.csv", index=False)
    settings = load_settings()
    a, b = load_dataset(settings, workbook), load_dataset(settings, folder)
    assert a.signups["eligible"].sum() == b.signups["eligible"].sum()
    assert list(a.countries.index) == ["Alpha", "Beta", "Gamma"]


def test_missing_columns_raise_a_clear_error():
    with pytest.raises(DatasetError, match="sign ups"):
        Dataset.from_frames(COUNTRIES, STAFFING, pd.DataFrame({"Country": ["Alpha"]}))


def test_missing_file_explains_where_to_put_it(tmp_path):
    with pytest.raises(DatasetError, match="Put the teaching team file"):
        load_dataset(load_settings(), tmp_path / "nothing.xlsx")


def test_env_file_adds_keys_without_overriding_the_shell(tmp_path, monkeypatch):
    from staffpilot.config import load_env_file

    env = tmp_path / ".env"
    env.write_text('# comment\nSTAFFPILOT_TEST_A="abc"\nSTAFFPILOT_TEST_B=keep\nEMPTY=\n', encoding="utf-8")
    monkeypatch.delenv("STAFFPILOT_TEST_A", raising=False)
    monkeypatch.setenv("STAFFPILOT_TEST_B", "from shell")
    assert load_env_file(env) == ["STAFFPILOT_TEST_A"]
    import os

    assert os.environ["STAFFPILOT_TEST_A"] == "abc"
    assert os.environ["STAFFPILOT_TEST_B"] == "from shell"


def test_offline_switch_hides_providers(monkeypatch):
    from staffpilot.agent.backends import available_providers

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("STAFFPILOT_OFFLINE", "1")
    assert available_providers() == []
    monkeypatch.setenv("STAFFPILOT_OFFLINE", "0")
    assert "openai" in available_providers()
