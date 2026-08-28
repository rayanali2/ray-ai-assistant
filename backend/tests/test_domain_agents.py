"""Phase 9 specialist agents: fitness, content, finance.

These agents reuse the Task table as a domain journal, so each domain has its own
category string and stores extra fields as JSON in the description. This keeps the
domain surface lightweight while the agents still get structured tools.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ray.agents.registry import get_agent_spec
from ray.llm.registry import ProviderRegistry
from ray.tools.domain_tools import DOMAIN_TOOLS
from ray.tools.manager import ToolContext, ToolManager
from tests.fakes import FakeProvider


def _manager() -> ToolManager:
    manager = ToolManager()
    for tool in DOMAIN_TOOLS:
        manager.register(tool)
    return manager


def _providers() -> ProviderRegistry:
    from ray.config import Settings

    settings = Settings(
        llm_provider="mock",
        llm_fallback_provider=None,
        llm_temperature=0.7,
        memory_enabled=False,
    )
    registry = ProviderRegistry(settings)
    registry.register("mock", FakeProvider())
    return registry


@pytest.mark.asyncio
async def test_fitness_agent_logs_workout(session: AsyncSession, user_id: uuid.UUID) -> None:
    manager = _manager()
    ctx = ToolContext(session=session, user_id=user_id)

    result = await manager.invoke(
        ctx,
        "fitness.log_workout",
        {"title": "Morning run", "exercises": ["5 km easy"], "notes": "Felt good"},
        allowed=("fitness.log_workout",),
    )
    assert result.status == "pending_approval"
    executed = await manager.execute_approved(session, user_id, result.invocation_id)
    assert executed is not None
    assert executed.status == "executed"
    assert executed.data["record"]["title"] == "Morning run"
    assert executed.data["record"]["exercises"] == ["5 km easy"]


@pytest.mark.asyncio
async def test_fitness_agent_lists_and_summarises(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    manager = _manager()
    ctx = ToolContext(session=session, user_id=user_id)
    for title in ("Morning run", "Leg day"):
        result = await manager.invoke(
            ctx,
            "fitness.log_workout",
            {"title": title},
            allowed=("fitness.log_workout",),
        )
        await manager.execute_approved(session, user_id, result.invocation_id)

    list_result = await manager.invoke(
        ctx, "fitness.list_workouts", {}, allowed=("fitness.list_workouts",)
    )
    assert list_result.status == "executed"
    assert list_result.data["count"] == 2

    progress = await manager.invoke(
        ctx, "fitness.get_progress", {}, allowed=("fitness.get_progress",)
    )
    assert progress.status == "executed"
    assert progress.data["total_workouts"] == 2


@pytest.mark.asyncio
async def test_content_agent_creates_and_lists_ideas(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    manager = _manager()
    ctx = ToolContext(session=session, user_id=user_id)

    result = await manager.invoke(
        ctx,
        "content.create_idea",
        {"title": "Why local-first AI matters", "format": "blog", "notes": "focus on privacy"},
        allowed=("content.create_idea", "content.list_ideas"),
    )
    assert result.status == "pending_approval"
    executed = await manager.execute_approved(session, user_id, result.invocation_id)
    assert executed.data["record"]["format"] == "blog"

    list_result = await manager.invoke(
        ctx, "content.list_ideas", {}, allowed=("content.list_ideas",)
    )
    assert list_result.status == "executed"
    assert list_result.data["count"] == 1


@pytest.mark.asyncio
async def test_finance_agent_records_and_summarises(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    manager = _manager()
    ctx = ToolContext(session=session, user_id=user_id)

    result = await manager.invoke(
        ctx,
        "finance.record_transaction",
        {
            "title": "Weekly groceries",
            "amount": 45.2,
            "currency": "USD",
            "type": "expense",
            "tags": ["food"],
        },
        allowed=("finance.record_transaction", "finance.get_summary"),
    )
    assert result.status == "pending_approval"
    executed = await manager.execute_approved(session, user_id, result.invocation_id)
    assert executed.data["record"]["amount"] == 45.2

    # Add income to see totals.
    salary = await manager.invoke(
        ctx,
        "finance.record_transaction",
        {
            "title": "Salary",
            "amount": 1000,
            "currency": "USD",
            "type": "income",
            "tags": ["salary"],
        },
        allowed=("finance.record_transaction",),
    )
    await manager.execute_approved(session, user_id, salary.invocation_id)

    summary = await manager.invoke(ctx, "finance.get_summary", {}, allowed=("finance.get_summary",))
    assert summary.status == "executed"
    assert summary.data["by_currency"]["USD"]["expense"] == 45.2
    assert summary.data["by_currency"]["USD"]["income"] == 1000


def test_agent_specs_exist() -> None:
    assert get_agent_spec("fitness").tools == (
        "fitness.log_workout",
        "fitness.list_workouts",
        "fitness.get_progress",
    )
    assert get_agent_spec("content").tools[0] == "content.create_idea"
    assert get_agent_spec("finance").tools[0] == "finance.record_transaction"


@pytest.mark.asyncio
async def test_routes_to_fitness_agent_by_keyword() -> None:
    from ray.agents.router import ExecutiveRouter

    registry = _providers()
    router = ExecutiveRouter(registry)
    decision = await router.decide(
        "Log my workout",
        enabled={"fitness", "content", "finance"},
    )
    assert decision.agents == ("fitness",)
    assert decision.mode == "keyword"
