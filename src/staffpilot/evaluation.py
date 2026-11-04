"""Compare backends (the offline router and several LLMs) on labelled questions.

Metrics per backend and split:

* intent, country and scenario field accuracy of the structured request,
* grounded rate: the answer passes the number check without the template fallback
  (always true for the offline backend, whose templates only use placeholders),
* judge score: mean 1 to 5 score from every judge model of another provider,
* agent tool accuracy: for LLM backends, whether the free form `create_agent` chat
  called the tool the intent needs,
* tokens and cost per question, and latency.

A case may list earlier questions in `context`; they are asked first in the same
conversation, so the case tests a follow up such as "And Mexico?".

Retrieval hit rate (is the labelled rule passage in the top three BM25 results) does
not depend on the backend and is reported once.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any

import pandas as pd

from staffpilot.agent.assistant import StaffPilot
from staffpilot.agent.backends import describe_error, make_backend
from staffpilot.agent.memory import Conversation
from staffpilot.agent.rag import Retriever
from staffpilot.planner import Planner


EXPECTED_TOOL = {
    "plan_lookup": "get_plan",
    "compare": "compare_policies",
    "what_if": "run_scenario",
    "sensitivity": "sensitivity",
    "insight": "signup_insights",
    "rules": "search_rules",
    "memo": "get_plan",
    "out_of_scope": None,
}
MIN_CASES_FOR_ROUTING = 3
log = logging.getLogger(__name__)


@dataclass
class Case:
    id: str
    question: str
    intent: str
    countries: list[str]
    months: list[int]
    scenario: dict[str, Any]
    insight_kind: str | None
    source: str | list[str] | None  # one heading, or several that each answer the question
    context: list[str] = field(default_factory=list)  # earlier questions in the same chat


def load_cases(path: Path) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            cases.append(
                Case(
                    raw["id"],
                    raw["question"],
                    raw["intent"],
                    raw.get("countries", []),
                    raw.get("months", []),
                    raw.get("scenario", {}),
                    raw.get("insight_kind"),
                    raw.get("source"),
                    raw.get("context", []),
                )
            )
    return cases


def _scenario_score(expected: dict[str, Any], actual: Any) -> float | None:
    if not expected:
        return None
    if actual is None:
        return 0.0
    got = actual.model_dump()
    hits = 0
    for key, want in expected.items():
        have = got.get(key)
        if isinstance(want, float) and isinstance(have, int | float):
            hits += abs(want - have) <= 0.011
        elif isinstance(want, list):
            hits += sorted(want) == sorted(have or [])
        else:
            hits += want == have
    return hits / len(expected)


def retrieval_hits(cases: Iterable[Case], retriever: Retriever | None = None) -> pd.DataFrame:
    """For rule questions labelled with a source heading: is that passage in the top three?"""
    retriever = retriever or Retriever()
    rows = []
    for case in cases:
        if case.source:
            accepted = case.source if isinstance(case.source, list) else [case.source]
            found = [p.heading for p in retriever.search(case.question, k=3)]
            hit = any(a in found for a in accepted)
            rows.append(
                {"id": case.id, "source": " or ".join(accepted), "top3": " | ".join(found), "hit": hit}
            )
    return pd.DataFrame(rows)


def _cost(backend: Any, prices: dict[str, list[float]], tokens_in: int, tokens_out: int) -> float | None:
    price = prices.get(getattr(backend, "model_spec", ""))
    return (tokens_in * price[0] + tokens_out * price[1]) / 1e6 if price else None


def _agent_row(agent: Any, name: str, case: Case) -> dict[str, Any]:
    from staffpilot.agent.chat_agent import chat

    started = time.perf_counter()
    expected = EXPECTED_TOOL[case.intent]
    try:
        for earlier in case.context:
            chat(agent, earlier, thread_id=f"{name}_{case.id}")
        reply = chat(agent, case.question, thread_id=f"{name}_{case.id}")
    except Exception as exc:
        return {
            "agent_tools": f"error {type(exc).__name__}",
            "agent_tool_ok": False,
            "agent_seconds": time.perf_counter() - started,
        }
    called_ok = (expected in reply.tools_called) if expected else not reply.tools_called
    return {
        "agent_tools": ",".join(reply.tools_called),
        "agent_tool_ok": called_ok,
        "agent_unsupported": len(reply.unsupported),
        "agent_seconds": time.perf_counter() - started,
    }


def evaluate_backend(
    planner: Planner,
    name: str,
    cases: Iterable[Case],
    cache_dir: Path | None,
    judges: list[Any] | None = None,
    run_agent: bool = False,
) -> pd.DataFrame:
    backend = make_backend(name, planner.settings, cache_dir)
    pilot = StaffPilot(planner, backend)
    provider = name.removesuffix("_fast")
    # A model is never graded by a model of its own provider.
    graders = [j for j in judges or [] if j.name.removesuffix("_fast") != provider]
    agent = None
    if run_agent and name != "offline":
        from staffpilot.agent.chat_agent import build_chat_agent

        agent = build_chat_agent(pilot.tools, backend.model_spec, planner.settings)
    prices = planner.settings.llm.prices
    rows, to_judge = [], []
    for case in cases:
        chat = Conversation() if case.context else None
        try:
            for earlier in case.context:
                pilot.ask(earlier, chat)
        except Exception as exc:
            log.warning("context of %s failed: %s", case.id, describe_error(exc))
        before = dict(backend.usage)
        try:
            if chat is not None:
                answer = pilot.ask(case.question, chat)
                route = answer.route
            elif case.intent == "memo" and case.countries:
                answer = pilot.memo(case.countries[0])
                route = pilot.route(case.question)[0]
            else:
                answer = pilot.ask(case.question)
                route = answer.route
        except Exception as exc:  # record the failure and keep evaluating
            rows.append(
                {
                    "backend": name,
                    "id": case.id,
                    "intent": case.intent,
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                }
            )
            continue
        tokens_in = backend.usage["input"] - before["input"]
        tokens_out = backend.usage["output"] - before["output"]
        # A model that sent nothing back (no credit, no quota, no network) is a failed case, not an
        # answer: the offline router and template stood in, and would be scored as if they were the model.
        failed = [g for g in answer.guardrails if " writer failed (" in g]
        if name != "offline" and failed and tokens_in + tokens_out == 0:
            rows.append(
                {
                    "backend": name,
                    "model": getattr(backend, "model_spec", name),
                    "id": case.id,
                    "intent": case.intent,
                    "error": f"no answer from the model: {failed[0]}"[:200],
                }
            )
            continue
        row = {
            "backend": name,
            "model": getattr(backend, "model_spec", name),
            "id": case.id,
            "intent": case.intent,
            "predicted_intent": route.intent.value,
            "intent_ok": route.intent.value == case.intent,
            "countries_ok": sorted(route.countries) == sorted(case.countries),
            "scenario_score": _scenario_score(case.scenario, route.scenario),
            "insight_ok": (route.insight_kind == case.insight_kind) if case.insight_kind else None,
            "grounded": answer.verified and not answer.fallback_used,
            "fallback": answer.fallback_used,
            "tokens": tokens_in + tokens_out,
            "cost_usd": _cost(backend, prices, tokens_in, tokens_out),
            "seconds": answer.seconds,
            "answer": answer.text,
            "error": "",
        }
        if agent is not None:
            row.update(_agent_row(agent, name, case))
        rows.append(row)
        to_judge.append((row, case, answer.text, {k: str(v) for k, v in answer.facts.items()}))
    # Each judge grades every answer in turn, after all answers are in. With local models this
    # keeps one model loaded at a time instead of swapping answerer and judge on every question.
    scores: dict[str, list[int]] = {case.id: [] for _, case, _, _ in to_judge}
    graded_by: set[str] = set()
    for grader in graders:
        log.info("Judge %s is grading %d answers from %s", grader.name, len(to_judge), name)
        for _, case, text, facts in to_judge:
            try:
                scores[case.id].append(grader.judge(case.question, text, facts).score)
                graded_by.add(getattr(grader, "model_spec", grader.name))
            except Exception as exc:  # a judge failure only leaves that score out
                log.warning("judge %s failed on %s: %s", grader.name, case.id, describe_error(exc))
    for row, case, _, _ in to_judge:
        given = scores[case.id]
        row["judge_score"] = sum(given) / len(given) if given else None
        row["judges"] = len(given)
        row["judged_by"] = ", ".join(sorted(graded_by))
    return pd.DataFrame(rows)


def _mean_or_none(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame or frame[column].dropna().empty:
        return None
    return float(frame[column].dropna().astype(float).mean())


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    def agg(frame: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "cases": len(frame),
                "errors": 0,
                "intent_accuracy": frame["intent_ok"].mean(),
                "country_accuracy": frame["countries_ok"].mean(),
                "scenario_accuracy": _mean_or_none(frame, "scenario_score"),
                "grounded_rate": frame["grounded"].mean(),
                "judge_score": _mean_or_none(frame, "judge_score"),
                "agent_tool_accuracy": _mean_or_none(frame, "agent_tool_ok"),
                "tokens_per_question": frame["tokens"].mean(),
                "cost_per_question_usd": _mean_or_none(frame, "cost_usd"),
                "mean_seconds": frame["seconds"].mean(),
                "model": next(iter(frame["model"].dropna()), "") if "model" in frame else "",
                # Judge scores compare fairly only between rows graded by the same judges.
                "judged_by": "; ".join(
                    sorted({j for j in frame.get("judged_by", pd.Series(dtype=str)).fillna("") if j})
                ),
            }
        )

    ok = results.dropna(subset=["intent_ok"]) if "intent_ok" in results else results
    keys = ["split", "backend"] if "split" in ok else ["backend"]
    summary = ok.groupby(keys).apply(agg, include_groups=False).reset_index()
    # Failed cases have no scores, so they are counted from all rows: `cases` are the scored ones.
    failed = results.get("error", pd.Series("", index=results.index)).fillna("").astype(str) != ""
    errors = failed.groupby([results[k] for k in keys]).sum().rename("errors").reset_index()
    # Outer, so a model that failed every case still shows, with its errors and no scores.
    merged = (
        summary.drop(columns="errors").merge(errors, on=keys, how="outer").fillna({"errors": 0, "cases": 0})
    )
    return merged[list(summary.columns)]


def routing_table(results: pd.DataFrame) -> dict[str, str]:
    """Best backend per intent: highest intent accuracy, then grounded rate, then speed.

    The holdout split is used when present, because the offline keywords were written
    while looking at the main test set and would look better than they are. An intent
    with fewer than three holdout questions keeps the overall best router.
    """
    ok = results.dropna(subset=["intent_ok"])
    if "split" in ok and (ok["split"] == "holdout").any():
        ok = ok[ok["split"] == "holdout"]
    table: dict[str, str] = {}
    overall = ok.groupby("backend").agg(acc=("intent_ok", "mean"), sec=("seconds", "mean"))
    table["router"] = overall.sort_values(["acc", "sec"], ascending=[False, True]).index[0]
    for intent, frame in ok.groupby("intent"):
        if frame["id"].nunique() < MIN_CASES_FOR_ROUTING:
            table[intent] = table["router"]
            continue
        scores = frame.groupby("backend").agg(
            acc=("intent_ok", "mean"), grounded=("grounded", "mean"), sec=("seconds", "mean")
        )
        table[intent] = scores.sort_values(["acc", "grounded", "sec"], ascending=[False, False, True]).index[
            0
        ]
    return table


def _build(name: str, planner: Planner, cache_dir: Path | None) -> Any | None:
    try:
        return make_backend(name, planner.settings, cache_dir)
    except ValueError as error:
        log.warning("Leaving %s out of the evaluation: %s", name, error)
        return None


def run_evaluation(
    planner: Planner,
    backends: list[str],
    testsets: Path | dict[str, Path],
    out_dir: Path,
    cache_dir: Path | None = None,
    judge_backends: list[str] | None = None,
    run_agent: bool = False,
    keep: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate each backend on each test set; write cases.csv, summary.csv, retrieval.csv and routing.json.

    With `keep`, the results already in `out_dir` stay for every backend not run this time,
    so online and local models can be run separately and still be compared on one page.
    """
    splits = testsets if isinstance(testsets, dict) else {"main": testsets}
    # A provider may have no usable model for a tier (a retired model, or no quota on a
    # free key); it is left out with a note instead of stopping the whole run.
    # A provider without a strong model judges with its fast one (Gemini's free tier, for example).
    judges = [
        j
        for j in (
            _build(name, planner, cache_dir) or _build(f"{name}_fast", planner, cache_dir)
            for name in judge_backends or []
        )
        if j
    ]
    backends = [name for name in backends if name == "offline" or _build(name, planner, cache_dir)]
    frames, retrieval = [], []
    for split, path in splits.items():
        cases = load_cases(path)
        hits = retrieval_hits(cases)
        if not hits.empty:
            retrieval.append(hits.assign(split=split))
        for name in backends:
            frame = evaluate_backend(planner, name, cases, cache_dir, judges, run_agent)
            frame.insert(0, "split", split)
            frames.append(frame)
    results = pd.concat(frames, ignore_index=True)
    earlier = out_dir / "cases.csv"
    if keep and earlier.exists():
        kept = pd.read_csv(earlier)
        kept = kept[~kept["backend"].isin(set(results["backend"]))]
        log.info("Keeping %d earlier results for %s", len(kept), sorted(set(kept["backend"])))
        results = pd.concat([kept, results], ignore_index=True)
    summary = summarize(results)
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "cases.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    if retrieval:
        pd.concat(retrieval, ignore_index=True).to_csv(out_dir / "retrieval.csv", index=False)
    (out_dir / "routing.json").write_text(json.dumps(routing_table(results), indent=2), encoding="utf-8")
    return results, summary
