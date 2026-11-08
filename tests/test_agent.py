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


@pytest.mark.parametrize(
    ("question", "months"),
    [
        ("What if Alpha sign ups increase 30% from October through December?", [10, 11, 12]),
        ("What if sign ups in Beta drop 25% in the first half of the year?", [1, 2, 3, 4, 5, 6]),
        ("What if sign ups in Alpha drop 15% between June and August?", [6, 7, 8]),
        ("What if sign ups in Alpha rise 10% in June and August?", [6, 8]),
    ],
)
def test_offline_router_reads_month_ranges_and_halves(question, months):
    assert OfflineBackend().route(question, COUNTRIES).scenario.months == months


@pytest.mark.parametrize(
    ("question", "value"),
    [
        ("What happens if all countries experience 120% demand?", 1.2),
        ("What if Alpha's demand doubles in March?", 2.0),
        ("What if demand in Beta halves in Q3?", 0.5),
    ],
)
def test_offline_router_reads_a_change_written_as_a_level(question, value):
    assert OfflineBackend().route(question, COUNTRIES).scenario.demand_multiplier == pytest.approx(value)


def test_a_what_if_answer_ends_with_what_to_do():
    from staffpilot.agent.backends import _scenario_action

    up = {"scenario.avg_active_base": 100.0, "scenario.avg_active_scenario": 110.0}
    down = {"scenario.avg_active_base": 100.0, "scenario.avg_active_scenario": 90.0}
    flat = {"scenario.avg_active_base": 100.0, "scenario.avg_active_scenario": 100.2}
    assert "hires a month early" in _scenario_action(up, True)[0]
    assert "notices a month early" in _scenario_action(down, True)[0]
    assert "absorbs" in _scenario_action(flat, True)[0] and _scenario_action(flat, False) == []
    # The line carries no number, so the number check has nothing to test in it.
    assert not any(
        ch.isdigit() for line in [*_scenario_action(up, True), *_scenario_action(down, True)] for ch in line
    )


@pytest.mark.parametrize(
    ("question", "words"),
    [
        ("What if Alpha sign ups increase 15% from October 2026 to March 2027?", "runs into the next year"),
        ("What if Alpha rises 50% and Beta falls 10% in Q4?", "Which months does each change cover"),
        ("What if Alpha grows 50% in Q4 and Atlantis falls 10% all year?", "I do not have data for Atlantis"),
        ("What if sign ups in Alpha drop 30% in Q3 and salaries rise 10%?", "not this mix"),
        ("What if Alpha grows 500% in Q4 and Beta falls 10% all year?", "outside the range"),
    ],
)
def test_offline_router_asks_instead_of_changing_the_request(question, words):
    # Cutting the period at December or keeping only one of two changes would answer another question.
    route = OfflineBackend().route(question, COUNTRIES)
    assert route.scenario is None and words in route.clarification


def test_number_check_accepts_rounded_facts_and_rejects_invented_ones():
    ledger = FactLedger({"x.salary_cost": 1_455_000.0, "x.service_rate": 0.9959, "x.avg_active": 79.42})
    text, missing = ledger.render(
        "Cost {{x.salary_cost}}, service {{x.service_rate}}, {{x.avg_active}} agents."
    )
    assert missing == []
    assert ledger.verify(text) == []
    assert ledger.verify("It will cost $2.1M and serve 95.0% with 81 agents.") == ["$2.1M", "95.0%", "81"]


def test_number_check_tests_headcounts_that_look_like_years():
    ledger = FactLedger({"x.end_agents": 2071.0})
    assert ledger.verify("In 2026 the team ends at 2,071 agents.") == []
    assert ledger.verify("In 2026 the team ends at 2,050 agents.") == ["2,050"]
    assert ledger.verify("The team ends at $2,071k.") == ["$2,071k"]
    assert ledger.verify("Germany needs 2000 agents in March 2026.") == ["2000"]


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


@pytest.mark.parametrize(
    "draft, problem",
    [
        ('{"name": "plan_lookup", "parameters": {"year": 2026}}', "JSON instead of sentences"),
        ("* Brazil.hires", "Brazil.hires"),
        ("* France.hires agents", "France.hires"),
        ("Arrivals are {Brazil.arrivals}.", "{Brazil.arrivals}"),
        ("**Headcount changes**\n* ,\n", "an empty bullet"),
    ],
)
def test_unfilled_or_unreadable_drafts_count_as_missing(draft, problem):
    # Each of these passed the number check in the local evaluation and was graded 1 by hand.
    _, missing = FactLedger({"Brazil.hires": 16.0, "plan.year": 2026.0}).render(draft)
    assert problem in missing


def test_file_names_and_years_read_normally():
    ledger = FactLedger({"plan.year": 2026.0})
    text, missing = ledger.render("Plan for {{plan.year}}, from rules.md.")
    assert text == "Plan for 2026, from rules.md." and missing == []


def test_country_adjectives_and_sentence_starts_are_not_unknown_places(planner):
    route = OfflineBackend().route("Net value of the Indian team over the year?", ["India", "Spain"])
    assert route.countries == ["India"] and route.clarification is None
    pilot = StaffPilot(planner)
    first = planner.countries[0]
    assert pilot.route(f"Net value of {first} over the year? Effect on the plan?")[0].clarification is None
    stray = RoutedQuery(intent=Intent.insight, countries=["All"], insight_kind="seasonality")
    cleaned = pilot._clean(stray, "When is the seasonal peak in sign ups?")
    assert cleaned.countries == [] and cleaned.clarification is None


def test_a_model_that_writes_numbers_in_braces_falls_back_to_the_template(planner):
    class Sloppy(OfflineBackend):
        name = "sloppy"

        def compose(self, *args, **kwargs):
            return "Net value moves to {{$41.7M}}."

    answer = StaffPilot(planner, Sloppy()).ask("What if sign ups in Alpha drop 30% in Q3?")
    assert answer.fallback_used and answer.verified and "{{" not in answer.text


def test_router_replies_are_repaired_field_by_field():
    from staffpilot.agent.schemas import repair_route

    # A what if with a percent written as 90 and an invented field: both are fixed, the rest kept.
    route, repairs = repair_route(
        {
            "intent": "what_if",
            "countries": ["Alpha"],
            "months": [7, 8, 9],
            "scenario": {"demand_multiplier": 0.7, "service_target": 90, "hiring_capped_at": 1000},
        }
    )
    assert route.intent == Intent.what_if and route.countries == ["Alpha"]
    assert route.scenario.demand_multiplier == 0.7 and route.scenario.service_target == 0.9
    assert any("hiring_capped_at" in r for r in repairs)

    # A plan question with a stray, invalid scenario keeps its intent and country.
    route, repairs = repair_route(
        {"intent": "plan_lookup", "countries": ["Beta"], "scenario": {"service_target": 10000}}
    )
    assert route.intent == Intent.plan_lookup and route.countries == ["Beta"] and route.scenario is None
    assert repairs == ["dropped a scenario on a question that is not a what if"]

    # An impossible value that is not a percent is dropped, not guessed.
    route, _ = repair_route(
        {"intent": "what_if", "scenario": {"service_target": 10000, "demand_multiplier": 1.2}}
    )
    assert route.scenario.service_target is None and route.scenario.demand_multiplier == 1.2

    with pytest.raises(ValueError):
        repair_route({"intent": "make_coffee"})


def test_a_model_reply_that_misses_the_schema_is_repaired_not_rejected(monkeypatch, settings):
    from langchain_core.messages import AIMessage

    from staffpilot.agent.backends import LangChainBackend

    raw = AIMessage(
        content='{"intent": "compare", "countries": ["Alpha"], "scenario": {"service_target": 90}}'
    )

    class Runnable:
        def invoke(self, messages):
            return {"raw": raw, "parsed": None, "parsing_error": ValueError("service_target too large")}

    class Model:
        def with_structured_output(self, *args, **kwargs):
            return Runnable()

    backend = LangChainBackend.__new__(LangChainBackend)
    backend.name, backend.model_spec, backend.usage, backend.model = (
        "fake",
        "local:fake",
        {"input": 0, "output": 0},
        Model(),
    )
    route = backend.route("Compare the plans for Alpha", ["Alpha"])
    assert route.intent == Intent.compare and route.countries == ["Alpha"] and route.scenario is None


def test_the_trace_counts_only_the_numbers_the_check_tests():
    from staffpilot.agent.facts import checked_numbers

    assert checked_numbers("In March 2026, 86 agents cost $1.2M and serve 99.1% of 3 groups.") == 3


def test_a_repair_asks_back_when_it_would_drop_the_change_that_was_asked_for():
    from staffpilot.agent.schemas import repair_route

    # "Brazil grows 400%" read as five times demand: running what is left would change nothing.
    route, repairs = repair_route(
        {
            "intent": "what_if",
            "countries": ["Brazil"],
            "scenario": {"countries": ["Brazil"], "demand_multiplier": 5},
        }
    )
    assert route.scenario is None and "outside the range" in route.clarification
    assert any("asked back" in r for r in repairs)
    # A stray field next to a real change is still dropped, and the change runs.
    route, _ = repair_route(
        {
            "intent": "what_if",
            "countries": ["Brazil"],
            "scenario": {"countries": ["Brazil"], "demand_multiplier": 0.7, "capacity_per_agent": 0},
        }
    )
    assert route.scenario.demand_multiplier == 0.7 and route.clarification is None


@pytest.mark.parametrize(
    ("question", "changes"),
    [
        (
            "What if Alpha grows 50% in Q4 and Beta falls 10% all year?",
            [(["Alpha"], [10, 11, 12], 1.5), (["Beta"], [], 0.9)],
        ),
        (
            "What if Alpha, Beta and Gamma drop 25% in the first half and the US rises 10% in Q4?",
            [(["Alpha", "Beta", "Gamma"], [1, 2, 3, 4, 5, 6], 0.75), (["USA"], [10, 11, 12], 1.1)],
        ),
        # A part that names no country keeps the country before it.
        (
            "What if Alpha rises 30% in Q4 and falls 10% in Q1?",
            [(["Alpha"], [10, 11, 12], 1.3), (["Alpha"], [1, 2, 3], 0.9)],
        ),
    ],
)
def test_offline_router_reads_several_sign_up_changes(question, changes):
    scenario = OfflineBackend().route(question, COUNTRIES).scenario
    got = [(sorted(a.countries), a.months, a.multiplier) for a in scenario.adjustments]
    assert got == [(sorted(c), m, pytest.approx(x)) for c, m, x in changes]
    assert scenario.demand_multiplier == 1.0


def test_several_changes_give_each_country_its_own_result(planner):
    from staffpilot.scenarios import DemandChange, ScenarioParams

    both = ScenarioParams(
        adjustments=[
            DemandChange(countries=["Alpha"], months=[10, 11, 12], multiplier=1.5),
            DemandChange(countries=["Beta"], multiplier=0.8),
        ]
    )
    together = planner.scenario(both).comparison.set_index("country")
    alone = {
        "Alpha": planner.scenario(
            ScenarioParams(countries=["Alpha"], months=[10, 11, 12], demand_multiplier=1.5)
        ),
        "Beta": planner.scenario(ScenarioParams(countries=["Beta"], demand_multiplier=0.8)),
    }
    assert sorted(together.index) == ["Alpha", "Beta"]
    for country, result in alone.items():
        assert together.loc[country, "net_value_scenario"] == pytest.approx(
            result.totals()["net_value_scenario"]
        )
    assert "sign ups in Alpha rise 50% from October to December and sign ups in Beta fall 20%" in both.plain()
    # Two changes to the same country and month multiply.
    stacked = ScenarioParams(
        adjustments=[
            DemandChange(countries=["Alpha"], multiplier=1.2),
            DemandChange(countries=["Alpha"], multiplier=1.5),
        ]
    )
    single = ScenarioParams(countries=["Alpha"], demand_multiplier=1.8)
    assert planner.scenario(stacked).totals()["net_value_scenario"] == pytest.approx(
        planner.scenario(single).totals()["net_value_scenario"]
    )


def test_a_follow_up_after_several_changes_asks_for_the_whole_question(planner):
    from staffpilot.agent.memory import Conversation

    pilot = StaffPilot(planner, OfflineBackend())
    chat = Conversation()
    pilot.ask("What if Alpha grows 50% in Q4 and Beta falls 10% all year?", chat)
    assert "several changes" in pilot.ask("And Gamma?", chat).text
