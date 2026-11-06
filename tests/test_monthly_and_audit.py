"""Monthly updates, service goals and the decision audit."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from staffpilot import audit
from staffpilot.planner import RECOMMENDED_POLICY, SERVICE_GOALS, policy_label, service_goal
from staffpilot.scenarios import ScenarioParams


def _update(planner, country="Alpha", as_of=4, scale=1.5, change=0, policy=RECOMMENDED_POLICY):
    actual = planner.forecast.demand(country)[: as_of - 1] * scale
    return planner.monthly_update(country, as_of, actual, change, policy)


def test_a_monthly_update_keeps_the_months_done_and_adds_agents_when_demand_rises(planner):
    update = _update(planner, scale=1.5)
    old, new, done = update.original, update.updated.plan, update.done
    assert new.hires[:done].tolist() == old.hires[:done].tolist()
    assert new.notices[:done].tolist() == old.notices[:done].tolist()
    assert new.active[:done].tolist() == old.active[:done].tolist()
    assert new.active[done:12].sum() > old.active[done:12].sum()
    assert update.ratio == pytest.approx(1.5)
    assert update.updated.kpis["service_rate"] >= update.kept.kpis["service_rate"]
    table = update.table()
    assert len(table) == 12 and table["status"].tolist()[:4] == ["carried out"] * 3 + ["decide now"]
    assert table["signups_used"].iloc[0] == round(update.actual[0])
    assert "Decide in April" in update.summary()


def test_lower_demand_and_resignations_are_planned_around(planner):
    lower = _update(planner, scale=0.6)
    assert lower.updated.plan.active[3:12].sum() <= lower.original.active[3:12].sum()
    resigned = _update(planner, scale=1.0, change=-2)
    # The month of the update already has the headcount the past decided, minus the two who left.
    assert resigned.updated.plan.active[3] == resigned.original.active[3] - 2
    assert resigned.kept.plan.active[3] == resigned.original.active[3] - 2
    assert "2 agents fewer than planned" in resigned.summary()


@pytest.mark.parametrize("as_of, scale", [(6, 2.0), (12, 1.5), (12, 2.0)])
def test_a_late_surge_is_planned_even_when_the_goal_can_no_longer_be_met(planner, as_of, scale):
    # The headcount of the update month was set by last month's decisions, so a repair may
    # only add agents from the month after; asking for more in the update month was infeasible.
    for country in planner.countries:
        update = _update(planner, country, as_of=as_of, scale=scale)
        done = update.done
        assert update.updated.plan.active[done] == update.original.active[done]
        assert update.updated.kpis["service_rate"] >= update.kept.kpis["service_rate"] - 1e-9


@pytest.mark.parametrize(
    "as_of, counts", [(1, []), (13, [1.0] * 12), (4, [1.0, 2.0]), (3, [1.0, -5.0]), (3, [1.0, np.nan])]
)
def test_a_monthly_update_rejects_impossible_inputs(planner, as_of, counts):
    with pytest.raises(ValueError):
        planner.monthly_update("Alpha", as_of, counts)


def test_service_goals_are_read_from_the_policy_name():
    assert service_goal("optimized") == (None, None)
    assert service_goal("service_98") == (0.98, None)
    assert service_goal("service_98_7d") == (0.98, 7)
    assert policy_label("service_98_14d") == "Optimized with at least 98 percent served within 14 days"
    for bad in ("service_x", "service_98_10d", "service_40", "service_98_70d"):
        with pytest.raises(ValueError):
            service_goal(bad)


def test_profit_only_against_service_goals(planner):
    frame = planner.service_tradeoff()
    assert frame["policy"].tolist() == list(SERVICE_GOALS)
    assert frame["cost_of_goal"].iloc[0] == 0
    fast = frame.set_index("policy")
    # A tighter wait limit buys faster service; it never makes advertisers wait longer.
    assert fast.loc["service_98_7d", "within_week_rate"] >= fast.loc["optimized", "within_week_rate"]
    assert fast.loc["service_98_7d", "mean_wait_days"] <= fast.loc["service_98", "mean_wait_days"] + 1e-9
    assert fast.loc["service_98_7d", "within_week_rate"] >= 0.97


def test_the_audit_keeps_proposed_adjusted_and_applied_apart(planner, tmp_path):
    bundle = planner.run(RECOMMENDED_POLICY)
    outcome = bundle.outcomes["Alpha"]
    proposed = outcome.plan.active.copy()
    proposed[5] -= 1  # as if the simulator check had raised month 6 by one agent
    repaired = replace(
        bundle, outcomes={"Alpha": replace(outcome, plan=replace(outcome.plan, proposed_active=proposed))}
    )
    rows = audit.plan_rows(repaired, ["Alpha"], "Profit only", "Profit, at least 98% served (recommended)")
    assert rows[0]["item"] == "service goal" and rows[0]["adjusted_by"] == "manager"
    raised = [r for r in rows if r.get("adjusted_by") == "simulator check"]
    assert len(raised) == 1 and raised[0]["proposed"] == raised[0]["applied"] - 1

    read = ScenarioParams(countries=["Beta"], demand_multiplier=0.7, months=[7, 8, 9])
    ran = read.model_copy(update={"demand_multiplier": 0.75})
    totals = {"net_value_change": -1.0, "service_rate_scenario": 0.99, "avg_active_scenario": 12.0}
    rows = audit.scenario_rows(read, ran, "GenAI (test model)", ["router reply repaired: x"], totals)
    by_item = {r["item"]: r for r in rows}
    assert by_item["demand_multiplier"]["proposed"] == "0.7"
    assert by_item["demand_multiplier"]["adjusted_by"] == "manager"
    assert by_item["demand_multiplier"]["applied"] == "0.75"
    assert by_item["months"]["adjusted"] == "" and by_item["months"]["proposed_by"] == "GenAI (test model)"
    assert by_item["net value change"]["proposed_by"] == audit.PLANNER
    assert "router reply repaired" in rows[0]["note"]

    update_rows = audit.update_rows(_update(planner, scale=1.5))
    assert update_rows[0]["item"] == "eligible sign ups" and update_rows[0]["adjusted_by"].startswith(
        "manager"
    )
    assert any(r["item"] == "agents at work" for r in update_rows)

    audit.record(rows, tmp_path)
    audit.record(update_rows, tmp_path)
    frame = audit.read(tmp_path)
    assert list(frame.columns) == audit.COLUMNS and len(frame) == len(rows) + len(update_rows)
    assert "scenario run" in set(frame["decision"]) and audit.read(tmp_path / "none").empty


def test_answers_record_the_guardrails_that_acted(planner):
    from staffpilot.agent import OfflineBackend, StaffPilot

    class Sloppy(OfflineBackend):
        name = "sloppy"

        def compose(self, *args, **kwargs):
            return "Net value moves to {{$41.7M}}."

    answer = StaffPilot(planner, Sloppy()).ask("What if sign ups in Alpha drop 30% in Q3?")
    assert any("number check rejected a draft" in g for g in answer.guardrails)
    assert "the template answer replaced the model's drafts" in answer.guardrails
    row = audit.answer_rows(answer)[0]
    assert row["adjusted_by"] == "number check" and "template answer" in row["applied"]

    class Broken(OfflineBackend):
        name = "broken"

        def route(self, question, countries, history=""):
            raise RuntimeError("network down")

    answer = StaffPilot(planner, Broken()).ask("How many agents does Alpha need?")
    assert any("router failed" in g for g in answer.guardrails)
    assert StaffPilot(planner).ask("How many agents does Alpha need?").guardrails == []


def test_monthly_update_page_and_decision_log(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    inputs = app.actual_inputs("Alpha", "April", 50)
    assert inputs["Month"].tolist() == ["January", "February", "March"]
    assert (inputs["Actual"] >= inputs["Forecast"]).all()
    planned = app.planned_staff("Alpha", "April")
    assert app.staff_input("Alpha", "April")["label"] == "Agents on staff in April"
    summary, chart, table, update = app.update_view("Alpha", "April", inputs, planned - 1, RECOMMENDED_POLICY)
    assert update.headcount_change == -1
    assert "Decide in April" in summary and chart is not None and len(table) == 12
    assert "→" in "".join(table["Agents at work"])
    assert "Approved" in app.approve_update(update)
    saved = list(tmp_path.glob("approved_update_Alpha_*_*.csv"))
    assert len(saved) == 1 and f"{update.year}-04" in saved[0].name
    assert "Update the plan first" in app.approve_update(None)
    for actual, staff in (
        (["x", 1, 2], planned),
        ([1, -2, 2], planned),
        ([1, 2, 2.5], planned),
        ([1, 2, 3], None),
    ):
        bad = app.update_view("Alpha", "April", pd.DataFrame({"Actual": actual}), staff, RECOMMENDED_POLICY)
        assert bad[0].startswith("Every count must be a whole number") and bad[3] is None

    text, figure, frame = app.tradeoff_view("service_98_7d")
    assert "Profit only" in text and "within 7 days" in text and figure is not None and len(frame) == 5
    cards, *_ = app.plan_view("All countries", "optimized")
    assert "Net value" in cards
    assert "Profit only" in app.approve("Alpha", "optimized")
    assert list(tmp_path.glob("approved_plan_Alpha_optimized_*.csv"))
    app.ask("How many agents does Alpha need?", [], "offline", None)
    params, _, proposal = app.parse_scenario("Gamma sign ups rise 20%", "offline")
    assert proposal["reader"].startswith("offline") and proposal["params"]["demand_multiplier"] == 1.2
    app.run_scenario(params, proposal)

    summary, log, file = app.open_log("Decision log")
    decisions = set(log.data["decision"])
    assert {"monthly update approved", "plan approved", "assistant answer", "scenario run"} <= decisions
    assert file.visible and "decisions logged" in summary and "changed by you" in summary
    _, changes, _ = app.log_view("Only changes")
    assert len(changes.data) and (changes.data["adjusted_by"] != "").all()
    _, scenarios, _ = app.log_view("Scenario run")
    assert set(scenarios.data["decision"]) == {"scenario run"}
    assert app.open_log("Plan")[1] == app.gr.update()


def test_the_sidebar_follows_the_managers_year(planner):
    from staffpilot import app

    app.build_app(planner)
    assert app.PAGES[:2] == ["Assistant", app.HOME] and app.PAGES.index("Data") < app.PAGES.index(
        "Monthly update"
    )
    synced = app.nav_sync("Monthly update")
    groups = [names for _, names in app.NAV_GROUPS]
    assert [s.value for s in synced] == [None, None, "Monthly update", None]
    assert len(synced) == len(groups)
    assert all(target in app.PAGES for target, _ in app.NEXT.values())


def test_this_year_shows_the_steps_for_each_moment(planner):
    from staffpilot import app

    app.build_app(planner)
    verdict, rail, *rest = app.home_view("Before the year starts")
    assert "Not approved" in verdict or "Approved" in verdict
    assert "more than keeping the January team" in verdict
    texts, buttons, pages, month = rest[:4], rest[4:8], rest[8], rest[9]
    assert rail.count("sp-rail-month") == 12 and "Decide now" in rail and "Notice" in rail
    assert pages == ["Data", "Plan", "Scenario", "Memo"] and texts[0].startswith("**1. Check the data")
    assert buttons[1].value == "Open Plan" and month == app.gr.update()
    _, rail, *rest = app.home_view("Start of April")
    assert rest[8] == ["Monthly update", "Decision log", "Assistant", "Scenario"]
    assert "plan April onward" in rest[0] and rest[9]["value"] == "April"
    assert rail.count("Carried out") == 3
    assert app.home_if_open("Plan", "Start of April", RECOMMENDED_POLICY) == [app.gr.update()] * 12


def test_monthly_inputs_are_checked_and_updates_build_on_each_other(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    app._APPROVED.clear()
    inputs = app.actual_inputs("Alpha", "March", 20)
    staff = app.planned_staff("Alpha", "March")
    assert "the numbers look consistent" in app.check_inputs("Alpha", "March", inputs, staff)
    odd = inputs.assign(Actual=[inputs["Forecast"].iloc[0] * 3, "x"])
    note = app.check_inputs("Alpha", "March", odd, staff)
    assert "Check this count" in note and "not a count" in note
    assert "Check this number" in app.check_inputs("Alpha", "March", inputs, staff * 2)
    assert "not a count" in app.check_inputs("Alpha", "March", inputs, None)
    assert "not a count" in app.check_inputs("Alpha", "March", inputs.assign(Actual=[1.5, 2]), staff)

    *_, march = app.update_view("Alpha", "March", inputs, staff, RECOMMENDED_POLICY)
    app.approve_update(march)
    april_inputs = app.actual_inputs("Alpha", "April", 0)
    assert april_inputs["Actual"].iloc[:2].tolist() == [round(v) for v in march.actual]
    april_staff = app.planned_staff("Alpha", "April")
    assert april_staff == int(march.updated.plan.active[3])
    assert "update approved in March" in app.check_inputs("Alpha", "April", april_inputs, april_staff)
    *_, april = app.update_view("Alpha", "April", april_inputs, april_staff, RECOMMENDED_POLICY)
    # April starts from March's approved update, so March's new decisions are now carried out.
    assert april.original.hires[2] == march.updated.plan.hires[2]
    assert april.updated.plan.hires[:3].tolist() == march.updated.plan.hires[:3].tolist()
    rail = app.home_view("Start of April")[1]
    assert "updated" in rail or march.changes() == []
    app._APPROVED.clear()
