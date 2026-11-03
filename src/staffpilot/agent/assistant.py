"""StaffPilot: the planning assistant.

A question goes through four steps:

1. route: a model (or the offline router) returns a typed `RoutedQuery`,
2. tools: the planner tools for that intent run and fill a fact ledger,
3. compose: a model writes the answer with `{{fact}}` placeholders,
4. check: placeholders are filled and every remaining number is verified. A failing
   answer is retried once with feedback, then replaced by the template answer.

Pass a `Conversation` to `ask` to keep a chat going: follow ups then inherit what they
leave out from the previous turn (see `memory.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any

import pandas as pd

from staffpilot.agent.backends import (
    OfflineBackend,
    ScenarioRangeError,
    _offline_intent,
    _offline_scenario,
    describe_error,
    template_answer,
)
from staffpilot.agent.facts import FactLedger
from staffpilot.agent.memory import Conversation, resolve_follow_up
from staffpilot.agent.schemas import Intent, MemoDraft, RoutedQuery
from staffpilot.agent.tools import PlannerTools, ToolOutput
from staffpilot.planner import Planner
from staffpilot.scenarios import ScenarioParams


log = logging.getLogger(__name__)


@dataclass
class Answer:
    question: str
    text: str
    route: RoutedQuery
    backend: str
    tools: list[str] = field(default_factory=list)
    tables: list[pd.DataFrame] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    fallback_used: bool = False
    seconds: float = 0.0
    facts: dict[str, float] = field(default_factory=dict)
    chart: Any = None  # a matplotlib Figure that illustrates the answer
    carried: list[str] = field(default_factory=list)  # what a follow up took from the previous turn

    @property
    def verified(self) -> bool:
        return not self.unsupported and not self.missing


class ModelRouter:
    """Chooses which backend writes the answer for each intent.

    The table comes from the evaluation (`eval/results/routing.json`): for each intent
    the backend with the best accuracy, then the lowest latency. Without it, every
    intent uses the default backend.
    """

    def __init__(self, backends: dict[str, Any], default: str, table: dict[str, str] | None = None) -> None:
        self.backends = backends
        self.default = default
        self.table = {k: v for k, v in (table or {}).items() if v in backends}

    @classmethod
    def from_file(cls, backends: dict[str, Any], default: str, path: Path) -> ModelRouter:
        table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(backends, default, table)

    def router_backend(self) -> Any:
        return self.backends[self.table.get("router", self.default)]

    def for_intent(self, intent: Intent) -> Any:
        return self.backends[self.table.get(intent.value, self.default)]


class StaffPilot:
    def __init__(
        self, planner: Planner, backend: Any | None = None, router: ModelRouter | None = None
    ) -> None:
        self.planner = planner
        self.tools = PlannerTools(planner)
        backend = backend or OfflineBackend()
        self.router = router or ModelRouter({backend.name: backend}, backend.name)
        self.offline = OfflineBackend()

    def route(self, question: str, conversation: Conversation | None = None) -> tuple[RoutedQuery, str]:
        route, name, _ = self._route(question, conversation)
        return route, name

    def _route(self, question: str, conversation: Conversation | None) -> tuple[RoutedQuery, str, list[str]]:
        backend = self.router.router_backend()
        countries = self.planner.countries
        history = conversation.transcript() if conversation else ""
        try:
            try:
                route = backend.route(question, countries, history=history) if history else None
            except TypeError:  # a backend written before memory existed takes no history
                route = None
            route = route or backend.route(question, countries)
            name = backend.name
        except Exception as error:  # a model failure must not break the app
            log.warning("Router %s failed; using the offline router. %s", backend.name, describe_error(error))
            route, name = self.offline.route(question, countries), "offline (router fallback)"
        carried: list[str] = []
        previous = conversation.last.route if conversation and conversation.last else None
        try:
            route, carried = resolve_follow_up(route, question, previous, _offline_intent(question, False))
        except ScenarioRangeError as error:
            route = route.model_copy(update={"clarification": str(error)})
        if carried:
            log.info("Follow up: carried %s from the previous turn", ", ".join(carried))
        return self._clean(route, question), name, carried

    def _clean(self, route: RoutedQuery, question: str) -> RoutedQuery:
        countries = [c for c in (self.planner.resolve_country(n) for n in route.countries) if c]
        unknown = [n for n in route.countries if not self.planner.resolve_country(n)]
        if unknown and not countries and not route.clarification:
            names = ", ".join(self.planner.countries)
            route = route.model_copy(
                update={
                    "clarification": f"I do not have data for {unknown[0]}. The countries in the data are {names}."
                }
            )
        months = [m for m in route.months if 1 <= m <= 12]
        scenario = route.scenario
        clarification = route.clarification
        if route.intent == Intent.what_if and not clarification:
            if scenario is None:
                try:
                    scenario = _offline_scenario(question, countries, months)
                except ScenarioRangeError as error:
                    clarification = str(error)
            if scenario is not None and not scenario.countries and countries:
                scenario = scenario.model_copy(update={"countries": countries})
            if scenario is None and clarification is None:
                clarification = (
                    "Which input should change, and by how much? For example: sign ups drop 30 percent in Q3."
                )
        return route.model_copy(
            update={
                "countries": countries,
                "months": months,
                "scenario": scenario,
                "clarification": clarification,
            }
        )

    def run_tools(self, route: RoutedQuery, question: str) -> list[ToolOutput]:
        t = self.tools
        intent = route.intent
        if route.clarification:
            return []
        if intent == Intent.plan_lookup or intent == Intent.memo:
            return [t.get_plan(route.countries, route.months)]
        if intent == Intent.compare:
            return [t.compare_policies(route.countries)]
        if intent == Intent.what_if:
            return [t.run_scenario(route.scenario or ScenarioParams(countries=route.countries))]
        if intent == Intent.sensitivity:
            return [t.sensitivity(route.countries)]
        if intent == Intent.insight:
            return [
                t.signup_insights(
                    route.insight_kind or "volatility", route.countries[0] if route.countries else None
                )
            ]
        if intent == Intent.rules:
            return [t.search_rules(question)]
        return []

    def _ledger(self, outputs: list[ToolOutput]) -> FactLedger:
        ledger = FactLedger()
        ledger.add("", self.tools.rule_facts())
        for output in outputs:
            ledger.add("", output.facts)
        return ledger

    def ask(self, question: str, conversation: Conversation | None = None) -> Answer:
        """Answer one question. With a conversation, read it as part of that chat and remember it."""
        try:
            answer = self._ask(question, conversation)
        except Exception as error:  # the app must show a message, never a stack trace
            log.exception("Could not answer %r", question)
            route = RoutedQuery(intent=Intent.out_of_scope, clarification="error")
            text = (
                f"I could not answer that ({type(error).__name__}). Please rephrase or narrow the question."
            )
            return Answer(question, text, route, "error")
        if conversation is not None:
            conversation.add(answer, answer.carried)
        return answer

    def _ask(self, question: str, conversation: Conversation | None = None) -> Answer:
        started = time.perf_counter()
        route, router_name, carried = self._route(question, conversation)
        outputs = self.run_tools(route, question)
        ledger = self._ledger(outputs)
        formatted = ledger.formatted()
        writer = self.router.for_intent(route.intent)
        sources = [s for o in outputs for s in o.sources]
        # Clarifications are written by the code, so their numbers (such as limits) are sources too.
        # Numbers from earlier answers in the chat already passed this check, so they may be repeated.
        earlier = conversation.earlier_answers() if conversation else ""
        context = " ".join(
            [question, route.clarification or "", *(n for o in outputs for n in o.notes), earlier]
        )
        text, feedback = "", ""
        for _ in range(2):
            try:
                draft = writer.compose(question, route, outputs, formatted, feedback)
            except Exception as error:  # a model or network failure falls back to the template
                feedback = f"model error {type(error).__name__}"
                log.warning("Writer %s failed. %s", writer.name, describe_error(error))
                break
            rendered, missing = ledger.render(draft)
            unsupported = ledger.verify(rendered, context, self.planner.countries)
            if not missing and not unsupported:
                text = rendered
                break
            feedback = f"unknown facts {missing[:5]} and unsupported numbers {unsupported[:5]}."
            log.warning("%s answer failed the number check: %s", writer.name, feedback)
        fallback = not text and writer.name != "offline"
        if fallback:
            log.warning("Using the template answer for %r", question)
        if not text:
            text, _ = ledger.render(template_answer(route, outputs, formatted))
        name = f"{writer.name} (template fallback)" if fallback else writer.name
        _, missing = ledger.render(text)
        answer = Answer(
            question=question,
            text=text,
            route=route,
            backend=name if router_name == writer.name else f"router {router_name}, writer {name}",
            tools=[o.name for o in outputs],
            tables=[o.table for o in outputs if o.table is not None],
            sources=sources,
            unsupported=ledger.verify(text, context, self.planner.countries),
            missing=missing,
            fallback_used=fallback,
            facts=dict(ledger.facts),
            chart=next((o.chart for o in outputs if o.chart is not None), None),
            carried=carried,
        )
        answer.seconds = time.perf_counter() - started
        log.info(
            "Answered as %s with %s in %.1fs (number check %s)",
            route.intent.value,
            answer.tools or "no tool",
            answer.seconds,
            "passed" if answer.verified else "failed",
        )
        return answer

    def memo(self, country: str) -> Answer:
        started = time.perf_counter()
        resolved = self.planner.resolve_country(country)
        if resolved is None:
            names = ", ".join(self.planner.countries)
            route = RoutedQuery(intent=Intent.memo, clarification="unknown country")
            return Answer(
                f"memo for {country}",
                f"I do not have data for {country}. The countries in the data are {names}.",
                route,
                "none",
            )
        route = RoutedQuery(intent=Intent.memo, countries=[resolved])
        outputs = [self.tools.get_plan([resolved])]
        ledger = self._ledger(outputs)
        formatted = ledger.formatted()
        writer = self.router.for_intent(Intent.memo)
        notes = [n for o in outputs for n in o.notes]
        try:
            draft = writer.draft_memo(resolved, formatted, notes)
        except Exception as error:  # fall back to the template memo
            log.warning("Memo writer %s failed. %s", writer.name, describe_error(error))
            draft = self.offline.draft_memo(resolved, formatted, notes)
        text, missing = ledger.render(memo_markdown(resolved, draft, self.planner.year))
        unsupported = ledger.verify(text, " ".join(notes), self.planner.countries)
        fallback = False
        if missing or unsupported:
            draft = self.offline.draft_memo(resolved, formatted, notes)
            text, missing = ledger.render(memo_markdown(resolved, draft, self.planner.year))
            unsupported, fallback = ledger.verify(text, " ".join(notes), self.planner.countries), True
        answer = Answer(
            f"memo for {resolved}",
            text,
            route,
            writer.name,
            ["get_plan"],
            [outputs[0].table] if outputs[0].table is not None else [],
            [],
            unsupported,
            missing,
            fallback,
            facts=dict(ledger.facts),
            chart=outputs[0].chart,
        )
        answer.seconds = time.perf_counter() - started
        return answer


def memo_markdown(country: str, draft: MemoDraft, year: int) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"* {item}" for item in items)

    return (
        f"### Staffing memo: {country}, {year}\n\n{draft.headline}\n\n"
        f"**Headcount changes**\n{bullets(draft.headcount_changes)}\n\n"
        f"**Cost and value**\n{bullets(draft.cost_and_value)}\n\n"
        f"**Why**\n{bullets(draft.rationale)}\n\n"
        f"**Risks to watch**\n{bullets(draft.risks)}\n"
    )
