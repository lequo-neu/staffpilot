from __future__ import annotations

from dataclasses import dataclass

import pytest

from staffpilot.agent import CachedBackend, Intent, OfflineBackend, RoutedQuery, StaffPilot
from staffpilot.agent.facts import FactLedger
from staffpilot.agent.rag import Retriever
from staffpilot.agent.tools import PlannerTools


COUNTRIES = ["Alpha", "Beta", "Gamma", "USA", "UK"]


@pytest.mark.parametrize(
    ("question", "intent", "field", "value"),
    [
        ("What if sign ups in Alpha drop 30% in Q3?", "what_if", "demand_multiplier", 0.7),
        ("What happens if demand rises 20 percent in the US?", "what_if", "demand_multiplier", 1.2),
        ("What if we lower the threshold in the UK by 20 percent?", "what_if", "threshold_multiplier", 0.8),
        ("What if we cap hiring at 5 agents per month in Beta?", "what_if", "max_hires_per_month", 5),
    ],
)
def test_offline_router_reads_scenarios(question, intent, field, value):
    route = OfflineBackend().route(question, COUNTRIES)
    assert route.intent.value == intent
    assert getattr(route.scenario, field) == pytest.approx(value)


def test_offline_router_reads_countries_and_quarters():
    route = OfflineBackend().route("Staffing for Alpha and the US in Q4?", COUNTRIES)
    assert route.intent == Intent.plan_lookup
    assert sorted(route.countries) == ["Alpha", "USA"]
    assert route.months == [10, 11, 12]


def test_number_check_accepts_rounded_facts_and_rejects_invented_ones():
    ledger = FactLedger({"x.salary_cost": 1_455_000.0, "x.service_rate": 0.9959, "x.avg_active": 79.42})
    text, missing = ledger.render(
        "Cost {{x.salary_cost}}, service {{x.service_rate}}, {{x.avg_active}} agents."
    )
    assert missing == []
    assert ledger.verify(text) == []
    assert ledger.verify("It will cost $2.1M and serve 95.0% with 81 agents.") == ["$2.1M", "95.0%", "81"]


def test_retriever_finds_the_waiting_pool_rule():
    hits = Retriever().search("How long can an advertiser wait in the pool?")
    assert hits and hits[0].heading == "Waiting pool"


@pytest.mark.parametrize(
    "question",
    [
        "How many agents does Alpha need in March?",
        "What if sign ups in Beta drop 30% in Q3?",
        "Compare the optimized plan with keeping January headcount.",
        "Which countries have the most volatile demand?",
        "How long can an advertiser wait in the pool?",
        "What is the weather tomorrow?",
        "",
    ],
)
def test_offline_answers_pass_the_number_check(planner, question):
    answer = StaffPilot(planner).ask(question)
    assert answer.text
    assert answer.verified, (answer.unsupported, answer.missing)


def test_memo_is_grounded(planner):
    answer = StaffPilot(planner).memo("Gamma")
    assert "Staffing memo: Gamma" in answer.text
    assert answer.verified


def test_langchain_tools_are_exposed(planner):
    tools = PlannerTools(planner).as_langchain_tools()
    assert {t.name for t in tools} == {
        "get_plan",
        "compare_policies",
        "run_scenario",
        "sensitivity",
        "signup_insights",
        "search_rules",
    }
    assert '"facts"' in tools[0].invoke({"countries": ["Alpha"]})


@dataclass
class _Counting:
    name: str = "fake"
    calls: int = 0

    def route(self, question, countries):
        self.calls += 1
        return RoutedQuery(intent=Intent.rules)


def test_cached_backend_reuses_replies(tmp_path):
    inner = _Counting()
    cached = CachedBackend(inner, tmp_path)
    cached.route("q", [])
    CachedBackend(inner, tmp_path).route("q", [])
    assert inner.calls == 1


def test_model_failures_fall_back_to_the_template(planner):
    class Broken:
        name = "broken"

        def route(self, question, countries):
            raise RuntimeError("network down")

        def compose(self, *args, **kwargs):
            raise RuntimeError("network down")

    answer = StaffPilot(planner, Broken()).ask("How many agents does Alpha need?")
    assert answer.fallback_used and answer.verified


def test_number_check_rejects_a_figure_attributed_to_the_wrong_country():
    ledger = FactLedger(
        {"Germany.avg_active": 133.0, "France.avg_active": 107.0, "rules.capacity_per_agent": 10}
    )
    countries = ["Germany", "France"]
    assert ledger.verify("Germany averages 133 agents.", countries=countries) == []
    assert ledger.verify("France averages 133 agents.", countries=countries) == ["133"]
    assert ledger.verify("Each agent holds 10 advertisers in France.", countries=countries) == []


def test_out_of_range_change_gets_a_clear_message_not_a_crash(planner):
    answer = StaffPilot(planner).ask("What if sign ups in Alpha drop 150%?")
    assert "between 0.1 and 3" in answer.text
    assert answer.tools == []


def test_unknown_country_is_named_instead_of_ignored(planner):
    pilot = StaffPilot(planner)
    for question in (
        "How many agents does Atlantis need in March?",
        "What if sign ups in Atlantis rise 20%?",
    ):
        answer = pilot.ask(question)
        assert "Atlantis" in answer.text and answer.tools == []
    assert "do not have data for Atlantis" in pilot.memo("Atlantis").text


def test_numbers_inside_braces_count_as_missing_facts():
    ledger = FactLedger({"Brazil.hires": 16.0})
    text, missing = ledger.render(
        "Hire {{Brazil.hires}} agents; sign ups fall to {{5,343}} and value to {{$41.7M}}."
    )
    assert text.startswith("Hire 16 agents")
    assert missing == ["5,343", "$41.7M"]


def test_a_model_that_writes_numbers_in_braces_falls_back_to_the_template(planner):
    class Sloppy(OfflineBackend):
        name = "sloppy"

        def compose(self, *args, **kwargs):
            return "Net value moves to {{$41.7M}}."

    answer = StaffPilot(planner, Sloppy()).ask("What if sign ups in Alpha drop 30% in Q3?")
    assert answer.fallback_used and answer.verified and "{{" not in answer.text
