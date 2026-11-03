"""Gradio app: a planning desk for support staffing managers ("Ledger" design).

A sidebar holds the pages (Assistant, Plan, Scenario, Memo, Data, Evaluation), the
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
import pandas as pd

from staffpilot import cache, charts
from staffpilot.agent import StaffPilot
from staffpilot.agent.catalog import usable_models, working_default
from staffpilot.agent.memory import Conversation, describe
from staffpilot.alerts import plan_alerts
from staffpilot.cli import EVAL_DIR, OUTPUTS
from staffpilot.eda import budget_figure, figures, profile
from staffpilot.planner import RECOMMENDED_POLICY, Planner
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
PAGES = ["Assistant", "Plan", "Scenario", "Memo", "Data", "Evaluation"]
# On a phone the sidebar covers the screen, so it starts closed and closes again after a choice.
CLOSE_SIDEBAR_ON_PHONE = """() => {
  if (window.innerWidth < 769) {
    const toggle = document.querySelector('.sidebar.open .toggle-button');
    if (toggle) toggle.click();
  }
}"""

_PLANNER: Planner | None = None
_PILOTS: dict[str, StaffPilot] = {}


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


def plan_kpis(p: Planner, country: str | None = None) -> str:
    """KPI cards with a monthly sparkline, each compared with keeping the January team all year."""
    bundle, hold = p.run(RECOMMENDED_POLICY), p.run("hold")
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
            f"They wait {t['mean_wait_days']:.1f} days on average; one in ten waits over {t['p90_wait_days']:.0f}.",
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
    )


def ask(message: str, history: list, backend: str, memory: Conversation | None = None):
    """Answer one message. Returns the chat, the cleared box, the trace, chart, table, route and memory."""
    # Each conversation has its own memory, kept in the browser tab's state.
    memory = memory or Conversation()
    if not message.strip():
        return history, "", components.trace_empty(), None, pd.DataFrame(), "{}", memory
    answer = pilot(backend).ask(message, memory)
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


def plan_view(country: str):
    p = planner()
    bundle = p.run(RECOMMENDED_POLICY)
    plan, monthly = bundle.plan_table(), bundle.monthly_table()
    monthly = monthly[monthly["month_index"] <= 12]
    chosen = None if country == "All countries" else country
    if chosen:
        plan, monthly = plan[plan["country"] == chosen], monthly[monthly["country"] == chosen]
    figure = charts.headcount(
        plan, monthly, f"{country}: recommended headcount for {p.year}", p.settings.rules.capacity_per_agent
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
    return plan_kpis(p, chosen), components.sharp(figure), _readable(shown)


def approve(country: str) -> str:
    plan = planner().run(RECOMMENDED_POLICY).plan_table()
    if country != "All countries":
        plan = plan[plan["country"] == country]
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / "approved_plan.csv"
    plan.to_csv(path, index=False)
    log.info("Plan approved for %s (%d rows)", country, len(plan))
    return f"Approved. {len(plan)} rows saved to `{path.name}`. Nothing is sent to anyone until a manager acts on it."


def parse_scenario(text: str, backend: str) -> tuple[str, str]:
    route, _ = pilot(backend).route(text)
    if route.scenario is None and not route.clarification:
        route, _ = pilot(backend).route(f"What if {text}")
    if route.clarification:
        return "{}", route.clarification
    params = route.scenario or ScenarioParams(countries=route.countries)
    return json.dumps(params.model_dump(mode="json"), indent=2), f"Understood as: {params.plain()}."


def run_scenario(params_json: str):
    try:
        params = ScenarioParams.model_validate_json(params_json)
    except ValueError as error:
        return f"Those parameters are not valid: {error}", None, pd.DataFrame()
    p = planner()
    result = p.scenario(params)
    t = result.totals()
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
    "Assistant": "Ask in plain English. Each answer shows its chart and how it was worked out.",
    "Plan": "Headcount month by month for the planning year. Approve it when it looks right.",
    "Scenario": "Describe a change in words, check how it was read, then run it against the plan.",
    "Memo": "A one page staffing memo for a country manager.",
    "Data": "How clean the sign up history is and the patterns the plan is built on.",
    "Evaluation": "How each assistant scored on labelled questions, and every recorded run.",
}
# Hover text for sidebar items and buttons, set once the page has loaded.
TIPS = {
    "Assistant": "Chat about the plan; follow up questions keep their context",
    "Plan": "Headline numbers, alerts and the month by month plan",
    "Scenario": "Test a change, such as fewer sign ups or a hiring cap",
    "Memo": "Write a staffing memo for one country",
    "Data": "Data quality checks and patterns in the sign ups",
    "Evaluation": "Assistant accuracy and the run history",
    "New chat": "Start a conversation with an empty memory",
    "Approve this plan": "Saves the plan to outputs/approved_plan.csv; nothing is sent to anyone",
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
            nav = gr.Radio(PAGES, value=PAGES[0], show_label=False, container=False, elem_classes="sp-nav")
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
            head = gr.HTML(page_head(PAGES[0]))

            with (
                gr.Column(visible=True, elem_classes="sp-page") as pages["Assistant"],
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
                    approve_btn = gr.Button("Approve this plan", variant="primary", scale=0, min_width=180)
                cards = gr.HTML()
                status = gr.Markdown(elem_classes="sp-note")
                with gr.Accordion(components.alert_summary(alerts), open=False, elem_classes="sp-alerts"):
                    gr.HTML(components.alert_list(alerts))
                with gr.Column(elem_classes="sp-panel"):
                    figure = gr.Plot(show_label=False, elem_classes="sp-plot")
                with gr.Column(elem_classes="sp-panel"):
                    plan_table = gr.Dataframe(label="Month by month", wrap=True)

            with (
                gr.Column(visible=False, elem_classes="sp-page") as pages["Scenario"],
                gr.Row(equal_height=False),
            ):
                with gr.Column(scale=2, min_width=300, elem_classes="sp-panel"):
                    text = gr.Textbox(label="Describe the change", value="Sign ups in Germany drop 30% in Q3")
                    with gr.Row():
                        read_btn = gr.Button("Read the scenario")
                        run_btn = gr.Button("Run the scenario", variant="primary")
                    understood = gr.Markdown(elem_classes="sp-note")
                    params = gr.Code(language="json", label="Parameters, which you can edit")
                with gr.Column(scale=3, min_width=320, elem_classes="sp-panel"):
                    summary = gr.Markdown(
                        "Read a scenario, then run it to compare it with the current plan.",
                        elem_classes="sp-prose",
                    )
                    scenario_plot = gr.Plot(show_label=False, elem_classes="sp-plot")
                    diff = gr.Dataframe(label="Current plan against the scenario", wrap=True)

            with gr.Column(visible=False, elem_classes="sp-page") as pages["Memo"]:
                with gr.Row(elem_classes="sp-toolbar"):
                    memo_country = gr.Dropdown(p.countries, value=p.countries[0], label="Country", scale=3)
                    memo_btn = gr.Button("Write the memo", variant="primary", scale=0, min_width=180)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_text = gr.Markdown("Pick a country and write its memo.", elem_classes="sp-prose")
                    with gr.Column(scale=1, min_width=320, elem_classes="sp-panel"):
                        memo_plot = gr.Plot(show_label=False, elem_classes="sp-plot")

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

        # Navigation and conversations
        demo.load(None, None, None, js=PAGE_JS)
        demo.load(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        for control in (nav, recent):
            control.input(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        new_btn.click(None, None, None, js=CLOSE_SIDEBAR_ON_PHONE)
        nav.change(show_page, nav, [pages[name] for name in PAGES]).then(page_head, nav, head)
        chat_out = [chat, box, details, table, route, memory, chats, current, recent]
        box.submit(send, [box, chat, backend, memory, chats, current], chat_out)
        chat.example_select(example_text, None, box).then(
            send, [box, chat, backend, memory, chats, current], chat_out
        )
        new_btn.click(start_chat, chats, chat_out).then(lambda: PAGES[0], None, nav)
        recent.input(open_chat, [recent, chats], [chat, memory, current]).then(lambda: PAGES[0], None, nav)
        export_btn.click(export_conversation, memory, saved)
        refresh_btn.click(refresh_models, backend, backend)

        # Pages. Data and evaluation tables load when their page is first opened.
        pick.change(plan_view, pick, [cards, figure, plan_table])
        approve_btn.click(approve, pick, status)
        read_btn.click(parse_scenario, [text, backend], [params, understood])
        run_btn.click(run_scenario, params, [summary, scenario_plot, diff])
        memo_btn.click(memo, [memo_country, backend], [memo_text, memo_plot])
        demo.load(plan_view, pick, [cards, figure, plan_table])
        loaded = gr.State(set())
        nav.change(
            load_page,
            [nav, loaded],
            [loaded, findings, trend, need, season, budgets, quality, eval_summary, eval_retrieval, runs],
        )
    return demo


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
