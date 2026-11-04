"""Charts with one consistent look, for the app, the assistant, the notebook and the EDA report.

Only the object oriented matplotlib API is used (no pyplot), so building a chart never
changes the plotting backend of the program that imports this module.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd


# Same colours as the app (staffpilot/ui/style.css): deep teal for the plan, slate for
# comparisons, a pale teal for areas, and red and amber only for cuts and warnings.
INK = "#17202b"
MUTED = "#6b7682"
GRID = "#e6eaee"
NAVY = "#0f6e75"  # the plan's own line; the name is kept for older callers
TEAL = "#3f9f8f"
AMBER = "#c98a1b"
RED = "#b5432c"
SOFT = "#bfdcdf"
SLATE = "#8c97a3"
FONT_CHOICES = ("IBM Plex Sans", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans")


def _installed_font() -> list[str]:
    # Matplotlib warns for every listed font that is missing, so only an installed one is passed on.
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [next((name for name in FONT_CHOICES if name in installed), "DejaVu Sans")]


FONTS = _installed_font()
POLICY_NAMES = {
    "hold": "Keep January headcount",
    "reactive": "Follow last month's demand",
    "peak_cover": "One cut to the yearly peak",
    "optimized": "Optimized for value",
    "service_98": "Recommended (98% served)",
    "service_98_21d": "98% served within 21 days",
    "service_98_14d": "98% served within 14 days",
    "service_98_7d": "98% served within 7 days",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def money(value: float) -> str:
    if abs(value) >= 1e6:
        return f"${value / 1e6:,.1f}M"
    if abs(value) >= 1e3:
        return f"${value / 1e3:,.0f}k"
    return f"${value:,.0f}"


def money_axis_label(value: float, _: object = None) -> str:
    """Axis ticks need no decimals: "$100M", "$2.5M", "$40k"."""
    return money(value).replace(".0M", "M")


def new_figure(width: float = 8.0, height: float = 3.6, ncols: int = 1) -> tuple[Figure, list]:
    fig = Figure(figsize=(width, height), dpi=110, facecolor="white")
    axes = fig.subplots(1, ncols)
    axes = list(np.atleast_1d(axes))
    for ax in axes:
        ax.set_facecolor("white")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=8.5, length=0, pad=6, labelfontfamily=FONTS)
        ax.yaxis.grid(True, color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
    return fig, axes


def finish(fig: Figure, title: str, subtitle: str = "") -> Figure:
    # Offsets in inches keep the title block the same size on short and tall charts.
    height = fig.get_figheight()
    fig.suptitle(
        title,
        x=0.012,
        y=1 - 0.1 / height,
        ha="left",
        va="top",
        fontsize=11,
        fontweight="bold",
        color=INK,
        fontfamily=FONTS,
    )
    if subtitle:
        fig.text(
            0.012,
            1 - 0.36 / height,
            subtitle,
            ha="left",
            va="top",
            fontsize=8.5,
            color=MUTED,
            fontfamily=FONTS,
        )
    for ax in fig.axes:
        for text in [ax.xaxis.label, ax.yaxis.label, ax.title, *ax.texts]:
            text.set_fontfamily(FONTS)
        legend = ax.get_legend()
        if legend:
            for text in legend.get_texts():
                text.set_fontfamily(FONTS)
                text.set_color(MUTED)
    fig.tight_layout(rect=(0, 0, 1, 1 - (0.52 if subtitle else 0.34) / height))
    return fig


def save(fig: Figure, path: Path, dpi: int = 130) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor="white")
    return path


def save_answer_chart(fig: Figure | None, question: str, folder: Path, dpi: int = 130) -> Path | None:
    """Save an answer's chart under a file name made from the question; None when there is no chart."""
    if fig is None:
        return None
    slug = "".join(ch if ch.isalnum() else "_" for ch in question.lower())[:40].strip("_") or "answer"
    return save(fig, folder / f"{slug}.png", dpi)


def _money_axis(ax) -> None:
    ax.yaxis.set_major_formatter(FuncFormatter(money_axis_label))


def headcount(plan: pd.DataFrame, monthly: pd.DataFrame, title: str, capacity: int = 10) -> Figure:
    """Active agents per month against a rough need line (two months of sign ups per ten slots)."""
    active = plan.groupby("month")["active_agents"].sum().to_numpy()
    arrivals = monthly.groupby("month_index")["arrivals"].sum().to_numpy()[: len(active)]
    need = np.convolve(arrivals, [1, 1])[: len(arrivals)] / capacity
    hires = plan.groupby("month")["hires_decided"].sum().to_numpy()
    notices = plan.groupby("month")["notices_given"].sum().to_numpy()
    x = np.arange(1, len(active) + 1)
    fig, (ax,) = new_figure()
    ax.fill_between(x, need, color=SOFT, alpha=0.55, linewidth=0, label="rough need")
    ax.plot(
        x,
        active,
        color=NAVY,
        linewidth=2.2,
        marker="o",
        markersize=3.5,
        markeredgecolor="white",
        markeredgewidth=0.8,
        label="agents at work",
    )
    for xi, h, n in zip(x, hires, notices, strict=True):
        # A month with both notices and hires gets one label above the point, so the hires
        # text never lands on a steep line.
        if n:
            text = f"{int(n):,} notices" + (f", +{int(h):,} hires" if h else "")
            ax.annotate(
                text, (xi, active[xi - 1]), xytext=(6, 6), textcoords="offset points", fontsize=7.5, color=RED
            )
        elif h:
            ax.annotate(
                f"+{int(h):,} hires",
                (xi, active[xi - 1]),
                xytext=(0, -13),
                textcoords="offset points",
                ha="center",
                fontsize=7.5,
                color=TEAL,
            )
    ax.set_xticks(x, MONTHS[: len(x)])
    ax.set_ylabel("agents", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    return finish(
        fig,
        title,
        "Notices take effect the month after they are given; hires start after one month of ramp up.",
    )


def policy_bars(comparison: pd.DataFrame, highlight: str) -> Figure:
    frame = comparison.sort_values("net_value")
    colors = [NAVY if p == highlight else SOFT for p in frame["policy"]]
    fig, (ax,) = new_figure(height=3.2)
    bars = ax.barh(frame["policy"].map(lambda p: POLICY_NAMES.get(p, p)), frame["net_value"], color=colors)
    for bar, value in zip(bars, frame["net_value"], strict=True):
        ax.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {money(value)}",
            va="center",
            fontsize=8.5,
            color=INK,
        )
    ax.xaxis.set_major_formatter(FuncFormatter(money_axis_label))
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID)
    ax.set_xlim(0, frame["net_value"].max() * 1.18)
    return finish(
        fig, "Net value by policy", "Expected uplift minus salaries and notice cost over the planning year."
    )


def scenario_lines(base: pd.DataFrame, scenario: pd.DataFrame, title: str, change: float) -> Figure:
    b = base.groupby("month")["active_agents"].sum().to_numpy()
    s = scenario.groupby("month")["active_agents"].sum().to_numpy()
    x = np.arange(1, len(b) + 1)
    fig, (ax,) = new_figure()
    ax.plot(x, b, color=SLATE, linewidth=1.8, linestyle=(0, (4, 3)), label="current plan")
    ax.plot(
        x,
        s,
        color=NAVY,
        linewidth=2.6,
        marker="o",
        markersize=4,
        label="under the scenario",
    )
    ax.set_xticks(x, MONTHS[: len(x)])
    ax.set_ylabel("active agents", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=8)
    sign = "+" if change >= 0 else "-"
    return finish(fig, title, f"Net value change {sign}{money(abs(change))} against the current plan.")


def service_tradeoff(frame: pd.DataFrame, chosen: str) -> Figure:
    """What each service goal costs against profit only, and how fast it serves advertisers."""
    names = frame["policy"].map(lambda p: "Profit only" if p == "optimized" else POLICY_NAMES.get(p, p))
    colors = [NAVY if p == chosen else SOFT for p in frame["policy"]]
    fig, (left, right) = new_figure(width=8.6, height=3.4, ncols=2)
    y = np.arange(len(frame))[::-1]
    given_up = frame["cost_of_goal"].clip(lower=0)
    left.barh(y, given_up, color=colors)
    right.barh(y, frame["within_week_rate"], color=colors)
    for ax, values, fmt in (
        (left, given_up, lambda v: money(v)),
        (right, frame["within_week_rate"], lambda v: f"{v:.1%}"),
    ):
        for yi, value in zip(y, values, strict=True):
            ax.text(value, yi, f"  {fmt(value)}", va="center", fontsize=8, color=INK)
        ax.yaxis.grid(False)
        ax.xaxis.grid(True, color=GRID)
    left.set_yticks(y, names, fontsize=8)
    right.set_yticks(y, [""] * len(y))
    left.set_xlim(0, max(float(given_up.max()), 1.0) * 1.45)
    left.xaxis.set_major_formatter(FuncFormatter(money_axis_label))
    right.set_xlim(0.8, 1.07)
    right.set_xticks([0.8, 0.85, 0.9, 0.95, 1.0])
    right.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    left.set_title("Net value given up against profit only", fontsize=9, color=MUTED, loc="left")
    right.set_title("Advertisers served within 7 days", fontsize=9, color=MUTED, loc="left")
    return finish(
        fig,
        "Profit against service level",
        "Each goal is a separate optimization; every number comes from the day by day simulator.",
    )


def monthly_update(table: pd.DataFrame, as_of: int, title: str) -> Figure:
    """Agents at work under the approved plan and the updated one; the months already done are shaded.

    January is left out: the large cut made then would flatten every later change.
    """
    x = np.arange(2, len(table) + 1)
    planned, updated = table["agents_planned"].to_numpy()[1:], table["agents_updated"].to_numpy()[1:]
    fig, (ax,) = new_figure()
    if as_of > 2:
        ax.axvspan(1.5, as_of - 0.5, color=GRID, alpha=0.6, linewidth=0)
        ax.text(
            1.6, 1.0, "carried out", transform=ax.get_xaxis_transform(), va="top", fontsize=7.5, color=MUTED
        )
    ax.plot(x, planned, color=SLATE, linewidth=1.8, linestyle=(0, (4, 3)), label="approved plan")
    start = as_of - 2  # position of the update month in x
    ax.plot(
        x[start:],
        updated[start:],
        color=NAVY,
        linewidth=2.6,
        marker="o",
        markersize=4,
        markeredgecolor="white",
        markeredgewidth=0.8,
        label="updated plan",
    )
    for i in range(start, len(x)):
        gap = int(updated[i] - planned[i])
        if gap and (i == start or gap != int(updated[i - 1] - planned[i - 1])):
            ax.annotate(
                f"{gap:+d}",
                (x[i], updated[i]),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color=TEAL if gap > 0 else RED,
            )
    ax.set_xticks(x, MONTHS[1 : len(x) + 1])
    ax.set_ylabel("agents at work", color=MUTED, fontsize=9)
    low = min(planned.min(), updated.min())
    ax.set_ylim(max(0, low * 0.85 - 2), max(planned.max(), updated.max()) * 1.12 + 2)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    return finish(
        fig, title, "February to December. Labels show agents added or removed against the approved plan."
    )


def sensitivity_panels(frame: pd.DataFrame) -> Figure:
    fig, (left, right) = new_figure(width=9.0, height=3.4, ncols=2)
    for label, part in frame.groupby("plan"):
        color = NAVY if label == "replanned" else SLATE
        left.plot(
            part["demand_scale"] * 100, part["net_value"], color=color, marker="o", linewidth=2, label=label
        )
        right.plot(
            part["demand_scale"] * 100,
            part["mean_wait_days"],
            color=color,
            marker="o",
            linewidth=2,
            label=label,
        )
    _money_axis(left)
    left.set_xlabel("sign ups, percent of forecast", color=MUTED, fontsize=8.5)
    right.set_xlabel("sign ups, percent of forecast", color=MUTED, fontsize=8.5)
    left.set_title("Net value", fontsize=9.5, color=INK, loc="left")
    right.set_title("Average wait (days)", fontsize=9.5, color=INK, loc="left")
    left.legend(frameon=False, fontsize=8)
    return finish(
        fig,
        "What happens if sign ups differ from the forecast",
        "Keeping the current plan versus rebuilding it for each volume.",
    )


def ranked_bars(
    labels: pd.Series,
    values: pd.Series,
    title: str,
    subtitle: str = "",
    highlight: str | None = None,
    percent: bool = False,
) -> Figure:
    order = values.sort_values().index
    fig, (ax,) = new_figure(height=max(3.0, 0.22 * len(order) + 1.2))
    colors = [RED if labels[i] == highlight else NAVY for i in order]
    ax.barh(labels[order], values[order], color=colors)
    if percent:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID)
    ax.tick_params(axis="y", labelsize=8)
    return finish(fig, title, subtitle)
