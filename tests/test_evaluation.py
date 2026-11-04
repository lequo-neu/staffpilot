from __future__ import annotations

import json

import pandas as pd

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


def test_a_backend_without_a_usable_model_is_left_out(planner, tmp_path, monkeypatch):
    from staffpilot import evaluation

    def make(name, settings, cache_dir=None):
        if name != "offline":
            raise ValueError(f"No {name} model is available")
        return evaluation.make_backend(name, settings, cache_dir)

    case = {
        "id": "a",
        "question": "How many agents does Alpha need?",
        "intent": "plan_lookup",
        "countries": ["Alpha"],
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    real = evaluation.make_backend
    monkeypatch.setattr(
        evaluation, "make_backend", lambda n, s, c=None: real(n, s, c) if n == "offline" else make(n, s, c)
    )
    results, summary = run_evaluation(
        planner, ["offline", "google"], path, tmp_path / "out", None, ["google"]
    )
    assert set(results["backend"]) == {"offline"} and len(summary) == 1


def test_a_provider_without_a_strong_model_judges_with_its_fast_one(planner, tmp_path, monkeypatch):
    from staffpilot import evaluation
    from staffpilot.agent.backends import ModelUnavailableError, OfflineBackend

    built = []

    def make(name, settings, cache_dir=None):
        built.append(name)
        if name == "google":
            raise ModelUnavailableError("no strong google model")
        return OfflineBackend()

    case = {
        "id": "a",
        "question": "How many agents does Alpha need?",
        "intent": "plan_lookup",
        "countries": ["Alpha"],
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    monkeypatch.setattr(evaluation, "make_backend", make)
    run_evaluation(planner, ["offline"], path, tmp_path / "out", None, ["google"])
    assert built[:2] == ["google", "google_fast"]


def test_local_models_judge_each_other_but_never_themselves(planner, tmp_path, monkeypatch):
    from staffpilot import evaluation
    from staffpilot.agent.backends import Judgement, OfflineBackend

    graded = []

    class Model(OfflineBackend):
        def __init__(self, name):
            super().__init__()
            self.name = name
            self.model_spec = name

        def judge(self, question, answer, facts):
            graded.append(self.name)
            return Judgement(score=4, reason="fine")

    case = {
        "id": "a",
        "question": "How many agents does Alpha need?",
        "intent": "plan_lookup",
        "countries": ["Alpha"],
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    monkeypatch.setattr(evaluation, "make_backend", lambda name, settings, cache_dir=None: Model(name))
    local = ["local:gemma", "local:llama"]
    results, _ = run_evaluation(planner, local, path, tmp_path / "out", None, local)
    by_backend = results.set_index("backend")
    assert by_backend.loc["local:gemma", "judges"] == 1 and by_backend.loc["local:llama", "judges"] == 1
    assert sorted(graded) == ["local:gemma", "local:llama"]  # each graded the other once


def test_keep_adds_new_models_to_the_earlier_results(planner, tmp_path, monkeypatch):
    from staffpilot import evaluation
    from staffpilot.agent.backends import Judgement, OfflineBackend

    class Model(OfflineBackend):
        def __init__(self, name):
            super().__init__()
            self.name = name
            self.model_spec = name

        def judge(self, question, answer, facts):
            return Judgement(score=4, reason="fine")

    case = {
        "id": "a",
        "question": "How many agents does Alpha need?",
        "intent": "plan_lookup",
        "countries": ["Alpha"],
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    real = evaluation.make_backend
    monkeypatch.setattr(
        evaluation, "make_backend", lambda n, s, c=None: real(n, s, c) if n == "offline" else Model(n)
    )
    out = tmp_path / "out"
    local = ["local:gemma", "local:llama"]
    run_evaluation(planner, ["offline", *local], path, out, None, local)
    # An online run with --keep replaces offline (run again) and adds the new model, keeping the local ones.
    _, summary = run_evaluation(planner, ["offline", "anthropic"], path, out, None, ["anthropic"], keep=True)
    assert set(summary["backend"]) == {"offline", "anthropic", *local}
    judged = summary.set_index("backend")["judged_by"]
    assert judged["local:gemma"] == "local:llama" and judged["offline"] == "anthropic"
    assert judged["anthropic"] == ""  # no other provider judged it in this run
    # Without --keep, the run stands alone as before.
    _, alone = run_evaluation(planner, ["offline"], path, out)
    assert set(alone["backend"]) == {"offline"}


def test_a_model_that_sends_nothing_back_counts_as_an_error_not_an_answer(planner, tmp_path, monkeypatch):
    from staffpilot import evaluation
    from staffpilot.agent.backends import OfflineBackend

    class Broke(OfflineBackend):
        """A model whose account has no credit left: every call fails before any token is used."""

        name = "anthropic"
        model_spec = "anthropic:claude-sonnet-5-5"

        def route(self, *args, **kwargs):
            raise RuntimeError("credit balance is too low")

        def compose(self, *args, **kwargs):
            raise RuntimeError("credit balance is too low")

    case = {
        "id": "a",
        "question": "How many agents does Alpha need?",
        "intent": "plan_lookup",
        "countries": ["Alpha"],
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case), encoding="utf-8")
    real = evaluation.make_backend
    monkeypatch.setattr(
        evaluation, "make_backend", lambda n, s, c=None: real(n, s, c) if n == "offline" else Broke()
    )
    results, summary = run_evaluation(planner, ["offline", "anthropic"], path, tmp_path / "out")
    row = results.set_index("backend").loc["anthropic"]
    assert row["error"].startswith("no answer from the model") and pd.isna(row["intent_ok"])
    scored = summary.set_index("backend")
    assert scored.loc["anthropic", "cases"] == 0 and scored.loc["anthropic", "errors"] == 1
    assert scored.loc["offline", "errors"] == 0 and scored.loc["offline", "model"] == "offline"
