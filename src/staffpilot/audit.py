"""Decision audit: what was proposed, what changed it, and what was applied.

Every decision a manager takes in the app adds rows to `outputs/decision_audit.csv`.
Each row separates three things so no step is a black box:

* `proposed`: the first value and who produced it (the optimizer, the forecast, or
  a language model reading a sentence),
* `adjusted`: a later change and who made it (the simulator check, a monthly update,
  the manager, or a GenAI guardrail such as the number check),
* `applied`: the value that was finally used.

`user` names who was signed in when the decision was taken (empty when sign in is off).

A language model never computes a staffing number. Where one is involved, its rows
say so (`proposed_by` names the model) and the numbers it led to are marked as
computed by the planner.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd


if TYPE_CHECKING:
    from staffpilot.agent.assistant import Answer
    from staffpilot.monthly import MonthlyUpdate
    from staffpilot.planner import PlanBundle
    from staffpilot.scenarios import ScenarioParams

log = logging.getLogger(__name__)

FILE_NAME = "decision_audit.csv"
COLUMNS = [
    "time",
    "user",
    "decision",
    "country",
    "month",
    "item",
    "proposed",
    "proposed_by",
    "adjusted",
    "adjusted_by",
    "applied",
    "note",
]
PLANNER = "planner (optimizer and simulator)"


def record(rows: Iterable[dict[str, Any]], folder: Path, user: str = "") -> Path:
    """Append rows to the audit file in `folder`, writing the header the first time."""
    stamp = datetime.now().isoformat(timespec="seconds")
    frame = pd.DataFrame(
        [{**{c: "" for c in COLUMNS}, "time": stamp, "user": user, **row} for row in rows], columns=COLUMNS
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE_NAME
    if not frame.empty:
        _upgrade(path)
        frame.to_csv(path, mode="a", header=not path.exists(), index=False)
        log.info("Decision audit: %d rows for %s", len(frame), frame["decision"].iloc[0])
    return path


def _upgrade(path: Path) -> None:
    """Rewrite a file written before a column was added, so new rows line up with the header."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as file:
        header = file.readline().strip().split(",")
    if header != COLUMNS:
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        old.reindex(columns=COLUMNS, fill_value="").to_csv(path, index=False)


def read(folder: Path, limit: int | None = None) -> pd.DataFrame:
    """The newest decisions first; the rows of one decision keep their order."""
    path = folder / FILE_NAME
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False).reindex(columns=COLUMNS, fill_value="")
    frame = frame.assign(_row=range(len(frame))).sort_values(["time", "_row"], ascending=[False, True])
    frame = frame.drop(columns="_row").reset_index(drop=True)
    return frame.head(limit) if limit else frame


def _month(year: int, index: int) -> str:
    return f"{year + index // 12}-{index % 12 + 1:02d}"


def plan_rows(bundle: PlanBundle, countries: list[str], goal: str, recommended: str) -> list[dict[str, Any]]:
    """Rows for an approved plan: the service goal, then each month's decisions and any simulator repair."""
    rows: list[dict[str, Any]] = [
        {
            "decision": "plan approved",
            "country": ", ".join(countries) if len(countries) <= 3 else f"{len(countries)} countries",
            "item": "service goal",
            "proposed": recommended,
            "proposed_by": "StaffPilot recommendation",
            "adjusted": goal if goal != recommended else "",
            "adjusted_by": "manager" if goal != recommended else "",
            "applied": goal,
        }
    ]
    for country in countries:
        plan = bundle.outcomes[country].plan
        proposed = plan.proposed_active if plan.proposed_active is not None else plan.active
        for t in range(12):
            base = {"decision": "plan approved", "country": country, "month": _month(bundle.year, t)}
            if proposed[t] != plan.active[t]:
                rows.append(
                    {
                        **base,
                        "item": "agents at work",
                        "proposed": int(proposed[t]),
                        "proposed_by": "optimizer",
                        "adjusted": int(plan.active[t]),
                        "adjusted_by": "simulator check",
                        "applied": int(plan.active[t]),
                        "note": "raised so that no agent holds more than the advertiser limit on any day "
                        "and the service goal holds",
                    }
                )
            for item, values in (("hires decided", plan.hires), ("notices given", plan.notices)):
                if values[t]:
                    rows.append(
                        {**base, "item": item, "proposed": int(values[t]), "proposed_by": PLANNER}
                        | {"applied": int(values[t])}
                    )
    return rows


def update_rows(update: MonthlyUpdate) -> list[dict[str, Any]]:
    """Rows for an approved monthly update: the actual inputs, then every decision that changed."""
    base = {"decision": "monthly update approved", "country": update.country}
    rows: list[dict[str, Any]] = [
        {
            **base,
            "month": _month(update.year, t),
            "item": "eligible sign ups",
            "proposed": round(float(update.forecast[t])),
            "proposed_by": "forecast",
            "adjusted": round(float(update.actual[t])),
            "adjusted_by": "manager (actual count)",
            "applied": round(float(update.actual[t])),
        }
        for t in range(update.done)
    ]
    if update.headcount_change:
        rows.append(
            {
                **base,
                "month": _month(update.year, update.done),
                "item": "agents on staff",
                "proposed": int(update.original.active[update.done]),
                "proposed_by": "approved plan",
                "adjusted": int(update.original.active[update.done]) + update.headcount_change,
                "adjusted_by": "manager (actual headcount)",
                "applied": int(update.original.active[update.done]) + update.headcount_change,
                "note": f"{update.headcount_change:+,} against the plan",
            }
        )
    old, new = update.original, update.updated.plan
    for t in range(update.done, 12):
        for item, before, after in (
            ("agents at work", old.active, new.active),
            ("hires decided", old.hires, new.hires),
            ("notices given", old.notices, new.notices),
        ):
            if before[t] != after[t]:
                rows.append(
                    {
                        **base,
                        "month": _month(update.year, t),
                        "item": item,
                        "proposed": int(before[t]),
                        "proposed_by": "approved plan",
                        "adjusted": int(after[t]),
                        "adjusted_by": "monthly update (planner)",
                        "applied": int(after[t]),
                        "note": f"sign ups at {update.ratio:.0%} of forecast",
                    }
                )
    return rows


def _shown(value: Any) -> str:
    if isinstance(value, list) and value and isinstance(value[0], dict) and "multiplier" in value[0]:
        from staffpilot.scenarios import DemandChange

        return "; ".join(DemandChange(**change).plain() for change in value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "all"
    return "" if value is None else str(value)


def scenario_rows(
    proposed: ScenarioParams | None,
    applied: ScenarioParams,
    reader: str,
    guardrails: list[str],
    totals: dict[str, float],
) -> list[dict[str, Any]]:
    """Rows for a scenario run: each parameter as read by the model and as run, then the computed result.

    `proposed` is what the reader (a language model or the offline parser) made of the
    manager's sentence; `applied` is what was run, after any edit by the manager.
    """
    base = {"decision": "scenario run", "country": _shown(applied.countries)}
    default = type(applied)()
    read = proposed.model_dump() if proposed is not None else None
    rows: list[dict[str, Any]] = []
    for name, value in applied.model_dump().items():
        before = read[name] if read is not None else None
        if value == getattr(default, name) and (before is None or before == value):
            continue
        edited = read is not None and before != value
        rows.append(
            {
                **base,
                "item": name,
                "proposed": _shown(before) if read is not None else "",
                "proposed_by": reader if read is not None else "",
                "adjusted": _shown(value) if edited or read is None else "",
                "adjusted_by": "manager" if edited or read is None else "",
                "applied": _shown(value),
            }
        )
    if rows and guardrails:
        rows[0]["note"] = "; ".join(guardrails)
    for item, key in (
        ("net value change", "net_value_change"),
        ("service rate under the scenario", "service_rate_scenario"),
        ("average agents under the scenario", "avg_active_scenario"),
    ):
        value = totals[key]
        shown = f"{value:.1%}" if "rate" in key else f"{value:,.0f}"
        rows.append(
            {
                **base,
                "item": item,
                "proposed_by": PLANNER,
                "applied": shown,
                "note": "computed by the planner; no language model wrote this number",
            }
        )
    return rows


def answer_rows(answer: Answer) -> list[dict[str, Any]]:
    """One row per assistant answer: who wrote it, which guardrails acted, and what was shown."""
    model_wrote = not answer.fallback_used and not answer.backend.startswith("offline")
    shown = "model answer" if model_wrote else "template answer"
    return [
        {
            "decision": "assistant answer",
            "country": ", ".join(answer.route.countries),
            "item": answer.question[:120],
            "proposed": f"{answer.route.intent.value}, tools {', '.join(answer.tools) or 'none'}",
            "proposed_by": answer.backend,
            "adjusted": "template answer" if answer.fallback_used else "",
            "adjusted_by": "number check" if answer.fallback_used else "",
            "applied": f"{shown}, number check {'passed' if answer.verified else 'failed'}",
            "note": "; ".join(answer.guardrails) or "no guardrail had to act",
        }
    ]
