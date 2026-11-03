"""Logging setup shared by the command line, the app and the notebook.

Modules log through `logging.getLogger(__name__)`. The level comes from, in order,
the `level` argument, the STAFFPILOT_LOG_LEVEL environment variable, and WARNING.

Messages go to the terminal and to a new file for every run, named after the start
time and the command, for example `logs/20261102_231805_plan.log`. The first lines
of each file say what was run, on which data and with which settings, so a run can
be traced later. Only the newest files are kept. STAFFPILOT_LOG_DIR moves the folder.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import platform
import sys

from staffpilot.config import REPO_ROOT


LEVEL_ENV_VAR = "STAFFPILOT_LOG_LEVEL"
DIR_ENV_VAR = "STAFFPILOT_LOG_DIR"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
KEEP_FILES = 50
_HANDLER_TAG = "_staffpilot_handler"


def configure_logging(level: str | None = None, log_dir: Path | None = None, run_name: str = "run") -> str:
    """Attach StaffPilot handlers to the package logger and return the level used."""
    chosen = (level or os.environ.get(LEVEL_ENV_VAR) or "WARNING").upper()
    if chosen not in LEVELS:
        chosen = "WARNING"
    logger = logging.getLogger("staffpilot")
    logger.setLevel(chosen)
    logger.propagate = False
    for handler in [h for h in logger.handlers if getattr(h, _HANDLER_TAG, False)]:
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
    setattr(console, _HANDLER_TAG, True)
    logger.addHandler(console)

    folder = log_dir or Path(os.environ.get(DIR_ENV_VAR) or REPO_ROOT / "logs")
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in run_name)[:30] or "run"
    path = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{safe_name}.log"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        # A read only checkout still runs; it just keeps logs in the terminal.
        return chosen
    # The file always keeps INFO, so a run can be traced even when the terminal shows warnings only.
    file_handler.setLevel(logging.DEBUG if chosen == "DEBUG" else logging.INFO)
    file_handler.setFormatter(logging.Formatter(FORMAT))
    setattr(file_handler, _HANDLER_TAG, True)
    logger.addHandler(file_handler)
    logger.setLevel(min(logging.getLevelName(chosen), logging.INFO))
    console.setLevel(chosen)
    _write_header(file_handler, run_name, chosen)
    _prune(folder)
    return chosen


def _write_header(handler: logging.Handler, run_name: str, level: str) -> None:
    from staffpilot import TEAM, __version__
    from staffpilot.config import load_settings

    try:
        settings = load_settings()
        data = Path(settings.data.path).name
    except Exception:  # the header must never stop a run
        data = "unknown"
    lines = [
        f"Run {run_name!r} started; StaffPilot {__version__} by {TEAM}, Python {platform.python_version()} on {platform.system()}",
        f"Command: {_command()}",
        f"Data file: {data}; terminal log level {level}",
    ]
    for line in lines:
        handler.handle(
            logging.makeLogRecord(
                {"name": "staffpilot.logs", "levelno": 20, "levelname": "INFO", "msg": line}
            )
        )


def _command() -> str:
    program = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "python"
    if program == "__main__.py":
        program = "python -m staffpilot"
    return " ".join([program, *sys.argv[1:]])


def _prune(folder: Path) -> None:
    files = sorted(folder.glob("*_*.log"))
    for old in files[:-KEEP_FILES]:
        try:
            old.unlink()
        except OSError:
            continue
