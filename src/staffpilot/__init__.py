"""StaffPilot: monthly support agent staffing with a GenAI planning assistant."""

from staffpilot.config import Settings, load_settings
from staffpilot.data import Dataset, load_dataset
from staffpilot.planner import POLICIES, PlanBundle, Planner
from staffpilot.scenarios import ScenarioParams


__all__ = [
    "POLICIES",
    "Dataset",
    "PlanBundle",
    "Planner",
    "ScenarioParams",
    "Settings",
    "load_dataset",
    "load_settings",
]
__version__ = "0.1.0"
TEAM = "Seven Team-5374"
COPYRIGHT = f"Copyright © 2026 {TEAM}"
