"""Ray Core: the pipeline every turn flows through.

It is an async generator rather than a function returning an answer, for two
reasons. Streaming has to be native — bolting it on later would mean buffering the
whole response first. And the trace has to be *recorded* as each step happens, not
reconstructed afterwards or, worse, asked of the model, which would produce a
plausible fiction instead of a fact.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ray.agents.base import AgentContext, AgentFinished, AgentToken
from ray.agents.coding import CodingAgent
from ray.agents.content import ContentAgent
from ray.agents.executive import ExecutiveAgent
from ray.agents.finance import FinanceAgent
from ray.agents.fitness import FitnessAgent
from ray.agents.learning import LearningAgent
from ray.agents.planning import PlanningAgent
from ray.agents.research import ResearchAgent
from ray.agents.router import ExecutiveRouter
from ray.config import Settings, get_settings
from ray.core.contracts import RayRequest, TraceEvent, TraceStage
from ray.core.events import (
    ApprovalEvent,
    DoneEvent,
    ErrorEvent,
    StreamEvent,
    TokenEvent,
    TraceStreamEvent,
)
from ray.db.session import get_sessionmaker
from ray.domain.enums import MessageRole
from ray.llm.base import LLMError
from ray.llm.registry import Degradation, ProviderRegistry, get_registry
from ray.memory.extraction import MemoryExtractor
from ray.memory.retrieval import Retriever, get_retriever
from ray.memory.writer import MemoryWriter
from ray.services import activity_service, agent_service, conversation_service
from ray.tools.manager import AgentToolbox, ToolContext, ToolManager, get_manager

log = structlog.get_logger()

_BACKGROUND: set[asyncio.Task[None]] = set()


def _agent_instance(name: str, providers: ProviderRegistry) -> Any:
    constructors: dict[str, type] = {
        "executive": ExecutiveAgent,
        "planning": PlanningAgent,
        "coding": CodingAgent,
        "learning": LearningAgent,
        "research": ResearchAgent,
        "fitness": FitnessAgent,
        "content": ContentAgent,
        "finance": FinanceAgent,
    }
    return constructors[name](providers)


class Orchestrator:
    def __init__(
        self,
        *,
        providers: ProviderRegistry | None = None,
        retriever: Retriever | None = None,
        writer: MemoryWriter | None = None,
        settings: Settings | None = None,
        tool_manager: ToolManager | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._providers = providers or get_registry()
        self._retriever = retriever or get_retriever(self._settings)
        self._writer = writer or MemoryWriter(
            MemoryExtractor(self._providers), settings=self._settings
        )
        self._tool_manager = tool_manager or get_manager()
        self._router = ExecutiveRouter(self._providers)
        self._last_answer = ("", "")

    async def run(
        self, session: AsyncSession, request: RayRequest, user_name: str
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        trace: list[TraceEvent] = []

        def record(stage: TraceStage, **detail: object) -> TraceStreamEvent:
            trace.append(TraceEvent(stage=stage, detail=detail))
            return TraceStreamEvent(stage=stage, detail=detail)

        conversation = await conversation_service.get_or_create(
            session, request.user_id, request.conversation_id, first_message=request.message
        )
        await conversation_service.add_message(
            session,
            conversation.id,
            role=MessageRole.USER,
            content=request.message,
            input_modality=request.input_modality,
        )
        await session.commit()

        history = await conversation_service.history_for_model(
            session, conversation.id, window=self._settings.history_window
        )
        history = history[:-1]

        memories = await self._retriever.retrieve(
            session, request.user_id, request.message, project_id=request.project_id
        )
        await session.commit()
        yield record(
            "memory",
            count=len(memories),
            top_score=round(max((m.score for m in memories), default=0.0), 3),
            categories=sorted({m.category for m in memories}),
        )

        agents_enabled = {
            a.name for a in await agent_service.list_agents(session, request.user_id) if a.enabled
        }
        routing = await self._router.decide(request.message, enabled=agents_enabled)
        yield record(
            "routing",
            agents=list(routing.agents),
            mode=routing.mode,
            fan_out=routing.fan_out,
            reason=routing.reason,
        )

        tool_ctx = ToolContext(
            session=session,
            user_id=request.user_id,
            conversation_id=conversation.id,
            project_id=request.project_id,
        )
        toolbox = AgentToolbox(self._tool_manager, tool_ctx)
        ctx = AgentContext(
            user_id=request.user_id,
            user_name=user_name,
            message=request.message,
            history=history,
            memories=memories,
            tools=toolbox,
            output_modality=request.output_modality,
            project_id=request.project_id,
        )

        agent_name = "executive"
        content = ""
        speech_text = ""
        degradations: list[Degradation] = []
        agent: Any = None

        try:
            if not routing.agents:
                agent = ExecutiveAgent(self._providers, temperature=self._settings.llm_temperature)
                yield record("agent", agent=agent.name, provider=self._providers.chain()[0])
                async for event in self._stream_agent(agent, ctx):
                    yield event
                content, speech_text = self._last_answer
                agent_name = agent.name
            elif not routing.fan_out:
                agent = _agent_instance(routing.agents[0], self._providers)
                yield record("agent", agent=agent.name, provider=self._providers.chain()[0])
                async for event in self._stream_agent(agent, ctx):
                    yield event
                content, speech_text = self._last_answer
                agent_name = agent.name
            else:
                # Fan-out: specialists run without streaming, then Executive composes.
                outputs: list[dict[str, str]] = []
                for name in routing.agents:
                    agent = _agent_instance(name, self._providers)
                    yield record("agent", agent=agent.name, provider=self._providers.chain()[0])
                    text = await self._run_agent_silent(
                        agent,
                        AgentContext(
                            user_id=ctx.user_id,
                            user_name=ctx.user_name,
                            message=ctx.message,
                            history=ctx.history,
                            memories=ctx.memories,
                            tools=ctx.tools,
                            output_modality=ctx.output_modality,
                            project_id=ctx.project_id,
                        ),
                    )
                    outputs.append({"agent": agent.name, "content": text})

                exec_agent = ExecutiveAgent(
                    self._providers, temperature=self._settings.llm_temperature
                )
                yield record(
                    "agent", agent="executive", provider=self._providers.chain()[0], composing=True
                )
                async for event in self._stream_agent_generator(exec_agent.compose(ctx, outputs)):
                    yield event
                content, speech_text = self._last_answer
                agent_name = "executive"

        except LLMError as exc:
            log.warning("orchestrator.provider_failed", error=str(exc), provider=exc.provider)
            await self._finish_activity(
                session, request, conversation.id, agent_name, started, success=False
            )
            yield ErrorEvent(
                message=f"{exc.provider or 'The model provider'} could not answer: {exc}",
                retryable=exc.is_retryable,
            )
            return

        for degradation in degradations:
            yield record(
                "compose", degraded_from=degradation.failed_provider, reason=degradation.reason
            )

        if toolbox.results:
            yield record(
                "tool",
                tools=[r.tool for r in toolbox.results],
                statuses=[r.status for r in toolbox.results],
                pending=[str(r.invocation_id) for r in toolbox.results if r.invocation_id],
            )
            for result in toolbox.results:
                if result.status == "pending_approval" and result.invocation_id:
                    yield ApprovalEvent(
                        invocation_id=result.invocation_id,
                        tool=result.tool,
                        payload=cast(dict[str, object], result.data.get("payload", {})),
                    )

        duration_ms = int((time.perf_counter() - started) * 1000)
        yield record("compose", duration_ms=duration_ms, spoken_chars=len(speech_text))

        message = await conversation_service.add_message(
            session,
            conversation.id,
            role=MessageRole.ASSISTANT,
            content=content,
            speech_text=speech_text,
            agent_name=agent_name,
            trace={"events": [{"stage": e.stage, **e.detail} for e in trace]},
        )
        await self._finish_activity(
            session, request, conversation.id, agent_name, started, success=True
        )
        self._learn(
            request,
            user_message=request.message,
            assistant_message=content,
            source_message_id=message.id,
        )

        yield DoneEvent(
            conversation_id=conversation.id,
            message_id=message.id,
            agent_name=agent_name,
            speech_text=speech_text,
            duration_ms=duration_ms,
        )

    async def _stream_agent(self, agent: Any, ctx: AgentContext) -> AsyncIterator[StreamEvent]:
        async for event in self._stream_agent_generator(agent.run(ctx)):
            yield event

    async def _stream_agent_generator(
        self, generator: AsyncIterator[object]
    ) -> AsyncIterator[StreamEvent]:
        content = ""
        speech_text = ""
        async for event in generator:
            if isinstance(event, AgentToken):
                yield TokenEvent(text=event.text)
                content += event.text
            elif isinstance(event, AgentFinished):
                content = event.content
                speech_text = event.speech_text
        self._last_answer = (content, speech_text)

    async def _run_agent_silent(self, agent: Any, ctx: AgentContext) -> str:
        content = ""
        async for event in agent.run(ctx):
            if isinstance(event, AgentToken):
                content += event.text
            elif isinstance(event, AgentFinished):
                content = event.content
        return content

    def _learn(
        self,
        request: RayRequest,
        *,
        user_message: str,
        assistant_message: str,
        source_message_id: uuid.UUID,
    ) -> None:
        if not self._settings.memory_enabled or not assistant_message.strip():
            return

        async def learn() -> None:
            async with get_sessionmaker()() as learn_session:
                await self._writer.write_exchange(
                    learn_session,
                    request.user_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    source_message_id=source_message_id,
                    project_id=request.project_id,
                )

        task = asyncio.create_task(learn())
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)

    async def _finish_activity(
        self,
        session: AsyncSession,
        request: RayRequest,
        conversation_id: uuid.UUID,
        agent_name: str,
        started: float,
        *,
        success: bool,
    ) -> None:
        await activity_service.record_activity(
            session,
            user_id=request.user_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            action="respond",
            summary=request.message,
            duration_ms=int((time.perf_counter() - started) * 1000),
            success=success,
        )
        await session.commit()
