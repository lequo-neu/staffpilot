"""Gradio app: a planning desk for support staffing managers ("Ledger" design).

A sidebar holds the pages (Assistant, Plan, Monthly update, Scenario, Memo, Data,
Evaluation, Decision log), the
recent conversations of this browser tab and the settings (language model, saving a
conversation). Every page starts with the headline numbers and the alerts. The look
lives in `staffpilot.ui`; this module holds the layout and the handlers.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import tempfile
import uuid

import gradio as gr
import numpy as np
import pandas as pd

from staffpilot import audit, cache, charts, checks
from staffpilot.agent import StaffPilot
from staffpilot.agent.catalog import usable_models, working_default
from staffpilot.agent.facts import checked_numbers
from staffpilot.agent.memory import Conversation, describe
from staffpilot.alerts import plan_alerts
from staffpilot.cli import EVAL_DIR, OUTPUTS
from staffpilot.eda import budget_figure, facts, figures, profile, quality_checks
from staffpilot.monthly import MONTH_NAMES, MonthlyUpdate
from staffpilot.planner import RECOMMENDED_POLICY, SERVICE_GOALS, Planner
from staffpilot.scenarios import ScenarioParams
from staffpilot.ui import CSS, components, icon, theme


log = logging.getLogger(__name__)

EXAMPLES = [
    "How many agents does Germany need in March and why?",
    "What if sign ups in Brazil drop 30% in Q3?",
    "Compare the optimized plan with keeping January headcount.",
    "What if we lower the eligibility threshold in the UK by 20 percent?",
    "Which countries have the most volatile demand?",
    "How long can an advertiser wait in the pool?",
]
HOME = "This year"
# The sidebar follows the manager's year: plan before it starts, update every month, ask any time.
NAV_GROUPS = [
    ("", [HOME]),
    ("Before the year starts", ["Data", "Plan", "Scenario", "Memo"]),
    ("Every month", ["Monthly update", "Decision log"]),
    ("Any time", ["Assistant"]),
    ("Behind the numbers", ["Evaluation"]),
]
PAGES = [page for _, names in NAV_GROUPS for page in names]
# The page that comes next in the manager's year, and why.
NEXT = {
    "Data": ("Plan", "Next: set the goal and approve."),
    "Plan": ("Scenario", "Next: stress test the plan."),
    "Scenario": ("Memo", "Next: brief the countries."),
    "Memo": (HOME, "The plan for the year is ready."),
    "Monthly update": ("Decision log", "Next: see what changed."),
    "Decision log": (HOME, "Back to the year."),
}
# The service goal is a business choice: profit only, or profit with a service level agreement.
GOAL_NAMES = {
    "optimized": "Profit only",
    "service_98": "Profit, 98% served (recommended)",
    "service_98_21d": "Profit, 98% served within 21 days",
    "service_98_14d": "Profit, 98% served within 14 days",
    "service_98_7d": "Profit, 98% served within 7 days",
}
GOALS = [(GOAL_NAMES[g], g) for g in SERVICE_GOALS]
# On a phone the sidebar covers the screen, so it starts closed and closes again after a choice.
CLOSE_SIDEBAR_ON_PHONE = """() => {
  if (window.innerWidth < 769) {
    const toggle = document.querySelector('.sidebar.open .toggle-button');
    if (toggle) toggle.click();
  }
}"""

_PLANNER: Planner | None = None
_PILOTS: dict[str, StaffPilot] = {}
# The monthly update approved last for each country; the next update starts from it.
_APPROVED: dict[str, MonthlyUpdate] = {}


def planner() -> Planner:
    global _PLANNER
    if _PLANNER is None:
        _PLANNER = Planner()
    return _PLANNER


def pilot(backend: str) -> StaffPilot:
    if backend not in _PILOTS:
        _PILOTS[backend] = StaffPilot.for_backend(planner(), backend, EVAL_DIR / "cache")
    return _PILOTS[backend]


def _monthly(bundle, country: str | None) -> pd.DataFrame:
    """One row per planning month: net value, agents, service, utilization and cost."""
    frame = bundle.monthly_table()
    frame = frame[frame["month_index"] <= 12]
    if country:
        frame = frame[frame["country"] == country]
    m = frame.groupby("month_index")[
        [
            "uplift_value",
            "salary_cost",
            "fire_cost",
            "active_agents",
            "served",
            "arrivals",
            "occupied_slot_days",
            "capacity_slot_days",
        ]
    ].sum()
    m["net_value"] = m["uplift_value"] - m["salary_cost"] - m["fire_cost"]
    m["cost"] = m["salary_cost"] + m["fire_cost"]
    m["service"] = m["served"] / m["arrivals"].where(m["arrivals"] > 0)
    m["utilization"] = m["occupied_slot_days"] / m["capacity_slot_days"].where(m["capacity_slot_days"] > 0)
    return m


AGAINST = "keeping the January team"


def _compare(
    new: float,
    old: float,
    good: str | None = "up",
    points: bool = False,
    words: tuple[str, str] = ("more than", "less than"),
    base: str = AGAINST,
) -> tuple[str, str, str, str]:
    """How a number moved against a reference: delta text, arrow, colour and the words after it.

    Shares (points=True) are compared in percentage points, everything else in percent.
    `good` says which direction is welcome; None leaves the delta uncoloured.
    """
    if points:
        diff = (new - old) * 100
        delta = f"{abs(diff):.1f} pts" if abs(diff) >= 0.05 else ""
    else:
        diff = (new - old) / abs(old) if old else 0.0
        delta = f"{abs(diff):.1%}" if diff else ""
    if not delta:
        return "", "", "", f"same as {base}"
    trend = "up" if diff > 0 else "down"
    tone = "" if good is None else "good" if trend == good else "bad"
    return delta, trend, tone, f"{words[0] if trend == 'up' else words[1]} {base}"


def plan_kpis(p: Planner, country: str | None = None, goal: str = RECOMMENDED_POLICY) -> str:
    """KPI cards with a monthly sparkline, each compared with keeping the January team all year."""
    bundle, hold = p.run(goal), p.run("hold")
    if country:
        t, h = bundle.outcomes[country].kpis, hold.outcomes[country].kpis
    else:
        t, h = bundle.totals(), hold.totals()
    m, mh = _monthly(bundle, country), _monthly(hold, country)
    util = m["occupied_slot_days"].sum() / max(m["capacity_slot_days"].sum(), 1)
    util_hold = mh["occupied_slot_days"].sum() / max(mh["capacity_slot_days"].sum(), 1)
    rules = p.settings.rules
    shares = {"points": True, "words": ("against", "against")}
    kpis = [
        components.Kpi(
            "Net value",
            charts.money(t["net_value"]),
            "Expected ad spend uplift from supported advertisers, minus agent salaries and the cost of notices, "
            "over the planning year. The line shows each month.",
            *_compare(t["net_value"], h["net_value"]),
            m["net_value"].tolist(),
        ),
        components.Kpi(
            "Agents at work",
            f"{t['avg_active']:,.0f}",
            "Average number of agents working in a month, after new hires finish ramp up and notices take effect.",
            *_compare(
                t["avg_active"],
                t["start_agents"],
                good=None,
                words=("more than", "fewer than"),
                base=f"the {t['start_agents']:,.0f} in January",
            ),
            m["active_agents"].tolist(),
        ),
        components.Kpi(
            "Advertisers served",
            f"{t['service_rate']:.1%}",
            f"Share of eligible advertisers who get an agent within the {rules.max_wait_days} day waiting window. "
            f"They wait {t['mean_wait_days']:.1f} days on average; one in ten waits over {t['p90_wait_days']:.0f}. "
            f"{t['within_week_rate']:.1%} get an agent within 7 days.",
            *_compare(t["service_rate"], h["service_rate"], **shares),
            m["service"].fillna(1.0).tolist(),
        ),
        components.Kpi(
            "Agent utilization",
            f"{util:.1%}",
            f"Share of agent capacity in use over the year; each agent can hold {rules.capacity_per_agent} advertisers.",
            *_compare(util, util_hold, **shares),
            m["utilization"].fillna(0.0).tolist(),
        ),
        components.Kpi(
            "Total cost",
            charts.money(t["total_cost"]),
            f"Salaries plus notice cost; a notice costs {rules.fire_cost_share:.0%} of a year's salary. "
            f"Notices make up {charts.money(t['fire_cost'])} of the total.",
            *_compare(t["total_cost"], h["total_cost"], good="down"),
            m["cost"].tolist(),
        ),
    ]
    return components.kpi_cards(kpis)


def _readable(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in out.columns:
        if not pd.api.types.is_numeric_dtype(out[column]):
            continue
        if any(k in column for k in ("cost", "value")):
            out[column] = out[column].map(charts.money)
        elif "rate" in column:
            out[column] = out[column].map(lambda v: f"{v:.1%}")
        elif pd.api.types.is_float_dtype(out[column]):
            out[column] = out[column].round(1)
    # "active_agents" reads as "Active agents" in the table header.
    out.columns = [str(c).replace("_", " ").capitalize() for c in out.columns]
    return out


def _trace(answer) -> str:
    return components.trace(
        answer.route.intent.value.replace("_", " "),
        ", ".join(answer.tools) or "no planner tool",
        answer.verified,
        answer.seconds,
        answer.backend,
        describe(answer.carried) if answer.carried else "",
        answer.guardrails,
        checked_numbers(answer.text) if answer.verified else 0,
        len(answer.facts),
    )


def ask(message: str, history: list, backend: str, memory: Conversation | None = None):
    """Answer one message. Returns the chat, the cleared box, the trace, chart, table, route and memory."""
    # Each conversation has its own memory, kept in the browser tab's state.
    memory = memory or Conversation()
    if not message.strip():
        return history, "", components.trace_empty(), None, pd.DataFrame(), "{}", memory
    answer = pilot(backend).ask(message, memory)
    audit.record(audit.answer_rows(answer), OUTPUTS)
    history = [*history, {"role": "user", "content": message}, {"role": "assistant", "content": answer.text}]
    path = charts.save_answer_chart(answer.chart, message, OUTPUTS / "answers", components.WEB_DPI)
    if path:
        history.append({"role": "assistant", "content": {"path": str(path)}})
    table = _readable(answer.tables[0]) if answer.tables else pd.DataFrame()
    route = json.dumps(answer.route.model_dump(mode="json", exclude_none=True), indent=2)
    return history, "", _trace(answer), answer.chart, table, route, memory


def export_conversation(memory: Conversation | None):
    if memory is None or not memory.turns:
        return gr.File(visible=False)
    folder = OUTPUTS / "conversations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"chat_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(memory.to_markdown(), encoding="utf-8")
    return gr.File(value=str(path), visible=True)


def _title(message: str) -> str:
    text = " ".join(message.split())
    return text if len(text) <= 42 else text[:40].rsplit(" ", 1)[0] + " ..."


def _recent(chats: dict, current: str | None):
    ordered = sorted(chats.items(), key=lambda kv: kv[1]["updated"], reverse=True)
    return gr.Radio(
        choices=[(chat["title"], key) for key, chat in ordered], value=current if current in chats else None
    )


def send(message: str, history: list, backend: str, memory, chats: dict | None, current: str | None):
    """`ask`, plus filing the conversation under Recent chats in the sidebar."""
    chats = dict(chats or {})
    # The chart is shown inside the answer, so the side panel keeps only the trace, table and route.
    history, box, trace, _, table, route, memory = ask(message, history, backend, memory)
    if message.strip():
        current = current or uuid.uuid4().hex[:8]
        title = chats.get(current, {}).get("title") or _title(message)
        chats[current] = {
            "title": title,
            "history": history,
            "memory": memory,
            "updated": datetime.now().timestamp(),
        }
    return history, box, trace, table, route, memory, chats, current, _recent(chats, current)


def example_text(evt: gr.SelectData) -> str:
    return evt.value["text"]


def start_chat(chats: dict | None):
    chats = chats or {}
    return (
        [],
        "",
        components.trace_empty(),
        pd.DataFrame(),
        "{}",
        Conversation(),
        chats,
        None,
        _recent(chats, None),
    )


def open_chat(key: str | None, chats: dict | None):
    chat = (chats or {}).get(key)
    if chat is None:
        return gr.update(), gr.update(), gr.update()
    return chat["history"], chat["memory"], key


def show_page(name: str):
    return [gr.Column(visible=name == page) for page in PAGES]


def model_choices(refresh: bool = False) -> tuple[list[tuple[str, str]], str]:
    """Offline, then every chat model the keys can use, cheapest first. Offline is the default.

    On start the cheapest models get one tiny check (see `catalog.working_default`, a few
    tokens, remembered for a day), so retired models drop out of the list and the cheapest
    one that answers is marked. Nothing else is sent until someone picks a model.
    """
    settings = planner().settings
    found = usable_models(settings, refresh)
    working = working_default(settings, found) if found else None
    # The check may have just ruled out a retired model, so the list is read again.
    found = usable_models(settings) if found else []
    listed = [(f"{c.label[:-1]}, cheapest working)" if c.spec == working else c.label, c.spec) for c in found]
    return [("Offline (free, no API key)", "offline"), *listed], "offline"


def plan_view(country: str, goal: str = RECOMMENDED_POLICY):
    p = planner()
    bundle = p.run(goal)
    plan, monthly = bundle.plan_table(), bundle.monthly_table()
    monthly = monthly[monthly["month_index"] <= 12]
    chosen = None if country == "All countries" else country
    if chosen:
        plan, monthly = plan[plan["country"] == chosen], monthly[monthly["country"] == chosen]
    figure = charts.headcount(
        plan,
        monthly,
        f"{country}: headcount for {p.year}, {GOAL_NAMES[goal]}",
        p.settings.rules.capacity_per_agent,
    )
    columns = [
        "active_agents",
        "hires_decided",
        "notices_given",
        "agents_in_ramp",
        "payroll_agents",
        "salary_cost",
        "fire_cost",
    ]
    shown = plan if chosen else plan.groupby("month", as_index=False)[columns].sum()
    shown = shown.reset_index(drop=True)
    hires, notices = list(shown["hires_decided"] > 0), list(shown["notices_given"] > 0)
    styled = _tinted(
        _readable(shown),
        {"Hires decided": hires, "Notices given": notices, "Fire cost": notices},
        {"Hires decided": "teal", "Notices given": "red", "Fire cost": "red"},
    )
    return plan_kpis(p, chosen, goal), components.sharp(figure), styled


def _chosen(country: str) -> str | None:
    return None if country == "All countries" else country


def check_view(country: str, goal: str = RECOMMENDED_POLICY) -> str:
    """Is the plan right, and is it the best? Every rule and comparison, with its numbers."""
    return components.checklist(checks.plan_checks(planner(), goal, _chosen(country)))


def breakdown_view(country: str, goal: str = RECOMMENDED_POLICY):
    """Net value rebuilt from its inputs, the month by month detail, and the detail as a CSV."""
    p = planner()
    chosen = _chosen(country)
    b = checks.value_breakdown(p, goal, chosen)
    rules = p.settings.rules
    spread = ", ".join(
        f"{level:.0%} with probability {prob:.0%}"
        for level, prob in zip(rules.uplift_levels, rules.uplift_probabilities, strict=True)
    )
    per = "average " if chosen is None else ""
    text = "\n".join(
        [
            f"**Net value = uplift − salaries − notice cost**, for {country}, {p.year}.",
            "",
            (
                f"* **Uplift** {charts.money(b['uplift'])} = {b['served']:,.0f} advertisers served × "
                f"${b['mean_budget']:,.0f} average projected annual budget × {b['uplift_rate']:.1%} expected "
                f"uplift (the brief's spread: {spread})."
            ),
            (
                f"* **Salaries** {charts.money(b['salary_cost'])} = {b['payroll_agent_months']:,.0f} paid agent months "
                f"(including ramp up and notice months) × ${b['salary_per_agent_month']:,.0f} {per}salary a month."
            ),
            (
                f"* **Notice cost** {charts.money(b['notice_cost'])} = {b['notices']:,.0f} notices × "
                f"${b['salary_per_notice']:,.0f} {per}annual salary × {b['fire_cost_share']:.0%}."
            ),
            (
                f"* **Net value** {charts.money(b['uplift'])} − {charts.money(b['salary_cost'])} − "
                f"{charts.money(b['notice_cost'])} = **{charts.money(b['net_value'])}**, the number on the card."
            ),
        ]
    )
    detail = checks.monthly_detail(p, goal, chosen)
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"plan_detail_{(chosen or 'all').replace(' ', '_')}.csv"
    detail.to_csv(path, index=False)
    shown = detail.assign(utilization=detail["utilization"].map(lambda v: f"{v:.0%}" if pd.notna(v) else ""))
    return text, _readable(shown), gr.File(value=str(path), visible=True)


def manual_inputs(country: str, goal: str = RECOMMENDED_POLICY, percent: float = -5) -> pd.DataFrame:
    """The optimized headcount and an editable copy changed by `percent` from February."""
    chosen = _chosen(country)
    if chosen is None:
        return pd.DataFrame({"Month": [], "Optimized": [], "Yours": []})
    active = planner().run(goal).outcomes[chosen].plan.active[:12]
    yours = active.copy()
    yours[1:] = (active[1:] * (1 + float(percent or 0) / 100)).round()
    return pd.DataFrame({"Month": checks.MONTHS, "Optimized": active.astype(int), "Yours": yours.astype(int)})


def manual_score(country: str, goal: str, table: pd.DataFrame):
    """Score the typed headcount with the same simulator and compare it with the optimized plan."""
    chosen = _chosen(country)
    if chosen is None:
        return "Pick one country in the list above, then try your own headcount for it.", None
    try:
        targets = pd.to_numeric(pd.DataFrame(table)["Yours"], errors="raise").to_numpy(dtype=float)
        result = checks.compare_manual(planner(), chosen, targets, goal)
    except (KeyError, TypeError, ValueError) as error:
        return f"Those numbers do not work: {error}", None
    change = result.manual.kpis["net_value"] - result.optimized.kpis["net_value"]
    figure = charts.manual_plan(
        result.table(), f"{chosen}: your headcount against the optimized plan", change
    )
    return result.summary(), components.sharp(figure)


def tradeoff_view(goal: str = RECOMMENDED_POLICY):
    """Profit only against each service goal: the value given up and the service bought with it."""
    frame = planner().service_tradeoff()
    profit, chosen = frame.iloc[0], frame[frame["policy"] == goal].iloc[0]
    text = (
        f"**Profit only** earns {charts.money(profit['net_value'])} and serves {profit['service_rate']:.1%} of "
        f"eligible advertisers, {profit['within_week_rate']:.1%} of them within 7 days. "
    )
    if goal != "optimized":
        text += (
            f"**{GOAL_NAMES[goal]}** gives up {charts.money(chosen['cost_of_goal'])} "
            f"({chosen['cost_of_goal'] / profit['net_value']:.2%} of net value) to serve {chosen['service_rate']:.1%}, "
            f"{chosen['within_week_rate']:.1%} within 7 days, with {chosen['avg_active'] - profit['avg_active']:+,.0f} "
            "agents on average."
        )
    shown = frame.assign(goal=frame["policy"].map(GOAL_NAMES))[
        [
            "goal",
            "net_value",
            "cost_of_goal",
            "service_rate",
            "within_week_rate",
            "avg_active",
            "mean_wait_days",
        ]
    ].rename(columns={"cost_of_goal": "value_given_up", "within_week_rate": "served_in_7_days_rate"})
    return text, components.sharp(charts.service_tradeoff(frame, goal)), _readable(shown)


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def approve(country: str, goal: str = RECOMMENDED_POLICY) -> str:
    bundle = planner().run(goal)
    plan = bundle.plan_table()
    countries = list(bundle.outcomes)
    if country != "All countries":
        plan, countries = plan[plan["country"] == country], [country]
    OUTPUTS.mkdir(exist_ok=True)
    # One file per approval, named by scope, goal and time, so any approval can be traced back.
    scope = "all" if country == "All countries" else _slug(country)
    path = OUTPUTS / f"approved_plan_{scope}_{goal}_{_stamp()}.csv"
    plan.to_csv(path, index=False)
    rows = audit.plan_rows(bundle, countries, GOAL_NAMES[goal], GOAL_NAMES[RECOMMENDED_POLICY])
    rows[0]["note"] = f"saved as {path.name}"
    audit.record(rows, OUTPUTS)
    log.info("Plan approved for %s with goal %s (%d rows)", country, goal, len(plan))
    return f"Approved with the goal *{GOAL_NAMES[goal]}*. Saved `{path.name}`; {len(rows)} rows in the decision log."


def _as_of(month: str) -> int:
    return MONTH_NAMES.index(month) + 1


MOMENTS = ["Before the year starts", *[f"Start of {m}" for m in MONTH_NAMES[1:]]]


def _moment_month(moment: str) -> int:
    """Calendar month the manager is deciding in: January before the year starts."""
    return 1 if moment == MOMENTS[0] else _as_of(moment.removeprefix("Start of "))


def nav_sync(name: str):
    """Show the open page as selected in its sidebar group and clear the other groups."""
    return [gr.Radio(value=name if name in names else None) for _, names in NAV_GROUPS]


def home_steps(moment: str) -> list[tuple[str, str]]:
    """What to do now, in order, as (text, page to open)."""
    now = _moment_month(moment)
    if now == 1:
        return [
            ("**1. Check the data.** Quality and seasonality.", "Data"),
            ("**2. Set the goal, check, approve.** Every rule is tested.", "Plan"),
            ("**3. Stress test.** Fewer sign ups, a hiring cap.", "Scenario"),
            ("**4. Brief the countries.** One memo each.", "Memo"),
        ]
    month = MONTH_NAMES[now - 1]
    upcoming = MONTH_NAMES[min(now, 11)]
    return [
        (f"**1. Enter what happened.** Actual sign ups and staff; plan {month} onward.", "Monthly update"),
        ("**2. See what changed.** Every month the update moved.", "Decision log"),
        (f"**3. Ask why.** For example: Germany in {upcoming}?", "Assistant"),
        ("**4. Test what comes next.** What if sign ups keep rising?", "Scenario"),
    ]


def home_view(moment: str, goal: str = RECOMMENDED_POLICY):
    """The year strip, the steps for this moment, and the month the Monthly update page should open on."""
    p = planner()
    now = _moment_month(moment)
    active, hires, notices, moved = np.zeros(12), np.zeros(12), np.zeros(12), [False] * 12
    for country, outcome in p.run(goal).outcomes.items():
        update = _APPROVED.get(country)
        plan = update.updated.plan if update else outcome.plan
        active += plan.active[:12]
        hires += plan.hires[:12]
        notices += plan.notices[:12]
        if update:
            for t in range(update.done, 12):
                moved[t] |= bool(update.updated.plan.active[t] != update.original.active[t])
    months = [
        {
            "label": MONTH_NAMES[t][:3],
            "agents": float(active[t]),
            "hires": float(hires[t]),
            "notices": float(notices[t]),
            "status": "done" if t < now - 1 else "now" if t == now - 1 else "planned",
            "updated": moved[t],
        }
        for t in range(12)
    ]
    steps = home_steps(moment)
    month = gr.update(value=MONTH_NAMES[now - 1]) if now > 1 else gr.update()
    return (
        home_verdict(goal),
        components.year_rail(p.year, months),
        *[text for text, _ in steps],
        *[gr.Button(value=f"Open {page}") for _, page in steps],
        [page for _, page in steps],
        month,
    )


def home_if_open(name: str, moment: str, goal: str):
    """Refresh This year when it is opened, since an approval elsewhere may have changed it."""
    return home_view(moment, goal) if name == HOME else [gr.update()] * 12


def _last_approval() -> tuple[str, str] | None:
    """(time, goal) of the latest plan approval in the decision log, if any."""
    log_frame = audit.read(OUTPUTS)
    if log_frame.empty:
        return None
    rows = log_frame[(log_frame["decision"] == "plan approved") & (log_frame["item"] == "service goal")]
    if rows.empty:
        return None
    return rows.iloc[0]["time"].replace("T", " ")[:16], rows.iloc[0]["applied"]


def home_verdict(goal: str = RECOMMENDED_POLICY) -> str:
    """The year in four facts: the value, the team, the service, and whether the plan is approved."""
    p = planner()
    t, h = p.run(goal).totals(), p.run("hold").totals()
    approval = _last_approval()
    status = (
        (f"Approved {approval[0]}", approval[1], "good")
        if approval
        else ("Not approved", "open Plan to check and approve it", "warn")
    )
    return components.facts(
        [
            (
                charts.money(t["net_value"]),
                f"net value, {charts.money(t['net_value'] - h['net_value'])} more than keeping the January team",
                "accent",
            ),
            (
                f"{t['start_agents']:,.0f} → {t['avg_active']:,.0f}",
                "agents: the January team, then the average month",
                "",
            ),
            (
                f"{t['service_rate']:.1%}",
                f"advertisers served, after {t['mean_wait_days']:.1f} days on average",
                "good",
            ),
            status,
        ]
    )


def check_inputs(country: str, month: str, actuals: pd.DataFrame, change: float) -> str:
    """Read the typed numbers back with their gap to the forecast, and flag the ones to check."""
    try:
        frame = pd.DataFrame(actuals)
        actual = pd.to_numeric(frame["Actual"], errors="coerce")
        forecast = pd.to_numeric(frame["Forecast"], errors="coerce")
    except KeyError:
        return ""
    if frame.empty:
        return ""
    lines, flags = [], 0
    for name, a, f in zip(frame["Month"], actual, forecast, strict=True):
        if pd.isna(a) or a < 0:
            lines.append(f"* {name}: **not a count**, type a whole number of sign ups.")
            flags += 1
            continue
        gap = (a - f) / f if f else 0.0
        note = ""
        if abs(gap) > 0.5:
            note = " **Check this count**: it is more than half away from the forecast."
            flags += 1
        lines.append(f"* {name}: {a:,.0f} against a forecast of {f:,.0f} ({gap:+.0%}).{note}")
    planned = planner().run(RECOMMENDED_POLICY).outcomes[country].plan.active[_as_of(month) - 1]
    if change and planned and abs(float(change)) > 0.2 * planned:
        lines.append(
            f"* Agents on staff: {float(change):+,.0f} against a plan of {planned:,.0f}. **Check this number**: "
            "it moves the team by more than a fifth."
        )
        flags += 1
    previous = _APPROVED.get(country)
    if previous and previous.as_of < _as_of(month):
        lines.append(
            f"* Starts from the update approved in {MONTH_NAMES[previous.as_of - 1]}; its actual counts are "
            "filled in above."
        )
    head = "**Input check:** " + (
        f"{flags} number(s) to look at." if flags else "the numbers look consistent."
    )
    return "\n".join([head, *lines])


def actual_inputs(country: str, month: str, percent: float) -> pd.DataFrame:
    """The months before the update, with the forecast and an actual count to edit (forecast plus `percent`)."""
    done = _as_of(month) - 1
    forecast = planner().forecast.demand(country)[:done]
    actual = forecast * (1 + float(percent or 0) / 100)
    # Months an approved earlier update already counted keep their actual numbers.
    previous = _APPROVED.get(country)
    if previous and previous.as_of <= done + 1:
        actual[: previous.done] = previous.actual
    return pd.DataFrame(
        {
            "Month": MONTH_NAMES[:done],
            "Forecast": forecast.round().astype(int),
            "Actual": actual.round().astype(int),
        }
    )


def update_view(country: str, month: str, actuals: pd.DataFrame, change: float, goal: str):
    """Plan again from `month` with the actual sign ups so far. Returns the summary, chart, table and result."""
    try:
        actual = pd.to_numeric(pd.DataFrame(actuals)["Actual"], errors="raise").to_numpy(dtype=float)
        previous = _APPROVED.get(country)
        # A later month builds on the update approved before it; the same month is planned again from scratch.
        base = previous.updated.plan if previous and previous.as_of < _as_of(month) else None
        update = planner().monthly_update(country, _as_of(month), actual, int(change or 0), goal, base=base)
    except (KeyError, TypeError, ValueError) as error:
        return f"Those inputs do not work: {error}", None, pd.DataFrame(), None
    table = update.table()
    figure = charts.monthly_update(table, update.as_of, f"{country}: plan updated in {month} {update.year}")
    return update.summary(), components.sharp(figure), _update_table(table), update


def _update_table(table: pd.DataFrame) -> pd.DataFrame:
    """The month by month comparison, narrow enough for the side panel."""

    def pair(before: pd.Series, after: pd.Series) -> list[str]:
        return [str(b) if b == a else f"{b} → {a}" for b, a in zip(before, after, strict=True)]

    return pd.DataFrame(
        {
            "Month": [MONTH_NAMES[int(m[-2:]) - 1][:3] for m in table["month"]],
            "Status": table["status"],
            "Sign ups": pair(table["forecast_signups"], table["signups_used"]),
            "Agents at work": pair(table["agents_planned"], table["agents_updated"]),
            "Hires": pair(table["hires_planned"], table["hires_updated"]),
            "Notices": pair(table["notices_planned"], table["notices_updated"]),
        }
    )


def approve_update(update) -> str:
    if update is None:
        return "Update the plan first, then approve it."
    OUTPUTS.mkdir(exist_ok=True)
    month = f"{update.year}-{update.as_of:02d}"
    path = OUTPUTS / f"approved_update_{_slug(update.country)}_{month}_{_stamp()}.csv"
    update.table().assign(country=update.country).to_csv(path, index=False)
    _APPROVED[update.country] = update
    rows = audit.update_rows(update)
    if rows:
        rows[0]["note"] = f"saved as {path.name}"
    audit.record(rows, OUTPUTS)
    log.info("Monthly update approved for %s in month %d", update.country, update.as_of)
    return f"Approved. Saved `{path.name}`; {len(rows)} rows in the decision log."


def _reader(name: str) -> str:
    return "offline reader (keywords)" if name.startswith("offline") else f"GenAI ({name})"


def parse_scenario(text: str, backend: str) -> tuple[str, str, dict]:
    """Read a sentence into scenario parameters. The third value records what the reader proposed."""
    route, name, guardrails = pilot(backend).read(text)
    if route.scenario is None and not route.clarification:
        route, name, guardrails = pilot(backend).read(f"What if {text}")
    proposal = {"params": None, "reader": _reader(name), "guardrails": guardrails}
    if route.clarification:
        return "{}", route.clarification, proposal
    params = route.scenario or ScenarioParams(countries=route.countries)
    proposal["params"] = params.model_dump(mode="json")
    return json.dumps(proposal["params"], indent=2), f"**Understood as:** {params.plain()}.", proposal


SCENARIO_EXAMPLES = [
    "Sign ups in Germany drop 30% in Q3",
    "Hiring in Brazil is capped at 5 agents a month",
    "The eligibility threshold in the UK is lowered by 20%",
]


def run_scenario(params_json: str, proposal: dict | None = None, record: bool = True):
    try:
        params = ScenarioParams.model_validate_json(params_json)
    except ValueError as error:
        return f"Those parameters are not valid: {error}", None, pd.DataFrame()
    p = planner()
    result = p.scenario(params)
    t = result.totals()
    proposal = proposal or {}
    proposed = ScenarioParams.model_validate(proposal["params"]) if proposal.get("params") else None
    if record:
        audit.record(
            audit.scenario_rows(
                proposed, params, proposal.get("reader", "manager"), proposal.get("guardrails", []), t
            ),
            OUTPUTS,
        )
    change = t["net_value_change"]
    sign = "+" if change >= 0 else "-"
    summary = (
        f"{params.plain()}, net value moves from **{charts.money(t['net_value_base'])}** to "
        f"**{charts.money(t['net_value_scenario'])}** ({sign}{charts.money(abs(change))}). "
        f"Service goes from {t['service_rate_base']:.1%} to {t['service_rate_scenario']:.1%}."
    )
    affected = result.comparison["country"].tolist()
    base = p.run(RECOMMENDED_POLICY).plan_table()
    where = ", ".join(affected) if len(affected) <= 3 else f"{len(affected)} countries"
    figure = charts.scenario_lines(
        base[base["country"].isin(affected)], result.plan, f"{where}: headcount under the scenario", change
    )
    names = {
        "country": "country",
        "avg_active_base": "agents_now",
        "avg_active_scenario": "agents_with_change",
        "net_value_base": "net_value_now",
        "net_value_scenario": "net_value_with_change",
        "net_value_change": "net_value_change",
        "service_rate_base": "served_rate_now",
        "service_rate_scenario": "served_rate_with_change",
    }
    shown = result.comparison[list(names)].rename(columns=names)
    worse = list(shown["net_value_change"] < 0)
    styled = _tinted(_readable(shown), {"Net value change": worse}, {"Net value change": "red"})
    return summary, components.sharp(figure), styled


def memo(country: str, backend: str):
    answer = pilot(backend).memo(country)
    check = (
        "Every number matches the planner."
        if answer.verified
        else f"Number check flagged {answer.unsupported}."
    )
    return f"{answer.text}\n\n*{check}*", components.sharp(answer.chart)


TINT = {
    "teal": "background-color: rgba(15, 110, 117, 0.22); font-weight: 600;",
    "red": "background-color: rgba(181, 67, 44, 0.13); font-weight: 600;",
    "amber": "background-color: rgba(201, 138, 27, 0.16); font-weight: 600;",
}


def _tinted(shown: pd.DataFrame, marks: dict[str, list[bool]], tint: dict[str, str]):
    """`shown` with the cells of each named column tinted where its mark is true."""

    def paint(column: pd.Series) -> list[str]:
        flags = marks.get(column.name)
        return [TINT[tint[column.name]] if flags and flags[i] else "" for i in range(len(column))]

    return shown.style.apply(paint).format(precision=1, thousands=",")


def eda_view():
    p = planner()
    report = profile(p.dataset, p.settings.rules.capacity_per_agent)
    figs = figures(report)
    return (
        components.facts(facts(report)),
        components.sharp(figs["monthly_trend"]),
        components.sharp(figs["staff_vs_need"]),
        components.sharp(figs["seasonality_heatmap"]),
        components.sharp(budget_figure(p.dataset)),
        components.checklist(quality_checks(report)),
        report.quality,
    )


def eval_view():
    """Charts and short facts first; the full tables sit below them for anyone who wants detail."""
    from staffpilot.tracking import history

    results = EVAL_DIR / "results"
    if not (results / "summary.csv").exists():
        empty = "No evaluation yet. Run `python -m staffpilot eval`, then open this page again."
        return empty, None, pd.DataFrame(), "", pd.DataFrame(), "", pd.DataFrame()
    summary = pd.read_csv(results / "summary.csv")
    holdout = summary[summary["split"] == "holdout"].sort_values("intent_accuracy", ascending=False)
    lead = ""
    if not holdout.empty:
        best = holdout.iloc[0]
        offline = holdout[holdout["backend"] == "offline"]
        lead = (
            f"On new wording (holdout), **{best['backend'].split(':', 1)[-1]}** reads "
            f"**{best['intent_accuracy']:.0%}** of questions right"
            + (
                f"; the offline keywords read {offline['intent_accuracy'].iloc[0]:.0%}."
                if len(offline)
                else "."
            )
        )
    view = summary[
        [
            "split",
            "backend",
            "cases",
            "intent_accuracy",
            "scenario_accuracy",
            "grounded_rate",
            "judge_score",
            "mean_seconds",
        ]
    ].rename(
        columns={
            "intent_accuracy": "intent_rate",
            "scenario_accuracy": "scenario_rate",
            "mean_seconds": "seconds",
        }
    )
    best_rows = view.groupby("split")["intent_rate"].transform("max") == view["intent_rate"]
    shown = _readable(view)
    scores = _tinted(shown, {"Intent rate": list(best_rows)}, {"Intent rate": "teal"})

    retrieval = (
        pd.read_csv(results / "retrieval.csv") if (results / "retrieval.csv").exists() else pd.DataFrame()
    )
    retrieval_facts, retrieval_table = "", pd.DataFrame()
    if not retrieval.empty:
        hits = int(retrieval["hit"].sum())
        retrieval_facts = components.facts(
            [
                (
                    f"{hits} of {len(retrieval)}",
                    "rule questions find the right passage in the top three",
                    "accent",
                ),
                (
                    str(len(retrieval) - hits),
                    "missed; marked in red below",
                    "bad" if hits < len(retrieval) else "good",
                ),
            ]
        )
        missed = list(~retrieval["hit"].astype(bool))
        shown_r = retrieval[["id", "split", "source", "top3", "hit"]].rename(
            columns={"source": "right passage", "top3": "top three found"}
        )
        retrieval_table = _tinted(shown_r, {"hit": missed, "id": missed}, {"hit": "red", "id": "red"})

    runs = history(15)
    run_facts, run_table = "", pd.DataFrame()
    if not runs.empty:
        latest = runs.iloc[-1]
        same = runs["net_value"].round(0).nunique() == 1
        run_facts = components.facts(
            [
                (str(len(runs)), "recorded plan runs", ""),
                (str(runs["dataset_sha"].nunique()), "data fingerprints", ""),
                (charts.money(float(latest["net_value"])), "net value in the latest run", "accent"),
                ("Same" if same else "Changed", "result across the runs", "good" if same else "warn"),
            ]
        )
        columns = [
            c
            for c in ("time_utc", "kind", "dataset", "git_commit", "net_value", "service_rate", "avg_active")
            if c in runs
        ]
        shown_runs = _readable(runs[columns].iloc[::-1].reset_index(drop=True))
        first = [i == 0 for i in range(len(shown_runs))]
        run_table = _tinted(
            shown_runs, {c: first for c in shown_runs.columns}, {c: "teal" for c in shown_runs.columns}
        )
    return (
        lead,
        components.sharp(charts.evaluation_bars(summary)),
        scores,
        retrieval_facts,
        retrieval_table,
        run_facts,
        run_table,
    )


LOG_FILTERS = [
    "All decisions",
    "Only changes",
    "Plan approved",
    "Monthly update approved",
    "Scenario run",
    "Assistant answer",
]


def log_view(choice: str = "All decisions"):
    """The decision log: what changed at a glance, then the rows, with every change marked."""
    frame = audit.read(OUTPUTS, 500)
    path = OUTPUTS / audit.FILE_NAME
    file = gr.File(value=str(path) if path.exists() else None, visible=path.exists())
    if frame.empty:
        return components.facts([("0", "decisions logged yet", "")]), frame, file
    changed = frame["adjusted_by"].str.len() > 0
    by_you = frame["adjusted_by"].str.startswith("manager")
    genai = frame["proposed_by"].str.contains(
        "GenAI|router|local:|anthropic|openai|google", case=False, regex=True
    )
    guarded = (frame["decision"] == "assistant answer") & (frame["note"] != "no guardrail had to act")
    decisions = frame.groupby(["time", "decision"]).ngroups
    tiles = components.facts(
        [
            (str(decisions), "decisions logged", ""),
            (
                str(int(changed.sum())),
                "values changed after the first proposal",
                "warn" if changed.any() else "",
            ),
            (str(int(by_you.sum())), "changed by you", "accent"),
            (
                str(int(guarded.sum())),
                "answers where a GenAI guardrail acted",
                "warn" if guarded.any() else "good",
            ),
        ]
    )
    if choice == "Only changes":
        keep = changed
    elif choice in LOG_FILTERS[2:]:
        keep = frame["decision"] == choice.lower()
    else:
        keep = pd.Series(True, index=frame.index)
    rows = frame[keep].reset_index(drop=True)
    marks_changed = list(changed[keep])
    marks_genai = list(genai[keep])
    styled = _tinted(
        rows,
        {
            "adjusted": marks_changed,
            "adjusted_by": marks_changed,
            "applied": marks_changed,
            "proposed_by": marks_genai,
        },
        {"adjusted": "amber", "adjusted_by": "amber", "applied": "amber", "proposed_by": "teal"},
    )
    return tiles, styled, file


PAGE_TEXT = {
    HOME: "Where you are in the year, and what to do next.",
    "Data": "The sign up history the plan is built on.",
    "Plan": "Choose a service goal, check the plan, approve it.",
    "Scenario": "Describe a change, check how it was read, run it.",
    "Memo": "A one page memo for each country manager.",
    "Monthly update": "Enter the real numbers, check them, plan the rest of the year.",
    "Decision log": "What was proposed, what changed it, what was applied.",
    "Assistant": "Ask in plain English; every number is checked.",
    "Evaluation": "How each assistant scores, and every recorded run.",
}
# Hover text for sidebar items and buttons, set once the page has loaded.
TIPS = {
    HOME: "Where you are in the year and what to do next",
    "Assistant": "Chat about the plan; follow up questions keep their context",
    "Plan": "Headline numbers, alerts and the month by month plan",
    "Monthly update": "Plan the rest of the year again with the actual sign ups so far",
    "Decision log": "What the optimizer, a language model and the manager each decided",
    "Update the plan": "Keeps the months already done and plans the remaining months again",
    "Score my plan": "Runs your headcount through the same simulator and compares it with the optimized plan",
    "Approve the update": "Saves a CSV named by country, month and time, and logs every change",
    "Scenario": "Test a change, such as fewer sign ups or a hiring cap",
    "Memo": "Write a staffing memo for one country",
    "Data": "Data quality checks and patterns in the sign ups",
    "Evaluation": "Assistant accuracy and the run history",
    "New chat": "Start a conversation with an empty memory",
    "Approve this plan": "Saves a CSV named by country, goal and time, and logs the decision",
    "Read the scenario": "Turns your sentence into scenario parameters you can check and edit",
    "Run the scenario": "Rebuilds the plan with the change and compares it with the current plan",
    "Write the memo": "Writes the memo from the plan's numbers; every number is checked",
    "Save conversation": "Downloads this chat as a Markdown file",
    "Refresh models": "Asks each provider again which models your keys can use",
}
PAGE_JS = """() => {
  const tips = TIPS_JSON;
  const label = (el) => el.textContent.trim();
  const apply = () => {
    document.querySelectorAll('.sp-nav label, button').forEach((el) => {
      const tip = tips[label(el)];
      if (tip && !el.title) el.title = tip;
    });
    // Recent chat titles are cut to one line, so the full question is the hover text.
    document.querySelectorAll('.sp-history label').forEach((el) => { el.title = label(el); });
    document.querySelectorAll('.sp-plot img').forEach((el) => { if (!el.title) el.title = 'Click to enlarge'; });
  };
  apply();
  new MutationObserver(apply).observe(document.body, { childList: true, subtree: true });
  // A chart opens at full size over the page; a click or Escape closes it.
  const close = () => document.querySelectorAll('.sp-zoom').forEach((box) => box.remove());
  document.addEventListener('click', (event) => {
    const chart = event.target.closest('.sp-plot img');
    if (!chart) return;
    const box = document.createElement('div');
    box.className = 'sp-zoom';
    box.innerHTML = '<span>Click or press Escape to close</span>';
    const big = document.createElement('img');
    big.src = chart.src;
    big.alt = 'Chart at full size';
    box.appendChild(big);
    box.addEventListener('click', close);
    document.body.appendChild(box);
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
}""".replace("TIPS_JSON", json.dumps(TIPS))


def page_head(name: str) -> str:
    return components.page_head(name, PAGE_TEXT[name])


def composer_note(spec: str, choices: list[tuple[str, str]]) -> str:
    """The line under the chat box: which model answers, and that its numbers are checked."""
    name = next((label for label, value in choices if value == spec), spec)
    return (
        '<div class="sp-composer-foot"><span>Answered by <b>' + name.replace("<", "") + "</b>. "
        "Change it in Settings.</span><span>Every number is checked against the planner</span></div>"
    )


def refresh_models(current: str):
    choices, default = model_choices(refresh=True)
    values = [value for _, value in choices]
    return gr.Dropdown(choices=choices, value=current if current in values else default)


def build_app(p: Planner | None = None) -> gr.Blocks:
    """Build the interface. Pass a planner to use other data (the tests use synthetic data)."""
    global _PLANNER
    if p is not None:
        _PLANNER = p
        _PILOTS.clear()
    p = planner()
    alerts = plan_alerts(p)
    choices, default_model = model_choices()
    pages: dict[str, gr.Column] = {}
    with gr.Blocks(title="StaffPilot", fill_height=True) as demo:
        chats = gr.State({})
        current = gr.State(None)
        memory = gr.State(None)

        with gr.Sidebar(open=True, width=256, elem_id="sp-sidebar"):
            gr.HTML(components.brand())
            new_btn = gr.Button("New chat", size="sm", elem_classes="sp-new")
            # One hidden list holds the open page; the visible groups only choose from it.
            nav = gr.Radio(PAGES, value=HOME, visible=False)
            groups = []
            for index, (title, names) in enumerate(NAV_GROUPS):
                if title:
                    gr.HTML(f'<div class="sp-nav-group">{title}</div>')
                groups.append(
                    gr.Radio(
                        names,
                        value=HOME if HOME in names else None,
                        show_label=False,
                        container=False,
                        elem_classes=["sp-nav", f"sp-nav-{index}"],
                    )
                )
            gr.HTML(components.section("Recent chats"))
            recent = gr.Radio([], show_label=False, container=False, elem_classes="sp-history")
            gr.HTML(components.history_empty(), elem_classes="sp-history-note")
            with gr.Accordion("Settings", open=False, elem_classes="sp-settings"):
                backend = gr.Dropdown(
                    choices,
                    value=default_model,
                    label="Language model",
                    info="Offline is free; others use your API keys",
                )
                refresh_btn = gr.Button("Refresh models", size="sm")
                gr.Markdown(
                    "Offline needs no key and costs nothing. A chat remembers its last four questions, "
                    "so a follow up such as *And Mexico?* works.",
                    elem_classes="sp-hint",
                )
                export_btn = gr.Button("Save conversation", size="sm")
                saved = gr.File(label="Conversation", visible=False)
            gr.HTML(components.legal())

        with gr.Column(elem_id="sp-main"):
            head = gr.HTML(page_head(HOME))

            def next_row(page: str) -> None:
                target, text = NEXT[page]
                with gr.Row(elem_classes="sp-next-row"):
                    gr.Markdown(text)
                    button = gr.Button(
                        f"Open {target}", size="sm", scale=0, min_width=170, elem_classes="sp-next"
                    )
                button.click(lambda: target, None, nav)

            with gr.Column(visible=True, elem_classes=["sp-page", "sp-home"]) as pages[HOME]:
                verdict = gr.HTML()
                with gr.Column(elem_classes="sp-panel"):
                    rail = gr.HTML()
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        moment = gr.Dropdown(
                            MOMENTS,
                            value=MOMENTS[0],
                            label="Where are you in the year?",
                            info="The steps below follow",
                        )
                        step_text, step_btns = [], []
                        with gr.Column(elem_classes="sp-steps"):
                            for _ in range(4):
                                with gr.Row(elem_classes="sp-step"):
                                    step_text.append(gr.Markdown())
                                    step_btns.append(gr.Button("Open", size="sm", scale=0, min_width=190))
                        step_pages = gr.State([page for _, page in home_steps(MOMENTS[0])])
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        urgent = [a for a in alerts if a.level != "info"]
                        gr.HTML(f'<div class="sp-panel-title">{components.alert_summary(alerts)}</div>')
                        gr.HTML(components.alert_list(urgent))

            with (
                gr.Column(visible=False, elem_classes="sp-page") as pages["Assistant"],
                gr.Row(equal_height=False, elem_classes="sp-chat-row"),
            ):
                with gr.Column(scale=3, min_width=340, elem_classes="sp-panel"):
                    chat = gr.Chatbot(
                        height="calc(100vh - 300px)",
                        min_height=380,
                        show_label=False,
                        placeholder=components.chat_empty(),
                        examples=[{"text": q} for q in EXAMPLES],
                        elem_classes="sp-chat",
                        buttons=["copy"],
                    )
                    box = gr.Textbox(
                        placeholder="Ask about headcount, a change to test, the data or a rule",
                        show_label=False,
                        container=False,
                        submit_btn=True,
                        lines=1,
                        max_lines=6,
                        elem_classes="sp-composer",
                    )
                    composer_foot = gr.HTML(composer_note(default_model, choices))
                with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                    gr.HTML('<div class="sp-panel-title">How this answer was built</div>')
                    details = gr.Markdown(components.trace_empty(), elem_classes="sp-trace")
                    with gr.Accordion("Tool output", open=False, elem_classes="sp-block"):
                        table = gr.Dataframe(show_label=False)
                    with gr.Accordion("How the question was read", open=False, elem_classes="sp-block"):
                        route = gr.Code(language="json", show_label=False)

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Plan"]:
                with gr.Row(elem_classes="sp-toolbar"):
                    pick = gr.Dropdown(
                        ["All countries", *p.countries], value="All countries", label="Country", scale=3
                    )
                    goal = gr.Dropdown(
                        GOALS,
                        value=RECOMMENDED_POLICY,
                        label="Service goal",
                        info="Profit only, or with a service level",
                        scale=3,
                    )
                    approve_btn = gr.Button("Approve this plan", variant="primary", scale=0, min_width=180)
                status = gr.Markdown(elem_classes="sp-note")
                with gr.Tabs(elem_classes="sp-tabs"):
                    with gr.Tab("Overview"):
                        cards = gr.HTML()
                        with gr.Accordion(
                            components.alert_summary(alerts), open=False, elem_classes="sp-alerts"
                        ):
                            gr.HTML(components.alert_list(alerts))
                        with gr.Column(elem_classes="sp-panel"):
                            figure = gr.Plot(show_label=False, elem_classes="sp-plot")
                        with gr.Column(elem_classes="sp-panel"):
                            tradeoff_text = gr.Markdown(elem_classes="sp-prose")
                            tradeoff_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                            with gr.Accordion("Every service goal", open=False, elem_classes="sp-block"):
                                tradeoff_table = gr.Dataframe(show_label=False)
                        with gr.Accordion(
                            "Month by month detail: hires in teal, notices in red",
                            open=False,
                            elem_classes="sp-block",
                        ):
                            plan_table = gr.Dataframe(show_label=False)
                    with gr.Tab("Check the plan"), gr.Column(elem_classes="sp-panel"):
                        check_html = gr.HTML()
                    with gr.Tab("How it is calculated"), gr.Column(elem_classes="sp-panel"):
                        breakdown_text = gr.Markdown(elem_classes="sp-prose")
                        breakdown_table = gr.Dataframe(label="Month by month, from the simulator")
                        breakdown_file = gr.File(label="Download the month by month detail", visible=False)
                    with gr.Tab("Try your own plan"), gr.Row(equal_height=True, elem_classes="sp-even"):
                        with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                            gr.Markdown(
                                "Your headcount for the country above, scored by the same simulator.",
                                elem_classes="sp-note",
                            )
                            manual_percent = gr.Slider(
                                -20, 20, value=-5, step=1, label="Change every month from February (percent)"
                            )
                            manual_table = gr.Dataframe(
                                label="Agents at work",
                                interactive=True,
                                column_count=3,
                                static_columns=[0, 1],
                            )
                            manual_btn = gr.Button("Score my plan", variant="primary")
                        with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                            manual_text = gr.Markdown(
                                "Pick a country, then score your plan.", elem_classes="sp-prose"
                            )
                            manual_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                next_row("Plan")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Monthly update"]:
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        up_country = gr.Dropdown(p.countries, value=p.countries[0], label="Country")
                        up_month = gr.Dropdown(
                            MONTH_NAMES[1:],
                            value=MONTH_NAMES[2],
                            label="Update made in",
                            info="Earlier months are done",
                        )
                        up_percent = gr.Slider(
                            -50,
                            100,
                            value=20,
                            step=5,
                            label="Sign ups so far against the forecast (percent)",
                            info="Fills Actual; edit any cell",
                        )
                        up_actuals = gr.Dataframe(
                            label="Actual eligible sign ups",
                            interactive=True,
                            column_count=3,
                            static_columns=[0, 1],
                        )
                        up_change = gr.Number(
                            0,
                            precision=0,
                            label="Agents on staff against the plan",
                            info="For example -2 after two resignations",
                        )
                        input_check = gr.Markdown(elem_classes="sp-note")
                        with gr.Row():
                            update_btn = gr.Button("Update the plan", variant="primary")
                            approve_update_btn = gr.Button("Approve the update")
                        update_status = gr.Markdown(elem_classes="sp-note")
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        update_summary = gr.Markdown(
                            "Enter the actual sign ups, then update the plan.",
                            elem_classes="sp-prose",
                        )
                        update_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                        update_table = gr.Dataframe(
                            value=pd.DataFrame(
                                columns=["Month", "Status", "Sign ups", "Agents at work", "Hires", "Notices"]
                            ),
                            label="Approved plan → update (forecast → actual for sign ups)",
                        )
                    update_state = gr.State(None)
                next_row("Monthly update")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Scenario"]:
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        text = gr.Textbox(
                            label="Describe the change", value="Sign ups in Germany drop 30% in Q3"
                        )
                        with gr.Row():
                            read_btn = gr.Button("Read the scenario")
                            run_btn = gr.Button("Run the scenario", variant="primary")
                        examples = [
                            gr.Button(example, size="sm", elem_classes="sp-example")
                            for example in SCENARIO_EXAMPLES
                        ]
                        understood = gr.Markdown(elem_classes="sp-note")
                        with gr.Accordion("Edit the parameters", open=False, elem_classes="sp-block"):
                            params = gr.Code(language="json", show_label=False)
                        proposal = gr.State({})
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        summary = gr.Markdown(
                            "Read a scenario, then run it.",
                            elem_classes="sp-prose",
                        )
                        scenario_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                        diff = gr.Dataframe(
                            value=pd.DataFrame(
                                columns=[
                                    "Country",
                                    "Agents now",
                                    "Agents with change",
                                    "Net value change",
                                ]
                            ),
                            label="Current plan against the scenario",
                        )
                next_row("Scenario")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Memo"]:
                with gr.Row(elem_classes="sp-toolbar"):
                    memo_country = gr.Dropdown(p.countries, value=p.countries[0], label="Country", scale=3)
                    memo_btn = gr.Button("Write the memo", variant="primary", scale=0, min_width=180)
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_text = gr.Markdown("Pick a country and write its memo.", elem_classes="sp-prose")
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                next_row("Memo")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Data"]:
                findings = gr.HTML()
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        trend = gr.Plot(show_label=False, elem_classes="sp-plot")
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        need = gr.Plot(show_label=False, elem_classes="sp-plot")
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        season = gr.Plot(show_label=False, elem_classes="sp-plot")
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        budgets = gr.Plot(show_label=False, elem_classes="sp-plot")
                with gr.Column(elem_classes="sp-panel"):
                    gr.HTML('<div class="sp-panel-title">Data quality</div>')
                    quality = gr.HTML()
                    with gr.Accordion("Every check, as a table", open=False, elem_classes="sp-block"):
                        quality_table = gr.Dataframe(show_label=False)
                next_row("Data")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Evaluation"]:
                with gr.Column(elem_classes="sp-panel"):
                    gr.HTML('<div class="sp-panel-title">Assistants</div>')
                    eval_lead = gr.Markdown(elem_classes="sp-prose")
                    eval_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                    with gr.Accordion(
                        "Every score: best per test set in teal", open=False, elem_classes="sp-block"
                    ):
                        eval_summary = gr.Dataframe(show_label=False)
                with gr.Row(equal_height=True, elem_classes="sp-even"):
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        gr.HTML('<div class="sp-panel-title">Rule retrieval</div>')
                        retrieval_facts = gr.HTML()
                        with gr.Accordion("Every rule question", open=False, elem_classes="sp-block"):
                            eval_retrieval = gr.Dataframe(show_label=False)
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        gr.HTML('<div class="sp-panel-title">Plan runs</div>')
                        run_facts = gr.HTML()
                        with gr.Accordion("Run history: latest in teal", open=False, elem_classes="sp-block"):
                            runs = gr.Dataframe(show_label=False)

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Decision log"]:
                with gr.Column(elem_classes="sp-panel"):
                    gr.Markdown(
                        "**Proposed** by the optimizer, forecast or a language model; **adjusted** by a check or "
                        "by you; **applied**. Staffing numbers always come from the planner.",
                        elem_classes="sp-note",
                    )
                    log_summary = gr.HTML()
                    log_filter = gr.Radio(
                        LOG_FILTERS,
                        value=LOG_FILTERS[0],
                        show_label=False,
                        container=False,
                        elem_classes="sp-filter",
                    )
                    gr.Markdown(
                        "Changed values in amber; proposals by a language model in teal.",
                        elem_classes="sp-note",
                    )
                    log_table = gr.Dataframe(show_label=False)
                    log_file = gr.File(label="decision_audit.csv", visible=False)
                next_row("Decision log")

        # Navigation and conversations
        demo.load(None, None, None, js=PAGE_JS)
        demo.load(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        for control in (*groups, recent):
            control.input(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        for group in groups:
            group.input(lambda name: name, group, nav)
        nav.change(nav_sync, nav, groups)
        new_btn.click(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        nav.change(show_page, nav, [pages[name] for name in PAGES]).then(page_head, nav, head)
        chat_out = [chat, box, details, table, route, memory, chats, current, recent]
        box.submit(send, [box, chat, backend, memory, chats, current], chat_out)
        chat.example_select(example_text, None, box).then(
            send, [box, chat, backend, memory, chats, current], chat_out
        )
        new_btn.click(start_chat, chats, chat_out).then(lambda: "Assistant", None, nav)
        recent.input(open_chat, [recent, chats], [chat, memory, current]).then(lambda: "Assistant", None, nav)
        export_btn.click(export_conversation, memory, saved)
        refresh_btn.click(refresh_models, backend, backend)
        backend.change(lambda spec: composer_note(spec, model_choices()[0]), backend, composer_foot)

        # Pages. Data and evaluation tables load when their page is first opened.
        for control in (pick, goal):
            control.change(plan_view, [pick, goal], [cards, figure, plan_table])
            control.change(check_view, [pick, goal], check_html)
            control.change(breakdown_view, [pick, goal], [breakdown_text, breakdown_table, breakdown_file])
            control.change(manual_inputs, [pick, goal, manual_percent], manual_table)
        manual_percent.change(manual_inputs, [pick, goal, manual_percent], manual_table)
        manual_btn.click(manual_score, [pick, goal, manual_table], [manual_text, manual_plot])
        goal.change(tradeoff_view, goal, [tradeoff_text, tradeoff_plot, tradeoff_table])
        approve_btn.click(approve, [pick, goal], status)
        for control in (up_country, up_month, up_percent):
            control.change(actual_inputs, [up_country, up_month, up_percent], up_actuals)
        for control in (up_actuals, up_change):
            control.change(check_inputs, [up_country, up_month, up_actuals, up_change], input_check)
        home_out = [verdict, rail, *step_text, *step_btns, step_pages, up_month]
        for control in (moment, goal):
            control.change(home_view, [moment, goal], home_out)
        demo.load(home_view, [moment, goal], home_out)
        nav.change(home_if_open, [nav, moment, goal], home_out)
        for i, button in enumerate(step_btns):
            button.click(lambda pages_, i=i: pages_[i], step_pages, nav)
        update_btn.click(
            update_view,
            [up_country, up_month, up_actuals, up_change, goal],
            [update_summary, update_plot, update_table, update_state],
        )
        approve_update_btn.click(approve_update, update_state, update_status).then(
            check_inputs, [up_country, up_month, up_actuals, up_change], input_check
        )
        read_btn.click(parse_scenario, [text, backend], [params, understood, proposal])
        for example, sentence in zip(examples, SCENARIO_EXAMPLES, strict=True):
            example.click(lambda s=sentence: s, None, text).then(
                parse_scenario, [text, backend], [params, understood, proposal]
            ).then(run_scenario, [params, proposal], [summary, scenario_plot, diff])
        # The page opens with the first example already read and run; this preview is not a decision.
        demo.load(parse_scenario, [text, backend], [params, understood, proposal]).then(
            lambda pj, pr: run_scenario(pj, pr, record=False),
            [params, proposal],
            [summary, scenario_plot, diff],
        )
        run_btn.click(run_scenario, [params, proposal], [summary, scenario_plot, diff])
        memo_btn.click(memo, [memo_country, backend], [memo_text, memo_plot])
        memo_seen = gr.State(False)
        nav.change(open_memo, [nav, memo_seen, memo_country, backend], [memo_seen, memo_text, memo_plot])
        demo.load(plan_view, [pick, goal], [cards, figure, plan_table])
        demo.load(check_view, [pick, goal], check_html)
        demo.load(breakdown_view, [pick, goal], [breakdown_text, breakdown_table, breakdown_file])
        demo.load(tradeoff_view, goal, [tradeoff_text, tradeoff_plot, tradeoff_table])
        # The page opens with the default inputs already worked through, so it is never empty.
        demo.load(actual_inputs, [up_country, up_month, up_percent], up_actuals).then(
            update_view,
            [up_country, up_month, up_actuals, up_change, goal],
            [update_summary, update_plot, update_table, update_state],
        )
        nav.change(open_log, [nav, log_filter], [log_summary, log_table, log_file])
        log_filter.change(log_view, log_filter, [log_summary, log_table, log_file])
        loaded = gr.State(set())
        data_out = [findings, trend, need, season, budgets, quality, quality_table]
        eval_out = [eval_lead, eval_plot, eval_summary, retrieval_facts, eval_retrieval, run_facts, runs]
        nav.change(load_page, [nav, loaded], [loaded, *data_out, *eval_out])
    return demo


def open_memo(name: str, seen: bool, country: str, backend: str):
    """Write the memo for the chosen country the first time the page opens, so it is never empty."""
    if name != "Memo" or seen:
        return seen, gr.update(), gr.update()
    return True, *memo(country, backend)


def open_log(name: str, choice: str = "All decisions"):
    """The decision log is read again each time its page opens, since every approval adds to it."""
    if name != "Decision log":
        return gr.update(), gr.update(), gr.update()
    return log_view(choice)


def load_page(name: str, loaded: set):
    """Fill the Data or Evaluation page the first time it is opened; later visits keep what is shown."""
    keep = [gr.update()] * 7
    if name in loaded or name not in {"Data", "Evaluation"}:
        return loaded, *keep, *keep
    loaded = {*loaded, name}
    if name == "Data":
        return loaded, *eda_view(), *keep
    return loaded, *keep, *eval_view()


def favicon() -> str | None:
    """The browser tab icon, drawn from the same mark as the sidebar."""
    for folder in (cache.folder(), Path(tempfile.gettempdir()) / "staffpilot"):
        try:
            return str(icon.write_png(folder / "favicon.png"))
        except OSError:
            continue
    return None


def launch(port: int = 7860) -> None:
    css = CSS + "\n" + icon.nav_css(NAV_GROUPS)
    build_app().launch(server_port=port, share=False, theme=theme(), css=css, favicon_path=favicon())
