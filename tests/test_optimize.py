from __future__ import annotations

import io
from pathlib import Path
import re
import tokenize

import numpy as np
import pytest

from staffpilot.optimize import path_from_targets
from staffpilot.planner import POLICIES


def test_hire_is_active_one_month_after_the_decision(settings):
    plan = path_from_targets(
        "Alpha", 10, np.array([10, 10, 15, 15]), 60000, settings.rules, settings.assumptions, "x"
    )
    assert plan.hires.tolist() == [0, 5, 0, 0]
    assert plan.active.tolist() == [10, 10, 15, 15]
    assert plan.payroll().tolist() == [10, 15, 15, 15]  # the trainee is paid in the ramp up month


def test_notice_leaves_one_month_later_and_costs_forty_percent(settings):
    plan = path_from_targets(
        "Alpha", 10, np.array([10, 6, 6, 6]), 60000, settings.rules, settings.assumptions, "x"
    )
    assert plan.notices.tolist() == [4, 0, 0, 0]
    assert plan.active.tolist() == [10, 6, 6, 6]
    assert plan.fire_cost()[0] == pytest.approx(4 * 0.40 * 60000)


def test_every_policy_produces_a_full_year(planner):
    for policy in POLICIES:
        table = planner.run(policy).plan_table()
        assert len(table) == 12 * len(planner.countries)
        assert table["active_agents"].min() >= 0


def test_optimized_plan_respects_capacity_day_by_day(planner):
    kpis = planner.run("optimized").kpi_table()
    assert kpis["max_overflow"].max() <= 0


def test_optimized_plan_beats_keeping_january_headcount(planner):
    comparison = planner.compare_policies(policies=("hold", "optimized"))
    values = dict(zip(comparison["policy"], comparison["net_value"], strict=True))
    assert values["optimized"] >= values["hold"]


def test_service_floor_is_met_in_simulation(planner):
    kpis = planner.run("service_98").kpi_table()
    assert (kpis["service_rate"] >= 0.98 - 0.005).all()


def test_scenario_with_lower_demand_needs_fewer_agents(planner):
    from staffpilot.scenarios import ScenarioParams

    result = planner.scenario(ScenarioParams(countries=["Alpha"], demand_multiplier=0.6))
    row = result.comparison.iloc[0]
    assert row["avg_active_scenario"] <= row["avg_active_base"]


def test_sensitivity_covers_volume_scenarios(planner):
    frame = planner.sensitivity(scales=(0.8, 1.0, 1.2), countries=["Beta"])
    assert set(frame["demand_scale"]) == {0.8, 1.0, 1.2}
    assert set(frame["plan"]) == {"current plan", "replanned"}


def test_monte_carlo_returns_one_row_per_run(planner):
    frame = planner.monte_carlo(runs=3, countries=["Gamma"])
    assert len(frame) == 3
    assert frame["service_rate"].between(0, 1).all()


def test_source_code_has_no_hard_coded_years():
    """Years must come from the data, so code tokens (not comments or docstrings) may not contain one."""
    pattern = re.compile(r"\b20[23]\d\b")
    # Not a calendar year of the data: the version string Anthropic's API requires in a header.
    allowed = {'"2023-06-01"'}
    # From Python 3.12 a formatted string literal is split into several tokens, its text being FSTRING_MIDDLE
    # (TSTRING_MIDDLE for 3.14 template strings). Scanning those too makes the check behave
    # the same on every version; before, 3.11 saw years in formatted strings that 3.12 missed.
    text_tokens = {tokenize.NUMBER, tokenize.STRING} | {
        getattr(tokenize, name) for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE") if hasattr(tokenize, name)
    }
    offenders = []
    for path in Path(__file__).resolve().parents[1].joinpath("src", "staffpilot").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        previous = tokenize.NEWLINE
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            is_docstring = token.type == tokenize.STRING and previous in (
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.NL,
            )
            if (
                token.type in text_tokens
                and not is_docstring
                and pattern.search(token.string)
                and token.string not in allowed
                # The copyright notice states when the code was written, not a planning year.
                and "Copyright" not in token.string
            ):
                offenders.append(f"{path.name}:{token.start[0]} {token.string[:40]}")
            if token.type not in (tokenize.COMMENT, tokenize.NL):
                previous = token.type
    assert not offenders, offenders


def test_countries_do_not_share_agents(planner):
    """Removing every agent in one country must not change another country's plan or service."""
    from staffpilot.scenarios import ScenarioParams

    base = planner.run("optimized").kpi_table().set_index("country")
    result = planner.scenario(ScenarioParams(countries=["Alpha"], demand_multiplier=0.1))
    assert set(result.comparison["country"]) == {"Alpha"}
    again = planner.run("optimized").kpi_table().set_index("country")
    assert again.loc["Beta", "served"] == base.loc["Beta", "served"]


def test_recommended_plan_serves_every_country(planner):
    from staffpilot.planner import RECOMMENDED_POLICY

    kpis = planner.run(RECOMMENDED_POLICY).kpi_table()
    assert (kpis["service_rate"] >= 0.975).all()
    assert "agents_in_notice" in planner.run(RECOMMENDED_POLICY).plan_table().columns


def test_country_with_no_eligible_sign_ups_still_plans(settings, signups):
    from staffpilot.data import Dataset
    from staffpilot.planner import Planner
    from tests.conftest import COUNTRIES, STAFFING

    countries = COUNTRIES.copy()
    countries.loc[countries["Country"] == "Gamma", "Advertiser_Eligibility_Threshold_USD"] = 1e12
    plan = Planner(settings, Dataset.from_frames(countries, STAFFING, signups)).run("optimized", ["Gamma"])
    assert plan.kpi_table().loc[0, "arrivals"] == 0
