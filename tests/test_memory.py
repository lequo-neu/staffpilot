"""Conversation memory: follow ups inherit what they leave out, and only within one chat."""

from __future__ import annotations

import pytest

from staffpilot.agent import Intent, OfflineBackend, RoutedQuery, StaffPilot
from staffpilot.agent.memory import Conversation, is_follow_up


@pytest.fixture
def pilot(planner):
    return StaffPilot(planner)


def test_a_follow_up_keeps_the_scenario_and_changes_the_country(pilot):
    chat = Conversation()
    first = pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    second = pilot.ask("And Beta?", chat)
    assert first.carried == []
    assert second.route.intent == Intent.what_if
    assert second.route.scenario.countries == ["Beta"]
    assert second.route.scenario.demand_multiplier == pytest.approx(0.7)
    assert second.route.scenario.months == [7, 8, 9]
    assert "scenario" in second.carried and second.verified
    assert second.text.startswith("If sign ups fall 30% from July to September in Beta")


def test_a_new_size_keeps_the_direction_of_the_change(pilot):
    chat = Conversation()
    pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    answer = pilot.ask("What about 50 percent instead?", chat)
    assert answer.route.scenario.demand_multiplier == pytest.approx(0.5)
    assert answer.route.scenario.countries == ["Alpha"]
    assert answer.verified


def test_a_follow_up_out_of_range_is_explained(pilot):
    chat = Conversation()
    pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    answer = pilot.ask("What about 150 percent instead?", chat)
    assert "between 0.1 and 3" in answer.text and answer.tools == []


def test_a_follow_up_keeps_the_country_and_changes_the_month(pilot):
    chat = Conversation()
    pilot.ask("How many agents does Alpha need in March?", chat)
    answer = pilot.ask("And in July?", chat)
    assert answer.route.intent == Intent.plan_lookup
    assert answer.route.countries == ["Alpha"] and answer.route.months == [7]
    assert "In July" in answer.text and answer.verified


def test_a_memo_request_is_finished_by_the_next_answer(pilot):
    chat = Conversation()
    assert "Which country" in pilot.ask("Write a memo", chat).text
    answer = pilot.ask("Gamma", chat)
    assert answer.route.intent == Intent.memo and answer.route.countries == ["Gamma"]


def test_new_questions_and_small_talk_do_not_inherit(pilot):
    chat = Conversation()
    pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    assert pilot.ask("How long can an advertiser wait in the pool?", chat).carried == []
    assert pilot.ask("thanks", chat).carried == []
    assert not is_follow_up("How many agents do we need overall?")
    assert is_follow_up("What about Beta?") and is_follow_up("Gamma too")


def test_without_a_conversation_each_question_stands_alone(pilot):
    pilot.ask("What if sign ups in Alpha drop 30% in Q3?")
    answer = pilot.ask("And Beta?")
    assert answer.route.intent == Intent.plan_lookup and answer.carried == []


def test_memory_is_bounded_resettable_and_exportable(pilot):
    chat = Conversation(max_turns=2)
    for question in ("How many agents does Alpha need?", "And Beta?", "And Gamma?"):
        pilot.ask(question, chat)
    assert [t.question for t in chat.turns] == ["And Beta?", "And Gamma?"]
    text = chat.to_markdown()
    assert "**1. You:** And Beta?" in text and "carried over: countries" not in text
    assert "User: And Beta?" in chat.transcript()
    chat.reset()
    assert chat.turns == [] and chat.last is None


def test_numbers_from_an_earlier_verified_answer_may_be_repeated(pilot):
    chat = Conversation()
    first = pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    change = first.text.split("a change of ")[1].split(".")[0]
    pilot.ask("And Beta?", chat)
    assert change in chat.earlier_answers()


def test_the_router_model_sees_the_recent_turns(planner):
    class Recording(OfflineBackend):
        name = "recording"

        def __init__(self):
            super().__init__()
            self.histories = []

        def route(self, question, countries, history=""):
            self.histories.append(history)
            return super().route(question, countries)

    backend = Recording()
    pilot = StaffPilot(planner, backend)
    chat = Conversation()
    pilot.ask("What if sign ups in Alpha drop 30% in Q3?", chat)
    pilot.ask("And Beta?", chat)
    assert backend.histories[0] == ""
    assert "User: What if sign ups in Alpha drop 30% in Q3?" in backend.histories[1]


def test_a_router_without_history_support_still_works(planner):
    class Old:
        name = "old"

        def route(self, question, countries):
            return RoutedQuery(intent=Intent.rules)

        def compose(self, *args, **kwargs):
            return "The case rules apply."

    pilot = StaffPilot(planner, Old())
    chat = Conversation()
    pilot.ask("How long can an advertiser wait?", chat)
    answer = pilot.ask("And the ramp?", chat)
    assert answer.text and answer.backend == "old"
