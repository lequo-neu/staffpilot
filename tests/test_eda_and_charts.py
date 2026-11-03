from __future__ import annotations

from matplotlib.figure import Figure

from staffpilot.agent import StaffPilot
from staffpilot.agent.tools import PlannerTools
from staffpilot.eda import figures, profile, write_report
from staffpilot.scenarios import ScenarioParams


def test_profile_reports_quality_and_findings(dataset):
    report = profile(dataset)
    checks = dict(zip(report.quality["check"], report.quality["value"], strict=True))
    assert checks["Rows"] == len(dataset.signups)
    assert checks["Duplicate advertiser ids"] == 0
    assert {"peak_need", "staff_to_need", "daily_cv", "eligible_rate"} <= set(report.countries.columns)
    assert any("Understaffed" in f or "January headcount" in f for f in report.findings)


def test_report_writes_markdown_and_charts(dataset, tmp_path):
    path = write_report(profile(dataset), dataset, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "## Findings" in text and "## Data quality" in text
    assert len(list(tmp_path.glob("*.png"))) == len(figures(profile(dataset))) + 1


def test_every_tool_draws_a_chart(planner):
    tools = PlannerTools(planner)
    outputs = [
        tools.get_plan(["Alpha"], [3]),
        tools.compare_policies(),
        tools.run_scenario(ScenarioParams(countries=["Beta"], demand_multiplier=0.8)),
        tools.sensitivity(["Gamma"]),
        tools.signup_insights("seasonality"),
        tools.signup_insights("eligibility", "Alpha"),
    ]
    for output in outputs:
        assert isinstance(output.chart, Figure), output.name
        assert output.chart.texts or output.chart._suptitle is not None


def test_answers_carry_a_chart_and_read_naturally(planner):
    pilot = StaffPilot(planner)
    answer = pilot.ask("What if sign ups in Beta drop 30% in Q3?")
    assert isinstance(answer.chart, Figure)
    assert "from July to September" in answer.text
    assert "x0.7" not in answer.text and "[" not in answer.text
    lookup = pilot.ask("How many agents does Alpha need in March?")
    assert "In March" in lookup.text and lookup.chart is not None
