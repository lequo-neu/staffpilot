"""Write the evaluation questions and their labels as one sheet for the team to review.

    python scripts/label_review_sheet.py [--force]

The sheet (eval/label_review.csv) opens in Excel or Google Sheets: one row per question,
with the labels in plain words and empty columns for the reviewer's verdict. Commit the
filled sheet as the record of the review; fix any wrong label in the eval/*.jsonl file.
A sheet that already holds verdicts is kept unless --force is given.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("testset", "holdout", "followups")
COLUMNS = [
    "split",
    "id",
    "earlier question",
    "question",
    "intent",
    "countries",
    "months",
    "scenario",
    "insight kind",
    "rule passage",
    "reviewer",
    "labels right (yes or no)",
    "corrected label",
    "comment",
]


def _plain(value: object) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k} = {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _reviewed(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return any(row.get("reviewer") for row in csv.DictReader(handle))


def main() -> None:
    out = ROOT / "eval" / "label_review.csv"
    if _reviewed(out) and "--force" not in sys.argv[1:]:
        print(f"{out.relative_to(ROOT)} already holds review verdicts; pass --force to start a new sheet")
        return
    rows = []
    for split in SPLITS:
        for line in (ROOT / "eval" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            rows.append(
                [
                    split,
                    case["id"],
                    _plain(case.get("context")),
                    case["question"],
                    case["intent"],
                    _plain(case.get("countries")),
                    _plain(case.get("months")),
                    _plain(case.get("scenario")),
                    _plain(case.get("insight_kind")),
                    _plain(case.get("source")),
                    "",
                    "",
                    "",
                    "",
                ]
            )
    # utf-8-sig lets Excel read the file without garbling any characters.
    with out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(f"Wrote {out.relative_to(ROOT)} with {len(rows)} questions to review")


if __name__ == "__main__":
    main()
