"""Model discovery: chat models only, cheapest first, the config wins when it names a model."""

from __future__ import annotations

from typing import ClassVar

import pytest

from staffpilot.agent import backends, catalog
from staffpilot.agent.catalog import ModelChoice, available_models, is_chat_model, pick_model


LISTS = {
    "openai": [
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5-pro",
        "text-embedding-3-small",
        "gpt-4o-realtime-preview",
    ],
    "anthropic": ["claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-5-5"],
    "google": ["gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-pro-image"],
}


@pytest.fixture(autouse=True)
def fresh_checks(tmp_path, monkeypatch):
    # Each test starts with no remembered model checks.
    monkeypatch.setattr(catalog, "_checks_file", lambda: tmp_path / "model_checks.json")


@pytest.fixture
def listed(monkeypatch):
    catalog._cache.clear()
    monkeypatch.setattr(backends, "available_providers", lambda: list(LISTS))
    monkeypatch.setattr(catalog, "fetch_models", lambda provider: LISTS[provider])
    yield
    catalog._cache.clear()


def test_only_chat_models_are_kept():
    assert is_chat_model("openai", "gpt-5-mini")
    assert not is_chat_model("openai", "text-embedding-3-small")
    assert not is_chat_model("openai", "gpt-4o-realtime-preview")
    assert not is_chat_model("google", "gemini-3-pro-image")
    assert is_chat_model("anthropic", "claude-haiku-5-5")


def test_models_are_sorted_cheapest_first(listed, settings):
    choices = available_models(settings)
    assert choices[0] == ModelChoice("openai", "gpt-5-nano")  # the only nano listed here
    assert choices[-1].model == "claude-opus-5-5"
    assert all(c.spec.split(":")[0] in {"openai", "anthropic", "google_genai"} for c in choices)


def test_a_configured_price_overrides_the_name_guess(listed, settings):
    priced = settings.with_updates(llm={"prices": {"anthropic:claude-opus-5-5": [0.01, 0.01]}})
    assert available_models(priced)[0].spec == "anthropic:claude-opus-5-5"


@pytest.fixture
def answering(monkeypatch):
    """Every model answers the tiny check, except the ones listed in `answering.down`."""

    class Fake:
        down: ClassVar[set[str]] = set()

        def __init__(self, name, spec, settings):
            self.spec = spec

        def ping(self):
            if self.spec in Fake.down:
                raise RuntimeError("404 model not found")
            return "OK"

    Fake.down = set()
    monkeypatch.setattr(backends, "LangChainBackend", Fake)
    return Fake


def test_tiers_pick_cheapest_and_strongest(listed, settings, answering):
    assert pick_model(settings, "google", "fast") == "google_genai:gemini-3.1-flash-lite"
    assert pick_model(settings, "anthropic", "strong") == "anthropic:claude-opus-5-5"
    # The premium "pro" tier of OpenAI is never picked automatically.
    assert pick_model(settings, "openai", "strong") == "openai:gpt-5"


def test_a_retired_model_is_never_picked_for_a_tier(listed, settings, answering):
    answering.down = {"google_genai:gemini-3.1-flash-lite", "google_genai:gemini-3.1-pro-preview"}
    assert pick_model(settings, "google", "fast") != "google_genai:gemini-3.1-flash-lite"
    assert pick_model(settings, "google", "strong") == "google_genai:gemini-3.5-flash"


def test_the_config_wins_over_discovery(listed, settings):
    pinned = settings.with_updates(llm={"fast_models": {"google": "google_genai:my-model"}})
    assert pick_model(pinned, "google", "fast") == "google_genai:my-model"


def test_a_provider_that_cannot_be_listed_is_left_out(monkeypatch, settings):
    catalog._cache.clear()

    def broken(provider):
        raise OSError("network down")

    monkeypatch.setattr(backends, "available_providers", lambda: ["openai"])
    monkeypatch.setattr(catalog, "fetch_models", broken)
    assert available_models(settings) == []
    assert pick_model(settings, "openai", "fast") is None
    catalog._cache.clear()


def test_a_full_model_spec_builds_a_backend(settings, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    backend = backends.make_backend("openai:gpt-5-nano", settings)
    assert backend.model_spec == "openai:gpt-5-nano"


def test_dated_snapshots_are_hidden_when_the_plain_name_exists():
    from staffpilot.agent.catalog import drop_snapshots

    listed = ["gpt-5-nano", "gpt-5-nano-2025-08-07", "claude-haiku-4-5-20251001", "gpt-4o"]
    assert drop_snapshots(listed) == ["gpt-5-nano", "claude-haiku-4-5-20251001", "gpt-4o"]


def test_reasoning_is_kept_short_for_reasoning_models():
    from staffpilot.agent.backends import fast_reasoning

    assert fast_reasoning("openai:gpt-5-nano") == {"reasoning_effort": "low"}
    assert fast_reasoning("openai:o4-mini") == {"reasoning_effort": "low"}
    assert fast_reasoning("openai:gpt-4.1-nano") == {}
    assert fast_reasoning("google_genai:gemini-3.5-flash") == {"thinking_level": "low"}
    assert fast_reasoning("anthropic:claude-haiku-5-5") == {}


def test_default_skips_retired_models_and_remembers_the_checks(listed, settings, monkeypatch):
    from staffpilot.agent import backends as b

    calls = []

    class Fake:
        def __init__(self, name, spec, settings):
            self.spec = spec

        def ping(self):
            calls.append(self.spec)
            if self.spec == "openai:gpt-5-nano":
                raise RuntimeError("404 The model has been deprecated")
            return "OK"

    monkeypatch.setattr(b, "LangChainBackend", Fake)
    first = catalog.working_default(settings)
    assert first != "openai:gpt-5-nano" and calls[0] == "openai:gpt-5-nano"
    assert catalog.working_default(settings) == first and len(calls) == 2  # read from the stored checks
    assert "openai:gpt-5-nano" not in [c.spec for c in catalog.usable_models(settings)]


def test_error_messages_never_show_api_keys():
    from staffpilot.agent.backends import describe_error

    text = describe_error(
        RuntimeError("404 not found for key AIzaSyA1b2C3d4E5f6G7h8I9j0 and sk-proj1234567890abcdef")
    )
    assert text.startswith("RuntimeError: 404") and "AIzaSy" not in text and "sk-proj" not in text
