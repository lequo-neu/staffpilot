"""Typed contracts between the language model and the planner."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
