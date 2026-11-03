"""Settings for the planner and the assistant, loaded from TOML."""

from __future__ import annotations

from importlib import resources
import os
from pathlib import Path
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


CONFIG_ENV_VAR = "STAFFPILOT_CONFIG"
REPO_ROOT = Path(__file__).resolve().parents[2]


class DataSettings(BaseModel):
    """Where the teaching team dataset lives and how its sheets are named."""

    path: str = Field(description="Workbook (.xlsx) or folder of CSV files, relative to the repo root")
    salary_sheet: str = "Agent Salary and Threshold"
    signup_sheet: str = "Advertiser Sign-ups"
    staffing_sheet: str = "Existing Agent Staffing"


class RuleSettings(BaseModel):
    """Business rules stated in the topic brief."""

    capacity_per_agent: int = Field(10, ge=1)
    support_days: int = Field(60, ge=1)
    max_wait_days: int = Field(60, ge=0)
    ramp_months: int = Field(1, ge=0, le=3)
    notice_months: int = Field(1, ge=0, le=3)
    fire_cost_share: float = Field(0.40, ge=0)
    uplift_levels: list[float]
    uplift_probabilities: list[float]
    eligibility: Literal["greater", "greater_or_equal"] = "greater"

    @model_validator(mode="after")
    def _check_uplift(self) -> RuleSettings:
        if len(self.uplift_levels) != len(self.uplift_probabilities):
            raise ValueError("uplift_levels and uplift_probabilities must have the same length")
        if abs(sum(self.uplift_probabilities) - 1.0) > 1e-6:
            raise ValueError("uplift_probabilities must sum to 1")
        return self

    @property
    def expected_uplift(self) -> float:
        return float(
            sum(level * p for level, p in zip(self.uplift_levels, self.uplift_probabilities, strict=True))
        )


class AssumptionSettings(BaseModel):
    """Choices the brief leaves open. Kept as switches so their impact can be tested."""

    uplift_base: Literal["annual_budget", "support_window"] = "annual_budget"
    initial_pool: Literal["empty", "carryover"] = "empty"
    queue_policy: Literal["fifo", "budget_priority"] = "fifo"
    pay_during_ramp: bool = True


class PlanningSettings(BaseModel):
    planning_year: int = Field(0, description="0 means the year after the last year in the data")
    expected_year: int = Field(
        0, description="Year the brief asks for; a different planning year raises an alert"
    )
    lookahead_months: int = Field(3, ge=0, le=12)
    occupancy_weeks: int = Field(9, ge=1)
    wait_weeks: int = Field(8, ge=0)
    service_target: float = Field(0.0, ge=0, le=1)
    safety_buffer: float = Field(0.0, ge=0, le=1)
    repair_rounds: int = Field(6, ge=0)
    wait_penalty_per_week: float = Field(
        0.01,
        ge=0,
        le=0.2,
        description="Share of uplift given up per week of waiting, used only to prefer earlier service",
    )
    solver_time_limit: int = Field(60, ge=1)
    monte_carlo_runs: int = Field(30, ge=1)
    seed: int = 7


class LlmSettings(BaseModel):
    default_backend: str = "offline"
    timeout: int = 60
    max_retries: int = 2
    models: dict[str, str] = Field(default_factory=dict)
    fast_models: dict[str, str] = Field(default_factory=dict)
    prices: dict[str, list[float]] = Field(default_factory=dict)
    # Local models served by LM Studio (or Bionic, which uses it) through its OpenAI style API.
    local_url: str = "http://localhost:1234/v1"
    local_timeout: int = 300
    # Requests per minute per provider, for free tiers with tight limits; 0 means no limit.
    requests_per_minute: dict[str, float] = Field(default_factory=dict)


class Settings(BaseModel):
    data: DataSettings
    rules: RuleSettings
    assumptions: AssumptionSettings = Field(default_factory=AssumptionSettings)
    planning: PlanningSettings = Field(default_factory=PlanningSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)

    def data_path(self) -> Path:
        path = Path(self.data.path)
        if path.is_absolute():
            return path
        # Prefer the working directory so the package also works when installed elsewhere.
        local = Path.cwd() / path
        return local if local.exists() else REPO_ROOT / path

    def with_updates(self, **sections: dict[str, Any]) -> Settings:
        """Return a copy with some fields replaced, for example with_updates(planning={"seed": 1})."""
        merged = self.model_dump()
        for section, values in sections.items():
            merged[section].update(values)
        return Settings.model_validate(merged)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_env_file(path: str | Path | None = None) -> list[str]:
    """Copy KEY=VALUE lines from a .env file into the environment.

    Values already set in the shell win, so a key exported in the terminal is never
    replaced. Returns the names that were added. Lines starting with # are ignored.
    With STAFFPILOT_OFFLINE=1 the repository's own .env is left unread, so offline runs
    (and the tests) never pick up real keys.
    """
    if path is None and os.environ.get("STAFFPILOT_OFFLINE", "").strip() in {"1", "true", "yes"}:
        return []
    env_path = Path(path) if path else REPO_ROOT / ".env"
    if not env_path.is_file():
        return []
    added = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        value = value.strip("\"'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value
            added.append(key)
    return added


def load_settings(path: str | Path | None = None) -> Settings:
    """Load the packaged defaults, then apply the first override file found.

    Lookup order: the path argument, the STAFFPILOT_CONFIG environment variable,
    then config/staffpilot.toml in the repository.
    """
    defaults = tomllib.loads(
        resources.files("staffpilot").joinpath("default_config.toml").read_text(encoding="utf-8")
    )
    candidates = [path, os.environ.get(CONFIG_ENV_VAR), REPO_ROOT / "config" / "staffpilot.toml"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            defaults = _deep_merge(defaults, _read_toml(Path(candidate)))
            break
    return Settings.model_validate(defaults)
