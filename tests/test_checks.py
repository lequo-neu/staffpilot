"""The evidence a manager can check: the plan checks, the value breakdown and a typed in plan."""

from __future__ import annotations

import numpy as np
import pytest

from staffpilot import checks
from staffpilot.planner import RECOMMENDED_POLICY


def test_the_plan_passes_every_rule_check_with_its_numbers(planner):
    found = checks.plan_checks(planner, RECOMMENDED_POLICY)
    by_title = {c.title.split(":")[0]: c for c in found}
    assert all(c.passed for c in found if c.passed is not None), [c for c in found if c.passed is False]
    assert "No agent holds more than 10 advertisers on any day" in by_title
    assert "Service goal" in by_title and "within 60 days" in by_title["Service goal"].title
    assert any("CBC proved optimality for 3 of 3 countries" in c.detail for c in found)
    assert any(c.title == "It holds up on real sign ups it never saw" for c in found)
    assert any(c.passed is None and "fewer agents from February" in c.detail for c in found)
    one = checks.plan_checks(planner, "service_98_7d", "Alpha")
    assert all("real sign ups" not in c.title for c in one)
    assert any("within 7 days" in c.title for c in one)


def test_a_broken_plan_fails_the_timing_check(planner):
    plan = planner.run(RECOMMENDED_POLICY).outcomes["Alpha"].plan
    saved = plan.active.copy()
    try:
        plan.active[4] += 3  # three agents appear with no hire behind them
        timing = next(
            c for c in checks.plan_checks(planner, RECOMMENDED_POLICY, "Alpha", False) if "ramp" in c.title
        )
        assert timing.passed is False
    finally:
        plan.active[:] = saved


def test_net_value_is_rebuilt_from_its_inputs(planner):
    for country in (None, "Beta"):
        b = checks.value_breakdown(planner, RECOMMENDED_POLICY, country)
        assert b["served"] * b["mean_budget"] * b["uplift_rate"] == pytest.approx(b["uplift"])
        assert b["payroll_agent_months"] * b["salary_per_agent_month"] == pytest.approx(b["salary_cost"])
        assert b["notices"] * b["salary_per_notice"] * b["fire_cost_share"] == pytest.approx(b["notice_cost"])
        bundle = planner.run(RECOMMENDED_POLICY)
        expected = bundle.outcomes[country].kpis["net_value"] if country else bundle.totals()["net_value"]
        assert b["net_value"] == pytest.approx(expected)
    detail = checks.monthly_detail(planner, RECOMMENDED_POLICY, "Beta")
    assert len(detail) == 12 and (detail["slots"] == detail["agents_at_work"] * 10).all()
    assert detail["salary_cost"].sum() == pytest.approx(b["salary_cost"])


def test_a_typed_in_plan_is_scored_by_the_same_simulator(planner):
    best = planner.run(RECOMMENDED_POLICY).outcomes["Alpha"]
    same = checks.compare_manual(planner, "Alpha", best.plan.active[:12], RECOMMENDED_POLICY)
    assert same.manual.kpis["net_value"] == pytest.approx(best.kpis["net_value"])
    assert "Your plan is the optimized plan" in same.summary()
    more = best.plan.active[:12].copy()
    more[1:] += 5
    richer = checks.compare_manual(planner, "Alpha", more, RECOMMENDED_POLICY)
    assert richer.manual.kpis["net_value"] < best.kpis["net_value"] and "less" in richer.summary()
    january = best.plan.active[:12].copy()
    january[0] += 10  # January cannot change: decisions take a month
    moved = checks.compare_manual(planner, "Alpha", january, RECOMMENDED_POLICY)
    assert moved.moved_by_lead_times()[0] == "Jan" and "Not possible as typed" in moved.summary()
    with pytest.raises(ValueError):
        planner.score_plan("Alpha", [1.0] * 11)
    with pytest.raises(ValueError):
        planner.score_plan("Atlantis", np.ones(12))


def test_plan_page_tabs(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    html = app.check_view("All countries")
    assert "checks pass" in html and "Pass" in html and "Fail" not in html
    text, table, file = app.breakdown_view("Beta", "optimized")
    assert "Net value = uplift" in text and len(table) == 12 and file.visible
    assert (tmp_path / "plan_detail_Beta.csv").exists()
    inputs = app.manual_inputs("Beta", RECOMMENDED_POLICY, 10)
    assert inputs["Yours"].iloc[0] == inputs["Optimized"].iloc[0] and len(inputs) == 12
    assert app.manual_inputs("All countries").empty
    summary, chart = app.manual_score("Beta", RECOMMENDED_POLICY, inputs)
    assert "Net value" in summary and chart is not None
    assert app.manual_score("All countries", RECOMMENDED_POLICY, inputs)[0].startswith("Pick one country")
    # Every month must hold a whole number of agents, 0 or more; the message names the months to fix.
    for wrong in ("x", -3, 2.5, None):
        bad = inputs.assign(Yours=[*inputs["Yours"].iloc[:11], wrong])
        message, chart = app.manual_score("Beta", RECOMMENDED_POLICY, bad)
        assert message.startswith("Type a whole number") and "Dec" in message and chart is None
