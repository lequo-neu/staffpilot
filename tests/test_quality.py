"""Syntax, imports and logging: the checks that catch a broken checkout first."""

from __future__ import annotations

import compileall
import importlib
import logging
from pathlib import Path
import pkgutil
import re

import staffpilot
from staffpilot.logs import configure_logging


ROOT = Path(__file__).resolve().parents[1]


def test_every_python_file_compiles():
    for folder in ("src", "scripts", "tests"):
        assert compileall.compile_dir(ROOT / folder, quiet=1, force=True), folder


def test_every_module_imports():
    names = [
        m.name
        for m in pkgutil.walk_packages(staffpilot.__path__, "staffpilot.")
        if not m.name.endswith("__main__")
    ]
    for name in names:
        importlib.import_module(name)
    assert "staffpilot.agent.assistant" in names


def test_log_level_comes_from_argument_then_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STAFFPILOT_LOG_LEVEL", "INFO")
    assert configure_logging(log_dir=tmp_path) == "INFO"
    assert configure_logging("debug", log_dir=tmp_path) == "DEBUG"
    assert configure_logging("nonsense", log_dir=tmp_path) == "WARNING"
    configure_logging("WARNING", log_dir=tmp_path)


def test_each_run_gets_its_own_log_file_with_a_header(tmp_path):
    configure_logging("WARNING", log_dir=tmp_path, run_name="plan")
    logging.getLogger("staffpilot.test").info("kept in the file even at WARNING")
    for handler in logging.getLogger("staffpilot").handlers:
        handler.flush()
    (path,) = tmp_path.glob("*_plan.log")
    assert re.fullmatch(r"\d{8}_\d{6}_plan\.log", path.name)
    text = path.read_text(encoding="utf-8")
    assert "Run 'plan' started" in text and "Data file:" in text
    assert "kept in the file even at WARNING" in text


def test_old_log_files_are_pruned(tmp_path, monkeypatch):
    from staffpilot import logs

    monkeypatch.setattr(logs, "KEEP_FILES", 3)
    for i in range(5):
        (tmp_path / f"20260101_00000{i}_old.log").write_text("x", encoding="utf-8")
    configure_logging("WARNING", log_dir=tmp_path, run_name="new")
    names = sorted(p.name for p in tmp_path.glob("*.log"))
    assert len(names) == 3 and names[-1].endswith("_new.log")


def test_cached_plans_match_a_fresh_solve(planner, monkeypatch, tmp_path):
    from staffpilot.planner import Planner

    monkeypatch.setenv("STAFFPILOT_CACHE_DIR", str(tmp_path))
    first = Planner(planner.settings, planner.dataset).run("hold").totals()
    assert list((tmp_path / "plans").glob("*.pkl"))
    again = Planner(planner.settings, planner.dataset).run("hold").totals()
    monkeypatch.setenv("STAFFPILOT_NO_CACHE", "1")
    fresh = Planner(planner.settings, planner.dataset).run("hold").totals()
    assert first == again == fresh
    # Different settings must not reuse the cached plan.
    monkeypatch.delenv("STAFFPILOT_NO_CACHE")
    cheaper = planner.settings.with_updates(planning={"wait_penalty_per_week": 0.02})
    Planner(cheaper, planner.dataset).run("hold")
    assert len(list((tmp_path / "plans").glob("*.pkl"))) == 2
