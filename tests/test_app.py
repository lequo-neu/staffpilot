"""The app builds and every handler works on synthetic data, without starting a server."""

from __future__ import annotations

import json

import gradio as gr


def test_app_builds_and_handlers_run(planner, tmp_path, monkeypatch):
    from staffpilot import app
    from staffpilot.ui import components

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    demo = app.build_app(planner)
    assert isinstance(demo, gr.Blocks)

    history, _, details, chart, _, route, memory = app.ask(
        "What if sign ups in Alpha drop 30% in Q3?", [], "offline", None
    )
    assert history[1]["content"].startswith("If sign ups fall 30%")
    assert chart is not None and "Numbers checked" in details and "planner facts" in details
    assert json.loads(route)["intent"] == "what_if"
    history, _, details, *_, memory = app.ask("And Beta?", history, "offline", memory)
    assert "it kept the" in details and len(memory.turns) == 2
    assert any(isinstance(m["content"], dict) and m["content"]["path"].endswith(".png") for m in history)
    saved = app.export_conversation(memory)
    assert saved.visible and (tmp_path / "conversations").exists()
    assert app.start_chat({})[5].turns == []

    cards, figure, table = app.plan_view("Beta")
    assert "Net value" in cards and "<svg" in cards and figure is not None and len(table.data) == 12
    # Months with a decision are tinted: hires in teal, notices in red.
    assert "rgba(" in app.plan_view("All countries")[2].to_html()
    assert "Agent utilization" in app.plan_view("All countries")[0]

    params, understood, proposal = app.parse_scenario("Gamma sign ups rise 20%", "offline")
    summary, scenario_chart, diff = app.run_scenario(params, proposal)
    assert scenario_chart is not None
    assert "Understood as" in understood and "net value moves" in summary and len(diff.data) == 1

    assert app.open_memo("Plan", False, "Alpha", "offline")[0] is False
    seen, opened, _ = app.open_memo("Memo", False, "Alpha", "offline")
    assert seen and "Staffing memo: Alpha" in opened
    assert "Answered by <b>Offline" in app.composer_note(
        "offline", [("Offline (free, no API key)", "offline")]
    )
    preview = app.run_scenario(params, proposal, record=False)
    assert "net value moves" in preview[0]
    text, memo_chart = app.memo("Alpha", "offline")
    assert "Staffing memo: Alpha" in text and memo_chart is not None
    assert "Approved" in app.approve("Alpha")
    facts, *plots, checks, quality = app.eda_view()
    assert "sp-questions" in facts and "Is demand seasonal?" in facts and "Is demand growing?" in facts
    assert all(p is not None for p in plots) and len(quality) > 3
    assert "checks pass" in checks and "Fail" not in checks
    # The committed evaluation results are read; runs exist only where the plan command was run.
    lead, chart, scores, retrieval, retrieval_rows, run_facts, _ = app.eval_view()
    assert "holdout" in lead and chart is not None and len(scores.data) >= 3
    assert "rule questions find the right passage" in retrieval and len(retrieval_rows.data) >= 1
    assert run_facts == "" or "recorded plan runs" in run_facts
    assert "Nothing needs attention" in components.alert_list([])


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


def test_models_are_checked_but_offline_stays_the_default(planner, monkeypatch):
    from staffpilot import app
    from staffpilot.agent import catalog
    from staffpilot.agent.catalog import ModelChoice

    app.build_app(planner)
    found = [ModelChoice("openai", "gpt-5-nano"), ModelChoice("anthropic", "claude-haiku-5-5")]
    monkeypatch.setattr(app, "usable_models", lambda settings, refresh=False: found)
    checked = []

    def check(settings, choices):
        checked.append([c.spec for c in choices])
        return "openai:gpt-5-nano"

    monkeypatch.setattr(app, "working_default", check)
    choices, default = app.model_choices()
    assert checked == [["openai:gpt-5-nano", "anthropic:claude-haiku-5-5"]]
    assert default == "offline"
    assert choices[0] == ("Offline (free, no API key)", "offline")
    assert choices[1] == ("gpt-5-nano (OpenAI, cheapest working)", "openai:gpt-5-nano")
    assert choices[2] == ("claude-haiku-5-5 (Anthropic)", "anthropic:claude-haiku-5-5")
    assert app.refresh_models("anthropic:claude-haiku-5-5").value == "anthropic:claude-haiku-5-5"
    assert app.refresh_models("openai:retired-model").value == "offline"
    assert catalog.PROVIDER_NAMES["openai"] == "OpenAI"


def test_charts_reach_the_browser_as_sharp_png():
    import base64
    import io

    from PIL import Image

    from staffpilot import charts
    from staffpilot.ui.components import WEB_DPI, sharp

    fig, (ax,) = charts.new_figure(width=8.0, height=3.6)
    ax.plot([1, 2, 3], [1, 3, 2])
    data = sharp(fig).plot
    assert data.startswith("data:image/png;base64,")
    picture = Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1])))
    assert picture.size[0] == 8 * WEB_DPI
    assert fig.get_dpi() == 110  # the figure itself is left as it was
    assert sharp(None) is None


def test_counts_must_be_whole_numbers_of_zero_or_more():
    from staffpilot import app

    values, bad = app.whole_numbers([0, "3", 12.0])
    assert bad == [] and values.tolist() == [0, 3, 12]
    assert app.whole_numbers(["x", -1, 2.5, None, "", 4])[1] == [0, 1, 2, 3, 4]


def test_this_year_states_the_limits_and_the_goal_as_a_floor(planner, tmp_path, monkeypatch):
    from staffpilot import app
    from staffpilot.ui import components

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    tiles = app.home_verdict()
    assert "more than keeping the January team" in tiles and "%)" in tiles and "fewer)" in tiles
    assert "(limit 60)" in tiles and "advertisers per agent (limit 10)" in tiles
    app.approve("All countries")
    tiles = app.home_verdict()
    assert "goal: Profit, at least 98% served (recommended)" in tiles and "Reached:" in tiles
    # An alert where the manager acts carries a button that opens that page.
    assert 'data-sp-open="Plan"' in components.alert_list(
        [components.Alert("warning", "hiring", "x", (), "Plan")]
    )
