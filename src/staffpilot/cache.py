"""Disk cache for slow, repeatable work: reading the workbook and solving plans.

Reading the 500,000 row workbook takes several seconds and every policy solves 22
optimization models, so the app, the notebook and the command line keep the results
in `.cache/` and reuse them on the next start. A key covers everything the result
depends on (the data, the settings and the planning code), so a change to any of
them starts fresh instead of reusing a stale answer.

Only files this module wrote are read back. STAFFPILOT_NO_CACHE=1 turns the cache
off; STAFFPILOT_CACHE_DIR moves it.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import logging
import os
from pathlib import Path
import pickle
from typing import TypeVar

from staffpilot.config import REPO_ROOT


log = logging.getLogger(__name__)
T = TypeVar("T")
# Files whose code decides a plan; editing any of them invalidates cached plans.
PLANNING_CODE = ("data.py", "forecast.py", "optimize.py", "planner.py", "simulate.py", "scenarios.py")


def enabled() -> bool:
    return os.environ.get("STAFFPILOT_NO_CACHE", "").strip() not in {"1", "true", "yes"}


def folder() -> Path:
    return Path(os.environ.get("STAFFPILOT_CACHE_DIR") or REPO_ROOT / ".cache")


def digest(*parts: object) -> str:
    blob = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:20]


def code_version() -> str:
    here = Path(__file__).parent
    return digest(*((here / name).read_bytes() for name in PLANNING_CODE))


def file_key(path: Path) -> str:
    stat = path.stat()
    return digest(path.resolve(), stat.st_size, stat.st_mtime_ns)


def cached(kind: str, key: str, compute: Callable[[], T]) -> T:
    """Return the stored result for (kind, key), or compute and store it."""
    if not enabled():
        return compute()
    path = folder() / kind / f"{key}.pkl"
    if path.exists():
        try:
            with path.open("rb") as handle:
                value = pickle.load(handle)  # noqa: S301 (written by this module)
            log.debug("Cache hit for %s %s", kind, key)
            return value
        except Exception as error:  # a broken or old file is recomputed, never fatal
            log.info("Ignoring unreadable cache file %s (%s)", path.name, type(error).__name__)
    value = compute()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(path)
    except Exception as error:  # a read only checkout still runs, just without the cache
        log.info("Could not write cache file %s (%s)", path.name, type(error).__name__)
    return value
