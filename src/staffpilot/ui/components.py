"""Small HTML pieces shared by the pages. Each returns a string for `gr.HTML`.

Text is escaped here, so callers can pass data from the planner or the user directly.
Elements given a tooltip (see `tip`) show their text on hover and on keyboard focus.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
import html
import io

from gradio.components.plot import PlotData
from matplotlib.figure import Figure

from staffpilot import COPYRIGHT, SLOGAN, TEAM
from staffpilot.alerts import Alert
from staffpilot.ui import icon


LEVEL_NAMES = {"critical": "Critical", "warning": "Warning", "info": "Note"}
# Charts reach the browser at twice their layout resolution so they stay sharp on
# high density screens and when a panel scales them up.
WEB_DPI = 300


def sharp(fig: Figure | None) -> PlotData | None:
    """A chart for `gr.Plot`, as lossless PNG at WEB_DPI.

    Gradio's default is lossy WebP at the figure's own resolution (110 dpi here), which
    looks soft on a laptop screen. Only the copy sent to the browser changes; the figure
    keeps its size for the notebook and the saved files.
    """
    if fig is None:
        return None
    with io.BytesIO() as buffer:
        fig.savefig(buffer, format="png", dpi=WEB_DPI, facecolor="white")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return PlotData(type="matplotlib", plot=f"data:image/png;base64,{encoded}")


@dataclass
class Kpi:
    label: str
    value: str
    tip: str  # what the number means, shown on hover
    delta: str = ""  # for example "29.5%"
    trend: str = ""  # "up" or "down": the arrow shows which way the number moved
    tone: str = ""  # "good" or "bad": the colour says whether that is welcome
    comparison: str = ""  # for example "more than keeping the January team"
    series: Sequence[float] = field(default_factory=list)  # one value per month, for the sparkline


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def tip(text: str, label: str = "i") -> str:
    """A small focusable marker that explains the item next to it."""
    return f'<span class="sp-info" tabindex="0" role="note" aria-label="{_e(text)}" data-tip="{_e(text)}">{_e(label)}</span>'


def sparkline(values: Sequence[float], width: int = 84, height: int = 30) -> str:
    """Inline SVG line of the monthly values; the last month is marked."""
    points = [float(v) for v in values]
    if len(points) < 2:
        return ""
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    step = (width - 4) / (len(points) - 1)
    coords = [(2 + i * step, height - 3 - (v - low) / span * (height - 6)) for i, v in enumerate(points)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    x, y = coords[-1]
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<polyline points="{path}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="currentColor"/></svg>'
    )


def brand() -> str:
    return (
        f'<div class="sp-brand"><div class="sp-mark">{icon.curve_svg()}</div><div>'
        f'<div class="sp-brand-name">StaffPilot</div><div class="sp-brand-tag">{_e(SLOGAN)}</div></div></div>'
    )


def section(title: str) -> str:
    return f'<div class="sp-section">{_e(title)}</div>'


def legal() -> str:
    return f'<div class="sp-legal">{_e(COPYRIGHT.replace(TEAM, ""))}<strong>{_e(TEAM)}</strong><br>{_e(SLOGAN)}</div>'


def page_head(title: str, subtitle: str = "") -> str:
    """Page title with one line saying what the page is for."""
    sub = f"<p>{_e(subtitle)}</p>" if subtitle else ""
    return f'<div class="sp-head"><div><h1>{_e(title)}</h1>{sub}</div></div>'


def kpi_cards(kpis: list[Kpi]) -> str:
    cards = []
    for k in kpis:
        arrow = {"up": "↑ ", "down": "↓ "}.get(k.trend, "")
        delta = (
            f'<b class="{k.tone}">{arrow}{_e(k.delta)}</b> {_e(k.comparison)}'
            if k.delta
            else _e(k.comparison)
        )
        cards.append(
            f'<div class="sp-kpi"><div class="label">{_e(k.label)}{tip(k.tip)}</div>'
            f'<div class="value">{_e(k.value)}</div>{sparkline(k.series)}'
            f'<div class="delta">{delta}</div></div>'
        )
    return f'<div class="sp-kpis">{"".join(cards)}</div>'


def alert_list(alerts: list[Alert]) -> str:
    if not alerts:
        return '<div class="sp-alert info"><span class="sp-level">Clear</span><span>Nothing needs attention.</span></div>'
    return "".join(
        f'<div class="sp-alert {a.level}"><span class="sp-level">{LEVEL_NAMES.get(a.level, a.level)}</span>'
        f"<span>{_e(a.message)}</span></div>"
        for a in alerts
    )


def alert_summary(alerts: list[Alert]) -> str:
    urgent = [a for a in alerts if a.level != "info"]
    if not urgent:
        return "Nothing needs attention"
    critical = sum(a.level == "critical" for a in urgent)
    noun = "item needs" if len(urgent) == 1 else "items need"
    return f"{len(urgent)} {noun} attention" + (f", {critical} of them critical" if critical else "")


def chat_empty() -> str:
    """Shown in an empty conversation (Gradio renders the chatbot placeholder as Markdown)."""
    return (
        '<div class="sp-empty"><h2>What do you want to know about the plan?</h2>'
        "<p>Ask about headcount in a country and month, test a change such as fewer sign ups, "
        "or check a rule. Answers use the planner's own numbers.</p></div>"
    )


def history_empty() -> str:
    return '<div class="sp-history-empty">Your chats in this tab appear here.</div>'


def trace(intent: str, tools: str, verified: bool, seconds: float, backend: str, carried: str = "") -> str:
    """How an answer was built, for the details panel (Markdown with a little HTML)."""
    if verified:
        check = '<span class="sp-chip ok" data-tip="Every number in the answer matches a planner result.">Numbers checked</span>'
    else:
        check = '<span class="sp-chip fail" data-tip="A number in the answer could not be matched to the planner.">Check failed</span>'
    chips = (
        f'{check}<span class="sp-chip" data-tip="How the question was understood">{_e(intent.capitalize())}</span>'
        f'<span class="sp-chip" data-tip="Time to answer">{seconds:.1f} s</span>'
    )
    lines = [chips, f"Answered with **{_e(tools)}** using **{_e(backend)}**."]
    if carried:
        lines.append(f"This was a follow up, so it kept the {_e(carried)} from your last question.")
    return "\n\n".join(lines)


def trace_empty() -> str:
    return "Ask something to see how the answer was built: the planner tool that ran, the numbers it used and how your question was read."
