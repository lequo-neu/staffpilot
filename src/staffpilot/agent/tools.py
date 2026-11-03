"""Planner capabilities exposed as tools.

Each tool returns a `ToolOutput` with a short table for display, a chart that makes
the point visible, and a flat dict of facts. Facts are the only numbers an answer
may contain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from matplotlib.figure import Figure
import pandas as pd
from pydantic import BaseModel, Field

from staffpilot import charts
from staffpilot.agent.rag import Retriever
from staffpilot.insights import INSIGHT_KINDS, insight
from staffpilot.planner import RECOMMENDED_POLICY, Planner
from staffpilot.scenarios import ScenarioParams


PLAN_FACTS = (
    "start_agents",
    "end_agents",
    "avg_active",
    "hires",
    "notices",
    "salary_cost",
    "fire_cost",
    "total_cost",
    "uplift_value",
    "net_value",
    "service_rate",
    "dropped",
    "mean_wait_days",
    "roi",
    "utilization",
    "avg_idle_agents",
)


@dataclass
class ToolOutput:
    name: str
    facts: dict[str, float]
    table: pd.DataFrame | None = None
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    chart: Figure | None = None


SUMMARY_COLUMNS = [
    "country",
    "start_agents",
    "end_agents",
    "avg_active",
    "hires",
    "notices",
    "total_cost",
    "net_value",
    "service_rate",
    "mean_wait_days",
]
INSIGHT_METRIC = {
    "volatility": ("monthly_cv", "Month to month variation", False),
    "eligibility": ("eligible_rate", "Share of sign ups that are eligible", True),
    "budget": ("mean", "Average eligible budget", False),
    "growth": ("change", "Change in eligible sign ups between the two years", True),
}


def _insight_chart(kind: str, table: pd.DataFrame, headline: str, focus: str | None) -> Figure:
    if kind == "seasonality":
        fig, (ax,) = charts.new_figure()
        colors = [
            charts.RED if v == table["seasonal_index"].max() else charts.NAVY for v in table["seasonal_index"]
        ]
        ax.bar(table["month"], table["seasonal_index"], color=colors)
        ax.axhline(1, color=charts.MUTED, linewidth=0.8, linestyle="--")
        ax.set_xticks(range(1, 13), charts.MONTHS)
        return charts.finish(fig, headline, "Eligible sign ups per calendar month; 1 is an average month.")
    column, title, percent = INSIGHT_METRIC[kind]
    return charts.ranked_bars(
        table["country"], table[column], title, headline, highlight=focus, percent=percent
    )


class CountryArgs(BaseModel):
    countries: list[str] = Field(default_factory=list, description="Country names; empty for all countries")
    months: list[int] = Field(default_factory=list, description="Calendar months 1 to 12 to report")


class InsightArgs(BaseModel):
    kind: str = Field(description=f"One of {', '.join(INSIGHT_KINDS)}")
    country: str | None = Field(None, description="Optional country to focus on")


class RulesArgs(BaseModel):
    query: str = Field(description="What to look up in the case rules and assumptions")


class PlannerTools:
    """Binds tool functions to one planner instance and caches slow results."""

    def __init__(self, planner: Planner, retriever: Retriever | None = None) -> None:
        self.planner = planner
        self.retriever = retriever or Retriever()
        self._sensitivity: dict[str, pd.DataFrame] = {}

    def _countries(self, names: list[str]) -> list[str]:
        resolved = [self.planner.resolve_country(n) for n in names]
        return [c for c in resolved if c]

    def rule_facts(self) -> dict[str, float]:
        rules = self.planner.settings.rules
        return {
            "rules.capacity_per_agent": rules.capacity_per_agent,
            "rules.support_days": rules.support_days,
            "rules.max_wait_days": rules.max_wait_days,
            "rules.fire_cost_share": rules.fire_cost_share,
            "rules.expected_uplift_rate": rules.expected_uplift,
            "plan.year": self.planner.year,
        }

    def get_plan(self, countries: list[str] | None = None, months: list[int] | None = None) -> ToolOutput:
        bundle = self.planner.run(RECOMMENDED_POLICY)
        chosen = self._countries(countries or []) or None
        kpis = bundle.kpi_table()
        table = bundle.plan_table()
        facts: dict[str, float] = {}
        if chosen:
            kpis = kpis[kpis["country"].isin(chosen)]
            table = table[table["country"].isin(chosen)]
            for _, row in kpis.iterrows():
                key = row["country"].replace(" ", "_")
                facts.update({f"{key}.{name}": float(row[name]) for name in PLAN_FACTS})
                plan = bundle.outcomes[row["country"]].plan
                for m in months or []:
                    if 1 <= m <= 12:
                        facts[f"{key}.active_month_{m}"] = float(plan.active[m - 1])
                        facts[f"{key}.hires_month_{m}"] = float(plan.hires[m - 1])
                        facts[f"{key}.notices_month_{m}"] = float(plan.notices[m - 1])
                cuts = [i + 1 for i, n in enumerate(plan.notices[:12]) if n > 0]
                adds = [i + 1 for i, h in enumerate(plan.hires[:12]) if h > 0]
                if cuts:
                    facts[f"{key}.first_notice_month"] = float(cuts[0])
                if adds:
                    facts[f"{key}.first_hire_month"] = float(adds[0])
        totals = bundle.totals()
        facts.update(
            {f"all.{k}": v for k, v in totals.items() if k in PLAN_FACTS or k in {"served", "arrivals"}}
        )
        notes = [
            f"Recommended plan (net value with a 98 percent service floor) for {self.planner.year}; {len(kpis)} countries shown."
        ]
        monthly = bundle.monthly_table()
        monthly = monthly[monthly["month_index"] <= 12]
        if chosen:
            monthly = monthly[monthly["country"].isin(chosen)]
        label = ", ".join(chosen) if chosen else "All countries"
        chart = charts.headcount(
            table,
            monthly,
            f"{label}: recommended headcount for {self.planner.year}",
            self.planner.settings.rules.capacity_per_agent,
        )
        # One country: its month by month plan. All countries: one row per country, so a
        # reader (or the chat agent) can rank countries without paging through 264 rows.
        shown = table if chosen else kpis[SUMMARY_COLUMNS]
        return ToolOutput("get_plan", facts, shown, notes, chart=chart)

    def compare_policies(self, countries: list[str] | None = None) -> ToolOutput:
        chosen = self._countries(countries or []) or None
        frame = self.planner.compare_policies(chosen)
        facts = {}
        for _, row in frame.iterrows():
            for name in (
                "net_value",
                "total_cost",
                "uplift_value",
                "service_rate",
                "avg_active",
                "fire_cost",
            ):
                facts[f"{row['policy']}.{name}"] = float(row[name])
            if "net_value_vs_hold" in row:
                facts[f"{row['policy']}.net_value_vs_hold"] = float(row["net_value_vs_hold"])
        columns = ["policy", "net_value", "total_cost", "uplift_value", "service_rate", "avg_active"]
        chart = charts.policy_bars(frame, RECOMMENDED_POLICY)
        return ToolOutput(
            "compare_policies", facts, frame[columns], ["Totals over the selected countries."], chart=chart
        )

    def run_scenario(self, params: ScenarioParams) -> ToolOutput:
        result = self.planner.scenario(params)
        totals = result.totals()
        facts = {f"scenario.{k}": v for k, v in totals.items()}
        if len(result.comparison) <= 4:
            for _, row in result.comparison.iterrows():
                key = row["country"].replace(" ", "_")
                for col in result.comparison.columns:
                    if col != "country":
                        facts[f"{key}.{col}"] = float(row[col])
        notes = [f"{params.plain()}."]
        columns = [
            "country",
            "net_value_base",
            "net_value_scenario",
            "net_value_change",
            "avg_active_base",
            "avg_active_scenario",
            "service_rate_base",
            "service_rate_scenario",
        ]
        affected = result.comparison["country"].tolist()
        base = self.planner.run(RECOMMENDED_POLICY).plan_table()
        where = ", ".join(affected) if len(affected) <= 3 else f"{len(affected)} countries"
        chart = charts.scenario_lines(
            base[base["country"].isin(affected)],
            result.plan,
            f"{where}: headcount under the scenario",
            totals["net_value_change"],
        )
        return ToolOutput("run_scenario", facts, result.comparison[columns], notes, chart=chart)

    def sensitivity(self, countries: list[str] | None = None) -> ToolOutput:
        chosen = self._countries(countries or []) or None
        key = ",".join(chosen or ["all"])
        if key not in self._sensitivity:
            self._sensitivity[key] = self.planner.sensitivity(countries=chosen)
        frame = self._sensitivity[key]
        facts = {}
        for _, row in frame.iterrows():
            tag = f"demand_{int(round(row['demand_scale'] * 100))}.{row['plan'].replace(' ', '_')}"
            for name in ("net_value", "service_rate", "total_cost", "avg_active", "mean_wait_days"):
                facts[f"{tag}.{name}"] = float(row[name])
        notes = ["Sign up volume from 70 to 130 percent of forecast."]
        return ToolOutput("sensitivity", facts, frame, notes, chart=charts.sensitivity_panels(frame))

    def signup_insights(self, kind: str, country: str | None = None) -> ToolOutput:
        kind = kind if kind in INSIGHT_KINDS else "volatility"
        resolved = self.planner.resolve_country(country) if country else None
        result = insight(self.planner.dataset, kind, resolved)
        facts = {f"insight.{k}": float(v) for k, v in result.facts.items()}
        return ToolOutput(
            "signup_insights",
            facts,
            result.table.head(22),
            [result.headline],
            chart=_insight_chart(kind, result.table, result.headline, resolved),
        )

    def search_rules(self, query: str) -> ToolOutput:
        passages = self.retriever.search(query, k=3)
        notes = [f"[{p.citation}] {p.text}" for p in passages]
        return ToolOutput("search_rules", self.rule_facts(), None, notes, [p.citation for p in passages])

    def as_langchain_tools(self) -> list[Any]:
        """The same capabilities as LangChain tools, for the free form agent."""
        from langchain_core.tools import StructuredTool

        def wrap(output: ToolOutput) -> str:
            payload = {"notes": output.notes, "facts": output.facts}
            if output.table is not None:
                # 30 rows fit one country's months and every country's summary.
                payload["table"] = output.table.head(30).round(4).to_dict(orient="records")
            return json.dumps(payload, default=float)

        return [
            StructuredTool.from_function(
                lambda countries=None, months=None: wrap(self.get_plan(countries, months)),
                name="get_plan",
                description=(
                    "The recommended staffing plan. With no countries: one row per country with start and end agents, "
                    "hires, notices given to agents, cost, net value and service. With countries: their month by month "
                    "plan; add months for the agents at work, hires and notices in those months."
                ),
                args_schema=CountryArgs,
            ),
            StructuredTool.from_function(
                lambda countries=None, months=None: wrap(self.compare_policies(countries)),
                name="compare_policies",
                description="Compare the optimized plan with simple baseline policies.",
                args_schema=CountryArgs,
            ),
            StructuredTool.from_function(
                lambda **kwargs: wrap(self.run_scenario(ScenarioParams(**kwargs))),
                name="run_scenario",
                description="Rerun the planner under a what if change and report the difference.",
                args_schema=ScenarioParams,
            ),
            StructuredTool.from_function(
                lambda countries=None, months=None: wrap(self.sensitivity(countries)),
                name="sensitivity",
                description="Net value and service when sign ups are 70 to 130 percent of forecast.",
                args_schema=CountryArgs,
            ),
            StructuredTool.from_function(
                lambda kind, country=None: wrap(self.signup_insights(kind, country)),
                name="signup_insights",
                description=(
                    "Patterns in advertiser sign ups (volatility, seasonality, eligibility, budget, growth); "
                    "not about agents or notices."
                ),
                args_schema=InsightArgs,
            ),
            StructuredTool.from_function(
                lambda query: wrap(self.search_rules(query)),
                name="search_rules",
                description="Look up the case rules, assumptions and metric definitions.",
                args_schema=RulesArgs,
            ),
        ]
