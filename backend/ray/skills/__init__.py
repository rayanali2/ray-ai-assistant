"""Skills: reusable tool bundles Ray can load at startup (ADR-0010 extension).

A skill is a small, versioned bundle of tools with its own prompt hint.  Built-in skills
ship with Ray; the loader is the same one a future external-skill installer would call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ray.tools.manager import Tool, ToolManager


@dataclass(frozen=True)
class Skill:
    """A named bundle of tools.

    ``register`` is called once at startup and adds the skill's tools to the shared
    ``ToolManager``.  Keeping registration explicit means Ray never silently loads a
    skill that could make unwanted network calls.
    """

    name: str
    description: str
    version: str
    register: Callable[[ToolManager], None]

    def load(self, manager: ToolManager) -> None:
        self.register(manager)


__all__ = ["Skill", "Tool", "ToolManager"]
