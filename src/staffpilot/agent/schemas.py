"""Typed contracts between the language model and the planner."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from staffpilot.scenarios import ScenarioParams


class Intent(StrEnum):
    """What the user wants. Each intent maps to one or two planner tools."""

    plan_lookup = "plan_lookup"
    compare = "compare"
    what_if = "what_if"
    sensitivity = "sensitivity"
    insight = "insight"
    memo = "memo"
    rules = "rules"
    out_of_scope = "out_of_scope"


class RoutedQuery(BaseModel):
    """Structured reading of a question, produced by the router model."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent = Field(description="The single best matching intent.")
    countries: list[str] = Field(
        default_factory=list, description="Countries named in the question, as written in the data."
    )
    months: list[int] = Field(default_factory=list, description="Calendar months mentioned, 1 to 12.")
    scenario: ScenarioParams | None = Field(
        None, description="Only for what_if questions: the change to test."
    )
    insight_kind: Literal["volatility", "seasonality", "eligibility", "budget", "growth"] | None = Field(
        None, description="Only for insight questions."
    )
    clarification: str | None = Field(
        None,
        description="A short follow up question when the request is too vague to act on, otherwise null.",
    )


class MemoDraft(BaseModel):
    """A staffing memo for one country manager. Numbers must be written as {{placeholders}}."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(description="One sentence summary of the plan for this country.")
    headcount_changes: list[str] = Field(description="Bullet points on hires and notices with their months.")
    cost_and_value: list[str] = Field(description="Bullet points on cost, uplift value and net value.")
    rationale: list[str] = Field(description="Why the plan looks like this.")
    risks: list[str] = Field(description="What could make the plan wrong and what to watch.")


# Scenario fields that are shares; a model sometimes writes 90 for 90 percent.
SHARE_FIELDS = ("service_target", "expected_uplift")
# Optional fields that can be dropped from a reply; the intent itself must be valid.
DROPPABLE = ("countries", "months", "scenario", "insight_kind", "clarification")


def repair_route(data: dict) -> tuple[RoutedQuery, list[str]]:
    """Validate a router reply, fixing or dropping the fields a model filled badly.

    Rejecting the whole reply for one bad field (Llama 3.1 8B often wrote service_target = 90
    on questions that had nothing to do with it) throws away a correct intent and country.
    Shares written in percent are divided by 100, a scenario is kept only for what if
    questions, and any other invalid or unknown field is dropped. An invalid intent still
    fails. Returns the route and what was changed.
    """
    data = dict(data)
    repairs: list[str] = []
    if data.get("intent") != Intent.what_if.value and data.get("scenario") is not None:
        data["scenario"] = None
        repairs.append("dropped a scenario on a question that is not a what if")
    scenario = data.get("scenario")
    if isinstance(scenario, dict):
        scenario = data["scenario"] = dict(scenario)
        for name in SHARE_FIELDS:
            value = scenario.get(name)
            if isinstance(value, int | float) and 1 < value <= 100:
                scenario[name] = value / 100
                repairs.append(f"read {name} = {value} as {value / 100:g}")
    for _ in range(12):
        try:
            return RoutedQuery.model_validate(data), repairs
        except ValidationError as error:
            changed = False
            for problem in error.errors():
                loc = problem["loc"]
                if loc and loc[0] == "scenario" and len(loc) > 1 and isinstance(data.get("scenario"), dict):
                    data["scenario"].pop(loc[1], None)
                    repairs.append(f"dropped scenario.{loc[1]}")
                    changed = True
                elif (
                    loc
                    and loc[0] != "intent"
                    and (loc[0] in DROPPABLE or problem["type"] == "extra_forbidden")
                ):
                    data.pop(loc[0], None)
                    repairs.append(f"dropped {loc[0]}")
                    changed = True
            if not changed:
                raise
    raise ValueError("router reply could not be repaired")
