"""Model backends: a rule based offline backend and LangChain chat models.

Every backend implements the same three calls, so the assistant, the evaluation and
the app do not care which one is used:

* `route` reads a question into a `RoutedQuery` (structured output),
* `compose` writes an answer that uses `{{fact}}` placeholders,
* `draft_memo` fills a `MemoDraft` for one country.

The offline backend needs no API key. It keeps the notebook and the tests runnable
anywhere and is the baseline the language models are compared against.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field, ValidationError

from staffpilot.agent.schemas import Intent, MemoDraft, RoutedQuery, repair_route
from staffpilot.agent.tools import ToolOutput
from staffpilot.config import Settings, load_env_file
from staffpilot.scenarios import DemandChange, ScenarioParams


log = logging.getLogger(__name__)


PROVIDER_KEYS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}
# Models running on this computer (LM Studio or Bionic); free and keyless.
LOCAL = "local"
PROVIDERS = (*PROVIDER_KEYS, LOCAL)
FULL_MONTHS = {
    name: i
    for i, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
SHORT_MONTHS = {
    "jan": 1,
    "feb": 2,
    "apr": 4,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
QUARTERS = {"q1": [1, 2, 3], "q2": [4, 5, 6], "q3": [7, 8, 9], "q4": [10, 11, 12]}
COUNTRY_ALIASES = {
    "us": "USA",
    "united states": "USA",
    "america": "USA",
    "united kingdom": "UK",
    "britain": "UK",
    "korea": "South Korea",
    "emirates": "UAE",
    "united arab emirates": "UAE",
    # Adjectives, so "the Indian team" means India. "Polish" is left out: it is also a verb.
    "american": "USA",
    "british": "UK",
    "german": "Germany",
    "indian": "India",
    "brazilian": "Brazil",
    "japanese": "Japan",
    "australian": "Australia",
    "canadian": "Canada",
    "french": "France",
    "mexican": "Mexico",
    "chinese": "China",
    "italian": "Italy",
    "spanish": "Spain",
    "korean": "South Korea",
    "south african": "South Africa",
    "vietnamese": "Vietnam",
    "argentine": "Argentina",
    "argentinian": "Argentina",
    "turkish": "Turkey",
    "indonesian": "Indonesia",
    "thai": "Thailand",
    "emirati": "UAE",
}
# Words a model may put in the country list when the question covers every country.
ALL_COUNTRIES = {"all", "all countries", "every country", "global", "worldwide", "overall", "total"}


class Judgement(BaseModel):
    score: int = Field(ge=1, le=5, description="1 is wrong or unhelpful, 5 is correct, complete and grounded")
    reason: str = Field(description="One sentence")


class Backend(Protocol):
    name: str

    def route(self, question: str, countries: list[str], history: str = "") -> RoutedQuery: ...

    def compose(
        self,
        question: str,
        route: RoutedQuery,
        outputs: list[ToolOutput],
        facts: dict[str, str],
        feedback: str = "",
    ) -> str: ...

    def draft_memo(self, country: str, facts: dict[str, str], notes: list[str]) -> MemoDraft: ...


OFFLINE_ENV_VAR = "STAFFPILOT_OFFLINE"


def available_providers() -> list[str]:
    """Providers with an API key in the environment or in the repository .env file.

    Setting STAFFPILOT_OFFLINE=1 hides every provider, so the notebook or the app can
    run without paid calls even when keys are present.
    """
    if os.environ.get(OFFLINE_ENV_VAR, "").strip() in {"1", "true", "yes"}:
        return []
    load_env_file()
    keyed = [name for name, keys in PROVIDER_KEYS.items() if any(os.environ.get(k) for k in keys)]
    return [*keyed, LOCAL] if local_server_running() else keyed


_local_seen: tuple[float, bool] = (0.0, False)


def local_server_running(url: str | None = None) -> bool:
    """True when a local model server answers; checked at most once every 30 seconds."""
    global _local_seen
    import time
    import urllib.request

    if time.time() - _local_seen[0] < 30:
        return _local_seen[1]
    from staffpilot.config import load_settings

    address = (url or load_settings().llm.local_url).rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(address, timeout=1):  # noqa: S310 (the configured local address)
            running = True
    except OSError:
        running = False
    _local_seen = (time.time(), running)
    return running


def describe_error(error: Exception, chars: int = 300) -> str:
    """Error type and the start of its message, with API keys removed, for logs and the models check."""
    text = re.sub(r"(sk|AIza|key)[A-Za-z0-9_\-]{12,}", "<key>", " ".join(str(error).split()))
    return f"{type(error).__name__}: {text[:chars]}"


# Offline backend


def _find_countries(text: str, countries: list[str]) -> list[str]:
    lowered = f" {text.lower()} "
    found = [c for c in countries if re.search(rf"(?<![a-z]){re.escape(c.lower())}(?![a-z])", lowered)]
    for alias, country in COUNTRY_ALIASES.items():
        if (
            country in countries
            and country not in found
            and re.search(rf"(?<![a-z]){alias}(?![a-z])", lowered)
        ):
            found.append(country)
    return found


_MONTH_WORD = "|".join(sorted([*FULL_MONTHS, *SHORT_MONTHS], key=len, reverse=True))
_RANGES = (
    re.compile(rf"\bbetween ({_MONTH_WORD})\b(?:\s+\d{{4}})? and ({_MONTH_WORD})\b"),
    re.compile(rf"\b({_MONTH_WORD})\b(?:\s+\d{{4}})?\s*(?:to|through|thru|until|till|-)\s*({_MONTH_WORD})\b"),
)
HALVES = {r"\b(?:first|1st) half\b|\bh1\b": range(1, 7), r"\b(?:second|2nd) half\b|\bh2\b": range(7, 13)}


def _month_number(word: str) -> int:
    return FULL_MONTHS.get(word) or SHORT_MONTHS[word]


def _month_ranges(text: str) -> list[tuple[int, int]]:
    """Month ranges such as "from October through December", as (first, last) numbers."""
    lowered = text.lower()
    return [(_month_number(a), _month_number(b)) for pattern in _RANGES for a, b in pattern.findall(lowered)]


def _find_months(text: str) -> list[int]:
    lowered = text.lower()
    months: set[int] = set()
    for quarter, values in QUARTERS.items():
        if re.search(rf"\b{quarter}\b", lowered):
            months.update(values)
    for pattern, values in HALVES.items():
        if re.search(pattern, lowered):
            months.update(values)
    for first, last in _month_ranges(text):
        if first <= last:
            months.update(range(first, last + 1))
    for name, number in FULL_MONTHS.items():
        if name == "may":
            # "may" is usually a verb; only count it with a clear date context.
            if re.search(r"\b(in|of|during|for|by) may\b|\bmay \d{4}\b", lowered):
                months.add(number)
        elif re.search(rf"\b{name}\b", lowered):
            months.add(number)
    for abbreviation, number in SHORT_MONTHS.items():
        if re.search(rf"\b{abbreviation}\b", lowered):
            months.add(number)
    return sorted(months)


_TIMES = {r"\bdoubl(?:e|es|ed|ing)\b": 2.0, r"\btripl(?:e|es|ed|ing)\b": 3.0, r"\bhalv(?:e|es|ed|ing)\b": 0.5}


def _level(text: str) -> float | None:
    """A change written as a level, not a rise or fall: "doubles", "120% demand", "80 percent of forecast"."""
    for pattern, factor in _TIMES.items():
        if re.search(pattern, text):
            return factor
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+(?:of\s+)?(?:the\s+)?(?:demand|forecast|sign\s?ups?|signups?)\b",
        text,
    )
    return float(match.group(1)) / 100 if match else None


_ALL_YEAR = re.compile(r"\b(?:all|the whole|the full|the entire) year\b|\bevery month\b|\byear round\b")
_SEPARATOR = re.compile(r"\s*(?:;|,|\band\b|\bwhile\b|\bbut\b)\s*")
ONE_AT_A_TIME = (
    "I can run several sign up changes at once, but not this mix. Ask about each change on its own, "
    "for example: sign ups in India rise 50 percent in Q4."
)


def _change_sizes(text: str) -> list[str]:
    """Every size of change in the text: percents and level words such as "doubles"."""
    lowered = text.lower()
    sizes = re.findall(r"\d+(?:\.\d+)?\s*(?:%|percent)", lowered)
    return sizes + [p for p in _TIMES if re.search(p, lowered)]


def _offline_changes(text: str, countries: list[str]) -> tuple[ScenarioParams | None, str | None]:
    """Read a question with several sign up changes, such as "India grows 50% in Q4 and Brazil falls 10% all year".

    The question is cut into parts with one size of change each. A part that names no country keeps the
    country of the part before it ("Germany rises 30% in Q4 and falls 10% in Q1"). Anything the parts do
    not settle is asked back rather than guessed: a change that is not about sign ups, or months named for
    one change but not for another.
    """
    parts: list[str] = []
    for piece in _SEPARATOR.split(text):
        if parts and _change_sizes(piece) and _change_sizes(parts[-1]):
            parts.append(piece)
        elif parts:
            parts[-1] += " and " + piece
        else:
            parts.append(piece)
    changes: list[DemandChange] = []
    named_months: list[bool] = []
    place: list[str] = []
    for part in parts:
        lowered = part.lower()
        if any(
            w in lowered
            for w in ("threshold", "salar", "wage", "uplift", "capacity", "hire", "served", "service")
        ):
            return None, ONE_AT_A_TIME
        sign, pct = _direction(part), _percent(lowered)
        factor = 1 + sign * pct if pct is not None and sign else _level(lowered)
        if factor is None:
            return None, ONE_AT_A_TIME
        # A part starts mid sentence, so a leading capital is a name, not the start of a sentence.
        unknown = _unknown_places(f"and {part}", countries)
        if unknown and not _find_countries(part, countries):
            return (
                None,
                f"I do not have data for {unknown[0]}. The countries in the data are {', '.join(countries)}.",
            )
        place = _find_countries(part, countries) or place
        months = _find_months(part)
        named_months.append(bool(months) or bool(_ALL_YEAR.search(lowered)))
        try:
            changes.append(DemandChange(countries=place, months=months, multiplier=round(factor, 4)))
        except ValidationError as error:
            return None, _range_message(error)
    if any(named_months) and not all(named_months):
        return None, (
            "Which months does each change cover? For example: India grows 50 percent in Q4 and Brazil falls "
            "10 percent all year."
        )
    return ScenarioParams(adjustments=changes), None


def _crossing_range(text: str) -> str | None:
    """A question about a period that runs past December, which one planning year cannot hold."""
    for first, last in _month_ranges(text):
        if first > last:
            names = list(FULL_MONTHS)
            return (
                f"The plan covers one calendar year, so {names[first - 1].capitalize()} to "
                f"{names[last - 1].capitalize()} runs into the next year. Ask about months within the year, "
                "for example October to December."
            )
    return None


def _percent(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", text.lower())
    return float(match.group(1)) / 100 if match else None


_DOWN = ("drop", "fall", "decrease", "lower", "cut", "down", "decline", "shrink", "less", "fewer", "reduce")
_UP = ("rise", "increase", "grow", "higher", "up", "more", "jump", "raise", "boost", "surge", "spike")


def _first_word(text: str, words: tuple[str, ...]) -> int:
    hits = [m.start() for w in words for m in [re.search(rf"\b{w}(s|ed|es|ing)?\b", text)] if m]
    return min(hits) if hits else -1


def _direction(text: str) -> int:
    # "sign ups" would otherwise read as the word "up".
    lowered = re.sub(r"sign\s?ups?|signups?", "signups", text.lower())
    down, up = _first_word(lowered, _DOWN), _first_word(lowered, _UP)
    if down >= 0 and (up < 0 or down < up):
        return -1
    return 1 if up >= 0 else 0


def _offline_scenario(question: str, countries: list[str], months: list[int]) -> ScenarioParams | None:
    q = question.lower()
    pct = _percent(q)
    sign = _direction(q)
    factor = 1 + sign * pct if pct is not None and sign else None
    if factor is None:
        factor = _level(q)
    fields: dict[str, Any] = {"countries": countries, "months": months}
    if any(w in q for w in ("keep the current plan", "without replanning", "current plan", "stress")):
        fields["replan"] = False
    numbers = [int(n) for n in re.findall(r"\b(\d{1,3})\b", q)]
    if "threshold" in q and factor:
        fields["threshold_multiplier"] = round(factor, 4)
    elif any(w in q for w in ("salar", "wage", "pay ")) and factor:
        fields["salary_multiplier"] = round(factor, 4)
    elif "uplift" in q and pct is not None:
        fields["expected_uplift"] = pct
    elif ("advertisers per agent" in q or "capacity" in q or "handle" in q) and numbers:
        fields["capacity_per_agent"] = numbers[0]
    elif (
        any(w in q for w in ("hire", "hiring"))
        and any(w in q for w in ("at most", "cap", "limit", "no more than"))
        and numbers
    ):
        fields["max_hires_per_month"] = numbers[0]
    elif any(w in q for w in ("priority", "highest budget", "high budget", "largest budget")):
        fields["queue_policy"] = "budget_priority"
    elif any(w in q for w in ("carryover", "carry over", "already waiting", "waiting on 1 january")):
        fields["initial_pool"] = "carryover"
    elif any(w in q for w in ("served", "service level", "serve at least")) and pct is not None:
        fields["service_target"] = pct
    elif factor:
        fields["demand_multiplier"] = round(factor, 4)
    else:
        return None
    try:
        return ScenarioParams(**fields)
    except ValidationError as error:
        raise ScenarioRangeError(_range_message(error)) from error


class ScenarioRangeError(ValueError):
    """A scenario was understood but its numbers fall outside what the planner accepts."""


def _range_message(error: ValidationError) -> str:
    field = str(error.errors()[0].get("loc", ["value"])[0]).replace("_", " ")
    return (
        f"That {field} is outside the range the planner accepts. Multipliers must be between 0.1 and 3, "
        "so a change from a 90 percent drop up to three times the forecast."
    )


_PLACE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_NOT_PLACES = {name.capitalize() for name in FULL_MONTHS} | {
    "Christmas",
    "The",
    "Our",
    "All",
    "Each",
    "Every",
    "Google",
    "What",
    "How",
    "Which",
    "When",
    "Why",
    "Who",
    "Is",
    "Are",
    "Do",
    "Does",
    "Can",
    "Could",
    "Would",
    "Should",
    "Give",
    "Show",
    "Write",
    "Draft",
    "Compare",
    "Suppose",
    "Imagine",
    "Assume",
    "If",
    "I",
    "We",
    "Please",
    "Put",
    "Say",
    "Hold",
    "Rank",
    "Picture",
}


def _unknown_places(text: str, countries: list[str]) -> list[str]:
    """Capitalised words, other than the first word of a sentence, that look like a place but match no country."""
    known = {c.lower() for c in countries} | set(COUNTRY_ALIASES)
    unknown = []
    for match in _PLACE.finditer(text):
        if match.start() == 0 or re.search(r"[.!?:]\s*$", text[: match.start()]):
            continue
        name = match.group(1)
        first = name.split()[0]
        if first in _NOT_PLACES or name.lower() in known or first.lower() in known:
            continue
        if any(c.lower().startswith(first.lower()) for c in countries):
            continue
        unknown.append(name)
    return unknown


# Keyword lists for the offline router, checked in this order.
MEMO_WORDS = ("memo", "briefing", "brief the", "note to the", "write a summary for")
SENSITIVITY_WORDS = (
    "sensitiv",
    "robust",
    "higher or lower",
    "range of demand",
    "how much does the plan change",
)
WHAT_IF_WORDS = (
    "what if",
    "what happens if",
    "suppose",
    "if sign ups",
    "if signups",
    "if demand",
    "if the threshold",
    "if salaries",
    "if we cap",
    "if each agent",
    "if we serve",
)
COMPARE_WORDS = (
    "compare",
    "baseline",
    " versus ",
    " vs ",
    "better than",
    "keeping january",
    "keep january",
    "hold policy",
    "do nothing",
    "stack up",
)
INSIGHT_WORDS = (
    "volatil",
    "seasonal",
    "season",
    "growth",
    "grew",
    "grow",
    "eligibility rate",
    "eligible rate",
    "share of sign ups",
    "budget distribution",
    "largest budget",
    "largest eligible budget",
    "which countries have",
    "which country has",
    "trend",
    "peak month",
    "peak in sign ups",
)
RULE_TOPICS = (
    "pool",
    "wait",
    "ramp",
    "notice",
    "eligib",
    "threshold",
    "uplift",
    "capacity",
    "fire",
    "firing",
    "salary",
    "service rate",
    "utilization",
    "net value",
    "roi",
    "metric",
    "graduat",
    "support",
    "agent",
)
RULE_ASKS = (
    "rule",
    "assumption",
    "defin",
    "explain",
    "how long",
    "what does it cost",
    "what is the",
    "how is",
    "how are",
    "what happens to",
    "why does",
)
PLAN_WORDS = (
    "agent",
    "headcount",
    "hire",
    "hiring",
    "fire",
    "staff",
    "plan",
    "notice",
    "cost",
    "net value",
    "service rate",
    "need",
)
INSIGHT_KIND_WORDS = (
    ("volatility", ("volatil", "noisy", "variab")),
    ("growth", ("growth", "grew", "grow", "trend")),
    ("eligibility", ("eligib",)),
    ("budget", ("budget",)),
    ("seasonality", ("season", "peak", "month")),
)


def _has(q: str, words: tuple[str, ...]) -> bool:
    return any(w in q for w in words)


def _offline_intent(q: str, has_country: bool) -> Intent:
    q = q.lower()
    if _has(q, MEMO_WORDS):
        return Intent.memo
    if _has(q, SENSITIVITY_WORDS):
        return Intent.sensitivity
    if _has(q, WHAT_IF_WORDS):
        return Intent.what_if
    if _has(q, COMPARE_WORDS):
        return Intent.compare
    if _has(q, INSIGHT_WORDS):
        return Intent.insight
    if (
        _has(q, RULE_ASKS)
        and _has(q, RULE_TOPICS)
        and not _has(q, ("how many agents", "plan for", "need in"))
    ):
        return Intent.rules
    if _has(q, PLAN_WORDS) or has_country:
        return Intent.plan_lookup
    return Intent.out_of_scope


def _insight_kind(q: str) -> str:
    q = q.lower()
    for kind, words in INSIGHT_KIND_WORDS:
        if _has(q, words):
            return kind
    return "volatility"


def _scenario_action(facts: dict[str, float], same_service: bool) -> list[str]:
    """One closing line on what to do, chosen from the direction of the change; it holds no number."""
    change = facts.get("scenario.avg_active_scenario", 0.0) - facts.get("scenario.avg_active_base", 0.0)
    if change >= 0.5:
        return [
            "Decide the hires a month early: a new agent needs a month of ramp up before taking advertisers."
        ]
    if change <= -0.5:
        return [
            "Give the notices a month early: an agent under notice is paid for that month but takes no new advertisers."
        ]
    if same_service:
        return ["The planned team absorbs the change, so no extra hiring or notice is needed."]
    return []


class OfflineBackend:
    """Keyword router and template writer. Deterministic and free."""

    name = "offline"
    model_spec = "offline"

    def __init__(self) -> None:
        self.usage = {"input": 0, "output": 0}

    def route(self, question: str, countries: list[str], history: str = "") -> RoutedQuery:
        # The history is not read here; the assistant fills follow ups from its memory.
        text = question.strip()
        if not text:
            return RoutedQuery(
                intent=Intent.out_of_scope,
                clarification="What would you like to know about the staffing plan?",
            )
        found = _find_countries(text, countries)
        months = _find_months(text)
        intent = _offline_intent(text, bool(found))
        clarification = None
        try:
            scenario = _offline_scenario(text, found, months) if intent == Intent.what_if else None
        except ScenarioRangeError as error:
            scenario, clarification = None, str(error)
        unknown = _unknown_places(text, countries) if not found and intent != Intent.out_of_scope else []
        if unknown:
            clarification = (
                f"I do not have data for {unknown[0]}. The countries in the data are {', '.join(countries)}."
            )
        elif intent == Intent.what_if and (crossing := _crossing_range(text)):
            # A request is never changed silently: a period past December is asked about, not cut.
            scenario, clarification = None, crossing
        elif intent == Intent.what_if and len(_change_sizes(text)) > 1:
            scenario, clarification = _offline_changes(text, countries)
        elif intent == Intent.what_if and scenario is None and clarification is None:
            clarification = (
                "Which input should change, and by how much? For example: sign ups drop 30 percent in Q3."
            )
        if intent == Intent.memo and not found:
            clarification = "Which country should the memo cover?"
        return RoutedQuery(
            intent=intent,
            countries=found,
            months=months,
            scenario=scenario,
            insight_kind=_insight_kind(text) if intent == Intent.insight else None,
            clarification=clarification,
        )

    def compose(
        self,
        question: str,
        route: RoutedQuery,
        outputs: list[ToolOutput],
        facts: dict[str, str],
        feedback: str = "",
    ) -> str:
        return template_answer(route, outputs, facts)

    def draft_memo(self, country: str, facts: dict[str, str], notes: list[str]) -> MemoDraft:
        key = country.replace(" ", "_")

        def has(name: str) -> bool:
            return f"{key}.{name}" in facts

        changes = []
        if has("first_notice_month"):
            changes.append(
                f"Give notice to {{{{{key}.notices}}}} agents in total, starting in month "
                f"{{{{{key}.first_notice_month}}}}; they leave one month after notice."
            )
        if has("first_hire_month"):
            changes.append(
                f"Hire {{{{{key}.hires}}}} agents in total; the first hiring decision is in month "
                f"{{{{{key}.first_hire_month}}}}, and new agents start one month later."
            )
        if not changes:
            changes.append("Keep the current team; no hires or notices are needed.")
        return MemoDraft(
            headline=f"{country}: move from {{{{{key}.start_agents}}}} to {{{{{key}.end_agents}}}} agents, "
            f"averaging {{{{{key}.avg_active}}}} active agents.",
            headcount_changes=changes,
            cost_and_value=[
                f"Salary cost {{{{{key}.salary_cost}}}} and firing cost {{{{{key}.fire_cost}}}}.",
                f"Expected uplift value {{{{{key}.uplift_value}}}}, net value {{{{{key}.net_value}}}}.",
                f"Service rate {{{{{key}.service_rate}}}} with an average wait of {{{{{key}.mean_wait_days}}}} days.",
            ],
            rationale=[
                (
                    "Headcount follows forecast eligible sign ups, with each agent holding at most "
                    "{{rules.capacity_per_agent}} advertisers for {{rules.support_days}} days."
                ),
                (
                    "Notices cost {{rules.fire_cost_share}} of annual salary, so cuts happen early when the saving "
                    "over the rest of the year is larger than that cost."
                ),
            ],
            risks=[
                "Sign ups vary a lot from day to day; the waiting pool absorbs short peaks but not a sustained rise.",
                "The value of support assumes uplift applies to the projected annual budget.",
            ],
        )


_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _month_name(facts: dict[str, str], key: str) -> str | None:
    value = facts.get(key)
    if value is None:
        return None
    try:
        return _MONTH_NAMES[int(float(value.replace(",", ""))) - 1]
    except (ValueError, IndexError):
        return None


def _plan_lines(key: str, route: RoutedQuery, names: set[str], facts: dict[str, str]) -> list[str]:
    label = key.replace("_", " ")
    lines = [
        (
            f"{label} should start the year with {{{{{key}.start_agents}}}} agents and finish it with "
            f"{{{{{key}.end_agents}}}}, with about {{{{{key}.avg_active}}}} at work in an average month. "
            f"That keeps {{{{{key}.service_rate}}}} of eligible advertisers served, with an average wait of "
            f"{{{{{key}.mean_wait_days}}}} days, and earns {{{{{key}.net_value}}}} of net value."
        )
    ]
    cut, hire = _month_name(facts, f"{key}.first_notice_month"), _month_name(facts, f"{key}.first_hire_month")
    if cut:
        lines.append(
            f"Most of the change is a cut: {{{{{key}.notices}}}} notices in total, the first in {cut}. "
            "Notices take effect a month later, so nobody is dropped mid support."
        )
    if hire:
        lines.append(
            f"The plan also hires {{{{{key}.hires}}}} agents, starting in {hire}, so they are trained before the busy months."
        )
    for m in route.months:
        if f"{key}.active_month_{m}" not in names:
            continue
        quiet = facts.get(f"{key}.hires_month_{m}") == "0" and facts.get(f"{key}.notices_month_{m}") == "0"
        decisions = (
            "with no hiring or notice decisions that month"
            if quiet
            else f"with {{{{{key}.hires_month_{m}}}}} hires and {{{{{key}.notices_month_{m}}}}} notices decided that month"
        )
        lines.append(
            f"In {_MONTH_NAMES[m - 1]}, {{{{{key}.active_month_{m}}}}} agents are working, {decisions}."
        )
    return lines


def template_answer(route: RoutedQuery, outputs: list[ToolOutput], facts: dict[str, str]) -> str:
    """Deterministic answer with placeholders; also the fallback when a model answer fails the check.

    Written the way an analyst would say it to a manager: the answer first, then why.
    """
    if route.clarification:
        return route.clarification
    lines: list[str] = []
    names = set(facts)
    for out in outputs:
        if out.name == "get_plan":
            keys = sorted(
                {k.split(".")[0] for k in names if k.endswith(".start_agents") and not k.startswith("all")}
            )
            for key in keys:
                lines.extend(_plan_lines(key, route, names, facts))
            if not keys:
                lines.append(
                    "Across all countries the recommended plan keeps about {{all.avg_active}} agents at work, "
                    "down from {{all.start_agents}} in January. It costs {{all.total_cost}} for the year, serves "
                    "{{all.service_rate}} of eligible advertisers and earns {{all.net_value}} of net value."
                )
        elif out.name == "compare_policies":
            lines.append(
                "Keeping January headcount all year would earn {{hold.net_value}}. The optimized plan earns "
                "{{optimized.net_value}}, which is {{optimized.net_value_vs_hold}} more, almost entirely because surplus "
                "agents are let go early rather than paid to wait for work."
            )
            lines.append(
                "It still serves {{optimized.service_rate}} of eligible advertisers with about {{optimized.avg_active}} "
                "agents at work in an average month. A simple rule that follows last month's demand gets most of the "
                "way there ({{reactive.net_value}})."
            )
        elif out.name == "run_scenario":
            lead = out.notes[0].rstrip(".") if out.notes else "Under this scenario"
            lines.append(
                f"{lead}, net value goes from {{{{scenario.net_value_base}}}} to {{{{scenario.net_value_scenario}}}}, "
                "a change of {{scenario.net_value_change}}."
            )
            same = facts.get("scenario.service_rate_base") == facts.get("scenario.service_rate_scenario")
            service = (
                "service stays at {{scenario.service_rate_scenario}}"
                if same
                else "service goes from {{scenario.service_rate_base}} to {{scenario.service_rate_scenario}}"
            )
            lines.append(
                "Headcount moves from about {{scenario.avg_active_base}} to {{scenario.avg_active_scenario}} agents in an "
                f"average month, and {service}."
            )
            lines += _scenario_action(out.facts, same)
        elif out.name == "sensitivity":
            lines.append(
                "If sign ups come in a fifth below forecast, rebuilding the plan earns {{demand_80.replanned.net_value}} "
                "against {{demand_80.current_plan.net_value}} for keeping it, because surplus agents can leave."
            )
            lines.append(
                "If they come in a fifth above, the current plan still earns {{demand_120.current_plan.net_value}}, but "
                "advertisers wait about {{demand_120.current_plan.mean_wait_days}} days on average. Rebuilding it keeps "
                "waits near {{demand_120.replanned.mean_wait_days}} days. Refreshing the plan every month is the safe habit."
            )
        elif out.name == "signup_insights":
            lines.extend(out.notes)
        elif out.name == "search_rules" and out.notes:
            lines.append("Here is what the case rules say.")
            lines.extend(out.notes[:2])
    if not lines:
        lines.append(
            "That is outside what I can help with. Ask me about the staffing plan, a what if scenario, "
            "the sign up data or the case rules."
        )
    return "\n\n".join(lines)


# LangChain backends


ROUTER_PROMPT = """You read questions from a support staffing manager and turn them into a structured request.
Countries in the data: {countries}.
Intents:
* plan_lookup: how many agents, hires, notices, cost or service in the optimized plan
* compare: the optimized plan against baselines such as keeping January headcount
* what_if: a change to inputs (sign ups, threshold, salary, uplift, capacity, hiring cap, queue order, service target)
* sensitivity: how results move across a range of sign up volumes
* insight: descriptive facts about the sign up data (volatility, seasonality, eligibility, budget, growth)
* memo: a written memo for a country manager
* rules: questions about the case rules, assumptions or metric definitions
* out_of_scope: anything else
For what_if fill `scenario`. Use multipliers: a 30 percent drop is 0.7, a 20 percent rise is 1.2. Quarters map to months
(Q3 is 7, 8, 9). When the question names two or more sign up changes, each with its own countries or months, put one
item per change in scenario.adjustments and leave demand_multiplier at 1. Set replan to false only when the user wants
to keep the current plan. Copy country names exactly as listed. Never change what was asked to make it fit: ask a
clarification instead when a country is not in the data, a period runs past December, a change is outside 0.1 to 3
times, or the question gives no size of change."""

HISTORY_PROMPT = """Earlier in this conversation:
{history}
Read the new question in that context. If it is a follow up that leaves out the intent, countries, months or
scenario, carry them over from the last turn and change only what the new question changes."""

ANSWER_PROMPT = """You are StaffPilot, a staffing analyst for Google's new advertiser support teams, talking to a
country or regional manager. Write the way an experienced analyst speaks: lead with the answer in one sentence, then
the main reason, then one practical point. Two or three short paragraphs, no headings, no bullet lists, no JSON, no
phrases like "based on the data provided". Use only the facts and notes below. Write every number as a placeholder
with the exact fact name in double braces, for example {{{{Germany.avg_active}}}}. Inside the braces put only a fact
name copied from the list, never a number: {{{{Germany.avg_active}}}} is right, {{{{133}}}} is wrong. Never type a
number yourself; write months as names. If a note cites a rule source in brackets, keep the citation."""

MEMO_PROMPT = """Write a staffing memo for the {country} country manager. Use only the facts below. Write every
number as a placeholder with the exact fact name in double braces, for example {{{{{key}.hires}}}}. Never type a
number yourself except month numbers. Be specific and brief."""

JUDGE_PROMPT = """You grade answers from a staffing assistant. The facts listed are the planning model's output and are
the ground truth. Score the answer from 1 to 5:
5: answers exactly what was asked, every number matches a fact about the right country or month, nothing invented.
4: correct and grounded but misses part of the question or adds an unneeded detail.
3: mostly right but one number is attached to the wrong thing, or the main point is buried.
2: answers a different question, or a key number is wrong.
1: wrong, invented or off topic.
A polite refusal of an out of scope question scores 5. Do not reward length."""


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return str(content or "")


def _usage(message: Any) -> tuple[int, int]:
    meta = getattr(message, "usage_metadata", None) or {}
    return int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0)


def fast_reasoning(model_spec: str) -> dict[str, Any]:
    """Keep built in reasoning short. Routing and writing from given facts need little of it,
    and at the provider defaults the cheapest reasoning models take tens of seconds per call."""
    provider, _, model = model_spec.partition(":")
    if provider == "openai" and re.match(r"(gpt-5|o\d)", model):
        return {"reasoning_effort": "low"}
    if provider == "google_genai" and re.match(r"gemini-3", model):
        return {"thinking_level": "low"}
    return {}


_limiters: dict[str, Any] = {}


def chat_model(model_spec: str, settings: Settings) -> Any:
    """The LangChain chat model for a "provider:model" spec, with each provider's quirks.

    Shared by the structured assistant and the create_agent chat so both behave the same.
    """
    from langchain.chat_models import init_chat_model

    provider, _, model = model_spec.partition(":")
    kwargs: dict[str, Any] = {"timeout": settings.llm.timeout, "max_retries": settings.llm.max_retries}
    if provider == "anthropic":
        # Recent Claude models reject sampling parameters, so none are set; max_tokens is required.
        kwargs["max_tokens"] = 4096
    kwargs.update(fast_reasoning(model_spec))
    rpm = settings.llm.requests_per_minute.get("google" if provider == "google_genai" else provider, 0)
    if rpm:
        from langchain_core.rate_limiters import InMemoryRateLimiter

        # One limiter per provider, so answers and judges share the same allowance.
        kwargs["rate_limiter"] = _limiters.setdefault(
            provider, InMemoryRateLimiter(requests_per_second=rpm / 60, check_every_n_seconds=0.5)
        )
    if provider == LOCAL:
        # LM Studio speaks the OpenAI API on this computer; it needs no real key.
        kwargs.update(base_url=settings.llm.local_url, api_key="local", timeout=settings.llm.local_timeout)
        return init_chat_model(f"openai:{model}", **kwargs)
    return init_chat_model(model_spec, **kwargs)


class LangChainBackend:
    """Any chat model that LangChain's init_chat_model can build from a "provider:model" string."""

    def __init__(self, name: str, model_spec: str, settings: Settings) -> None:
        self.name = name
        self.model_spec = model_spec
        self.usage = {"input": 0, "output": 0}
        self.model = chat_model(model_spec, settings)

    def _count(self, message: Any) -> None:
        tokens_in, tokens_out = _usage(message)
        log.debug("%s call: %d input and %d output tokens", self.model_spec, tokens_in, tokens_out)
        self.usage["input"] += tokens_in
        self.usage["output"] += tokens_out

    def _structured(self, schema: type[BaseModel], messages: list[tuple[str, str]]) -> BaseModel:
        # Native JSON schema output works on every provider here and avoids forced tool choice,
        # which current Claude models reject.
        # The OpenAI client (also used for local servers) validates a Pydantic schema itself and
        # raises before StaffPilot can repair the reply, so it gets the plain JSON schema instead.
        validates_itself = self.model_spec.split(":", 1)[0] in {"openai", LOCAL}
        target = schema.model_json_schema() if validates_itself else schema
        runnable = self.model.with_structured_output(target, method="json_schema", include_raw=True)
        result = runnable.invoke(messages)
        self._count(result.get("raw"))
        parsed = result.get("parsed")
        if isinstance(parsed, BaseModel):
            return parsed
        if result.get("parsing_error") is not None or parsed is None:
            # The reply did not fit the schema; keep its JSON so a router reply can be repaired.
            try:
                parsed = json.loads(_text(result.get("raw")))
            except (TypeError, ValueError):
                raise ValueError(
                    f"{self.name} returned output that does not match {schema.__name__}"
                ) from None
        if schema is RoutedQuery:
            route, repairs = repair_route(parsed)
            if repairs:
                log.info("Repaired the %s router reply: %s", self.name, "; ".join(repairs))
            self.last_repairs = repairs
            return route
        return schema.model_validate(parsed)

    def route(self, question: str, countries: list[str], history: str = "") -> RoutedQuery:
        self.last_repairs: list[str] = []  # filled when the reply had to be repaired
        system = ROUTER_PROMPT.format(countries=", ".join(countries))
        if history:
            system += "\n\n" + HISTORY_PROMPT.format(history=history)
        messages = [("system", system), ("human", question)]
        return cast(RoutedQuery, self._structured(RoutedQuery, messages))

    def compose(
        self,
        question: str,
        route: RoutedQuery,
        outputs: list[ToolOutput],
        facts: dict[str, str],
        feedback: str = "",
    ) -> str:
        notes = "\n".join(n for o in outputs for n in o.notes)
        # Each fact is shown as the placeholder to copy, then its value, so a model that copies
        # what it sees copies the placeholder rather than the number.
        fact_lines = "\n".join(f"{{{{{k}}}}} means {v}" for k, v in sorted(facts.items()))
        body = f"Question: {question}\nIntent: {route.intent.value}\nNotes:\n{notes}\nFacts:\n{fact_lines}"
        if feedback:
            body += (
                f"\nYour previous answer was rejected: {feedback} Use placeholders for every number, and put only "
                "fact names from the list inside the braces."
            )
        message = self.model.invoke([("system", ANSWER_PROMPT), ("human", body)])
        self._count(message)
        return _text(message).strip()

    def draft_memo(self, country: str, facts: dict[str, str], notes: list[str]) -> MemoDraft:
        key = country.replace(" ", "_")
        fact_lines = "\n".join(f"{k} = {v}" for k, v in sorted(facts.items()))
        messages = [
            ("system", MEMO_PROMPT.format(country=country, key=key)),
            ("human", f"Notes:\n{chr(10).join(notes)}\nFacts:\n{fact_lines}"),
        ]
        return cast(MemoDraft, self._structured(MemoDraft, messages))

    def ping(self) -> str:
        """A tiny call that shows whether the key and the model name work."""
        message = self.model.invoke([("human", "Reply with the single word OK.")])
        self._count(message)
        return _text(message).strip()

    def judge(self, question: str, answer: str, facts: dict[str, str]) -> Judgement:
        fact_lines = "\n".join(f"{k} = {v}" for k, v in sorted(facts.items()))
        messages = [
            ("system", JUDGE_PROMPT),
            ("human", f"Question: {question}\nFacts:\n{fact_lines}\nAnswer:\n{answer}"),
        ]
        return cast(Judgement, self._structured(Judgement, messages))


@dataclass
class CachedBackend:
    """Stores model replies, with their token counts, so the notebook can be rerun without new calls."""

    inner: Any
    folder: Path

    def __post_init__(self) -> None:
        self.name = self.inner.name
        self.model_spec = getattr(self.inner, "model_spec", self.name)
        self.usage = {"input": 0, "output": 0}
        self.folder.mkdir(parents=True, exist_ok=True)
        # A "provider:model" name holds a colon, which Windows does not allow in file names.
        self.path = self.folder / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', self.name)}.jsonl"
        self._cache: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._cache[record["key"]] = record

    def _key(self, kind: str, payload: Any) -> str:
        blob = json.dumps([self.model_spec, kind, payload], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]

    def _call(self, kind: str, payload: Any, produce: Any) -> Any:
        key = self._key(kind, payload)
        if key not in self._cache:
            before = dict(getattr(self.inner, "usage", {"input": 0, "output": 0}))
            value = produce()
            after = getattr(self.inner, "usage", before)
            record = {
                "key": key,
                "value": value,
                "usage": {k: after[k] - before.get(k, 0) for k in ("input", "output")},
            }
            self._cache[key] = record
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        record = self._cache[key]
        for k in ("input", "output"):
            self.usage[k] += record.get("usage", {}).get(k, 0)
        return record["value"]

    def route(self, question: str, countries: list[str], history: str = "") -> RoutedQuery:
        # Without history the key stays the question alone, so existing cache files still match.
        payload = [question, history] if history else question
        self.last_repairs: list[str] = []

        def produce() -> dict[str, Any]:
            route = (
                self.inner.route(question, countries, history=history)
                if history
                else self.inner.route(question, countries)
            )
            # Repairs are known only when the model is really called, not on a replay.
            self.last_repairs = list(getattr(self.inner, "last_repairs", []))
            return route.model_dump(mode="json")

        value = self._call("route", payload, produce)
        return RoutedQuery.model_validate(value)

    def compose(
        self,
        question: str,
        route: RoutedQuery,
        outputs: list[ToolOutput],
        facts: dict[str, str],
        feedback: str = "",
    ) -> str:
        payload = [question, route.model_dump(mode="json"), sorted(facts.items()), feedback]
        return self._call(
            "compose", payload, lambda: self.inner.compose(question, route, outputs, facts, feedback)
        )

    def draft_memo(self, country: str, facts: dict[str, str], notes: list[str]) -> MemoDraft:
        value = self._call(
            "memo",
            [country, sorted(facts.items())],
            lambda: self.inner.draft_memo(country, facts, notes).model_dump(mode="json"),
        )
        return MemoDraft.model_validate(value)

    def judge(self, question: str, answer: str, facts: dict[str, str]) -> Judgement:
        value = self._call(
            "judge",
            [question, answer],
            lambda: self.inner.judge(question, answer, facts).model_dump(mode="json"),
        )
        return Judgement.model_validate(value)


def backend_names(providers: list[str], tier: str = "both") -> list[str]:
    """Backend names for providers: "anthropic" is the strong tier, "anthropic_fast" the fast tier."""
    names = []
    for provider in providers:
        if tier in {"strong", "both"}:
            names.append(provider)
        if tier in {"fast", "both"}:
            names.append(f"{provider}_fast")
    return names


class ModelUnavailableError(ValueError):
    """No usable model for the requested backend (unknown name, no key, or nothing answers)."""


def make_backend(name: str, settings: Settings, cache_dir: Path | None = None) -> Any:
    """Build a backend by name.

    `name` is "offline", a provider ("openai", "anthropic", "google" or "local", optionally
    with a "_fast" suffix for the cheap tier), or a full "provider:model" spec chosen in the app.
    Provider names resolve to a model through `catalog.pick_model`: the config when it
    names one, otherwise what the provider lists for this key.
    """
    if name == "offline":
        return OfflineBackend()
    load_env_file()  # keys in .env count even when nothing has read the file yet
    if ":" in name:
        spec = name
    else:
        from staffpilot.agent.catalog import pick_model

        provider, tier = (name[: -len("_fast")], "fast") if name.endswith("_fast") else (name, "strong")
        if provider not in PROVIDERS:
            raise ModelUnavailableError(f"Unknown backend {name!r}; use offline, {', '.join(PROVIDERS)}")
        spec = pick_model(settings, provider, tier)
        if spec is None:
            raise ModelUnavailableError(
                f"No {provider} model is available; check the API key with python -m staffpilot models"
            )
    backend = LangChainBackend(name, spec, settings)
    return CachedBackend(backend, cache_dir) if cache_dir else backend
