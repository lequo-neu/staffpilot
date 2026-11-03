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


def test_models_command_lists_cheapest_first_and_hides_keys(monkeypatch, capsys):
    from staffpilot import cli
    from staffpilot.agent import backends, catalog

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
    assert "ok ('OK')" in out and "FAILED RuntimeError: 404" in out
    assert "<key>" in out and "AIzaSy" not in out
