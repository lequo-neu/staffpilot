"""Build and execute the submission notebook.

Usage, from the repository root:

    python scripts/build_notebook.py            # build and run every cell, offline
    python scripts/build_notebook.py --live     # let the demo cells call language models
    python scripts/build_notebook.py write      # only write the cells

The build is offline by default, even when API keys are set, so rebuilding the
notebook never costs money. The evaluation section reads the results that
`python -m staffpilot eval` wrote instead of running the evaluation again.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "StaffPilot_Topic3.ipynb"

AI = "\n\n"
CELLS: list[tuple[str, str]] = [
    (
        "md",
        """# StaffPilot: dynamic agent staffing with a GenAI planning assistant

IE5374 Applied Generative AI, Module 7 Hackathon, Topic 3 (problem contributed by Google).

**Seven Team-5374** · Copyright © 2026 Seven Team-5374

**Question.** How many support agents should each of 22 countries have in each month of the planning year, given uncertain sign ups, a 10 advertiser capacity per agent, a 60 day waiting pool, one month of ramp up and a firing cost of 40 percent of salary?

**Answer in one line.** January headcount is roughly three times what demand needs. Giving notice in January, hiring a few agents back before the fourth quarter and growing Vietnam raises expected net value by about 109 million dollars (30 percent) while serving every eligible advertiser with waits of about a day. A GenAI assistant puts the model in a manager's hands: it reads questions into typed requests, runs the planner as a tool, and only reports numbers that the planner produced.

Sections (brief requirement numbers as in the README): 1 setup and data (R16) · 2 rules and assumptions (R3 to R11) · 3 sign up data (R20) · 4 forecast (R24) · 5 simulator checks (R5 to R10) · 6 two countries first (R23) · 7 policies compared (R12, R13) · 8 the monthly plan (R1, R2) · 9 service versus value · 10 sensitivity and Monte Carlo (R14) · 11 assumptions that matter · 12 backtest on real sign ups · 13 other considerations (R15) · 14 the GenAI application (R17 to R22) · 15 multi LLM evaluation · 16 conclusions (R29).

> Every section was drafted with AI assistance and is marked as such; see docs/AI_USAGE.md for what was checked and how.""",
    ),
    ("md", "## 1. Setup and data" + AI),
    (
        "code",
        """%matplotlib inline
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from staffpilot import Planner, ScenarioParams, load_settings
from staffpilot.agent import StaffPilot, available_providers
from staffpilot.planner import RECOMMENDED_POLICY
from staffpilot.logs import configure_logging

configure_logging("WARNING", run_name="notebook")  # "INFO" or "DEBUG" shows what the planner and assistant do
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")

settings = load_settings()
planner = Planner(settings)
data = planner.dataset
print(f"Source file: {Path(data.source).name}")
print(f"History years {data.history_years}, planning year {planner.year}, {len(planner.countries)} countries")
print(f"{len(data.signups):,} sign ups, {int(data.signups['eligible'].sum()):,} eligible ({data.signups['eligible'].mean():.1%})")
data.countries.head()""",
    ),
    (
        "md",
        """## 2. Rules and assumptions

The brief rules are settings, not constants in code, and every open point is a switch. The planning year comes from the data: the course dataset holds sign ups for 2024 and 2025 and staffing as of January 2026, one year later than the brief's text, so the plan covers 2026. A file with 2023 and 2024 would plan 2025 with no code change."""
        + AI,
    ),
    (
        "code",
        """rules = settings.rules
print(f"capacity {rules.capacity_per_agent} advertisers per agent, support {rules.support_days} days, max wait {rules.max_wait_days} days")
print(f"ramp up {rules.ramp_months} month, notice {rules.notice_months} month, firing cost {rules.fire_cost_share:.0%} of annual salary")
print(f"expected uplift {rules.expected_uplift:.3f}")
print("assumptions:", settings.assumptions.model_dump())""",
    ),
    (
        "md",
        "## 3. Exploratory data analysis\n\nData quality first, then the patterns that drive the plan. The same report is written by `python -m staffpilot eda`."
        + AI,
    ),
    (
        "code",
        """from staffpilot.eda import budget_figure, figures, profile

report = profile(data, settings.rules.capacity_per_agent)
for finding in report.findings:
    print("*", finding)
report.quality""",
    ),
    (
        "code",
        """eda_figures = figures(report)
display(eda_figures["monthly_trend"], eda_figures["staff_vs_need"])""",
    ),
    (
        "code",
        """display(eda_figures["seasonality_heatmap"], budget_figure(data), eda_figures["daily_noise"])""",
    ),
    (
        "code",
        """report.countries[["country", "signups", "eligible_rate", "median_eligible_budget", "threshold", "agents", "peak_need", "staff_to_need", "yearly_change", "daily_cv"]].sort_values("staff_to_need", ascending=False)""",
    ),
    (
        "md",
        """## 4. Forecast

Three seasonal methods are backtested: train on the first year, predict the second. With one training year they tie, so the seasonal mean of both years is used because it draws on the most data."""
        + AI,
    ),
    (
        "code",
        """bt = planner.forecast.backtest
print("chosen method:", planner.forecast.method)
bt.groupby("method")["mape"].describe()[["mean", "50%", "max"]]""",
    ),
    (
        "md",
        """## 5. Simulator checks and the flow model

Every number reported later comes from a day by day simulator. A slot counts as free only if it exists for the whole 60 day support under the plan, so an agent under notice takes no new advertisers and the 10 advertiser limit holds every day. The first checks can be verified by hand."""
        + AI,
    ),
    (
        "code",
        """from staffpilot.forecast import DemandStream
from staffpilot.simulate import simulate

def stream(days, arrivals):
    return DemandStream([np.array(arrivals.get(d, []), float) for d in range(days)], [])

months = np.minimum(np.arange(130) // 30, 11)
no_agents = simulate(stream(130, {0: [1000.0] * 5}), np.zeros(12), months, rules, settings.assumptions)
one_agent = simulate(stream(130, {0: [1000.0] * 10, 1: [1000.0]}), np.ones(12), months, rules, settings.assumptions)
cut = np.array([4, 1] + [1] * 10)
arrivals = stream(130, {d: [1000.0] * 3 for d in range(40)})
aware = simulate(arrivals, cut, months, rules, settings.assumptions)
greedy = simulate(arrivals, cut, months, rules, settings.assumptions, dispatch="greedy")
print("0 agents, 5 sign ups: served", no_agents.totals(12)["served"], "dropped", no_agents.totals(12)["dropped"])
print("1 agent, 11 sign ups: longest wait", int(one_agent.waits.max()), "days (the slot frees after 60 days)")
print("headcount cut from 4 to 1: overflow", aware.monthly["max_overflow"].max(), "with the notice rule,", greedy.monthly["max_overflow"].max(), "if free slots are filled greedily")""",
    ),
    (
        "md",
        """Our first simulator filled today's free slots greedily and showed plans breaking the 10 advertiser limit whenever headcount was cut. We first blamed the optimizer's monthly flows, but the real fix was the dispatch rule above. With that rule in place, the table compares a simple optimizer (advertiser flows by month, 60 days treated as two months) with the weekly one we use.""",
    ),
    (
        "code",
        """flows = planner.flow_resolution_check()
flows.assign(net_value=flows["net_value"] / 1e6).rename(columns={"net_value": "net_value ($M)"})""",
    ),
    (
        "md",
        """Both models are feasible under the notice rule. The monthly model keeps fewer agents and earns about 1.4 million dollars more, but advertisers wait almost twice as long. We keep weekly flows because the brief asks for timely support, and say so rather than claim the weekly model is required.""",
    ),
    (
        "md",
        "## 6. Walking skeleton: two countries first\n\nGermany (most overstaffed) and Vietnam (understaffed) before scaling to all 22."
        + AI,
    ),
    (
        "code",
        """two = planner.run("optimized", ["Germany", "Vietnam"])
two.kpi_table()[["country", "start_agents", "end_agents", "avg_active", "hires", "notices", "service_rate", "mean_wait_days", "net_value"]]""",
    ),
    (
        "md",
        """## 7. All countries: policies compared

Baselines: keep January headcount (hold), match last month's demand (reactive), one cut to the yearly peak plus 10 percent (peak cover). Optimized plans come from a mixed integer program per country (monthly decisions, weekly advertiser flows, three months of lookahead), then are scored by the simulator. The recommended plan adds a 98 percent service floor."""
        + AI,
    ),
    (
        "code",
        """comparison = planner.compare_policies()
money = ["net_value", "net_value_vs_hold", "uplift_value", "salary_cost", "fire_cost", "total_cost"]
view = comparison[["policy", *money, "service_rate", "avg_active", "mean_wait_days"]].copy()
view[money] = view[money] / 1e6
view.rename(columns={c: f"{c} ($M)" for c in money})""",
    ),
    (
        "md",
        """Reading the table: uplift is almost the same under every policy, because nearly every eligible advertiser is served either way. The whole gain is lower cost. A sensible heuristic (reactive) gets most of it; the optimizer adds about 11 million dollars more and, unlike the heuristics, handles hiring caps, service floors and scenarios in one model.""",
    ),
    ("md", "## 8. The recommended monthly plan" + AI),
    (
        "code",
        """bundle = planner.run(RECOMMENDED_POLICY)
plan = bundle.plan_table()
plan.to_csv("../outputs/plan.csv", index=False)
active = plan.pivot(index="country", columns="month", values="active_agents")
active.columns = [c[-2:] for c in active.columns]
active""",
    ),
    (
        "code",
        """changes = plan[(plan["hires_decided"] > 0) | (plan["notices_given"] > 0)][["country", "month", "hires_decided", "notices_given", "agents_in_notice", "active_agents"]]
print(f"{len(changes)} country months with a hiring or notice decision")
changes.head(25)""",
    ),
    (
        "code",
        """kpis = bundle.kpi_table()
kpis[["country", "start_agents", "avg_active", "service_rate", "mean_wait_days", "p90_wait_days", "utilization", "avg_idle_agents", "roi", "net_value"]].sort_values("net_value", ascending=False)""",
    ),
    (
        "code",
        """# The checks the Plan page shows: every brief rule with its numbers, the solver's proof,
# the gain over simple rules, the backtest, and how lean the plan is by the exact daily rules.
from staffpilot import checks
for check in checks.plan_checks(planner, RECOMMENDED_POLICY):
    state = {True: "PASS", False: "FAIL", None: "NOTE"}[check.passed]
    print(f"{state}  {check.title}\\n      {check.detail}")
b = checks.value_breakdown(planner, RECOMMENDED_POLICY)
print(f"\\nNet value {b['uplift'] / 1e6:,.1f}M uplift - {b['salary_cost'] / 1e6:,.1f}M salaries - "
      f"{b['notice_cost'] / 1e6:,.1f}M notices = {b['net_value'] / 1e6:,.1f}M")""",
    ),
    (
        "md",
        "### Alerts\n\nChecks a manager should see before acting on the plan. Each rule is a plain threshold, so the reason is visible."
        + AI,
    ),
    (
        "code",
        """from staffpilot.alerts import plan_alerts

for alert in plan_alerts(planner):
    print(f"[{alert.level}] {alert.message}")""",
    ),
    (
        "md",
        "## 9. Profit only or profit with a service level\n\nThe service goal is the manager's choice, offered on the Plan page. Each goal is its own optimization: profit only, at least 98 percent served, and 98 percent served within 21, 14 or 7 days. Only advertisers served within the limit count towards a timed goal; later service stays allowed."
        + AI,
    ),
    (
        "code",
        """from staffpilot.charts import service_tradeoff
tradeoff = planner.service_tradeoff()
display(service_tradeoff(tradeoff, RECOMMENDED_POLICY))
view = tradeoff[["goal", "net_value", "cost_of_goal", "service_rate", "within_week_rate", "avg_active", "mean_wait_days"]].copy()
view[["net_value", "cost_of_goal"]] = view[["net_value", "cost_of_goal"]] / 1e6
view.rename(columns={"net_value": "net_value_M", "cost_of_goal": "given_up_M"})""",
    ),
    (
        "md",
        """Serving everyone is nearly free because support pays for itself in 21 of 22 countries; the small cost of the 98 percent floor is the UAE. Speed is the real trade: serving 98 percent within a week costs a few million dollars and adds agents in every country. We recommend the 98 percent goal and leave the faster goals as a choice, since the brief values timely support but puts no price on a day of waiting.""",
    ),
    ("md", "## 10. Sensitivity to sign up volume and Monte Carlo" + AI),
    (
        "code",
        """sens = planner.sensitivity()
table = sens.pivot(index="demand_scale", columns="plan", values=["net_value", "service_rate", "mean_wait_days", "avg_active"])
table["net_value"] = table["net_value"] / 1e6
table""",
    ),
    (
        "code",
        """fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
for label, frame in sens.groupby("plan"):
    ax[0].plot(frame["demand_scale"], frame["net_value"] / 1e6, marker="o", label=label)
    ax[1].plot(frame["demand_scale"], frame["mean_wait_days"], marker="o", label=label)
ax[0].set(title="Net value ($M)", xlabel="sign ups relative to forecast")
ax[1].set(title="Mean wait (days)", xlabel="sign ups relative to forecast")
ax[0].legend(); plt.tight_layout(); plt.show()""",
    ),
    (
        "md",
        """When sign ups fall, replanning earns more because it lets surplus agents go. When they rise by 10 to 20 percent, the existing plan earns slightly more on paper because advertisers simply wait longer (up to about two weeks on average), which the brief counts as worse support; replanning keeps waits near one day. At 30 percent more sign ups the existing plan starts losing advertisers and replanning is clearly better.""",
    ),
    (
        "code",
        """mc = planner.monte_carlo(runs=20)
print("Monte Carlo over resampled daily sign ups and sampled uplift, 20 runs")
mc[["net_value", "service_rate", "dropped"]].describe(percentiles=[0.1, 0.5, 0.9]).loc[["mean", "10%", "50%", "90%"]]""",
    ),
    (
        "md",
        """### Monthly update from actual sign ups

The forecast will be wrong, so the plan is updated during the year (`Planner.monthly_update`, the Monthly update page, `python -m staffpilot update`). The months already done keep their hires and notices; their actual sign ups replace the forecast, the remaining months are scaled by how far the last three months were from it, and only the remaining months are solved again. Three cases:""",
    ),
    (
        "code",
        """from staffpilot.charts import monthly_update as update_chart
cases = [("Germany", 2, 1.4, 0), ("USA", 3, 1.2, 0), ("Vietnam", 5, 0.8, -2)]
for country, month, scale, staff in cases:
    actual = planner.forecast.demand(country)[: month - 1] * scale
    update = planner.monthly_update(country, month, actual, staff)
    print(f"{country}, update in month {month}, sign ups at {scale:.0%} of forecast, staff change {staff}")
    print(update.summary().replace("**", ""), "\\n")
display(update_chart(update.table(), update.as_of, "Vietnam: plan updated in May"))""",
    ),
    ("md", "## 11. Which assumptions matter" + AI),
    (
        "code",
        """variants = {
    "default": {},
    "A1 uplift on the 60 day window only": {"assumptions": {"uplift_base": "support_window"}},
    "A3 pool carries over on 1 January": {"assumptions": {"initial_pool": "carryover"}},
    "A8 highest budget served first": {"assumptions": {"queue_policy": "budget_priority"}},
    "A9 no preference for early service": {"planning": {"wait_penalty_per_week": 0.0}},
}
rows = []
for name, change in variants.items():
    variant = Planner(settings.with_updates(**change), data)
    compared = variant.compare_policies(policies=("hold", "optimized")).set_index("policy")
    t = variant.run("optimized").totals()
    rows.append({"assumption": name, "optimized_M": t["net_value"] / 1e6, "hold_M": compared.loc["hold", "net_value"] / 1e6,
                 "avg_active": t["avg_active"], "notices": t["notices"], "mean_wait_days": t["mean_wait_days"], "service_rate": t["service_rate"]})
pd.DataFrame(rows)""",
    ),
    (
        "md",
        """A1 matters most. If uplift only counts during the 60 days of support, every policy loses money, yet the optimized plan still beats holding January headcount by more than 100 million dollars and gives even more notices. The question it raises is whether support pays for itself at all, which only Google can answer. A9 shows the price of timely support: dropping the preference for early service adds about 3 million dollars but nearly triples the average wait.""",
    ),
    (
        "md",
        "## 12. Backtest on real sign ups\n\nPlan the last history year using only the year before it, then simulate on what actually happened. Hindsight is the same optimizer given the real daily sign ups."
        + AI,
    ),
    (
        "code",
        """from staffpilot.backtest import run_backtest, summarize_backtest
summarize_backtest(run_backtest(settings, data))""",
    ),
    ("md", "## 13. Other considerations" + AI),
    (
        "code",
        """rows = []
for country in ("UK", "Germany", "France", "USA", "Mexico", "UAE"):
    r = planner.scenario(ScenarioParams(countries=[country], threshold_multiplier=0.8)).totals()
    rows.append({"country": country, "net_value_change_M": r["net_value_change"] / 1e6, "agents_change": r["avg_active_change"], "extra_served": r["served_change"]})
print("Lowering the eligibility threshold by 20 percent instead of letting idle capacity go:")
pd.DataFrame(rows)""",
    ),
    (
        "code",
        """value_plan = planner.run("optimized").kpi_table().set_index("country")
recommended = kpis.set_index("country")
uae_cost = (value_plan.loc["UAE", "net_value"] - recommended.loc["UAE", "net_value"]) / 1e6
print(f"UAE: the pure value plan gives notice to all {int(value_plan.loc['UAE', 'notices'])} agents and serves {value_plan.loc['UAE', 'service_rate']:.0%};")
print(f"one agent's yearly uplift there is below its salary. The recommended plan keeps about {recommended.loc['UAE', 'avg_active']:.0f} agents on average,")
print(f"serves {recommended.loc['UAE', 'service_rate']:.0%} and costs ${uae_cost:,.2f}M of net value in total.")
print(f"Vietnam: starts with {int(recommended.loc['Vietnam', 'start_agents'])} agents and hires {int(recommended.loc['Vietnam', 'hires'])}; ROI {recommended.loc['Vietnam', 'roi']:.1f}.")""",
    ),
    (
        "md",
        """Further points for the report: cutting about two thirds of the workforce has morale, legal notice and employer brand costs the model does not price; notice rules in several countries are longer than one month; ramp up productivity is likely below full capacity; and serving high budgets first treats small advertisers worse.""",
    ),
    (
        "md",
        """## 14. The GenAI application

StaffPilot uses all six course techniques: API calls (OpenAI, Anthropic, Google through LangChain), prompt engineering (router, answer, memo and judge prompts), structured output (Pydantic `RoutedQuery`, `ScenarioParams`, `MemoDraft`), LangChain (`init_chat_model`, six tools, `create_agent` with memory), RAG (BM25 over the rules, assumptions and metric definitions, with citations) and agents.

Two agent designs are offered. The structured assistant routes each question to one intent and runs a fixed tool for it, which keeps answers predictable and easy to evaluate. The `create_agent` chat lets the model choose and chain tools itself, with memory per conversation. Every answer is written with `{{fact}}` placeholders that are filled from tool output; any number left in the text that no tool produced, or that belongs to another country, is rejected. Without API keys the offline backend (keyword router plus templates) runs the same pipeline."""
        + AI,
    ),
    (
        "code",
        """providers = available_providers()
print("LLM providers with keys:", providers or "none, using the offline backend")
pilot = StaffPilot.for_backend(planner, providers[0] if providers else "offline", Path("../eval/cache"))
questions = [
    "How many agents does Germany need in March and why?",
    "What if sign ups in Brazil drop 30% in Q3?",
    "Compare the optimized plan with keeping January headcount.",
    "What if we lower the eligibility threshold in the UK by 20 percent?",
    "Which countries have the most volatile demand?",
    "How long can an advertiser wait in the pool?",
    "What if sign ups in Atlantis rise 20%?",
]
for q in questions:
    a = pilot.ask(q)
    print(f"Q: {q}\\n({a.route.intent.value}, {', '.join(a.tools) or 'no tool'}, number check {'passed' if a.verified else 'failed'})\\n")
    print(a.text, "\\n")
    if a.chart is not None:
        display(a.chart)""",
    ),
    (
        "code",
        """print(pilot.route("What if sign ups in Brazil drop 30% in Q3?")[0].model_dump_json(indent=2, exclude_none=True))""",
    ),
    (
        "code",
        """# Follow up questions: a Conversation keeps the last four turns, so short follow ups
# inherit the country, months and scenario they leave out.
from staffpilot.agent.memory import Conversation, describe
talk = Conversation()
for q in ["What if sign ups in Brazil drop 30% in Q3?", "And Mexico?", "What about 50 percent instead?"]:
    a = pilot.ask(q, talk)
    kept = f", kept the {describe(a.carried)}" if a.carried else ""
    print(f"Q: {q}\\n({a.route.scenario.plain() if a.route.scenario else a.route.intent.value}{kept})\\n{a.text}\\n")""",
    ),
    (
        "code",
        """# The decision log keeps apart what a language model proposed and what the planner computed.
# Here a scenario is read from a sentence, edited as a manager would, run, and logged.
import tempfile
from staffpilot import audit
read, reader, guardrails = pilot.read("What if sign ups in Brazil drop 30% in Q3?")
ran = read.scenario.model_copy(update={"demand_multiplier": 0.75})
rows = audit.scenario_rows(read.scenario, ran, reader, guardrails, planner.scenario(ran).totals())
rows += audit.answer_rows(pilot.ask("How many agents does Germany need in March?"))
log_folder = Path(tempfile.mkdtemp())
audit.record(rows, log_folder)
audit.read(log_folder)[["decision", "item", "proposed", "proposed_by", "adjusted", "adjusted_by", "applied", "note"]]""",
    ),
    (
        "code",
        """memo = pilot.memo("Vietnam")
print(memo.text)
print("number check:", "passed" if memo.verified else memo.unsupported)
display(memo.chart)""",
    ),
    (
        "code",
        """from staffpilot.agent.tools import PlannerTools
print("LangChain tools:", [t.name for t in PlannerTools(planner).as_langchain_tools()])
if providers:
    from staffpilot.agent.chat_agent import build_chat_agent, chat
    from staffpilot.agent.catalog import pick_model
    agent = build_chat_agent(PlannerTools(planner), pick_model(settings, providers[0], "strong"), settings)
    reply = chat(agent, "Which three countries cut the most agents, and how many?", thread_id="demo")
    print(reply.text, "\\ntools:", reply.tools_called, "unsupported:", reply.unsupported)
    print(chat(agent, "And the first of those, what is its net value?", thread_id="demo").text)
else:
    print("The free form create_agent chat needs an API key; see README.")""",
    ),
    (
        "md",
        """## 15. Multi LLM evaluation

Forty labelled questions (`eval/testset.jsonl`) and a 32 question holdout written in different words (`eval/holdout.jsonl`). Metrics: intent, country and scenario field accuracy; grounded rate (passes the number check without the template fallback, always true for the offline templates); a 1 to 5 judge score averaged over judge models of other providers, with a written rubric; tool choice accuracy of the `create_agent` chat; tokens, cost and latency. Strong and fast tiers are compared separately so models face their peers. The offline keywords were written while looking at the main set, so the holdout is the fair comparison. The table below is read from `eval/results/`, written by `python -m staffpilot eval`; building the notebook never reruns the evaluation, so it never calls a model. Run that command with API keys to add the language model rows (replies are cached in `eval/cache`), then rebuild the notebook."""
        + AI,
    ),
    (
        "code",
        """results = Path("../eval/results")
if not (results / "summary.csv").exists():
    # First run only, and free: the offline backend needs no model.
    from staffpilot.evaluation import run_evaluation
    splits = {name: Path(f"../eval/{name}.jsonl") for name in ("testset", "holdout", "followups")}
    run_evaluation(planner, ["offline"], {"main": splits["testset"], "holdout": splits["holdout"],
                                          "followups": splits["followups"]}, results, None)
summary = pd.read_csv(results / "summary.csv")
summary""",
    ),
    (
        "code",
        """retrieval = pd.read_csv("../eval/results/retrieval.csv")
print(f"Retrieval hit rate (labelled rule passage in the top three): {retrieval['hit'].mean():.0%} of {len(retrieval)} rule questions")
retrieval""",
    ),
    (
        "md",
        """## 16. Conclusions

* The January team is far larger than demand needs in 21 of 22 countries; Vietnam is the exception and needs hiring now.
* The recommended plan keeps about 2,200 agents on average instead of 6,474, gives most notices in January, rehires a few agents before the fourth quarter, serves every eligible advertiser with waits of about a day, and raises expected net value by about 109 million dollars. Uplift is unchanged; the gain is cost.
* On the real sign ups of the last history year, a plan built from the earlier year reaches over 99 percent of the hindsight value.
* The largest open question is the value of support (A1). Under the stricter reading every policy loses money, yet the plan still beats holding headcount by more than 100 million dollars.
* Replan monthly: when sign ups rise, an unchanged plan lets waits grow to weeks before it starts losing advertisers. The monthly update keeps the months done and solves only the rest; Germany at 40 percent above forecast in January needs 31 hires in February instead of none.
* The service goal is a business choice: a 98 percent floor costs almost nothing, while serving 98 percent within a week costs a few million dollars.
* Every approval, scenario and answer goes into a decision log that keeps what a language model proposed apart from what the planner computed.
* Where agents sit idle, lowering the eligibility threshold by 20 percent is worth a few million dollars per large country. In the UAE support does not pay for itself, but keeping it costs very little in total.

AI use: see docs/AI_USAGE.md.""",
    ),
]


def build() -> nbformat.NotebookNode:
    cells = [new_markdown_cell(src) if kind == "md" else new_code_cell(src) for kind, src in CELLS]
    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nb


def execute(nb: nbformat.NotebookNode) -> None:
    """Run every cell with the Python that runs this script.

    A temporary kernel spec is used so a stale global "python3" kernel on the machine
    cannot point the run at another environment.
    """
    import json
    import tempfile

    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    from nbclient import NotebookClient

    with tempfile.TemporaryDirectory() as folder:
        spec_dir = Path(folder) / "staffpilot"
        spec_dir.mkdir()
        spec = {
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Python 3",
            "language": "python",
        }
        (spec_dir / "kernel.json").write_text(json.dumps(spec), encoding="utf-8")
        specs = KernelSpecManager(kernel_dirs=[folder])
        manager = KernelManager(kernel_name="staffpilot", kernel_spec_manager=specs)
        client = NotebookClient(
            nb, km=manager, timeout=1800, resources={"metadata": {"path": str(NOTEBOOK.parent)}}
        )
        client.execute()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}


def main() -> None:
    args = sys.argv[1:]
    nb = build()
    NOTEBOOK.parent.mkdir(exist_ok=True)
    if "--live" in args:
        print(
            "Live mode: the demo cells may call the language models whose keys are set (a few dozen short calls)."
        )
        if input("Type yes to continue: ").strip().lower() != "yes":
            raise SystemExit("Stopped; nothing was called.")
    else:
        # The kernel inherits this, so no cell can reach a paid API.
        os.environ["STAFFPILOT_OFFLINE"] = "1"
    if "write" not in args:
        execute(nb)
    nbformat.write(nb, NOTEBOOK)
    print(f"Wrote {NOTEBOOK}")


if __name__ == "__main__":
    main()
