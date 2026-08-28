"""Agents come from the code registry; the database only overrides state (ADR-0005)."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ray.agents.registry import AGENTS, ROUTABLE_AGENTS, get_agent_spec
from ray.db.models import AgentConfig
from ray.services import agent_service


def test_registry_contains_the_specified_agents() -> None:
    assert set(AGENTS) == {
        "executive",
        "planning",
        "coding",
        "learning",
        "research",
        "fitness",
        "content",
        "finance",
    }
    # The executive routes; routing to itself would be a loop.
    assert "executive" not in ROUTABLE_AGENTS


def test_unknown_agent_raises() -> None:
    try:
        get_agent_spec("memory")
    except ValueError as exc:
        # Memory is a service, not an agent (ADR-0005).
        assert "memory" in str(exc)
    else:
        raise AssertionError("expected ValueError")


async def test_agents_default_to_enabled_without_a_database_row(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    agents = await agent_service.list_agents(session, user_id)
    assert len(agents) == len(AGENTS)
    assert all(agent.enabled for agent in agents)


async def test_database_row_can_disable_an_agent(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.add(AgentConfig(user_id=user_id, agent_name="research", enabled=False))
    await session.commit()

    agents = {a.name: a for a in await agent_service.list_agents(session, user_id)}
    assert agents["research"].enabled is False
    assert agents["coding"].enabled is True


async def test_agents_endpoint_exposes_tool_allowlists(auth_client: AsyncClient) -> None:
    agents = {a["name"]: a for a in (await auth_client.get("/agents")).json()}
    assert "github.read_repo" in agents["coding"]["tools"]
    # The planning agent has no business reading repositories.
    assert "github.read_repo" not in agents["planning"]["tools"]
