"""Free form chat agent built with LangChain `create_agent`.

The structured assistant in `assistant.py` handles one question at a time with a
fixed tool per intent, which makes it easy to evaluate. This agent lets the model
choose and chain tools itself and keeps conversation memory per thread. Its numbers
are checked afterwards against the facts returned by the tools it called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from staffpilot.agent.backends import _text
from staffpilot.agent.facts import FactLedger
from staffpilot.agent.tools import PlannerTools
from staffpilot.config import Settings


AGENT_PROMPT = """You are StaffPilot, a staffing analyst for Google's new advertiser support teams.
Use the tools for every number you give; do not estimate or recall numbers. Prefer one tool call per question,
chain a second only when needed. Quote numbers exactly as the tools return them, rounded sensibly, and say which
tool they came from. If a request is unclear, ask one short question.
Words in this domain: "notices" are notices of termination given to support agents (staff cuts) and "hires" are
agents hired; both are in the staffing plan (get_plan). "Sign ups" are advertisers joining, described by
signup_insights. "Net value" is expected ad spend uplift minus salaries and notice cost. Rank countries from the
per country rows that get_plan returns when no country is given."""


@dataclass
class ChatReply:
    text: str
    tools_called: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def build_chat_agent(tools: PlannerTools, model_spec: str, settings: Settings) -> Any:
    from langchain.agents import create_agent
    from langchain.chat_models import init_chat_model
    from langgraph.checkpoint.memory import InMemorySaver

    kwargs: dict[str, Any] = {"timeout": settings.llm.timeout, "max_retries": settings.llm.max_retries}
    if model_spec.startswith("anthropic:"):
        kwargs["max_tokens"] = 4096
    model = init_chat_model(model_spec, **kwargs)
    return create_agent(
        model, tools.as_langchain_tools(), system_prompt=AGENT_PROMPT, checkpointer=InMemorySaver()
    )


def chat(agent: Any, message: str, thread_id: str = "default") -> ChatReply:
    state = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    messages = state["messages"]
    # Only this turn's tool results count as evidence for this turn's answer.
    last_user = max(i for i, m in enumerate(messages) if getattr(m, "type", "") == "human")
    ledger = FactLedger()
    called, evidence = [], [message]
    for m in messages[last_user:]:
        if getattr(m, "type", "") == "tool":
            called.append(getattr(m, "name", "tool"))
            # Facts carry names; table rows and notes are evidence too, since the agent reads them.
            evidence.append(_text(m))
            try:
                ledger.add("", json.loads(_text(m)).get("facts", {}))
            except (json.JSONDecodeError, AttributeError):
                continue
    text = _text(messages[-1])
    return ChatReply(text, called, ledger.verify(text, " ".join(evidence)) if called else [])
