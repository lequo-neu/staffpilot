"""A small run history: what was run, on which data and settings, and what came out.

Each command appends one JSON line to runs/runs.jsonl, so results can be traced back
to the exact dataset file and configuration. `python -m staffpilot history` lists them.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

import pandas as pd

from staffpilot.config import REPO_ROOT, Settings


log = logging.getLogger(__name__)
RUNS_FILE = REPO_ROOT / "runs" / "runs.jsonl"
_FILE_HASHES: dict[tuple[str, float], str] = {}


def file_fingerprint(path: Path) -> str:
    """First 12 hex digits of the SHA256 of a file, cached by path and modification time."""
    key = (str(path), path.stat().st_mtime)
    if key not in _FILE_HASHES:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        _FILE_HASHES[key] = digest.hexdigest()[:12]
    return _FILE_HASHES[key]


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 git is looked up on PATH on purpose
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def record_run(
    kind: str,
    settings: Settings,
    metrics: dict[str, Any],
    seconds: float,
    dataset_path: Path | None = None,
    extra: dict[str, Any] | None = None,
    runs_file: Path | None = None,
) -> dict[str, Any]:
    """Append one run record and return it. Failing to write never stops the program."""
    config = json.dumps(settings.model_dump(), sort_keys=True, default=str)
    record: dict[str, Any] = {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S_")
        + hashlib.sha256(config.encode("utf-8")).hexdigest()[:6],
        "time_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "kind": kind,
        "config_hash": hashlib.sha256(config.encode("utf-8")).hexdigest()[:12],
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "seconds": round(seconds, 2),
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()},
    }
    if dataset_path is not None and dataset_path.is_file():
        record["dataset"] = dataset_path.name
        record["dataset_sha"] = file_fingerprint(dataset_path)
    if extra:
        record.update(extra)
    target = runs_file or RUNS_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError as error:
        log.warning("Could not write the run history: %s", error)
    return record


def history(limit: int = 20, runs_file: Path | None = None) -> pd.DataFrame:
    target = runs_file or RUNS_FILE
    if not target.exists():
        return pd.DataFrame()
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines()[-limit:]:
        if not line.strip():
            continue
        record = json.loads(line)
        flat = {k: v for k, v in record.items() if k != "metrics"}
        flat.update(record.get("metrics", {}))
        rows.append(flat)
    return pd.DataFrame(rows)
