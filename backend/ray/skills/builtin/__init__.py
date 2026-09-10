"""Built-in skills that ship with Ray."""

from __future__ import annotations

from ray.skills.builtin.system import register_system_skill
from ray.skills.builtin.utility import register_utility_skill
from ray.tools.manager import ToolManager


def load_builtin_skills(manager: ToolManager) -> None:
    """Register all built-in skills with the shared ToolManager."""
    register_utility_skill(manager)
    register_system_skill(manager)
