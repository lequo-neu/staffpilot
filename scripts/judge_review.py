"""Check the AI judge against people: the team grades a sample of answers by hand.

    python scripts/judge_review.py sheet [--force]  (never replaces an existing sheet without --force)
    python scripts/judge_review.py compare

`sheet` picks 30 answers from eval/results/cases.csv, ten per model, spread over the
scores the AI judges gave, and writes them to eval/judge_review.xlsx with the facts the
judges saw. The sheet is an Excel file because a CSV with multi line cells breaks when
Excel saves it with another separator. It hides which model wrote each answer and what
the judges gave; both are in eval/judge_review_key.csv, which graders should not open.
Each grader renames one pair of columns to their own name ("Hamad score", "Hamad reason")
and grades every answer on the judges' own 1 to 5 rubric (printed by `sheet`), without
talking to the other grader.

`compare` reads every "<name> score" column and reports how often the graders agree,
how close each AI judge is to them, and whether people rank the models the same way. Nothing here
calls a model: answers are replayed from the evaluation cache, and an answer whose replay
differs from what was graded is left out.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import random
import sys
from typing import Any


os.environ.setdefault("STAFFPILOT_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
SHEET, KEY = EVAL / "judge_review.xlsx", EVAL / "judge_review_key.csv"
SPLITS = {"main": "testset", "holdout": "holdout", "followups": "followups"}
PER_MODEL = 10
GRADERS = ("grader A", "grader B")


class _CacheOnly:
    """Stands in for a model inside CachedBackend, so a replay can never make a paid call."""

    def __init__(self, spec: str) -> None:
        self.name = self.model_spec = spec
        self.usage = {"input": 0, "output": 0}

    def __getattr__(self, attr: str) -> Any:
        raise RuntimeError(f"{attr} is not in the evaluation cache")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    # utf-8-sig lets Excel read the file without garbling any characters.
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_sheet() -> list[dict[str, str]]:
    import pandas as pd

    frame = pd.read_excel(SHEET, dtype=str).fillna("")
    return [{k: str(v).strip() for k, v in row.items()} for row in frame.to_dict("records")]


def _write_sheet(columns: list[str], rows: list[dict[str, Any]]) -> None:
    from openpyxl.styles import Alignment
    import pandas as pd

    with pd.ExcelWriter(SHEET, engine="openpyxl") as writer:
        pd.DataFrame(rows, columns=columns).to_excel(writer, index=False, sheet_name="grades")
        page = writer.sheets["grades"]
        widths = {"A": 6, "B": 30, "C": 40, "D": 45, "E": 70}
        for letter in "ABCDEFGHI":
            page.column_dimensions[letter].width = widths.get(letter, 16 if letter in "FH" else 40)
        for row in page.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        page.freeze_panes = "F2"


def _graders(row: dict[str, str]) -> list[str]:
    return [c.removesuffix(" score") for c in row if c.endswith(" score")]


def _judge_cache() -> dict[str, Any]:
    records = {}
    for path in (EVAL / "cache").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["key"]] = record["value"]
    return records


def _judge_key(spec: str, question: str, answer: str) -> str:
    # The same key CachedBackend uses for a judge call.
    blob = json.dumps([spec, "judge", [question, answer]], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _replay(planner: Any, spec: str, case: Any) -> Any | None:
    """The answer and facts the evaluation produced for this case, rebuilt from the cache."""
    from staffpilot.agent.assistant import StaffPilot
    from staffpilot.agent.backends import CachedBackend, OfflineBackend
    from staffpilot.agent.memory import Conversation

    backend = OfflineBackend() if spec == "offline" else CachedBackend(_CacheOnly(spec), EVAL / "cache")
    pilot = StaffPilot(planner, backend)
    try:
        if case.context:
            chat = Conversation()
            for earlier in case.context:
                pilot.ask(earlier, chat)
            return pilot.ask(case.question, chat)
        if case.intent == "memo" and case.countries:
            return pilot.memo(case.countries[0])
        return pilot.ask(case.question)
    except Exception:
        return None


def _pick(rows: list[dict[str, str]], rng: random.Random) -> list[dict[str, str]]:
    """Ten answers per model, taking turns over the judge scores so low scores are not missed."""
    picked = []
    for model in sorted({r["model"] for r in rows}):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            if row["model"] == model:
                groups.setdefault(str(round(float(row["judge_score"]))), []).append(row)
        for group in groups.values():
            rng.shuffle(group)
        chosen: list[dict[str, str]] = []
        while len(chosen) < PER_MODEL and any(groups.values()):
            for score in sorted(groups):
                if groups[score] and len(chosen) < PER_MODEL:
                    chosen.append(groups[score].pop())
        picked += chosen
    rng.shuffle(picked)
    return picked


def sheet() -> None:
    # A new sheet comes with a new key, so an existing pair is kept even before anyone grades.
    if (SHEET.exists() or KEY.exists()) and "--force" not in sys.argv:
        print(f"{SHEET.relative_to(ROOT)} already exists; pass --force to replace it and its key")
        return
    from staffpilot.evaluation import load_cases
    from staffpilot.planner import Planner

    planner = Planner()
    cases = {(split, c.id): c for split, name in SPLITS.items() for c in load_cases(EVAL / f"{name}.jsonl")}
    judged = [r for r in _read(EVAL / "results" / "cases.csv") if r.get("judge_score")]
    judges = sorted({r["model"] for r in judged} - {"offline"})
    cache = _judge_cache()
    ready = []
    for row in judged:
        case = cases[(row["split"], row["id"])]
        answer = _replay(planner, row["model"], case)
        if answer is None or answer.text != row["answer"]:
            continue
        given = {
            spec: cache[_judge_key(spec, case.question, row["answer"])]["score"]
            for spec in judges
            if spec != row["model"] and _judge_key(spec, case.question, row["answer"]) in cache
        }
        if given:
            ready.append({**row, "case": case, "facts": answer.facts, "given": given})
    picked = _pick(ready, random.Random(5374))
    grades = [f"{g} {part}" for g in GRADERS for part in ("score", "reason")]
    sheet_rows, key_rows = [], []
    for item, row in enumerate(picked, start=1):
        case = row["case"]
        sheet_rows.append(
            {
                "item": item,
                "earlier question": " / ".join(case.context),
                "question": case.question,
                "facts": "\n".join(f"{k} = {v}" for k, v in sorted(row["facts"].items())),
                "answer": row["answer"],
                **{column: "" for column in grades},
            }
        )
        key_rows.append(
            {
                "item": item,
                "split": row["split"],
                "id": row["id"],
                "model": row["model"],
                "ai judge score": row["judge_score"],
                **{f"judge {spec}": score for spec, score in row["given"].items()},
            }
        )
    _write_sheet(["item", "earlier question", "question", "facts", "answer", *grades], sheet_rows)
    key_columns = ["item", "split", "id", "model", "ai judge score", *[f"judge {s}" for s in judges]]
    _write(KEY, key_columns, key_rows)
    print(
        f"Wrote {SHEET.relative_to(ROOT)} with {len(sheet_rows)} answers to grade ({len(ready)} could be replayed)"
    )
    from staffpilot.agent.backends import JUDGE_PROMPT

    print(f"The rubric, as the AI judges get it:\n{JUDGE_PROMPT}")


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _agreement(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    import pandas as pd

    if not pairs:
        return {"answers": 0}
    left, right = pd.Series([a for a, _ in pairs]), pd.Series([b for _, b in pairs])
    gap = (left - right).abs()
    return {
        "answers": len(pairs),
        "same score": f"{(gap < 0.5).mean():.0%}",
        "within one point": f"{(gap <= 1).mean():.0%}",
        "mean gap": round(gap.mean(), 2),
        "bias (second minus first)": round((right - left).mean(), 2),
        # Spearman's rank correlation, written out because pandas needs scipy for it.
        "rank correlation": round(left.rank().corr(right.rank()), 2) if len(pairs) > 2 else None,
    }


def compare() -> None:
    import pandas as pd

    grades = {r["item"]: r for r in _read_sheet()}
    names = _graders(next(iter(grades.values())))
    key = _read(KEY)
    judges = [c for c in key[0] if c.startswith("judge ")]
    between: list[tuple[float, float]] = []
    people, per_model = [], []
    by_judge: dict[str, list[tuple[float, float]]] = {j: [] for j in ["ai judge score", *judges]}
    for row in key:
        scores = [_number(grades[row["item"]].get(f"{name} score")) for name in names]
        if len(scores) > 1 and scores[0] is not None and scores[1] is not None:
            between.append((scores[0], scores[1]))
        given = [s for s in scores if s is not None]
        if not given:
            continue
        person = sum(given) / len(given)
        people.append(person)
        for judge, pairs in by_judge.items():
            score = _number(row.get(judge))
            if score is not None:
                pairs.append((person, score))
        per_model.append(
            {"model": row["model"], "people": person, "ai judges": _number(row["ai judge score"])}
        )
    if not people:
        print(f"No grades yet in {SHEET.relative_to(ROOT)}")
        return
    report = [{"comparison": f"{names[0]} against {names[1]}", **_agreement(between)}] if between else []
    for judge, pairs in by_judge.items():
        name = "mean of the AI judges" if judge == "ai judge score" else judge.removeprefix("judge ")
        report.append({"comparison": f"people against {name}", **_agreement(pairs)})
    table = pd.DataFrame(report)
    models = pd.DataFrame(per_model).groupby("model").mean().round(2)
    out = EVAL / "results" / "judge_agreement.csv"
    table.to_csv(out, index=False)
    print(table.to_string(index=False))
    print("\nMean score per model, from people and from the AI judges:")
    print(models.sort_values("people", ascending=False).to_string())
    print(f"\nWrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in {"sheet", "compare"}:
        sys.exit(__doc__)
    sheet() if command == "sheet" else compare()
