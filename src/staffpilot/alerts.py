"""Alerts a staffing manager should see before acting on a plan.

They come from the data and the simulated plan, not from a monitoring server: each
rule is a plain check with a threshold, so the reason for every alert is visible.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from staffpilot.planner import RECOMMENDED_POLICY, Planner


log = logging.getLogger(__name__)
LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    level: str  # critical, warning or info
    topic: str
    message: str
    countries: tuple[str, ...] = ()


def _names(countries: list[str], limit: int = 6) -> str:
    shown = ", ".join(countries[:limit])
    return shown + (f" and {len(countries) - limit} more" if len(countries) > limit else "")


def plan_alerts(planner: Planner, policy: str = RECOMMENDED_POLICY) -> list[Alert]:
    s = planner.settings
    alerts: list[Alert] = []
    expected = s.planning.expected_year
    if expected and planner.year != expected:
        alerts.append(
            Alert(
                "critical",
                "data",
                f"This file plans {planner.year}, but the brief asks for {expected}. Load the official course file before "
                "using these numbers.",
            )
        )
    if planner.dataset.repaired_dates:
        alerts.append(
            Alert(
                "info",
                "data",
                f"{planner.dataset.repaired_dates} sign ups had impossible dates (such as 29 February in a normal year) and "
                "were moved to the end of their month.",
            )
        )

    kpis = planner.run(policy).kpi_table().set_index("country")
    value_only = planner.run("optimized").kpi_table().set_index("country")

    low_service = kpis.index[kpis["service_rate"] < 0.98].tolist()
    if low_service:
        alerts.append(
            Alert(
                "critical",
                "service",
                f"Fewer than 98% of eligible advertisers are served in {_names(low_service)}.",
                tuple(low_service),
            )
        )
    overflow = kpis.index[kpis["max_overflow"] > 0].tolist()
    if overflow:
        alerts.append(
            Alert(
                "critical",
                "capacity",
                f"The ten advertiser limit is broken in {_names(overflow)}.",
                tuple(overflow),
            )
        )
    slow = kpis.index[kpis["p90_wait_days"] > 14].tolist()
    if slow:
        alerts.append(
            Alert(
                "warning",
                "waiting",
                f"One in ten advertisers waits more than two weeks in {_names(slow)}.",
                tuple(slow),
            )
        )
    short = kpis.index[kpis["end_agents"] > kpis["start_agents"]].tolist()
    if short:
        alerts.append(
            Alert(
                "warning",
                "hiring",
                f"{_names(short)} must grow the team; hires decided in January only "
                "start in February, so approve them first.",
                tuple(short),
            )
        )
    deep_cuts = kpis.index[kpis["notices"] > 0.5 * kpis["start_agents"]].tolist()
    if deep_cuts:
        alerts.append(
            Alert(
                "warning",
                "people",
                f"{len(deep_cuts)} countries let more than half of their January team "
                "go. Check local notice rules and plan the communication before notices are sent.",
                tuple(deep_cuts),
            )
        )
    # Salary only: the one time firing cost says nothing about whether ongoing support pays.
    unprofitable = value_only.index[value_only["uplift_value"] < value_only["salary_cost"]].tolist()
    if unprofitable:
        alerts.append(
            Alert(
                "warning",
                "value",
                f"In {_names(unprofitable)} support costs more than the uplift it brings "
                "at current salaries; keeping service there is a business decision.",
                tuple(unprofitable),
            )
        )
    alerts.append(
        Alert(
            "info",
            "assumption",
            "The plan assumes uplift applies to the projected annual budget. If it only counts during the 60 days of "
            "support, every policy loses money; confirm this with Google before giving notice.",
        )
    )
    alerts.sort(key=lambda a: LEVEL_ORDER[a.level])
    for alert in alerts:
        if alert.level != "info":
            log.warning("%s alert (%s): %s", alert.level, alert.topic, alert.message)
    return alerts
