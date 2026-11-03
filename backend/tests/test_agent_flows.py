"""Specialist agent flows: the agent loop calls tools and emits trace events."""

import json
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ray.agents.base import AgentContext, AgentFinished, AgentToken
from ray.agents.planning import PlanningAgent
from ray.agents.research import ResearchAgent
from ray.config import get_settings
from ray.domain.enums import Modality
from ray.integrations.knowledge import NotionAdapter
from ray.llm.registry import ProviderRegistry
from ray.services import integration_service, tool_service
from ray.tools.manager import AgentToolbox, ToolContext, get_manager
from tests.fakes import FakeProvider


def _settings():
    # Route to the fake test double, never to a real model.
    return get_settings().model_copy(update={"llm_provider": "mock", "llm_fallback_provider": None})


async def _run_agent(agent, ctx: AgentContext) -> tuple[str, list[str]]:
    text = ""
    tool_names: list[str] = []
    async for event in agent.run(ctx):
        if isinstance(event, AgentToken):
            text += event.text
        elif isinstance(event, AgentFinished):
            text = event.content
    for result in ctx.tools.results:
        tool_names.append(result.tool)
    return text, tool_names


async def test_planning_agent_calls_task_list(session: AsyncSession, user_id: uuid.UUID) -> None:
    """A planning request routes to the Planning Agent and reads the user's tasks."""
    provider = FakeProvider(
        ["Done."],
        tool_routing={"tasks.list": {}},
    )
    registry = ProviderRegistry(_settings())
    registry.register("mock", provider)

    manager = get_manager()
    ctx = AgentContext(
        user_id=user_id,
        user_name="Rayan",
        message="Plan my week",
        history=[],
        tools=AgentToolbox(manager, ToolContext(session=session, user_id=user_id)),
        output_modality=Modality.TEXT,
    )
    agent = PlanningAgent(registry)

    text, tools = await _run_agent(agent, ctx)

    assert "tasks.list" in tools
    assert text
    assert provider.calls
    # The first planning decision offered the tool, the second streamed the answer.
    assert any(c.tools for c in provider.calls)


@pytest.mark.parametrize("approve", [True, False])
async def test_research_append_requests_approval_before_writing(
    session: AsyncSession, user_id: uuid.UUID, auth_client: httpx.AsyncClient, monkeypatch, approve
) -> None:
    payload = {"page_id": "test-page", "content": "Ray append test"}
    provider = FakeProvider(tool_routing={"notion.append": payload})
    registry = ProviderRegistry(_settings())
    registry.register("mock", provider)
    requests = []

    def wire(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:

        async def resolve(*args, **kwargs):
            return NotionAdapter("test-token", client=client)

        monkeypatch.setattr(integration_service, "resolve_adapter", resolve)
        ctx = AgentContext(
            user_id=user_id,
            user_name="Test User",
            message="Append the line 'Ray append test' to Notion page test-page. "
            "Request approval and wait.",
            tools=AgentToolbox(get_manager(), ToolContext(session=session, user_id=user_id)),
        )
        text, tools = await _run_agent(ResearchAgent(registry), ctx)

        assert tools == ["notion.append"]
        assert "need your approval" in text
        assert not requests
        assert len(provider.calls) == 1
        request = provider.calls[0]
        assert "To request approval for a write, call the write tool" in request.system
        assert 'conversational "yes"' in request.system
        spec = next(tool for tool in request.tools if tool.name == "notion.append")
        assert spec.parameters["required"] == ["page_id", "content"]
        assert "queues a pending approval" in spec.description

        pending = await tool_service.list_pending(session, user_id)
        assert len(pending) == 1
        assert pending[0].payload == payload
        action = "approve" if approve else "reject"
        response = await auth_client.post(
            f"/approvals/{pending[0].id}/{action}", json={"always_allow": False}
        )
        assert response.status_code == 200
        assert response.json()["invocation"]["status"] == ("executed" if approve else "rejected")
        assert len(requests) == int(approve)
        if approve:
            assert requests[0].method == "PATCH"
            assert requests[0].url.path == "/v1/blocks/test-page/children"
            children = json.loads(requests[0].content)["children"]
            assert len(children) == 1
            assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == payload["content"]
        assert not await tool_service.list_pending(session, user_id)
