"""Command line entry point.

Examples (run from the repository root):

    python -m staffpilot plan
    python -m staffpilot eda
    python -m staffpilot ask "What if sign ups in Brazil drop 30% in Q3?"
    python -m staffpilot chat
    python -m staffpilot memo Germany
    python -m staffpilot models
    python -m staffpilot eval anthropic openai google
    python -m staffpilot app
"""

from __future__ import annotations

import argparse
import sys

from staffpilot.config import REPO_ROOT


OUTPUTS = REPO_ROOT / "outputs"
EVAL_DIR = REPO_ROOT / "eval"


def _ascii(text: str) -> str:
    # Some Windows consoles cannot print characters outside their code page.
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _shown(path) -> str:
    """A path as the user typed it: relative to the repository when it is inside it."""
    return str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)


def _pilot(backend: str):
    from staffpilot.agent import StaffPilot
    from staffpilot.planner import Planner

    return StaffPilot.for_backend(Planner(), backend, EVAL_DIR / "cache")


def cmd_plan(_: argparse.Namespace) -> None:
    from staffpilot.planner import Planner

    planner = Planner()
    OUTPUTS.mkdir(exist_ok=True)
    from staffpilot.planner import RECOMMENDED_POLICY

    bundle = planner.run(RECOMMENDED_POLICY)
    bundle.plan_table().to_csv(OUTPUTS / "plan.csv", index=False)
    bundle.kpi_table().to_csv(OUTPUTS / "kpis.csv", index=False)
    comparison = planner.compare_policies()
    comparison.to_csv(OUTPUTS / "policy_comparison.csv", index=False)
    totals = bundle.totals()
    print(
        f"Planning year {planner.year}, forecast method {planner.forecast.method}, plan {RECOMMENDED_POLICY}"
    )
    print(
        f"Net value ${totals['net_value'] / 1e6:,.1f}M, service {totals['service_rate']:.1%}, "
        f"average active agents {totals['avg_active']:,.0f} (January {totals['start_agents']:,.0f})"
    )
    view = comparison[["policy", "net_value", "service_rate", "avg_active"]].copy()
    view["net_value"] = view["net_value"].map(lambda v: f"${v / 1e6:,.1f}M")
    view["service_rate"] = view["service_rate"].map(lambda v: f"{v:.1%}")
    view["avg_active"] = view["avg_active"].map(lambda v: f"{v:,.0f}")
    print(view.to_string(index=False))
    print(f"Wrote {_shown(OUTPUTS / 'plan.csv')}, kpis.csv and policy_comparison.csv")
    from staffpilot.alerts import plan_alerts
    from staffpilot.tracking import record_run

    alerts = plan_alerts(planner)
    if alerts:
        print("\nAlerts:")
        for alert in alerts:
            print(f"  [{alert.level}] {alert.message}")
    record_run(
        "plan",
        planner.settings,
        {k: totals[k] for k in ("net_value", "service_rate", "avg_active", "total_cost")},
        bundle.seconds,
        planner.settings.data_path(),
        {"planning_year": planner.year, "alerts": sum(a.level != "info" for a in alerts)},
    )


def cmd_eda(_: argparse.Namespace) -> None:
    from staffpilot.config import load_settings
    from staffpilot.data import load_dataset
    from staffpilot.eda import profile, write_report

    settings = load_settings()
    dataset = load_dataset(settings)
    report = profile(dataset, settings.rules.capacity_per_agent)
    path = write_report(report, dataset, OUTPUTS / "eda")
    for finding in report.findings:
        print(f"* {finding}")
    print(f"Wrote {_shown(path)} and {len(list(path.parent.glob('*.png')))} charts")


def _save_chart(answer, name: str) -> str:
    from staffpilot.charts import save_answer_chart

    path = save_answer_chart(answer.chart, name, OUTPUTS / "answers")
    if path is None:
        return ""
    return f" Chart saved to {_shown(path)}."


def _footer(answer) -> str:
    tools = ", ".join(answer.tools) if answer.tools else "no planner tool"
    check = "every number checked against the planner" if answer.verified else "number check failed"
    return f"({answer.backend} answer from {tools}; {check}; {answer.seconds:.1f}s.)"


def cmd_ask(args: argparse.Namespace) -> None:
    question = " ".join(args.question)
    answer = _pilot(args.backend).ask(question)
    print(_ascii(answer.text))
    print(f"\n{_footer(answer)}{_save_chart(answer, question)}")


def cmd_chat(args: argparse.Namespace) -> None:
    from staffpilot.agent.memory import Conversation, describe

    pilot = _pilot(args.backend)
    memory = Conversation()
    print("Ask a question. Follow ups such as 'And Mexico?' use the earlier questions.")
    print(
        "Type 'new' to start over, 'save' to keep the conversation, or press Enter on an empty line to quit."
    )
    while True:
        try:
            question = input("\nYou: ").strip()
        except EOFError:
            break
        if question.lower() in {"", "exit", "quit"}:
            break
        if question.lower() == "new":
            memory.reset()
            print("Started a new conversation.")
            continue
        if question.lower() == "save":
            path = OUTPUTS / "conversations" / "chat.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(memory.to_markdown(), encoding="utf-8")
            print(f"Saved to {_shown(path)}.")
            continue
        answer = pilot.ask(question, memory)
        carried = f" Kept the {describe(answer.carried)} from your last question." if answer.carried else ""
        print(f"\nStaffPilot: {_ascii(answer.text)}")
        print(f"\n{_footer(answer)}{carried}{_save_chart(answer, question)}")


def cmd_models(args: argparse.Namespace) -> None:
    from staffpilot.agent.backends import LangChainBackend, available_providers, describe_error
    from staffpilot.agent.catalog import ModelChoice, cost_key, pick_model, provider_models
    from staffpilot.config import load_settings

    providers = available_providers()
    if not providers:
        print(
            "No API keys found, so only the offline backend is available. See README, Using language models."
        )
        return
    settings = load_settings()
    for provider in providers:
        listed = sorted(
            (ModelChoice(provider, m) for m in provider_models(provider, refresh=True)),
            key=lambda c: cost_key(c, settings.llm.prices),
        )
        if not listed:
            print(f"{provider}: the model list could not be read; see the log for the reason.")
            continue
        fast, strong = pick_model(settings, provider, "fast"), pick_model(settings, provider, "strong")
        print(f"{provider}: {len(listed)} chat models, cheapest first")
        for choice in listed:
            tags = [t for t, spec in (("fast tier", fast), ("strong tier", strong)) if spec == choice.spec]
            print(f"  {choice.spec}" + (f"   <- {', '.join(tags)}" if tags else ""))
        if args.ping:
            for tier, spec in (("fast", fast), ("strong", strong)):
                try:
                    reply = LangChainBackend(f"{provider}_{tier}", spec, settings).ping()
                    print(f"  ping {tier:6} {spec}: ok ({reply[:20]!r})")
                except Exception as error:  # report every model, even when one fails
                    print(f"  ping {tier:6} {spec}: FAILED {describe_error(error, 200)}")


def cmd_memo(args: argparse.Namespace) -> None:
    country = " ".join(args.country)
    answer = _pilot(args.backend).memo(country)
    print(_ascii(answer.text))
    print(_save_chart(answer, f"memo {country}").strip())


def cmd_eval(args: argparse.Namespace) -> None:
    from staffpilot.agent.backends import available_providers, backend_names
    from staffpilot.evaluation import run_evaluation
    from staffpilot.planner import Planner

    providers = available_providers()
    requested = args.providers or providers
    missing = [p for p in requested if p != "offline" and p not in providers]
    if missing:
        print(f"Skipping {missing}: no API key in the environment")
    usable = [p for p in requested if p in providers]
    names = ["offline", *backend_names(usable, args.tier)]
    # Strong models of every available provider grade the answers; a model never grades its own provider.
    judges = usable
    testsets = {
        "main": EVAL_DIR / "testset.jsonl",
        "holdout": EVAL_DIR / "holdout.jsonl",
        "followups": EVAL_DIR / "followups.jsonl",
    }
    _, summary = run_evaluation(
        Planner(),
        names,
        testsets,
        EVAL_DIR / "results",
        EVAL_DIR / "cache",
        judges,
        run_agent=not args.skip_agent,
    )
    print(summary.round(3).to_string(index=False))


def cmd_history(args: argparse.Namespace) -> None:
    from staffpilot.tracking import history

    frame = history(args.limit)
    if frame.empty:
        print("No runs recorded yet. Run: python -m staffpilot plan")
        return
    columns = [
        c
        for c in (
            "time_utc",
            "kind",
            "dataset",
            "planning_year",
            "net_value",
            "service_rate",
            "avg_active",
            "alerts",
            "git_commit",
            "config_hash",
        )
        if c in frame
    ]
    frame = frame[columns].copy()
    if "net_value" in frame:
        frame["net_value"] = frame["net_value"].map(lambda v: f"${v / 1e6:,.1f}M")
    if "service_rate" in frame:
        frame["service_rate"] = frame["service_rate"].map(lambda v: f"{v:.1%}")
    if "avg_active" in frame:
        frame["avg_active"] = frame["avg_active"].map(lambda v: f"{v:,.0f}")
    # Runs made before the folder was a git repository have no commit.
    print(frame.fillna("none").to_string(index=False))


def cmd_app(args: argparse.Namespace) -> None:
    from staffpilot.app import launch

    print(
        f"Starting StaffPilot at http://127.0.0.1:{args.port} (the first load takes 10 to 20 seconds).",
        flush=True,
    )
    print("Press Control and C here to stop.", flush=True)
    launch(args.port)


def main(argv: list[str] | None = None) -> None:
    from staffpilot import COPYRIGHT, SLOGAN, __version__

    parser = argparse.ArgumentParser(
        prog="staffpilot",
        description="Support agent staffing planner",
        epilog=f"{COPYRIGHT}. {SLOGAN}.",
    )
    parser.add_argument(
        "--version", action="version", version=f"StaffPilot {__version__}, {COPYRIGHT}, {SLOGAN}"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="default WARNING, or STAFFPILOT_LOG_LEVEL",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="build the recommended plan and write outputs").set_defaults(func=cmd_plan)
    sub.add_parser("eda", help="data quality checks and exploratory charts").set_defaults(func=cmd_eda)
    ask = sub.add_parser("ask", help="ask the planning assistant")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--backend", default="offline")
    ask.set_defaults(func=cmd_ask)
    chat = sub.add_parser("chat", help="talk to the assistant with follow up questions")
    chat.add_argument("--backend", default="offline")
    chat.set_defaults(func=cmd_chat)
    models = sub.add_parser("models", help="list the language models each provider offers to your keys")
    models.add_argument("--ping", action="store_true", help="also send one tiny request to the chosen models")
    models.set_defaults(func=cmd_models)
    memo = sub.add_parser("memo", help="staffing memo for one country")
    memo.add_argument("country", nargs="+")
    memo.add_argument("--backend", default="offline")
    memo.set_defaults(func=cmd_memo)
    evaluate = sub.add_parser("eval", help="compare the offline backend and LLM providers on the test sets")
    evaluate.add_argument("providers", nargs="*", help="openai, anthropic, google (default: all with keys)")
    evaluate.add_argument("--tier", choices=["strong", "fast", "both"], default="both")
    evaluate.add_argument("--skip-agent", action="store_true", help="do not evaluate the create_agent chat")
    evaluate.set_defaults(func=cmd_eval)
    hist = sub.add_parser("history", help="list recorded runs")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(func=cmd_history)
    app = sub.add_parser("app", help="start the Gradio app")
    app.add_argument("--port", type=int, default=7860)
    app.set_defaults(func=cmd_app)
    args = parser.parse_args(argv)
    from staffpilot.data import DatasetError
    from staffpilot.logs import configure_logging

    configure_logging(args.log_level, run_name=args.command)

    try:
        args.func(args)
    except DatasetError as error:
        print(f"Data problem: {error}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
