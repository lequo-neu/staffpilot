"""Short term conversation memory for the assistant.

A `Conversation` keeps the last few turns of one chat. It does two jobs:

* follow ups such as "And Mexico?" or "What about 50 percent instead?" inherit the
  intent, countries, months and scenario that the question leaves out,
* the recent turns go to a language model router as context.

Memory lives only as long as the chat (one browser tab in the app, one `chat`
session on the command line). Nothing is written to disk unless the user exports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

from pydantic import ValidationError

from staffpilot.agent.backends import ScenarioRangeError, _range_message
from staffpilot.agent.schemas import Intent, RoutedQuery
from staffpilot.scenarios import ScenarioParams


if TYPE_CHECKING:
    from staffpilot.agent.assistant import Answer


FOLLOW_UP_STARTS = (
    "and ",
    "what about",
    "how about",
    "same ",
    "now ",
    "also ",
    "then ",
    "instead",
    "ok ",
    "okay ",
)
FOLLOW_UP_WORDS = (" instead", " too", " as well", " same ", " there", " that one", " the same")
FRESH_START_WORDS = ("all countries", "overall", "in total", "every country", "each country", "start over")
SMALL_TALK = ("thank", "thanks", "hello", "hi", "hey", "bye", "great", "ok", "okay", "cool")
# Clarifications that stay even when a follow up fills in the gaps.
KEEP_CLARIFICATIONS = ("I do not have data", "That ")
CARRIED_INTENTS = {
    Intent.what_if,
    Intent.compare,
    Intent.sensitivity,
    Intent.insight,
    Intent.plan_lookup,
    Intent.memo,
}
MULTIPLIERS = ("demand_multiplier", "threshold_multiplier", "salary_multiplier")


@dataclass
class Turn:
    question: str
    route: RoutedQuery
    text: str
    verified: bool
    carried: list[str] = field(default_factory=list)


@dataclass
class Conversation:
    max_turns: int = 4
    turns: list[Turn] = field(default_factory=list)

    @property
    def last(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    def add(self, answer: Answer, carried: list[str] | None = None) -> None:
        self.turns.append(Turn(answer.question, answer.route, answer.text, answer.verified, carried or []))
        del self.turns[: -self.max_turns]

    def reset(self) -> None:
        self.turns.clear()

    def transcript(self, chars: int = 400) -> str:
        """Recent turns as plain text for a router prompt; long answers are shortened."""
        lines = []
        for turn in self.turns:
            answer = turn.text if len(turn.text) <= chars else turn.text[:chars].rsplit(" ", 1)[0] + " ..."
            lines.append(f"User: {turn.question}\nStaffPilot: {answer}")
        return "\n".join(lines)

    def earlier_answers(self) -> str:
        """Text of earlier answers that passed the number check; their numbers may be repeated."""
        return " ".join(t.text for t in self.turns if t.verified)

    def to_markdown(self) -> str:
        parts = ["# StaffPilot conversation", ""]
        for i, turn in enumerate(self.turns, start=1):
            note = f" (carried over: {', '.join(turn.carried)})" if turn.carried else ""
            parts += [f"**{i}. You:** {turn.question}", "", f"**StaffPilot{note}:** {turn.text}", ""]
        return "\n".join(parts)


def describe(carried: list[str]) -> str:
    """Join carried field names as a sentence would, for the note under an answer."""
    return carried[0] if len(carried) == 1 else f"{', '.join(carried[:-1])} and {carried[-1]}"


def is_follow_up(question: str) -> bool:
    q = f"{question.strip().lower()} "
    if any(w in q for w in FRESH_START_WORDS) or re.sub(r"[^a-z ]", "", q).strip() in SMALL_TALK:
        return False
    return q.startswith(FOLLOW_UP_STARTS) or any(w in q for w in FOLLOW_UP_WORDS) or len(q.split()) <= 3


def resolve_follow_up(
    route: RoutedQuery, question: str, previous: RoutedQuery | None, own_intent: Intent
) -> tuple[RoutedQuery, list[str]]:
    """Fill what a follow up leaves out from the previous turn.

    `own_intent` is what the question asks for on its own, read without any country
    names: out_of_scope means it carries no request of its own ("And Mexico?").
    Returns the new route and the names of the fields that were carried over.
    """
    if previous is None or not is_follow_up(question):
        return route, []
    for clarification in (previous.clarification, route.clarification):
        if clarification and clarification.startswith(KEEP_CLARIFICATIONS):
            return route, []
    update: dict[str, object] = {}
    carried: list[str] = []
    intent = route.intent
    if own_intent == Intent.out_of_scope and previous.intent in CARRIED_INTENTS and intent != previous.intent:
        intent = previous.intent
        update["intent"] = intent
        carried.append("kind of question")
    if intent != previous.intent:
        return route, []
    if not route.countries and previous.countries:
        update["countries"] = previous.countries
        carried.append("countries")
    if not route.months and previous.months:
        update["months"] = previous.months
        carried.append("months")
    if intent == Intent.insight and route.insight_kind is None:
        update["insight_kind"] = previous.insight_kind
    if intent == Intent.what_if and previous.scenario is not None:
        scenario = _carry_scenario(route, question, previous, update)
        if scenario is not None:
            update["scenario"] = scenario
            carried.append("scenario")
    if not carried:
        return route, []
    update["clarification"] = None
    return route.model_copy(update=update), carried


def _carry_scenario(
    route: RoutedQuery, question: str, previous: RoutedQuery, update: dict[str, object]
) -> ScenarioParams | None:
    base = previous.scenario
    assert base is not None
    countries = update.get("countries", route.countries)
    months = update.get("months", route.months)
    if route.scenario is not None:
        # The question set its own change; only fill the places and months it left out.
        fill = {
            k: v for k, v in (("countries", countries), ("months", months)) if not getattr(route.scenario, k)
        }
        return route.scenario.model_copy(update=fill) if fill else None
    changes: dict[str, object] = {"countries": countries, "months": months}
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", question.lower())
    if match:
        # "50 percent instead" keeps the direction of the change it replaces.
        size = float(match.group(1)) / 100
        name = next((m for m in MULTIPLIERS if getattr(base, m) != 1.0), "demand_multiplier")
        sign = -1 if getattr(base, name) < 1 else 1
        changes[name] = round(1 + sign * size, 4)
    try:
        return ScenarioParams.model_validate({**base.model_dump(), **changes})
    except ValidationError as error:
        raise ScenarioRangeError(_range_message(error)) from error
