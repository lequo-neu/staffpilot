"""Manager tools without a language model: policy comparison, sensitivity, the step by step
scenario and the country inputs. Every number must come from the planner or the dataset."""

from __future__ import annotations

import pandas as pd
import pytest

from staffpilot import charts, manager
from staffpilot.planner import POLICIES, RECOMMENDED_POLICY
from staffpilot.scenarios import DemandChange


def test_policy_comparison_is_the_planners_own(planner):
    frame = manager.policy_comparison(planner)
    expected = planner.compare_policies(None, POLICIES)
    assert list(frame["policy"]) == list(POLICIES)
    pd.testing.assert_series_equal(frame["net_value"], expected["net_value"])

    table = manager.policy_table(frame)
    assert len(table) == len(POLICIES)
    assert table.iloc[0]["Net value"] == charts.money(frame["net_value"].max())
    assert {"Against the January team", "Eligible served", "Average agents", "Notices"} <= set(table.columns)
    assert (table["Policy"] == "Keep January headcount").sum() == 1

    lines = manager.policy_takeaways(frame)
    text = " ".join(lines)
    assert lines[0].startswith("**Most value:**")
    assert "service promise" in text and "Keeping the January team" in text
    assert "Following last month's demand" in text and "One cut to the yearly peak" in text
    hold = frame.set_index("policy").loc["hold"]
    assert f"{hold['avg_active']:,.0f} agents" in text


def test_policy_comparison_for_one_country(planner):
    frame = manager.policy_comparison(planner, ["Beta"])
    beta = planner.run(RECOMMENDED_POLICY).outcomes["Beta"].kpis["net_value"]
    recommended = frame.set_index("policy").loc[RECOMMENDED_POLICY, "net_value"]
    assert recommended == pytest.approx(beta)


def test_sensitivity_uses_the_planner_and_is_kept(planner):
    frame = manager.sensitivity(planner, ["Alpha"])
    expected = planner.sensitivity(manager.SENSITIVITY_SCALES, ["Alpha"], RECOMMENDED_POLICY)
    pd.testing.assert_frame_equal(frame.reset_index(drop=True), expected.reset_index(drop=True))
    again = manager.sensitivity(planner, ["Alpha"])
    pd.testing.assert_frame_equal(frame, again)

    table = manager.sensitivity_table(frame)
    assert list(table["Sign ups"]) == ["30% fewer sign ups", "As forecast", "30% more sign ups"]
    assert table.loc[1, "Gain from rebuilding"] == "same"
    lines = manager.sensitivity_takeaways(frame)
    assert lines[0].startswith("**30% fewer sign ups:**") and lines[1].startswith("**30% more sign ups:**")
    assert lines[-1].startswith("**What it means:**") and "Monthly update" in lines[-1]


def test_periods_and_months():
    assert manager.chosen_months("All year") == []
    assert manager.chosen_months("Q3 (July to September)") == [7, 8, 9]
    assert manager.chosen_months(manager.CUSTOM, ["March", "January", "March"]) == [1, 3]
    with pytest.raises(manager.ScenarioChoiceError, match="at least one month"):
        manager.chosen_months(manager.CUSTOM, [])
    with pytest.raises(manager.ScenarioChoiceError):
        manager.chosen_months("Next spring")


def test_build_params_one_and_two_changes():
    first = manager.demand_change(["Alpha"], "Q4 (October to December)", None, 20)
    params = manager.build_params(first)
    assert params.countries == ["Alpha"] and params.months == [10, 11, 12]
    assert params.demand_multiplier == pytest.approx(1.2) and params.replan and not params.adjustments
    assert params.plain() == "If sign ups rise 20% from October to December in Alpha, and we rebuild the plan"

    kept = manager.build_params(first, rebuild=False)
    assert kept.replan is False and kept.plain().endswith("and we keep the current plan")

    second = manager.demand_change(["Beta"], "All year", None, -10)
    both = manager.build_params(first, second)
    assert [a.countries for a in both.adjustments] == [["Alpha"], ["Beta"]]
    assert both.demand_multiplier == 1.0 and both.all_countries() == ["Alpha", "Beta"]
    assert "sign ups in Beta fall 10%" in both.plain()

    # A second change left at 0 percent is skipped; no change at all cannot run.
    skipped = manager.build_params(first, DemandChange(multiplier=1.0))
    assert not skipped.adjustments and skipped.demand_multiplier == pytest.approx(1.2)
    with pytest.raises(manager.ScenarioChoiceError, match="slider is at 0%"):
        manager.build_params(manager.demand_change([], "All year", None, 0))
    with pytest.raises(manager.ScenarioChoiceError):
        manager.demand_change([], "All year", None, 500)


def test_country_inputs_match_the_dataset(planner):
    frame = manager.country_inputs(planner)
    countries = planner.dataset.countries
    assert list(frame["Country"]) == sorted(countries.index)
    alpha = frame.set_index("Country").loc["Alpha"]
    assert alpha["Agent salary a year"] == countries.loc["Alpha", "salary"]
    assert alpha["Eligibility threshold"] == countries.loc["Alpha", "threshold"]
    assert alpha["Agents on 1 January"] == countries.loc["Alpha", "agents"]
    years = [c for c in frame.columns if c.startswith("Eligible sign ups")]
    assert years == [f"Eligible sign ups {y}" for y in planner.dataset.history_years]
    assert frame[years].to_numpy().sum() == len(planner.dataset.eligible())
    assert frame["Share eligible"].between(0, 1).all()
    assert "countries** start the year with" in manager.country_summary(frame)


def test_assumptions_read_the_settings(planner):
    table = manager.assumptions(planner)
    shown = table.set_index("Assumption")["Used in the plan"]
    rules = planner.settings.rules
    assert shown["Advertisers per agent"] == f"At most {rules.capacity_per_agent} at a time"
    assert shown["Value of support"].startswith(f"{rules.expected_uplift:.1%}")
    assert "strictly greater" in shown["Who gets support"]
    assert table["Why it matters"].str.len().gt(20).all()


def test_manager_pages_in_the_app(planner, tmp_path, monkeypatch):
    from staffpilot import app
    from staffpilot.ui import icon

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    assert {"Compare policies", "Country inputs"} <= set(app.PAGES)
    assert all(page in icon.NAV_ICONS for page in app.PAGES)
    assert app.NEXT["Plan"][0] == "Compare policies" and app.NEXT["Compare policies"][0] == "Scenario"

    text, chart, table = app.compare_view("All countries")
    assert "Most value" in text and chart is not None and len(table) == len(POLICIES)
    text, chart, table = app.sensitivity_view("Gamma")
    assert "30% more sign ups" in text and chart is not None and len(table) == 3
    assert app.open_compare("Plan", False, "All countries")[0] is False
    assert app.open_compare("Compare policies", True, "All countries")[1] == app.gr.update()

    summary, styled, assumptions = app.country_view()
    assert "agents" in summary and len(styled.data) == 3 and len(assumptions) > 5
    assert "$60,000" in styled.to_html()
    assert app.open_countries("Data", False)[0] is False


def test_step_by_step_scenario_runs_without_a_model(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    choice = [["Alpha"], "Q4 (October to December)", [], 20, [], "All year", [], 0, manager.REBUILD]
    preview = app.builder_preview(*choice, "service_98_14d")
    assert preview.startswith("**You chose:** If sign ups rise 20% from October to December in Alpha")
    assert "at least 98% served within 14 days" in preview

    summary, chart, diff = app.run_builder(*choice, RECOMMENDED_POLICY)
    assert "net value moves" in summary and "Staffing policy: Profit, at least 98% served" in summary
    assert chart is not None and list(diff.data["Country"]) == ["Alpha"]
    # The run is a manager decision, so it reaches the decision log with the manager as its author.
    log = pd.read_csv(tmp_path / "decision_audit.csv")
    assert (log["decision"] == "scenario run").any() and "manager" in set(log["adjusted_by"].dropna())

    two = [["Alpha"], "All year", [], 20, ["Beta"], manager.CUSTOM, ["March"], -30, manager.KEEP]
    summary, _, diff = app.run_builder(*two, "optimized")
    assert "keep the current plan" in summary and set(diff.data["Country"]) == {"Alpha", "Beta"}

    nothing = [[], "All year", [], 0, [], "All year", [], 0, manager.REBUILD]
    assert app.builder_preview(*nothing, RECOMMENDED_POLICY).startswith("**Not ready yet:**")
    message, chart, table = app.run_builder(*nothing, RECOMMENDED_POLICY)
    assert message.startswith("**Not ready yet:**") and chart is None and table.empty
