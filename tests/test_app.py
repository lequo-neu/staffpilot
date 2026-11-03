"""The app builds and every handler works on synthetic data, without starting a server."""

from __future__ import annotations

import json

import gradio as gr


def test_app_builds_and_handlers_run(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    demo = app.build_app(planner)
    assert isinstance(demo, gr.Blocks)

    history, _, details, chart, _, route, memory = app.ask(
        "What if sign ups in Alpha drop 30% in Q3?", [], "offline", None
    )
    assert history[1]["content"].startswith("If sign ups fall 30%")
    assert chart is not None and "Numbers checked" in details
    assert json.loads(route)["intent"] == "what_if"
    history, _, details, *_, memory = app.ask("And Beta?", history, "offline", memory)
    assert "it kept the" in details and len(memory.turns) == 2
    assert any(isinstance(m["content"], dict) and m["content"]["path"].endswith(".png") for m in history)
    saved = app.export_conversation(memory)
    assert saved.visible and (tmp_path / "conversations").exists()
    assert app.new_conversation()[-1].turns == []

    cards, figure, table = app.plan_view("Beta")
    assert "Net value" in cards and "<svg" in cards and figure is not None and len(table) == 12
    assert "Agent utilization" in app.plan_view("All countries")[0]

    params, understood = app.parse_scenario("Gamma sign ups rise 20%", "offline")
    summary, scenario_chart, diff = app.run_scenario(params)
    assert scenario_chart is not None
    assert "Understood as" in understood and "net value moves" in summary and len(diff) == 1

    text, memo_chart = app.memo("Alpha", "offline")
    assert "Staffing memo: Alpha" in text and memo_chart is not None
    assert "Approved" in app.approve("Alpha")
    findings, *plots, quality = app.eda_view()
    assert findings and all(p is not None for p in plots) and len(quality) > 3
    assert "need attention" not in app.alerts_html([])


def test_conversations_are_filed_and_reopened(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    first = app.send("What if sign ups in Alpha drop 30% in Q3?", [], "offline", None, {}, None)
    history, _, _, _, _, memory, chats, current, recent = first
    assert current in chats and chats[current]["title"].startswith("What if sign ups in Alpha")
    assert recent.choices[0][1] == current
    *_, chats, current, _ = app.send("And Beta?", history, "offline", memory, chats, current)
    assert len(chats) == 1 and len(chats[current]["memory"].turns) == 2

    cleared = app.start_chat(chats)
    assert cleared[0] == [] and cleared[-2] is None and cleared[-1].value is None
    *_, chats, second, _ = app.send(
        "How long can an advertiser wait in the pool?", [], "offline", None, chats, None
    )
    assert len(chats) == 2 and second != current

    reopened, memory, key = app.open_chat(current, chats)
    assert key == current and len(memory.turns) == 2 and reopened == chats[current]["history"]


def test_pages_switch_and_models_default_to_offline_without_keys(planner):
    from staffpilot import app

    app.build_app(planner)
    shown = app.show_page("Plan")
    assert [c.visible for c in shown] == [page == "Plan" for page in app.PAGES]
    choices, default = app.model_choices()
    assert default == "offline" and choices[0][1] == "offline"
    head = app.page_head("Plan")
    assert "Plan" in head and ".xlsx" not in head and "Planning" not in head
    from PIL import Image

    tab_icon = app.favicon()
    assert tab_icon and Image.open(tab_icon).size == (64, 64)


def test_model_list_starts_with_offline_then_the_cheapest(planner, monkeypatch):
    from staffpilot import app
    from staffpilot.agent import catalog
    from staffpilot.agent.catalog import ModelChoice

    app.build_app(planner)
    found = [ModelChoice("openai", "gpt-5-nano"), ModelChoice("anthropic", "claude-haiku-5-5")]
    monkeypatch.setattr(app, "usable_models", lambda settings, refresh=False: found)
    monkeypatch.setattr(app, "working_default", lambda settings, choices: choices[0].spec)
    choices, default = app.model_choices()
    assert choices[0] == ("Offline (free, no API key)", "offline")
    assert choices[1] == ("gpt-5-nano (OpenAI, default)", "openai:gpt-5-nano")
    assert choices[2] == ("claude-haiku-5-5 (Anthropic)", "anthropic:claude-haiku-5-5")
    assert default == "openai:gpt-5-nano"
    assert app.refresh_models("anthropic:claude-haiku-5-5").value == "anthropic:claude-haiku-5-5"
    assert catalog.PROVIDER_NAMES["openai"] == "OpenAI"
