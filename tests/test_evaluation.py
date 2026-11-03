from __future__ import annotations

import json

from staffpilot.evaluation import evaluate_backend, load_cases, routing_table, run_evaluation


def test_offline_evaluation_writes_summary_and_routing(tmp_path, planner):
    testset = tmp_path / "cases.jsonl"
    cases = [
        {
            "id": "a",
            "question": "How many agents does Alpha need in March?",
            "intent": "plan_lookup",
            "countries": ["Alpha"],
        },
        {
            "id": "b",
            "question": "What if sign ups in Beta drop 30%?",
            "intent": "what_if",
            "countries": ["Beta"],
            "scenario": {"demand_multiplier": 0.7},
        },
        {
            "id": "c",
            "question": "How long can an advertiser wait in the pool?",
            "intent": "rules",
            "countries": [],
        },
    ]
    testset.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    results, summary = run_evaluation(planner, ["offline"], testset, tmp_path / "out")
    assert len(load_cases(testset)) == 3
    assert summary.loc[0, "intent_accuracy"] == 1.0
    assert summary.loc[0, "scenario_accuracy"] == 1.0
    assert (tmp_path / "out" / "routing.json").exists()
    assert routing_table(results)["router"] == "offline"


def test_follow_up_cases_are_asked_after_their_context(planner, tmp_path):
    case = {
        "id": "f1",
        "context": ["What if sign ups in Alpha drop 30% in Q3?"],
        "question": "And Beta?",
        "intent": "what_if",
        "countries": ["Beta"],
        "scenario": {"demand_multiplier": 0.7, "countries": ["Beta"]},
    }
    path = tmp_path / "followups.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    (loaded,) = load_cases(path)
    assert loaded.context == case["context"]
    row = evaluate_backend(planner, "offline", [loaded], None).iloc[0]
    assert row["intent_ok"] and row["countries_ok"] and row["scenario_score"] == 1.0
