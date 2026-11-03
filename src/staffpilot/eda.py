"""Exploratory data analysis of the sign up workbook.

`profile` checks data quality and summarises each country; `figures` draws the charts;
`write_report` saves both as a Markdown report with PNG files (python -m staffpilot eda).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

from staffpilot import charts
from staffpilot.data import Dataset


log = logging.getLogger(__name__)


@dataclass
class EdaReport:
    overview: dict[str, object]
    quality: pd.DataFrame
    countries: pd.DataFrame
    monthly: pd.DataFrame  # country, year, month, eligible
    weekday: pd.DataFrame
    budget_quantiles: pd.DataFrame
    findings: list[str] = field(default_factory=list)


def _peak_need(dataset: Dataset, country: str, year: int, capacity: int) -> float:
    daily = pd.Series(dataset.daily_eligible_counts(country, year))
    return float(np.ceil(daily.rolling(60, min_periods=1).sum().max() / capacity))


def profile(dataset: Dataset, capacity: int = 10) -> EdaReport:
    s = dataset.signups
    years = dataset.history_years
    last = years[-1]
    quality = pd.DataFrame(
        [
            ("Rows", len(s), "one row per sign up"),
            ("Missing values", int(s.isna().sum().sum()), "across all columns"),
            ("Duplicate advertiser ids", int(s["advertiser_id"].duplicated().sum()), ""),
            ("Impossible dates repaired", dataset.repaired_dates, "moved to the last day of the month"),
            ("Budgets at or below zero", int((s["budget"] <= 0).sum()), ""),
            (
                "Budgets exactly on the threshold",
                int((s["budget"] == s["country"].map(dataset.countries["threshold"])).sum()),
                "ineligible under the strict rule",
            ),
            ("Countries", len(dataset.countries), ""),
        ],
        columns=["check", "value", "note"],
    )
    eligible = dataset.eligible()
    by_country = s.groupby("country").agg(signups=("eligible", "size"), eligible=("eligible", "sum"))
    by_country["eligible_rate"] = by_country["eligible"] / by_country["signups"]
    budgets = eligible.groupby("country")["budget"]
    by_country["median_eligible_budget"] = budgets.median()
    by_country = by_country.join(dataset.countries)
    by_country["peak_need"] = [_peak_need(dataset, c, last, capacity) for c in by_country.index]
    by_country["staff_to_need"] = by_country["agents"] / by_country["peak_need"].replace(0, np.nan)
    if len(years) > 1:
        per_year = eligible.groupby(["country", eligible["signup_date"].dt.year]).size().unstack(fill_value=0)
        by_country["yearly_change"] = per_year[years[-1]] / per_year[years[-2]].replace(0, np.nan) - 1
    daily = eligible.groupby(["country", "signup_date"]).size()
    by_country["daily_cv"] = daily.groupby(level=0).agg(lambda x: x.std() / x.mean() if x.mean() else 0)
    monthly = (
        eligible.groupby(
            [
                eligible["country"],
                eligible["signup_date"].dt.year.rename("year"),
                eligible["signup_date"].dt.month.rename("month"),
            ]
        )
        .size()
        .rename("eligible")
        .reset_index()
    )
    weekday = eligible.groupby(eligible["signup_date"].dt.day_of_week).size().rename("eligible").reset_index()
    weekday["index"] = weekday["eligible"] / weekday["eligible"].mean()
    quantiles = s["budget"].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).rename("budget").reset_index()
    quantiles.columns = ["quantile", "budget"]
    overview = {
        "source": Path(dataset.source).name,
        "history_years": years,
        "planning_year": dataset.planning_year(),
        "signups": len(s),
        "eligible": int(s["eligible"].sum()),
        "eligible_rate": float(s["eligible"].mean()),
        "january_agents": int(dataset.countries["agents"].sum()),
        "peak_need": int(by_country["peak_need"].sum()),
    }
    report = EdaReport(overview, quality, by_country.reset_index(), monthly, weekday, quantiles)
    report.findings = _findings(report)
    log.info("EDA profile: %d sign ups, %d countries", len(s), len(by_country))
    return report


def _findings(report: EdaReport) -> list[str]:
    c = report.countries.set_index("country")
    o = report.overview
    total_by_month = report.monthly.groupby("month")["eligible"].sum()
    peak, low = int(total_by_month.idxmax()), int(total_by_month.idxmin())
    short = c[c["staff_to_need"] < 1].index.tolist()
    found = [
        f"{o['eligible_rate']:.1%} of {o['signups']:,} sign ups clear their country threshold.",
        (
            f"January headcount is {o['january_agents']:,} agents against a peak need of about {o['peak_need']:,}, "
            f"{o['january_agents'] / max(o['peak_need'], 1):.1f} times what the busiest 60 days require."
        ),
        (
            f"Demand peaks in {charts.MONTHS[peak - 1]} and is lowest in {charts.MONTHS[low - 1]}; "
            f"the peak month is {total_by_month.max() / total_by_month.min():.1f} times the quietest."
        ),
        (
            f"Day to day noise is high: the median daily coefficient of variation is {c['daily_cv'].median():.2f}, "
            "far above what steady random arrivals would give, so the waiting pool matters."
        ),
    ]
    if short:
        found.append(f"Understaffed in January: {', '.join(short)}.")
    if "yearly_change" in c:
        found.append(
            f"Eligible sign ups changed by {c['yearly_change'].median():+.1%} (median country) between the two years."
        )
    weekday_spread = report.weekday["index"].max() - report.weekday["index"].min()
    found.append(
        f"Weekdays differ by only {weekday_spread:.0%} from each other, so weekly patterns can be ignored."
    )
    return found


def figures(report: EdaReport) -> dict[str, Figure]:
    c = report.countries
    out: dict[str, Figure] = {}

    fig, (ax,) = charts.new_figure()
    for (year, part), color in zip(
        report.monthly.groupby("year"), (charts.SOFT, charts.NAVY, charts.TEAL), strict=False
    ):
        series = part.groupby("month")["eligible"].sum()
        ax.plot(series.index, series.to_numpy(), marker="o", linewidth=2.2, color=color, label=str(year))
    ax.set_xticks(range(1, 13), charts.MONTHS)
    ax.legend(frameon=False, fontsize=8)
    out["monthly_trend"] = charts.finish(
        fig, "Eligible sign ups per month", "All countries, one line per history year."
    )

    pivot = report.monthly.groupby(["country", "month"])["eligible"].sum().unstack(fill_value=0)
    index = pivot.div(pivot.mean(axis=1), axis=0)
    fig, (ax,) = charts.new_figure(height=6.2)
    image = ax.imshow(index.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=0.5, vmax=1.5)
    ax.set_yticks(range(len(index)), index.index, fontsize=7.5)
    ax.set_xticks(range(12), charts.MONTHS)
    ax.yaxis.grid(False)
    fig.colorbar(image, ax=ax, shrink=0.8, label="month / average month")
    out["seasonality_heatmap"] = charts.finish(
        fig, "Seasonality by country", "Above 1 means a busier than average month."
    )

    fig, (ax,) = charts.new_figure(width=9.0, height=5.6)
    order = c.sort_values("staff_to_need")
    y = np.arange(len(order))
    ax.barh(y - 0.2, order["agents"], height=0.4, color=charts.NAVY, label="January headcount")
    ax.barh(y + 0.2, order["peak_need"], height=0.4, color=charts.AMBER, label="peak 60 day need")
    ax.set_yticks(y, order["country"], fontsize=8)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=charts.GRID)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    out["staff_vs_need"] = charts.finish(
        fig,
        "January headcount against the busiest 60 days",
        "Need = eligible sign ups in the busiest 60 day window of the last year, divided by 10.",
    )

    out["eligibility_rate"] = charts.ranked_bars(
        c["country"],
        c["eligible_rate"],
        "Share of sign ups that are eligible",
        "Projected budget above the country threshold.",
        percent=True,
    )
    out["daily_noise"] = charts.ranked_bars(
        c["country"],
        c["daily_cv"],
        "Day to day noise in eligible sign ups",
        "Coefficient of variation of daily counts; steady random arrivals would sit near 0.2.",
    )
    return out


def budget_figure(dataset: Dataset) -> Figure:
    s = dataset.signups
    fig, (ax,) = charts.new_figure()
    ax.hist(np.log10(s["budget"].clip(lower=1)), bins=60, color=charts.SOFT)
    for value in dataset.countries["threshold"].quantile([0.0, 0.5, 1.0]):
        ax.axvline(np.log10(value), color=charts.RED, linewidth=1, linestyle="--")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: charts.money_axis_label(10**v)))
    ax.set_xlabel("projected annual budget (log scale)", color=charts.MUTED, fontsize=8.5)
    return charts.finish(
        fig,
        "Projected budgets of all sign ups",
        "Dashed lines: lowest, median and highest country threshold.",
    )


def markdown_table(frame: pd.DataFrame, digits: int = 3) -> str:
    """A plain Markdown table, so the report needs no extra package."""

    def cell(value: object) -> str:
        if isinstance(value, float):
            return f"{value:,.{digits}f}".rstrip("0").rstrip(".") if not np.isnan(value) else ""
        if isinstance(value, int | np.integer):
            return f"{int(value):,}"
        return str(value)

    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *rows])


def write_report(report: EdaReport, dataset: Dataset, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pictures = {**figures(report), "budget_distribution": budget_figure(dataset)}
    for name, fig in pictures.items():
        charts.save(fig, out_dir / f"{name}.png")
    o = report.overview
    lines = [
        "# Exploratory data analysis",
        "",
        f"Source `{o['source']}`, history years {o['history_years']}, planning year {o['planning_year']}.",
        "",
        "## Findings",
        "",
        *[f"* {f}" for f in report.findings],
        "",
        "## Data quality",
        "",
        markdown_table(report.quality),
        "",
        "## Countries",
        "",
        markdown_table(report.countries),
        "",
        "## Charts",
        "",
        *[f"![{name}]({name}.png)" for name in pictures],
        "",
    ]
    path = out_dir / "eda_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
