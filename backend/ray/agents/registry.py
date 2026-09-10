"""The agent registry.

Agents are code, not database rows (ADR-0005). This module is the single source of
truth for which agents exist and what each is allowed to touch; the database only
records whether the user has disabled one and what it did.

Phase 4 gives these entries real implementations. Declaring them now keeps the
Executive Agent's routing table and the dashboard honest in the meantime.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentSpec:
    name: str
    display_name: str
    description: str
    # Tool names this agent may request. The Tool Manager enforces the list; an
    # agent asking for anything outside it is a bug, not a negotiation.
    tools: tuple[str, ...] = field(default=())


AGENTS: dict[str, AgentSpec] = {
    "executive": AgentSpec(
        name="executive",
        display_name="Executive Agent",
        description=(
            "Understands the request, decides which specialist should handle it, and "
            "composes the final answer in Ray's voice."
        ),
        tools=(
            "memory.search",
            "feedback.create_improvement_task",
            "time.now",
            "date.today",
            "weather.current",
            "news.headlines",
            "web.search",
            "wikipedia.summary",
            "dictionary.define",
            "calculator.compute",
            "system.info",
            "system.open_url",
        ),
    ),
    "planning": AgentSpec(
        name="planning",
        display_name="Planning Agent",
        description="Tasks, deadlines, priorities, scheduling, and time blocking.",
        tools=(
            "tasks.list",
            "tasks.create",
            "tasks.update",
            "calendar.list",
            "calendar.create",
            "time.now",
            "date.today",
            "weather.current",
            "system.info",
        ),
    ),
    "coding": AgentSpec(
        name="coding",
        display_name="Coding Agent",
        description=(
            "Project-aware programming help that teaches rather than replacing the user's work."
        ),
        tools=(
            "projects.get",
            "github.read_repo",
            "github.read_tree",
            "github.read_file",
            "github.read_issues",
            "github.read_commits",
            "files.read",
            "system.info",
            "calculator.compute",
        ),
    ),
    "learning": AgentSpec(
        name="learning",
        display_name="Learning Agent",
        description="Explains, quizzes, and tracks proficiency per topic.",
        tools=(
            "learning.get",
            "learning.update",
            "memory.search",
            "wikipedia.summary",
            "dictionary.define",
            "web.search",
        ),
    ),
    "research": AgentSpec(
        name="research",
        display_name="Research Agent",
        description="Structured investigation using memory, files, and knowledge sources.",
        tools=(
            "memory.search",
            "knowledge.search",
            "files.read",
            "projects.list",
            "web.search",
            "wikipedia.summary",
            "news.headlines",
            "weather.current",
            "dictionary.define",
        ),
    ),
    "fitness": AgentSpec(
        name="fitness",
        display_name="Fitness Agent",
        description="Workout logging, progression tracking, and recovery notes.",
        tools=(
            "fitness.log_workout",
            "fitness.list_workouts",
            "fitness.get_progress",
            "time.now",
            "date.today",
            "weather.current",
            "system.info",
        ),
    ),
    "content": AgentSpec(
        name="content",
        display_name="Content Agent",
        description="Ideas, drafts, and repurposing content across formats.",
        tools=(
            "content.create_idea",
            "content.list_ideas",
            "content.create_draft",
            "content.list_drafts",
            "web.search",
            "news.headlines",
            "wikipedia.summary",
            "system.info",
        ),
    ),
    "finance": AgentSpec(
        name="finance",
        display_name="Finance Agent",
        description="Local budget, spending, income, and savings-goal tracking.",
        tools=(
            "finance.record_transaction",
            "finance.list_transactions",
            "finance.get_summary",
            "calculator.compute",
            "time.now",
            "date.today",
        ),
    ),
}

# The executive routes; it is never a routing target itself.
ROUTABLE_AGENTS: tuple[str, ...] = tuple(name for name in AGENTS if name != "executive")


def get_agent_spec(name: str) -> AgentSpec:
    try:
        return AGENTS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown agent: {name!r}") from exc
