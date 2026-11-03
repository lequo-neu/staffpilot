"""Which language models each provider offers to this account, and which one is cheapest.

Model names change every few months, so none is written in the code. For every
provider with a key, `available_models` asks the provider's model list endpoint (a
free metadata request, no tokens), keeps the chat models and sorts them from the
cheapest to the most expensive:

* by the price table in the config (`[llm.prices]`) when the model is listed there,
* otherwise by the model family in its name: nano, lite, then mini, haiku and flash,
  then the standard models, then sonnet, pro and opus.

A listed model is not always usable: providers keep retired models in the list and
answer 404 when they are called. `working_default` therefore sends one tiny request
to the cheapest models until one answers, and remembers the outcome for a day.

`[llm.models]` and `[llm.fast_models]` in the config still win when they are set,
which keeps an evaluation repeatable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import os
import re
import time
from typing import Any
import urllib.request

from staffpilot.agent import backends
from staffpilot.agent.backends import PROVIDER_KEYS, describe_error
from staffpilot.config import Settings


log = logging.getLogger(__name__)

LANGCHAIN_PREFIX = {"openai": "openai", "anthropic": "anthropic", "google": "google_genai", "local": "local"}
PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "local": "on this computer",
}
CACHE_SECONDS = 3600
# Lower is cheaper. The first matching word decides.
# Rough blended price (US dollars per million tokens) of each rank, used only to compare a
# model without a configured price against one with a price; they are not quoted anywhere.
RANK_PRICE = {0: 0.1, 1: 0.15, 2: 0.6, 5: 3.0, 6: 6.0, 8: 6.0, 9: 20.0}
FAMILY_RANK = (
    ("nano", 0),
    ("lite", 1),
    ("mini", 2),
    ("haiku", 2),
    ("flash", 2),
    ("opus", 9),
    ("pro", 8),
    ("sonnet", 6),
)
STANDARD_RANK = 5
# Names that are not plain chat models (speech, images, embeddings, search and so on).
NOT_CHAT = (
    "embed",
    "tts",
    "audio",
    "realtime",
    "transcribe",
    "image",
    "dall",
    "whisper",
    "moderation",
    "search",
    "aqa",
    "live",
    "omni",
    "lyria",
    "veo",
    "imagen",
    "banana",
    "codex",
    "computer",
    "instruct",
    "davinci",
    "babbage",
    "customtools",
    "robotics",
)
# On a local server only these mark a model that cannot chat; names such as
# the Llama 3.1 8B "instruct" build are ordinary chat models there.
LOCAL_NOT_CHAT = ("embed", "rerank", "whisper", "tts")
_cache: dict[str, tuple[float, list[str]]] = {}


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str

    @property
    def spec(self) -> str:
        """The "provider:model" string LangChain's init_chat_model reads."""
        return f"{LANGCHAIN_PREFIX[self.provider]}:{self.model}"

    @property
    def label(self) -> str:
        return f"{self.model} ({PROVIDER_NAMES[self.provider]})"


def _key(provider: str) -> str:
    return next((os.environ[k] for k in PROVIDER_KEYS[provider] if os.environ.get(k)), "")


def _get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    # Only the fixed provider addresses and the configured local server reach this function.
    with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
        return json.load(response)


def fetch_models(provider: str) -> list[str]:
    """Model ids the provider lists for this key. Raises on network or key errors."""
    if provider == backends.LOCAL:
        from staffpilot.config import load_settings

        data = _get(load_settings().llm.local_url.rstrip("/") + "/models", {})
        return [m["id"] for m in data.get("data", [])]
    key = _key(provider)
    if provider == "openai":
        data = _get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        return [m["id"] for m in data.get("data", [])]
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        data = _get("https://api.anthropic.com/v1/models?limit=100", headers)
        return [m["id"] for m in data.get("data", [])]
    if provider == "google":
        data = _get(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": key}
        )
        return [
            m["name"].removeprefix("models/")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    raise ValueError(f"Unknown provider {provider!r}")


def is_chat_model(provider: str, model: str) -> bool:
    name = model.lower()
    if provider == backends.LOCAL:
        return not any(word in name for word in LOCAL_NOT_CHAT)
    if any(word in name for word in NOT_CHAT):
        return False
    if provider == "openai":
        # Chat models are the gpt family and the o series reasoning models.
        return bool(re.match(r"(gpt|o\d|chatgpt)", name)) and "gpt-3.5" not in name
    if provider == "google":
        return name.startswith("gemini") and "gemini-1" not in name
    return name.startswith("claude")


def drop_snapshots(models: list[str]) -> list[str]:
    """Leave out dated copies such as gpt-5-nano-2025-08-07 when the plain name is also listed."""
    dated = re.compile(r"^(.*?)-(\d{4}-\d{2}-\d{2}|\d{8})$")
    names = set(models)
    return [m for m in models if not ((match := dated.match(m)) and match.group(1) in names)]


def family_rank(model: str) -> int:
    # Whole name parts only: "gemini" must not count as "mini".
    parts = set(re.split(r"[^a-z0-9]+", model.lower()))
    return next((rank for word, rank in FAMILY_RANK if word in parts), STANDARD_RANK)


def cost_key(choice: ModelChoice, prices: dict[str, list[float]]) -> tuple:
    """Sort key from cheapest to most expensive: a configured price when there is one, else the family estimate."""
    # Models on this computer cost nothing per token.
    price = [0.0, 0.0] if choice.provider == backends.LOCAL else prices.get(choice.spec)
    # A typical question reads about four times more tokens than it writes.
    blended = 0.8 * price[0] + 0.2 * price[1] if price else RANK_PRICE[family_rank(choice.model)]
    # At the same price a model without built in reasoning answers in seconds instead of tens of
    # seconds, so it comes first.
    return (blended, _reasoning(choice), _unstable(choice.model), len(choice.model), choice.model)


def _reasoning(choice: ModelChoice) -> bool:
    return bool(backends.fast_reasoning(choice.spec))


def provider_models(provider: str, refresh: bool = False) -> list[str]:
    """Chat models of one provider, cached for an hour; empty when the listing fails."""
    cached = _cache.get(provider)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        models = drop_snapshots(sorted({m for m in fetch_models(provider) if is_chat_model(provider, m)}))
    except Exception as error:  # a provider that cannot be reached is left out, not fatal
        log.warning("Could not list %s models. %s", provider, describe_error(error))
        models = []
    _cache[provider] = (time.time(), models)
    log.info("%s lists %d chat models", provider, len(models))
    return models


def available_models(settings: Settings, refresh: bool = False) -> list[ModelChoice]:
    """Every chat model this account can use, cheapest first."""
    providers = backends.available_providers()
    # One request per provider, sent together so a slow provider does not add up.
    with ThreadPoolExecutor(max_workers=max(1, len(providers))) as pool:
        listed = list(pool.map(lambda p: provider_models(p, refresh), providers))
    choices = [
        ModelChoice(provider, model)
        for provider, models in zip(providers, listed, strict=True)
        for model in models
    ]
    return sorted(choices, key=lambda c: cost_key(c, settings.llm.prices))


def pick_model(settings: Settings, provider: str, tier: str) -> str | None:
    """The model spec for a provider and tier.

    The config wins when it names one. Otherwise the provider's models are put in order
    (cheapest first for the fast tier, most capable first for the strong tier) and the
    first one that answers a tiny check is used, so a retired model is never picked.
    """
    configured = (settings.llm.fast_models if tier == "fast" else settings.llm.models).get(provider)
    if configured:
        return configured
    listed = [ModelChoice(provider, m) for m in provider_models(provider)]
    if provider == backends.LOCAL:
        # All local models are free, so size decides: the smallest is fast, the largest strong.
        ordered = sorted(listed, key=lambda c: _billions(c.model), reverse=tier != "fast")
    elif tier == "fast":
        ordered = sorted(listed, key=lambda c: cost_key(c, settings.llm.prices))
    else:
        # The most capable family, then stable names before previews, then the newest version.
        # OpenAI's "pro" models are a premium tier priced far above the rest, so they are skipped.
        ordered = sorted(
            [c for c in listed if not (provider == "openai" and "pro" in c.model.lower())] or listed,
            key=lambda c: (family_rank(c.model), not _unstable(c.model), _version(c.model), -len(c.model)),
            reverse=True,
        )
    return working_default(settings, ordered) if ordered else None


def _billions(model: str) -> float:
    """Parameter count read from a name such as qwen3.6-27b or gemma-4-e4b (in billions)."""
    sizes = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)b\b", model.lower())]
    return max(sizes) if sizes else 0.0


def _unstable(model: str) -> bool:
    name = model.lower()
    return "preview" in name or "exp" in name or "latest" in name


def _version(model: str) -> tuple[int, ...]:
    # Dates in snapshot names (20251001) are not versions, so only small numbers count.
    return tuple(int(n) for n in re.findall(r"\d+", model) if int(n) < 100)


CHECK_SECONDS = 24 * 3600
MAX_CHECKS = 4


def _checks_file():
    from staffpilot import cache

    return cache.folder() / "model_checks.json"


def _load_checks() -> dict[str, dict[str, Any]]:
    try:
        checks = json.loads(_checks_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in checks.items() if time.time() - v.get("time", 0) < CHECK_SECONDS}


def _save_checks(checks: dict[str, dict[str, Any]]) -> None:
    try:
        path = _checks_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(checks, indent=1), encoding="utf-8")
    except OSError:
        pass


def usable_models(settings: Settings, refresh: bool = False) -> list[ModelChoice]:
    """Listed models, cheapest first, without the ones that failed a check in the last day."""
    failed = {k for k, v in _load_checks().items() if not v.get("ok")}
    return [c for c in available_models(settings, refresh) if c.spec not in failed]


def working_default(settings: Settings, choices: list[ModelChoice] | None = None) -> str | None:
    """The first of `choices` (by default every usable model, cheapest first) that answers a
    tiny request. Each model is checked at most once a day; failures are skipped."""
    from staffpilot.agent.backends import LangChainBackend

    checks = _load_checks()
    candidates = choices if choices is not None else usable_models(settings)
    tried = 0
    for choice in candidates:
        known = checks.get(choice.spec)
        if known is not None:
            if known.get("ok"):
                return choice.spec
            continue
        if tried == MAX_CHECKS:
            break
        tried += 1
        try:
            LangChainBackend(choice.spec, choice.spec, settings).ping()
        except Exception as error:  # a retired or unavailable model is skipped
            checks[choice.spec] = {"ok": False, "time": time.time(), "reason": describe_error(error, 160)}
            _save_checks(checks)
            log.warning("Skipping %s. %s", choice.spec, describe_error(error, 160))
            continue
        checks[choice.spec] = {"ok": True, "time": time.time()}
        _save_checks(checks)
        log.info("Default model %s answered the check", choice.spec)
        return choice.spec
    return None
