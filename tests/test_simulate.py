"""The simulator is the yardstick for every plan, so its rules are tested on cases small enough to check by hand."""

from __future__ import annotations

import numpy as np
import pytest

from staffpilot.config import load_settings
from staffpilot.forecast import DemandStream
from staffpilot.simulate import simulate


SETTINGS = load_settings()
RULES, ASSUME = SETTINGS.rules, SETTINGS.assumptions


def _stream(days: int, arrivals: dict[int, list[float]], initial=None) -> DemandStream:
    return DemandStream([np.array(arrivals.get(d, []), dtype=float) for d in range(days)], initial or [])


def _months(days: int) -> np.ndarray:
    return np.minimum(np.arange(days) // 30, 11)


def test_without_agents_everyone_leaves_after_sixty_days():
    stream = _stream(120, {0: [1000.0] * 5})
    result = simulate(stream, np.zeros(12), _months(120), RULES, ASSUME)
    assert result.totals(12)["served"] == 0
    assert result.totals(12)["dropped"] == 5
    # Day 61 is the first day the wait exceeds 60 days; it falls in the third 30 day month.
    assert result.monthly.loc[2, "dropped"] == 5


def test_slot_frees_exactly_after_sixty_days_of_support():
    stream = _stream(100, {0: [1000.0] * 10, 1: [1000.0]})
    result = simulate(stream, np.ones(12), _months(100), RULES, ASSUME)
    assert max(result.waits.tolist()) == 59  # the eleventh advertiser waits from day 1 to day 60
    assert result.totals(12)["served"] == 11


def test_capacity_is_never_exceeded_with_constant_headcount():
    rng = np.random.default_rng(1)
    arrivals = {d: [5000.0] * int(rng.poisson(4)) for d in range(360)}
    result = simulate(_stream(360, arrivals), np.full(12, 3), _months(360), RULES, ASSUME)
    assert result.monthly["max_overflow"].max() <= 0
    assert (result.monthly["utilization"] <= 1.0 + 1e-9).all()


def test_every_advertiser_is_accounted_for():
    rng = np.random.default_rng(2)
    arrivals = {d: [3000.0] * int(rng.poisson(6)) for d in range(360)}
    initial = [(-10, 2000.0), (-30, 2000.0)]
    result = simulate(_stream(360, arrivals, initial), np.full(12, 4), _months(360), RULES, ASSUME)
    c = result.cohorts
    total_in = sum(len(v) for v in arrivals.values()) + len(initial)
    assert c["arrivals"].sum() == total_in
    assert c["served"].sum() + c["dropped"].sum() + c["pending"].sum() == total_in


def test_expected_uplift_value_uses_the_brief_distribution():
    assert RULES.expected_uplift == pytest.approx(0.135)
    result = simulate(_stream(30, {0: [10000.0, 20000.0]}), np.ones(12), _months(30), RULES, ASSUME)
    assert result.monthly["uplift_value"].sum() == pytest.approx(0.135 * 30000.0)


def test_sampled_uplift_averages_to_the_expected_value():
    stream = _stream(5, {0: [1000.0] * 4000})
    result = simulate(
        stream, np.full(12, 400), _months(5), RULES, ASSUME, np.random.default_rng(0), sample_uplift=True
    )
    assert result.monthly["uplift_value"].sum() / 4_000_000 == pytest.approx(0.135, abs=0.004)


def test_budget_priority_serves_the_largest_budget_first():
    priority = ASSUME.model_copy(update={"queue_policy": "budget_priority"})
    short_wait = RULES.model_copy(update={"max_wait_days": 30})
    stream = _stream(70, {0: [1000.0] * 10 + [50.0, 90000.0]})
    result = simulate(stream, np.ones(12), _months(70), short_wait, priority)
    fifo = simulate(stream, np.ones(12), _months(70), short_wait, ASSUME)
    assert result.monthly["uplift_value"].sum() > fifo.monthly["uplift_value"].sum()


def test_support_window_assumption_scales_value():
    window = ASSUME.model_copy(update={"uplift_base": "support_window"})
    base = simulate(_stream(10, {0: [36500.0]}), np.ones(12), _months(10), RULES, ASSUME)
    short = simulate(_stream(10, {0: [36500.0]}), np.ones(12), _months(10), RULES, window)
    assert short.monthly["uplift_value"].sum() == pytest.approx(base.monthly["uplift_value"].sum() * 60 / 365)


def test_greedy_dispatch_breaks_the_limit_when_headcount_is_cut():
    """Why agents under notice must not take new advertisers."""
    stream = _stream(90, {d: [1000.0] * 3 for d in range(40)})
    active = np.array([4, 1] + [1] * 10)
    greedy = simulate(stream, active, _months(90), RULES, ASSUME, dispatch="greedy")
    aware = simulate(stream, active, _months(90), RULES, ASSUME)
    assert greedy.monthly["max_overflow"].max() > 0
    assert aware.monthly["max_overflow"].max() <= 0


def test_agents_start_the_year_with_no_advertisers():
    result = simulate(_stream(5, {}), np.full(12, 3), _months(5), RULES, ASSUME)
    assert result.monthly.loc[0, "occupied_slot_days"] == 0
