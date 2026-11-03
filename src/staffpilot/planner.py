"""High level entry point: forecast, plan, simulate and compare policies."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import logging
import math
import os
import time

import numpy as np
import pandas as pd

from staffpilot import cache
from staffpilot.config import Settings, load_settings
from staffpilot.data import Dataset, load_dataset
from staffpilot.forecast import Forecast, build_forecast, demand_stream, month_of_day
from staffpilot.optimize import CountryPlan, optimize_country, path_from_targets
from staffpilot.scenarios import ScenarioParams, ScenarioResult
from staffpilot.simulate import SimulationResult, simulate


POLICIES = ("hold", "reactive", "peak_cover", "optimized", "service_98")
# The delivered plan: net value with a 98 percent service floor. It costs very little versus the pure
# value optimum and keeps service in countries (the UAE) where support does not pay for itself.
RECOMMENDED_POLICY = "service_98"
log = logging.getLogger(__name__)
POLICY_LABELS = {
    "hold": "Keep January headcount all year",
    "reactive": "Match last month's demand",
    "peak_cover": "Cut once to the yearly peak plus 10 percent",
    "optimized": "Optimized for net value",
    "service_98": "Optimized with at least 98 percent served",
}


@dataclass
class Context:
    """Inputs a plan depends on. Scenarios build a modified copy."""

    settings: Settings
    dataset: Dataset
    forecast: Forecast
    multipliers: dict[str, np.ndarray] | None = None
    max_hires_per_month: int | None = None


@dataclass
class CountryOutcome:
    plan: CountryPlan
    simulation: SimulationResult
    kpis: dict[str, float]


@dataclass
class PlanBundle:
    year: int
    policy: str
    outcomes: dict[str, CountryOutcome]
    seconds: float = 0.0

    def plan_table(self, months: int = 12) -> pd.DataFrame:
        return pd.concat([o.plan.table(self.year, months) for o in self.outcomes.values()], ignore_index=True)

    def kpi_table(self) -> pd.DataFrame:
        frame = pd.DataFrame([{"country": c, **o.kpis} for c, o in self.outcomes.items()])
        return frame.sort_values("country").reset_index(drop=True)

    def monthly_table(self) -> pd.DataFrame:
        rows = []
        for country, outcome in self.outcomes.items():
            frame = outcome.simulation.monthly.copy()
            frame.insert(0, "country", country)
            frame["salary_cost"] = outcome.plan.salary_cost()[: len(frame)]
            frame["fire_cost"] = outcome.plan.fire_cost()[: len(frame)]
            rows.append(frame)
        return pd.concat(rows, ignore_index=True)

    def totals(self) -> dict[str, float]:
        table = self.kpi_table()
        sums = {
            k: float(table[k].sum())
            for k in (
                "salary_cost",
                "fire_cost",
                "total_cost",
                "uplift_value",
                "net_value",
                "served",
                "arrivals",
                "dropped",
                "hires",
                "notices",
                "start_agents",
                "end_agents",
                "avg_active",
            )
        }
        sums["service_rate"] = sums["served"] / sums["arrivals"] if sums["arrivals"] else 1.0
        waits = np.concatenate(
            [o.simulation.waits[o.simulation.wait_months <= 12] for o in self.outcomes.values()]
        )
        sums["mean_wait_days"] = float(waits.mean()) if waits.size else 0.0
        sums["p90_wait_days"] = float(np.percentile(waits, 90)) if waits.size else 0.0
        sums["roi"] = sums["uplift_value"] / sums["total_cost"] if sums["total_cost"] else 0.0
        sums["max_overflow"] = float(table["max_overflow"].max())
        return sums


def _kpis(plan: CountryPlan, sim: SimulationResult, months: int = 12) -> dict[str, float]:
    totals = sim.totals(months)
    salary = float(plan.salary_cost()[:months].sum())
    fire = float(plan.fire_cost()[:months].sum())
    cost = salary + fire
    return {
        "start_agents": float(plan.active[0]),
        "end_agents": float(plan.active[months - 1]),
        "avg_active": float(plan.active[:months].mean()),
        "hires": float(plan.hires[:months].sum()),
        "notices": float(plan.notices[:months].sum()),
        "salary_cost": salary,
        "fire_cost": fire,
        "total_cost": cost,
        "uplift_value": totals["uplift_value"],
        "net_value": totals["uplift_value"] - cost,
        "roi": totals["uplift_value"] / cost if cost else 0.0,
        "arrivals": totals["arrivals"],
        "served": totals["served"],
        "dropped": totals["dropped"],
        "waiting_at_end": totals["waiting_at_end"],
        "service_rate": totals["service_rate"],
        "mean_wait_days": totals["mean_wait_days"],
        "p90_wait_days": totals["p90_wait_days"],
        "utilization": totals["utilization"],
        "avg_idle_agents": float(sim.monthly["idle_agents"].iloc[:months].mean()),
        "max_overflow": totals["max_overflow"],
    }


class Planner:
    """Owns the dataset and forecast and produces staffing plans for every country."""

    def __init__(self, settings: Settings | None = None, dataset: Dataset | None = None) -> None:
        self.settings = settings or load_settings()
        self.dataset = dataset or load_dataset(self.settings)
        self.year = self.dataset.planning_year(self.settings.planning.planning_year)
        forecast = build_forecast(self.dataset, self.year, self.settings.planning.lookahead_months)
        self.context = Context(self.settings, self.dataset, forecast)
        self._bundles: dict[str, PlanBundle] = {}

    @property
    def countries(self) -> list[str]:
        return self.dataset.country_names

    @property
    def forecast(self) -> Forecast:
        return self.context.forecast

    def horizon_months(self, ctx: Context | None = None) -> int:
        ctx = ctx or self.context
        return 12 + ctx.settings.planning.lookahead_months

    def resolve_country(self, name: str) -> str | None:
        lookup = {c.lower(): c for c in self.countries}
        aliases = {
            "us": "USA",
            "united states": "USA",
            "america": "USA",
            "united kingdom": "UK",
            "britain": "UK",
            "korea": "South Korea",
            "emirates": "UAE",
            "united arab emirates": "UAE",
        }
        key = name.strip().lower()
        return lookup.get(key) or (aliases[key] if aliases.get(key) in self.countries else None)

    # Demand

    def demand(
        self,
        country: str,
        months: int,
        ctx: Context | None = None,
        rng: np.random.Generator | None = None,
        bootstrap: bool = False,
    ):
        ctx = ctx or self.context
        multipliers = (ctx.multipliers or {}).get(country)
        carry = (
            ctx.settings.rules.max_wait_days if ctx.settings.assumptions.initial_pool == "carryover" else 0
        )
        return demand_stream(ctx.dataset, ctx.forecast, country, months, multipliers, rng, bootstrap, carry)

    # Plans

    def plan_country(
        self, country: str, policy: str = "optimized", ctx: Context | None = None
    ) -> CountryPlan:
        ctx = ctx or self.context
        s = ctx.settings
        row = ctx.dataset.countries.loc[country]
        months = self.horizon_months(ctx)
        start, salary = int(row["agents"]), float(row["salary"])
        demand = ctx.forecast.demand(country)[:months]
        multipliers = (ctx.multipliers or {}).get(country)
        if multipliers is not None:
            demand = demand * multipliers[:months]
        capacity = s.rules.capacity_per_agent
        if policy == "hold":
            plan = path_from_targets(
                country, start, np.full(months, start), salary, s.rules, s.assumptions, policy
            )
        elif policy == "reactive":
            targets = np.ceil(np.concatenate([[start], 2 * demand[:-1] / capacity]))
            plan = path_from_targets(country, start, targets, salary, s.rules, s.assumptions, policy)
        elif policy == "peak_cover":
            concurrent = (demand + np.concatenate([[0], demand[:-1]])) / capacity
            targets = np.full(months, math.ceil(concurrent.max() * 1.1))
            targets[0] = start
            plan = path_from_targets(country, start, targets, salary, s.rules, s.assumptions, policy)
        elif policy in {"optimized", "service_98"}:
            target = 0.98 if policy == "service_98" else (s.planning.service_target or None)
            plan = self._optimize_with_repair(country, ctx, target)
        else:
            raise ValueError(f"Unknown policy {policy!r}; choose one of {POLICIES}")
        plan.policy = policy
        return plan

    def _optimize_with_repair(self, country: str, ctx: Context, service_target: float | None) -> CountryPlan:
        s = ctx.settings
        months = self.horizon_months(ctx)
        row = ctx.dataset.countries.loc[country]
        stream = self.demand(country, months, ctx)
        month_by_day = month_of_day(self.year, months)
        budgets = ctx.forecast.mean_budget(country)[:months]
        min_active: np.ndarray | None = None
        plan: CountryPlan | None = None
        for _ in range(s.planning.repair_rounds + 1):
            plan = optimize_country(
                country,
                stream.daily_counts,
                month_by_day,
                budgets,
                int(row["agents"]),
                float(row["salary"]),
                s.rules,
                s.assumptions,
                s.planning,
                service_target,
                min_active,
                ctx.max_hires_per_month,
                initial_pool=len(stream.initial_pool),
            )
            sim = self._simulate(country, plan, ctx)
            overflow = sim.monthly["max_overflow"].to_numpy()
            short = service_target is not None and sim.totals()["service_rate"] < service_target - 1e-9
            if overflow.max() <= 0 and not short:
                break
            extra = np.zeros(months)
            need = np.ceil(np.clip(overflow, 0, None) / s.rules.capacity_per_agent)
            extra[: len(need)] = need
            # A cut right after an overflow month tends to recreate it, so protect the next month too.
            extra[1 : len(need) + 1] = np.maximum(extra[1 : len(need) + 1], need[: months - 1])
            if short:
                dropped = sim.monthly["dropped"].to_numpy()
                extra[: len(dropped)] += np.where(dropped > 0, 1, 0)
            min_active = np.maximum(min_active if min_active is not None else 0, plan.active + extra)
            plan.notes.append("repair round applied")
            log.info("%s: simulator found a gap (overflow or service below target); solving again", country)
        return plan

    def _simulate(
        self,
        country: str,
        plan: CountryPlan,
        ctx: Context,
        rng: np.random.Generator | None = None,
        bootstrap: bool = False,
        sample_uplift: bool = False,
    ) -> SimulationResult:
        months = self.horizon_months(ctx)
        stream = self.demand(country, months, ctx, rng, bootstrap)
        return simulate(
            stream,
            plan.active,
            month_of_day(self.year, months),
            ctx.settings.rules,
            ctx.settings.assumptions,
            rng,
            sample_uplift,
        )

    def run(
        self,
        policy: str = "optimized",
        countries: list[str] | None = None,
        ctx: Context | None = None,
        use_cache: bool = True,
    ) -> PlanBundle:
        key = f"{policy}:{','.join(countries or [])}"
        if use_cache and ctx is None and key in self._bundles:
            return self._bundles[key]
        if use_cache and ctx is None:
            # The base plans are the same on every start with the same data, settings and
            # code, so they are kept on disk (see staffpilot.cache).
            disk_key = cache.digest(
                key, self.dataset.fingerprint(), self.settings.model_dump_json(), cache.code_version()
            )
            bundle = cache.cached("plans", disk_key, lambda: self._solve(policy, countries, self.context))
            self._bundles[key] = bundle
            return bundle
        bundle = self._solve(policy, countries, ctx or self.context)
        if ctx is None or ctx is self.context:
            self._bundles[key] = bundle
        return bundle

    def _solve(self, policy: str, countries: list[str] | None, ctx: Context) -> PlanBundle:
        started = time.perf_counter()
        names = countries or self.countries

        def one(country: str) -> CountryOutcome:
            plan = self.plan_country(country, policy, ctx)
            sim = self._simulate(country, plan, ctx)
            return CountryOutcome(plan, sim, _kpis(plan, sim))

        # Each country is an independent model solved by an external CBC process, so
        # countries run side by side; results keep the country order.
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2, len(names))) as pool:
            outcomes = dict(zip(names, pool.map(one, names), strict=True))
        bundle = PlanBundle(self.year, policy, outcomes, time.perf_counter() - started)
        log.info("Policy %s for %d countries in %.1fs", policy, len(outcomes), bundle.seconds)
        return bundle

    def compare_policies(
        self, countries: list[str] | None = None, policies: tuple[str, ...] = POLICIES
    ) -> pd.DataFrame:
        rows = []
        for policy in policies:
            totals = self.run(policy, countries).totals()
            rows.append({"policy": policy, "description": POLICY_LABELS[policy], **totals})
        frame = pd.DataFrame(rows)
        hold = frame.loc[frame["policy"] == "hold", "net_value"]
        if not hold.empty:
            frame["net_value_vs_hold"] = frame["net_value"] - float(hold.iloc[0])
        return frame

    def flow_resolution_check(self) -> pd.DataFrame:
        """Compare optimizer plans built with monthly versus weekly advertiser flows.

        Each plan is scored by the simulator twice: with the rule that agents under
        notice take no new advertisers, and with greedy dispatch that fills today's free
        slots regardless of planned cuts. Greedy dispatch breaks the ten advertiser
        limit for any plan that cuts headcount, which is why the default rule exists.
        """
        s = self.settings
        months = self.horizon_months()
        month_by_day = month_of_day(self.year, months)
        rows = []
        for flow in ("month", "week"):
            for dispatch in ("notice_aware", "greedy"):
                totals = {
                    "net_value": 0.0,
                    "served": 0.0,
                    "arrivals": 0.0,
                    "avg_active": 0.0,
                    "max_overflow": 0.0,
                }
                waits = []
                for country in self.countries:
                    row = self.dataset.countries.loc[country]
                    stream = self.demand(country, months)
                    plan = optimize_country(
                        country,
                        stream.daily_counts,
                        month_by_day,
                        self.forecast.mean_budget(country)[:months],
                        int(row["agents"]),
                        float(row["salary"]),
                        s.rules,
                        s.assumptions,
                        s.planning,
                        flow_period=flow,
                    )
                    sim = simulate(
                        stream, plan.active, month_by_day, s.rules, s.assumptions, dispatch=dispatch
                    )
                    kpis = _kpis(plan, sim)
                    for key in ("net_value", "served", "arrivals", "avg_active"):
                        totals[key] += kpis[key]
                    totals["max_overflow"] = max(totals["max_overflow"], kpis["max_overflow"])
                    waits.append(sim.waits[sim.wait_months <= 12])
                all_waits = np.concatenate(waits)
                rows.append(
                    {
                        "flows": flow,
                        "dispatch": dispatch,
                        "net_value": totals["net_value"],
                        "service_rate": totals["served"] / totals["arrivals"],
                        "avg_active": totals["avg_active"],
                        "mean_wait_days": float(all_waits.mean()),
                        "p90_wait_days": float(np.percentile(all_waits, 90)),
                        "worst_overflow": totals["max_overflow"],
                    }
                )
        return pd.DataFrame(rows)

    # Uncertainty

    def monte_carlo(
        self,
        policy: str = "optimized",
        runs: int | None = None,
        countries: list[str] | None = None,
        demand_scale: float = 1.0,
    ) -> pd.DataFrame:
        """Rerun the fixed plan on resampled daily demand and sampled uplift."""
        bundle = self.run(policy, countries)
        runs = runs or self.settings.planning.monte_carlo_runs
        ctx = self.context
        if demand_scale != 1.0:
            ctx = self._scaled_context(demand_scale)
        rows = []
        for r in range(runs):
            rng = np.random.default_rng(self.settings.planning.seed + r)
            served = arrivals = uplift = cost = dropped = 0.0
            for country, outcome in bundle.outcomes.items():
                sim = self._simulate(country, outcome.plan, ctx, rng, bootstrap=True, sample_uplift=True)
                t = sim.totals()
                served, arrivals, dropped = (
                    served + t["served"],
                    arrivals + t["arrivals"],
                    dropped + t["dropped"],
                )
                uplift += t["uplift_value"]
                cost += outcome.kpis["total_cost"]
            rows.append(
                {
                    "run": r,
                    "uplift_value": uplift,
                    "total_cost": cost,
                    "net_value": uplift - cost,
                    "service_rate": served / arrivals if arrivals else 1.0,
                    "dropped": dropped,
                }
            )
        return pd.DataFrame(rows)

    def _scaled_context(
        self, scale: float, countries: list[str] | None = None, months: list[int] | None = None
    ) -> Context:
        horizon = self.horizon_months()
        factors = np.ones(horizon)
        for index in range(horizon):
            if not months or (index % 12) + 1 in months:
                factors[index] = scale
        targets = countries or self.countries
        return replace(self.context, multipliers={c: factors for c in targets})

    def sensitivity(
        self,
        scales: tuple[float, ...] = (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3),
        countries: list[str] | None = None,
        policy: str = "optimized",
    ) -> pd.DataFrame:
        """Sign up volume scenarios: the fixed plan under stress versus a plan rebuilt for each volume."""
        base = self.run(policy, countries)
        rows = []
        for scale in scales:
            ctx = self._scaled_context(scale, countries)
            stressed = {}
            for country, outcome in base.outcomes.items():
                sim = self._simulate(country, outcome.plan, ctx)
                stressed[country] = CountryOutcome(outcome.plan, sim, _kpis(outcome.plan, sim))
            fixed = PlanBundle(self.year, policy, stressed)
            replanned = self.run(policy, countries, ctx=ctx, use_cache=False)
            for label, bundle in (("current plan", fixed), ("replanned", replanned)):
                t = bundle.totals()
                rows.append(
                    {
                        "demand_scale": scale,
                        "plan": label,
                        "net_value": t["net_value"],
                        "total_cost": t["total_cost"],
                        "uplift_value": t["uplift_value"],
                        "service_rate": t["service_rate"],
                        "dropped": t["dropped"],
                        "avg_active": t["avg_active"],
                        "mean_wait_days": t["mean_wait_days"],
                        "p90_wait_days": t["p90_wait_days"],
                    }
                )
        return pd.DataFrame(rows)

    # Scenarios

    def scenario(self, params: ScenarioParams, policy: str = "optimized") -> ScenarioResult:
        targets = [c for c in (self.resolve_country(n) for n in params.countries) if c] or self.countries
        ctx = self._scenario_context(params, targets)
        base = self.run(policy)
        rows, plans = [], []
        for country in targets:
            base_outcome = base.outcomes[country]
            if params.replan:
                plan = self.plan_country(
                    country, policy if params.service_target is None else "optimized", ctx
                )
            else:
                plan = replace(
                    base_outcome.plan,
                    salary=float(ctx.dataset.countries.loc[country, "salary"]),
                    rules=ctx.settings.rules,
                    assumptions=ctx.settings.assumptions,
                )
            sim = self._simulate(country, plan, ctx)
            kpis = _kpis(plan, sim)
            row = {"country": country}
            for key in (
                "net_value",
                "total_cost",
                "uplift_value",
                "served",
                "arrivals",
                "dropped",
                "avg_active",
                "service_rate",
                "hires",
                "notices",
            ):
                row[f"{key}_base"] = base_outcome.kpis[key]
                row[f"{key}_scenario"] = kpis[key]
                row[f"{key}_change"] = kpis[key] - base_outcome.kpis[key]
            rows.append(row)
            plans.append(plan.table(self.year))
        return ScenarioResult(params, pd.DataFrame(rows), pd.concat(plans, ignore_index=True))

    def _scenario_context(self, params: ScenarioParams, targets: list[str]) -> Context:
        settings = self.settings
        rules_update: dict[str, object] = {}
        if params.capacity_per_agent:
            rules_update["capacity_per_agent"] = params.capacity_per_agent
        if params.expected_uplift is not None:
            rules_update["uplift_levels"] = [params.expected_uplift]
            rules_update["uplift_probabilities"] = [1.0]
        assumptions_update = {
            k: v
            for k, v in (("queue_policy", params.queue_policy), ("initial_pool", params.initial_pool))
            if v
        }
        planning_update = (
            {"service_target": params.service_target} if params.service_target is not None else {}
        )
        if rules_update or assumptions_update or planning_update:
            settings = settings.with_updates(
                rules=rules_update, assumptions=assumptions_update, planning=planning_update
            )
        dataset = self.dataset
        if params.threshold_multiplier != 1.0:
            dataset = dataset.with_thresholds({c: params.threshold_multiplier for c in targets})
        if params.salary_multiplier != 1.0:
            countries = dataset.countries.copy()
            countries.loc[targets, "salary"] = countries.loc[targets, "salary"] * params.salary_multiplier
            dataset = replace(dataset, countries=countries)
        forecast = self.forecast
        if dataset is not self.dataset and params.threshold_multiplier != 1.0:
            forecast = build_forecast(
                dataset, self.year, settings.planning.lookahead_months, self.forecast.method
            )
        multipliers = None
        if params.demand_multiplier != 1.0:
            multipliers = self._scaled_context(params.demand_multiplier, targets, params.months).multipliers
        return Context(settings, dataset, forecast, multipliers, params.max_hires_per_month)
