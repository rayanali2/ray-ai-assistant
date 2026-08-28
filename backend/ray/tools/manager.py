"""The Tool Manager: the single place a tool call can happen (ADR-0010).

Every tool call in Ray goes through ``invoke``. That is what makes the guarantees in
ADR-0014 structural rather than aspirational: permissions, the approval gate,
timeouts, error normalisation, and the audit row are all in one function, so there is
no code path that can skip them, and no prompt that can talk its way past them.

The manager is also where credentials *would* live once integrations arrive in Phase
5 — handed to the handler, never to the agent.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ray.config import Settings, get_settings
from ray.domain.enums import InvocationStatus, PermissionMode
from ray.llm.base import ToolSpec
from ray.services import tool_service
from ray.services.errors import ServiceError
from ray.tools.types import ToolResult

log = structlog.get_logger()


@dataclass
class ToolContext:
    """What a handler gets. Not what the agent gets."""

    session: AsyncSession
    user_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None


Handler = Callable[[ToolContext, dict[str, object]], Awaitable[dict[str, object]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, object]
    handler: Handler
    side_effect: bool = False
    standing_allow_eligible: bool = True
    """False for anything that writes outside Ray's own database (ADR-0014): those
    always ask, and no amount of clicking "always allow" changes that."""
    summarise: Callable[[dict[str, object]], str] | None = None
    """Renders the payload as the sentence the approval card shows. The user approves
    an action they can read, not a JSON blob."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    def summary(self, arguments: dict[str, object]) -> str:
        if self.summarise is None:
            return f"Run {self.name}"
        return self.summarise(arguments)


@dataclass
class ToolManager:
    tools: dict[str, Tool] = field(default_factory=dict)
    settings: Settings = field(default_factory=get_settings)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def specs(self, allowed: Sequence[str]) -> list[ToolSpec]:
        """The subset of an agent's declared tools that actually exists.

        Agent specs name tools from later phases (`github.read_repo`, `web.search`).
        Filtering here means a Phase 5 integration becomes available to its agent by
        being registered, with no change to the agent.
        """
        return [self.tools[name].spec() for name in allowed if name in self.tools]

    async def invoke(
        self,
        ctx: ToolContext,
        name: str,
        arguments: dict[str, object],
        *,
        allowed: Sequence[str] = (),
    ) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            # Models invent tool names. That is a normal event, not an error state.
            return ToolResult(tool=name, status="failed", error=f"Unknown tool {name!r}.")
        if allowed and name not in allowed:
            log.warning("tool.not_permitted_for_agent", tool=name)
            return ToolResult(
                tool=name, status="denied", error=f"{name} is not available to this agent."
            )

        mode = await tool_service.permission_mode(ctx.session, ctx.user_id, name)
        if mode is PermissionMode.NEVER:
            return ToolResult(
                tool=name, status="denied", error=f"{name} is switched off in Settings."
            )

        if tool.side_effect and not self._standing_allowed(tool, mode):
            return await self._request_approval(ctx, tool, arguments)

        return await self._execute(ctx, tool, arguments)

    def _standing_allowed(self, tool: Tool, mode: PermissionMode) -> bool:
        return mode is PermissionMode.ALWAYS_ALLOW and tool.standing_allow_eligible

    async def _request_approval(
        self, ctx: ToolContext, tool: Tool, arguments: dict[str, object]
    ) -> ToolResult:
        invocation = await tool_service.record(
            ctx.session,
            ctx.user_id,
            tool_name=tool.name,
            payload=arguments,
            side_effect=True,
            status=InvocationStatus.PENDING_APPROVAL,
            conversation_id=ctx.conversation_id,
        )
        # Committed immediately: the approval card the user is about to see refers to
        # this row, and the request that approves it is a different request.
        await ctx.session.commit()
        log.info("tool.awaiting_approval", tool=tool.name, invocation_id=str(invocation.id))
        return ToolResult(
            tool=tool.name,
            status="pending_approval",
            invocation_id=invocation.id,
            data={"summary": tool.summary(arguments), "payload": arguments},
        )

    async def _execute(
        self, ctx: ToolContext, tool: Tool, arguments: dict[str, object]
    ) -> ToolResult:
        """Run a handler and turn anything that goes wrong into a result.

        A tool that raises must not take the turn down with it: the agent is told the
        call failed and can say so, which is the difference between "GitHub auth
        expired" and a fabricated answer (ADR-0010).
        """
        try:
            data = await asyncio.wait_for(
                tool.handler(ctx, arguments), timeout=self.settings.tool_timeout_seconds
            )
        except TimeoutError:
            return await self._log_failure(ctx, tool, arguments, "Timed out.")
        except (ServiceError, ValueError, KeyError, TypeError) as exc:
            # Bad arguments from the model land here: the schema is a hint to the
            # model, not a guarantee.
            return await self._log_failure(ctx, tool, arguments, str(exc) or type(exc).__name__)

        await tool_service.record(
            ctx.session,
            ctx.user_id,
            tool_name=tool.name,
            payload=arguments,
            side_effect=tool.side_effect,
            status=InvocationStatus.EXECUTED,
            conversation_id=ctx.conversation_id,
            result=data,
        )
        return ToolResult(tool=tool.name, status="executed", data=data)

    async def _log_failure(
        self, ctx: ToolContext, tool: Tool, arguments: dict[str, object], error: str
    ) -> ToolResult:
        log.warning("tool.failed", tool=tool.name, error=error)
        await tool_service.record(
            ctx.session,
            ctx.user_id,
            tool_name=tool.name,
            payload=arguments,
            side_effect=tool.side_effect,
            status=InvocationStatus.FAILED,
            conversation_id=ctx.conversation_id,
            error=error,
        )
        return ToolResult(tool=tool.name, status="failed", error=error)

    # -- the approval decision ----------------------------------------------

    async def execute_approved(
        self, session: AsyncSession, user_id: uuid.UUID, invocation_id: uuid.UUID
    ) -> ToolResult | None:
        """Run a call the user approved. ``None`` if there is nothing to approve.

        The payload comes from the row, not from the request, so the action executed
        is the action the card displayed — an approval cannot be widened in flight.
        """
        invocation = await tool_service.get_pending(session, user_id, invocation_id)
        if invocation is None:
            return None
        tool = self.tools.get(invocation.tool_name)
        if tool is None:
            await tool_service.settle(
                invocation, status=InvocationStatus.FAILED, error="Tool no longer exists."
            )
            await session.commit()
            return ToolResult(
                tool=invocation.tool_name, status="failed", error="Tool no longer exists."
            )

        ctx = ToolContext(
            session=session, user_id=user_id, conversation_id=invocation.conversation_id
        )
        try:
            data = await asyncio.wait_for(
                tool.handler(ctx, dict(invocation.payload)),
                timeout=self.settings.tool_timeout_seconds,
            )
        except (TimeoutError, ServiceError, ValueError, KeyError, TypeError) as exc:
            error = "Timed out." if isinstance(exc, TimeoutError) else str(exc)
            await tool_service.settle(invocation, status=InvocationStatus.FAILED, error=error)
            await session.commit()
            return ToolResult(tool=tool.name, status="failed", error=error)

        await tool_service.settle(invocation, status=InvocationStatus.EXECUTED, result=data)
        await session.commit()
        log.info("tool.approved_and_executed", tool=tool.name)
        return ToolResult(tool=tool.name, status="executed", data=data, invocation_id=invocation.id)

    async def reject(
        self, session: AsyncSession, user_id: uuid.UUID, invocation_id: uuid.UUID
    ) -> bool:
        invocation = await tool_service.get_pending(session, user_id, invocation_id)
        if invocation is None:
            return False
        await tool_service.settle(invocation, status=InvocationStatus.REJECTED)
        await session.commit()
        return True


class AgentToolbox:
    """The ``ToolInvoker`` an agent is handed for one turn.

    It closes over the session, the user, and the conversation so an agent cannot
    name a different user's data, and it records what was called so the orchestrator
    can put the tools used into the trace.
    """

    def __init__(self, manager: ToolManager, ctx: ToolContext) -> None:
        self._manager = manager
        self._ctx = ctx
        self.results: list[ToolResult] = []

    def specs(self, allowed: tuple[str, ...]) -> list[ToolSpec]:
        return self._manager.specs(allowed)

    async def call(
        self, name: str, arguments: dict[str, object], *, allowed: tuple[str, ...]
    ) -> ToolResult:
        result = await self._manager.invoke(self._ctx, name, arguments, allowed=allowed)
        self.results.append(result)
        return result


_manager: ToolManager | None = None


def get_manager() -> ToolManager:
    """The process-wide manager, with the internal and integration tools registered."""
    global _manager
    if _manager is None:
        from ray.tools.domain_tools import DOMAIN_TOOLS
        from ray.tools.integration_tools import INTEGRATION_TOOLS
        from ray.tools.internal import INTERNAL_TOOLS

        _manager = ToolManager()
        for tool in INTERNAL_TOOLS:
            _manager.register(tool)
        for tool in INTEGRATION_TOOLS:
            _manager.register(tool)
        for tool in DOMAIN_TOOLS:
            _manager.register(tool)
    return _manager
