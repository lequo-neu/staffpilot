from __future__ import annotations

import pandas as pd
import pytest

from staffpilot.alerts import plan_alerts
from staffpilot.planner import Planner
from staffpilot.tracking import history, record_run


def test_alerts_flag_wrong_year_understaffing_and_the_key_assumption(settings, dataset):
    planner = Planner(settings.with_updates(planning={"expected_year": 2020}), dataset)
    alerts = plan_alerts(planner)
    levels = {a.topic: a.level for a in alerts}
    assert levels["data"] == "critical"
    assert levels["hiring"] == "warning" and "Beta" in next(a for a in alerts if a.topic == "hiring").message
    assert levels["assumption"] == "info"
    assert [a.level for a in alerts] == sorted(
        (a.level for a in alerts), key=["critical", "warning", "info"].index
    )


def test_no_year_alert_when_the_year_matches(settings, dataset):
    planner = Planner(settings.with_updates(planning={"expected_year": dataset.planning_year()}), dataset)
    assert all(a.topic != "data" or a.level != "critical" for a in plan_alerts(planner))


def test_run_history_round_trip(settings, tmp_path):
    runs = tmp_path / "runs.jsonl"
    data = tmp_path / "data.bin"
    data.write_bytes(b"abc")
    record_run(
        "plan", settings, {"net_value": 1.5, "service_rate": 0.99}, 2.0, data, {"planning_year": 2033}, runs
    )
    record_run("eda", settings, {}, 0.5, runs_file=runs)
    frame = history(runs_file=runs)
    assert list(frame["kind"]) == ["plan", "eda"]
    assert frame.loc[0, "dataset"] == "data.bin" and frame.loc[0, "net_value"] == 1.5
    assert len(frame.loc[0, "dataset_sha"]) == 12


@pytest.fixture
def workbook(tmp_path, signups):
    from tests.conftest import COUNTRIES, STAFFING

    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        COUNTRIES.to_excel(writer, sheet_name="Agent Salary and Threshold", index=False)
        signups.to_excel(writer, sheet_name="Advertiser Sign-ups", index=False)
        STAFFING.to_excel(writer, sheet_name="Existing Agent Staffing", index=False)
    config = tmp_path / "test.toml"
    config.write_text(
        f'[data]\npath = "{path.as_posix()}"\n[planning]\nlookahead_months = 2\n', encoding="utf-8"
    )
    return config


def test_command_line_end_to_end(workbook, tmp_path, monkeypatch, capsys):
    from staffpilot import cli, tracking

    monkeypatch.setenv("STAFFPILOT_CONFIG", str(workbook))
    monkeypatch.setattr(cli, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(tracking, "RUNS_FILE", tmp_path / "runs.jsonl")
    cli.main(["plan"])
    assert (tmp_path / "outputs" / "plan.csv").exists()
    cli.main(["eda"])
    assert (tmp_path / "outputs" / "eda" / "eda_report.md").exists()
    cli.main(["ask", "What if sign ups in Alpha drop 30% in Q3?"])
    cli.main(["memo", "Beta"])
    cli.main(["history"])
    replies = iter(["What if sign ups in Alpha drop 30% in Q3?", "And Beta?", "save", "new", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    cli.main(["chat"])
    out = capsys.readouterr().out
    assert "Alerts:" in out and "Chart saved to" in out and "plan" in out
    assert "Kept the kind of question" in out and "Started a new conversation" in out
    assert (tmp_path / "outputs" / "conversations" / "chat.md").exists()
    assert list((tmp_path / "outputs" / "answers").glob("*.png"))


def test_missing_data_gives_a_message_not_a_traceback(tmp_path, monkeypatch, capsys):
    from staffpilot import cli

    config = tmp_path / "missing.toml"
    config.write_text(f'[data]\npath = "{(tmp_path / "nothing.xlsx").as_posix()}"\n', encoding="utf-8")
    monkeypatch.setenv("STAFFPILOT_CONFIG", str(config))
    with pytest.raises(SystemExit) as stop:
        cli.main(["plan"])
    assert stop.value.code == 2
    assert "Data problem" in capsys.readouterr().err


def test_models_command_lists_cheapest_first_and_hides_keys(monkeypatch, capsys, tmp_path):
    from staffpilot import cli
    from staffpilot.agent import backends, catalog

    # A config without pinned models, so the tiers come from the listing below.
    no_pins = tmp_path / "no_pins.toml"
    no_pins.write_text("", encoding="utf-8")
    monkeypatch.setenv("STAFFPILOT_CONFIG", str(no_pins))

    class Fake:
        def __init__(self, name, spec, settings):
            self.spec = spec

        def ping(self):
            if "pro" in self.spec:
                raise RuntimeError("404 not found for key AIzaSyA1b2C3d4E5f6G7h8I9j0")
            return "OK"

    listed = [
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-preview-tts",
    ]
    monkeypatch.setattr(backends, "available_providers", lambda: ["google"])
    monkeypatch.setattr(catalog, "fetch_models", lambda provider: listed)
    monkeypatch.setattr(backends, "LangChainBackend", Fake)
    cli.main(["models", "--ping"])
    out = capsys.readouterr().out
    lines = [line.strip() for line in out.splitlines() if line.strip().startswith("google_genai:")]
    assert lines[0].startswith("google_genai:gemini-3.1-flash-lite") and "fast tier" in lines[0]
    assert not any("tts" in line for line in lines)
    # The strong tier skips the model that does not answer and uses the next best one.
    assert "google_genai:gemini-3.5-flash   <- strong tier" in out
    assert "ok ('OK')" in out and "FAILED" not in out and "AIzaSy" not in out


def test_agent_chat_shows_tools_and_the_number_check(workbook, monkeypatch, capsys):
    from staffpilot import cli
    from staffpilot.agent import backends, chat_agent

    class Spec:
        model_spec = "anthropic:test-model"

    seen = []

    def fake_chat(agent, message, thread_id):
        seen.append(thread_id)
        return chat_agent.ChatReply("Alpha gives 12 notices.", ["get_plan"], ["99"])

    monkeypatch.setenv("STAFFPILOT_CONFIG", str(workbook))
    monkeypatch.setattr(backends, "make_backend", lambda name, settings, cache_dir=None: Spec())
    monkeypatch.setattr(chat_agent, "build_chat_agent", lambda tools, spec, settings: object())
    monkeypatch.setattr(chat_agent, "chat", fake_chat)
    replies = iter(["Which country cuts most?", "new", "And next?", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    cli.main(["chat", "--agent", "--backend", "anthropic_fast"])
    out = capsys.readouterr().out
    assert "Agent chat with anthropic:test-model" in out and "tools called: get_plan" in out
    assert "numbers not found in the tool output: 99" in out
    assert seen == ["cli_1", "cli_2"]  # 'new' starts a fresh thread

    cli.main(["chat", "--agent"])
    assert "The agent needs a language model" in capsys.readouterr().out


def test_an_unknown_backend_gives_a_message_not_a_traceback(workbook, monkeypatch, capsys):
    from staffpilot import cli

    monkeypatch.setenv("STAFFPILOT_CONFIG", str(workbook))
    with pytest.raises(SystemExit) as stop:
        cli.main(["ask", "How many agents?", "--backend", "nonsense"])
    assert stop.value.code == 2
    assert "Model problem: Unknown backend 'nonsense'" in capsys.readouterr().err


def test_eval_lineups_for_online_keys_and_local_models(monkeypatch, capsys):
    import argparse

    from staffpilot import cli
    from staffpilot.agent import backends, catalog

    def args(source, *words):
        return argparse.Namespace(source=source, providers=list(words), tier="fast", skip_agent=True)

    monkeypatch.setattr(backends, "available_providers", lambda: ["anthropic", "google", "local"])
    names, judges = cli._eval_lineup(args("online"))
    assert names == ["offline", "anthropic_fast", "google_fast"] and judges == ["anthropic", "google"]

    monkeypatch.setattr(backends, "local_server_running", lambda url=None: True)
    monkeypatch.setattr(
        catalog,
        "provider_models",
        lambda provider, refresh=False: ["google/gemma-4-e4b", "meta/llama-3.1-8b", "qwen/qwen3.6-27b"],
    )
    names, judges = cli._eval_lineup(args("local", "gemma", "llama"))
    assert names == ["offline", "local:google/gemma-4-e4b", "local:meta/llama-3.1-8b"]
    assert judges == names[1:] and "no cost" in capsys.readouterr().out
    assert cli._eval_lineup(args("local", "gemma")) is None
    assert "load at least two" in capsys.readouterr().out

    monkeypatch.setattr(backends, "local_server_running", lambda url=None: False)
    assert cli._eval_lineup(args("local")) is None
    assert "lms server start" in capsys.readouterr().out
