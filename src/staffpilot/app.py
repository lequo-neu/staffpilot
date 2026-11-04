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
from staffpilot.agent.memory import Conversation, describe
from staffpilot.alerts import plan_alerts
from staffpilot.cli import EVAL_DIR, OUTPUTS
from staffpilot.eda import budget_figure, figures, profile
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
    "Data": ("Plan", "Next: choose the service goal, check the plan and approve it."),
    "Plan": ("Scenario", "Next: stress test the plan before the year starts."),
    "Scenario": ("Memo", "Next: brief each country manager."),
    "Memo": (HOME, "The plan for the year is ready. Each month, start from This year."),
    "Monthly update": ("Decision log", "Next: see what the update changed, month by month."),
    "Decision log": (HOME, "Back to the year at a glance."),
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
    return plan_kpis(p, chosen, goal), components.sharp(figure), _readable(shown)


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


def approve(country: str, goal: str = RECOMMENDED_POLICY) -> str:
    bundle = planner().run(goal)
    plan = bundle.plan_table()
    countries = list(bundle.outcomes)
    if country != "All countries":
        plan, countries = plan[plan["country"] == country], [country]
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / "approved_plan.csv"
    plan.to_csv(path, index=False)
    rows = audit.plan_rows(bundle, countries, GOAL_NAMES[goal], GOAL_NAMES[RECOMMENDED_POLICY])
    audit.record(rows, OUTPUTS)
    log.info("Plan approved for %s with goal %s (%d rows)", country, goal, len(plan))
    return (
        f"Approved with the goal *{GOAL_NAMES[goal]}*. {len(plan)} rows saved to `{path.name}` and "
        f"{len(rows)} rows added to the decision log. Nothing is sent to anyone until a manager acts on it."
    )


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
            ("**1. Check the data.** See how clean the sign up history is and when demand peaks.", "Data"),
            (
                (
                    "**2. Choose the service goal and approve the plan.** Read the checks first: every rule is "
                    "tested with its numbers, and you can score a headcount of your own."
                ),
                "Plan",
            ),
            (
                "**3. Stress test it.** Try fewer sign ups in the peak, a hiring cap or a lower threshold.",
                "Scenario",
            ),
            ("**4. Brief the countries.** Write a one page memo for each country manager.", "Memo"),
        ]
    month, before = MONTH_NAMES[now - 1], MONTH_NAMES[now - 2]
    upcoming = MONTH_NAMES[min(now, 11)]
    done = {2: "January", 3: "January and February"}.get(now, f"January to {before}")
    return [
        (
            (
                f"**1. Enter what happened.** Type the actual eligible sign ups for {done} and the agents on staff, "
                f"check them, then plan {month} to December again."
            ),
            "Monthly update",
        ),
        (
            "**2. See what changed.** The decision log lists every month the update moved, and why.",
            "Decision log",
        ),
        (
            f"**3. Ask why.** For example: How many agents does Germany need in {upcoming} and why?",
            "Assistant",
        ),
        ("**4. Test what could come next.** What if sign ups keep running above the forecast?", "Scenario"),
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
        components.year_rail(p.year, months),
        *[text for text, _ in steps],
        *[gr.Button(value=f"Open {page}") for _, page in steps],
        [page for _, page in steps],
        month,
    )


def home_if_open(name: str, moment: str, goal: str):
    """Refresh This year when it is opened, since an approval elsewhere may have changed it."""
    return home_view(moment, goal) if name == HOME else [gr.update()] * 11


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
    path = OUTPUTS / "approved_update.csv"
    update.table().assign(country=update.country).to_csv(path, index=False)
    _APPROVED[update.country] = update
    rows = audit.update_rows(update)
    audit.record(rows, OUTPUTS)
    log.info("Monthly update approved for %s in month %d", update.country, update.as_of)
    return f"Approved. The updated plan is saved to `{path.name}` and {len(rows)} rows are added to the decision log."


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
    return json.dumps(proposal["params"], indent=2), f"Understood as: {params.plain()}.", proposal


def run_scenario(params_json: str, proposal: dict | None = None):
    try:
        params = ScenarioParams.model_validate_json(params_json)
    except ValueError as error:
        return f"Those parameters are not valid: {error}", None, pd.DataFrame()
    p = planner()
    result = p.scenario(params)
    t = result.totals()
    proposal = proposal or {}
    proposed = ScenarioParams.model_validate(proposal["params"]) if proposal.get("params") else None
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
    columns = [
        "country",
        "avg_active_base",
        "avg_active_scenario",
        "net_value_base",
        "net_value_scenario",
        "net_value_change",
        "service_rate_base",
        "service_rate_scenario",
    ]
    return summary, components.sharp(figure), _readable(result.comparison[columns])


def memo(country: str, backend: str):
    answer = pilot(backend).memo(country)
    check = (
        "Every number matches the planner."
        if answer.verified
        else f"Number check flagged {answer.unsupported}."
    )
    return f"{answer.text}\n\n*{check}*", components.sharp(answer.chart)


def eda_view():
    p = planner()
    report = profile(p.dataset, p.settings.rules.capacity_per_agent)
    figs = figures(report)
    findings = "\n".join(f"* {f}" for f in report.findings)
    return (
        findings,
        components.sharp(figs["monthly_trend"]),
        components.sharp(figs["staff_vs_need"]),
        components.sharp(figs["seasonality_heatmap"]),
        components.sharp(budget_figure(p.dataset)),
        report.quality,
    )


def eval_tables():
    from staffpilot.tracking import history

    results = EVAL_DIR / "results"
    summary = (
        pd.read_csv(results / "summary.csv").round(3)
        if (results / "summary.csv").exists()
        else pd.DataFrame({"note": ["Run: python -m staffpilot eval"]})
    )
    retrieval = (
        pd.read_csv(results / "retrieval.csv") if (results / "retrieval.csv").exists() else pd.DataFrame()
    )
    return summary, retrieval, history(15)


PAGE_TEXT = {
    HOME: "Where you are in the staffing year, and what to do next.",
    "Data": "Before the year starts: how clean the sign up history is and the patterns the plan is built on.",
    "Plan": "Before the year starts: choose a service goal, check the plan, then approve it.",
    "Scenario": "Before or during the year: describe a change in words, check how it was read, then run it.",
    "Memo": "Before the year starts: a one page staffing memo for each country manager.",
    "Monthly update": "Every month: enter the real numbers so far, check them, and plan the remaining months again.",
    "Decision log": "Every month: what was proposed, what changed it and what was applied.",
    "Assistant": "Any time: ask in plain English. Each answer shows its chart and how it was worked out.",
    "Evaluation": "Behind the numbers: how each assistant scored on labelled questions, and every recorded run.",
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
    "Approve the update": "Saves the updated plan and records every change in the decision log",
    "Scenario": "Test a change, such as fewer sign ups or a hiring cap",
    "Memo": "Write a staffing memo for one country",
    "Data": "Data quality checks and patterns in the sign ups",
    "Evaluation": "Assistant accuracy and the run history",
    "New chat": "Start a conversation with an empty memory",
    "Approve this plan": "Saves the plan to outputs/approved_plan.csv and logs the decision; nothing is sent",
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
  };
  apply();
  new MutationObserver(apply).observe(document.body, { childList: true, subtree: true });
}""".replace("TIPS_JSON", json.dumps(TIPS))


def page_head(name: str) -> str:
    return components.page_head(name, PAGE_TEXT[name])


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
            for title, names in NAV_GROUPS:
                if title:
                    gr.HTML(f'<div class="sp-nav-group">{title}</div>')
                groups.append(
                    gr.Radio(
                        names,
                        value=HOME if HOME in names else None,
                        show_label=False,
                        container=False,
                        elem_classes="sp-nav",
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
                    info="Offline is free. The models below come from your API keys, cheapest first.",
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
                with gr.Column(elem_classes="sp-panel"):
                    rail = gr.HTML()
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        moment = gr.Dropdown(
                            MOMENTS,
                            value=MOMENTS[0],
                            label="Where are you in the year?",
                            info="Pick the month you are deciding in; the steps below follow",
                        )
                        step_text, step_btns = [], []
                        with gr.Column(elem_classes="sp-steps"):
                            for _ in range(4):
                                with gr.Row(elem_classes="sp-step"):
                                    step_text.append(gr.Markdown())
                                    step_btns.append(gr.Button("Open", size="sm", scale=0, min_width=190))
                        step_pages = gr.State([page for _, page in home_steps(MOMENTS[0])])
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        gr.HTML('<div class="sp-panel-title">Which page for which moment</div>')
                        gr.HTML(components.cycle())

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
                    gr.HTML(
                        '<div class="sp-composer-foot"><span>Press Enter to send. Shift and Enter adds a line.</span>'
                        "<span>Numbers are checked against the planner</span></div>"
                    )
                with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                    gr.HTML('<div class="sp-panel-title">How this answer was built</div>')
                    details = gr.Markdown(components.trace_empty(), elem_classes="sp-trace")
                    with gr.Accordion("Tool output", open=False, elem_classes="sp-block"):
                        table = gr.Dataframe(show_label=False, wrap=True)
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
                        info="Profit only, or profit with a service level for advertisers",
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
                                tradeoff_table = gr.Dataframe(show_label=False, wrap=True)
                        with gr.Column(elem_classes="sp-panel"):
                            plan_table = gr.Dataframe(label="Month by month", wrap=True)
                    with gr.Tab("Check the plan"), gr.Column(elem_classes="sp-panel"):
                        check_html = gr.HTML()
                    with gr.Tab("How it is calculated"), gr.Column(elem_classes="sp-panel"):
                        breakdown_text = gr.Markdown(elem_classes="sp-prose")
                        breakdown_table = gr.Dataframe(label="Month by month, from the simulator", wrap=True)
                        breakdown_file = gr.File(label="Download the month by month detail", visible=False)
                    with gr.Tab("Try your own plan"), gr.Row(equal_height=False):
                        with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                            gr.Markdown(
                                "Type the agents you would keep in each month of the country picked above, "
                                "or change every month at once. The same simulator scores your plan.",
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
                                "Pick a country above, then score your plan.", elem_classes="sp-prose"
                            )
                            manual_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                next_row("Plan")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Monthly update"]:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        up_country = gr.Dropdown(p.countries, value=p.countries[0], label="Country")
                        up_month = gr.Dropdown(
                            MONTH_NAMES[1:],
                            value=MONTH_NAMES[2],
                            label="Update made in",
                            info="The months before it are done and keep their decisions",
                        )
                        up_percent = gr.Slider(
                            -50,
                            100,
                            value=20,
                            step=5,
                            label="Sign ups so far against the forecast (percent)",
                            info="Fills the Actual column; edit any month by hand",
                        )
                        up_actuals = gr.Dataframe(
                            label="Actual eligible sign ups",
                            interactive=True,
                            wrap=True,
                            column_count=3,
                            static_columns=[0, 1],
                        )
                        up_change = gr.Number(
                            0,
                            precision=0,
                            label="Agents on staff against the plan",
                            info="For example -2 when two agents resigned",
                        )
                        input_check = gr.Markdown(elem_classes="sp-note")
                        with gr.Row():
                            update_btn = gr.Button("Update the plan", variant="primary")
                            approve_update_btn = gr.Button("Approve the update")
                        update_status = gr.Markdown(elem_classes="sp-note")
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        update_summary = gr.Markdown(
                            "Enter the actual sign ups so far, then update the plan. The approved plan's decisions "
                            "in the months already done stay as they were.",
                            elem_classes="sp-prose",
                        )
                        update_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                        update_table = gr.Dataframe(
                            value=pd.DataFrame(
                                columns=["Month", "Status", "Sign ups", "Agents at work", "Hires", "Notices"]
                            ),
                            label="Approved plan → update (forecast → actual for sign ups)",
                            wrap=True,
                        )
                    update_state = gr.State(None)
                next_row("Monthly update")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Scenario"]:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                        text = gr.Textbox(
                            label="Describe the change", value="Sign ups in Germany drop 30% in Q3"
                        )
                        with gr.Row():
                            read_btn = gr.Button("Read the scenario")
                            run_btn = gr.Button("Run the scenario", variant="primary")
                        understood = gr.Markdown(elem_classes="sp-note")
                        params = gr.Code(language="json", label="Parameters, which you can edit")
                        proposal = gr.State({})
                    with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                        summary = gr.Markdown(
                            "Read a scenario, then run it to compare it with the current plan.",
                            elem_classes="sp-prose",
                        )
                        scenario_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                        diff = gr.Dataframe(
                            value=pd.DataFrame(
                                columns=[
                                    "Country",
                                    "Net value base",
                                    "Net value scenario",
                                    "Net value change",
                                ]
                            ),
                            label="Current plan against the scenario",
                            wrap=True,
                        )
                next_row("Scenario")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Memo"]:
                with gr.Row(elem_classes="sp-toolbar"):
                    memo_country = gr.Dropdown(p.countries, value=p.countries[0], label="Country", scale=3)
                    memo_btn = gr.Button("Write the memo", variant="primary", scale=0, min_width=180)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_text = gr.Markdown("Pick a country and write its memo.", elem_classes="sp-prose")
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                next_row("Memo")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Data"]:
                with gr.Column(elem_classes="sp-panel"):
                    findings = gr.Markdown(elem_classes="sp-prose")
                with gr.Row():
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        trend = gr.Plot(show_label=False, elem_classes="sp-plot")
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        need = gr.Plot(show_label=False, elem_classes="sp-plot")
                with gr.Row():
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        season = gr.Plot(show_label=False, elem_classes="sp-plot")
                    with gr.Column(elem_classes="sp-panel", min_width=320):
                        budgets = gr.Plot(show_label=False, elem_classes="sp-plot")
                with gr.Column(elem_classes="sp-panel"):
                    quality = gr.Dataframe(label="Data quality checks")
                next_row("Data")

            with (
                gr.Column(visible=False, elem_classes="sp-page") as pages["Evaluation"],
                gr.Column(elem_classes="sp-panel"),
            ):
                gr.Markdown(
                    "Scores on 40 labelled questions, a 32 question holdout and 10 follow ups, then retrieval "
                    "hits on rule questions and the run history.",
                    elem_classes="sp-note",
                )
                eval_summary = gr.Dataframe(label="Assistants")
                eval_retrieval = gr.Dataframe(label="Retrieval")
                runs = gr.Dataframe(label="Runs")

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Decision log"]:
                with gr.Column(elem_classes="sp-panel"):
                    gr.Markdown(
                        "Each row keeps apart what was **proposed** (by the optimizer, the forecast or a language "
                        "model reading your words), what **adjusted** it (the simulator check, a monthly update, "
                        "a GenAI guardrail or you) and what was finally **applied**. No language model writes a "
                        "staffing number: numbers come from the planner.",
                        elem_classes="sp-note",
                    )
                    log_summary = gr.Markdown(elem_classes="sp-note")
                    log_table = gr.Dataframe(show_label=False, wrap=True)
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
        home_out = [rail, *step_text, *step_btns, step_pages, up_month]
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
        run_btn.click(run_scenario, [params, proposal], [summary, scenario_plot, diff])
        memo_btn.click(memo, [memo_country, backend], [memo_text, memo_plot])
        demo.load(plan_view, [pick, goal], [cards, figure, plan_table])
        demo.load(check_view, [pick, goal], check_html)
        demo.load(breakdown_view, [pick, goal], [breakdown_text, breakdown_table, breakdown_file])
        demo.load(tradeoff_view, goal, [tradeoff_text, tradeoff_plot, tradeoff_table])
        demo.load(actual_inputs, [up_country, up_month, up_percent], up_actuals)
        nav.change(open_log, nav, [log_summary, log_table, log_file])
        loaded = gr.State(set())
        nav.change(
            load_page,
            [nav, loaded],
            [loaded, findings, trend, need, season, budgets, quality, eval_summary, eval_retrieval, runs],
        )
    return demo


def open_log(name: str):
    """The decision log is read again each time its page opens, since every approval adds to it."""
    if name != "Decision log":
        return gr.update(), gr.update(), gr.update()
    frame = audit.read(OUTPUTS, 500)
    path = OUTPUTS / audit.FILE_NAME
    return (
        audit.summary(frame),
        frame,
        gr.File(value=str(path) if path.exists() else None, visible=path.exists()),
    )


def load_page(name: str, loaded: set):
    """Fill the Data or Evaluation page the first time it is opened; later visits keep what is shown."""
    keep = [gr.update()] * 9
    if name in loaded or name not in {"Data", "Evaluation"}:
        return loaded, *keep
    loaded = {*loaded, name}
    if name == "Data":
        return loaded, *eda_view(), *keep[:3]
    return loaded, *keep[:6], *eval_tables()


def favicon() -> str | None:
    """The browser tab icon, drawn from the same mark as the sidebar."""
    for folder in (cache.folder(), Path(tempfile.gettempdir()) / "staffpilot"):
        try:
            return str(icon.write_png(folder / "favicon.png"))
        except OSError:
            continue
    return None


def launch(port: int = 7860) -> None:
    build_app().launch(server_port=port, share=False, theme=theme(), css=CSS, favicon_path=favicon())
