"""Workflow CRUD and execution.

A workflow is an autonomous, recurring prompt.  The scheduler (``ray.core.scheduler``)
calls ``run_workflow`` when ``next_run_at`` is due; the service runs it through the same
orchestrator a user turn uses, so every agent/tool/memory is available automatically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ray.db.models import Workflow, WorkflowRun
from ray.db.session import get_sessionmaker
from ray.domain.enums import Modality
from ray.schemas import WorkflowCreate, WorkflowUpdate
from ray.services import user_service


def _compute_next(run_at: datetime | None, interval_minutes: int) -> datetime:
    base = run_at or datetime.now(UTC)
    # Move strictly forward so a backlog doesn't cause a storm.
    now = datetime.now(UTC)
    candidate = base + timedelta(minutes=interval_minutes)
    while candidate <= now:
        candidate += timedelta(minutes=interval_minutes)
    return candidate


async def list_workflows(session: AsyncSession, user_id: uuid.UUID) -> list[Workflow]:
    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.runs))
        .where(Workflow.user_id == user_id)
        .order_by(Workflow.next_run_at)
    )
    return list(result.scalars().unique())


async def get_workflow(
    session: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID
) -> Workflow | None:
    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.runs))
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_workflow(
    session: AsyncSession, user_id: uuid.UUID, data: WorkflowCreate
) -> Workflow:
    workflow = Workflow(
        user_id=user_id,
        name=data.name,
        description=data.description,
        agent=data.agent,
        prompt=data.prompt,
        enabled=data.enabled,
        interval_minutes=data.interval_minutes,
        next_run_at=_compute_next(None, data.interval_minutes),
    )
    session.add(workflow)
    await session.flush()
    result = await session.execute(
        select(Workflow).options(selectinload(Workflow.runs)).where(Workflow.id == workflow.id)
    )
    return result.scalar_one()


async def update_workflow(
    session: AsyncSession,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
) -> Workflow | None:
    workflow = await get_workflow(session, user_id, workflow_id)
    if workflow is None:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        if field in {"created_at", "updated_at"}:
            continue
        setattr(workflow, field, value)

    # Recompute schedule if the interval or explicit next-run changed.
    if data.interval_minutes is not None or data.next_run_at is not None:
        workflow.next_run_at = _compute_next(
            data.next_run_at, data.interval_minutes or workflow.interval_minutes
        )

    await session.flush()
    result = await session.execute(
        select(Workflow).options(selectinload(Workflow.runs)).where(Workflow.id == workflow.id)
    )
    return result.scalar_one()


async def delete_workflow(
    session: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID
) -> bool:
    workflow = await get_workflow(session, user_id, workflow_id)
    if workflow is None:
        return False
    await session.delete(workflow)
    await session.flush()
    return True


async def run_workflow(workflow_id: uuid.UUID) -> WorkflowRun:
    """Execute a workflow through the orchestrator and record the result."""
    # Imports are local to avoid a startup import cycle: orchestrator imports services,
    # and services may be imported by the orchestrator's own modules.
    from ray.core.contracts import RayRequest
    from ray.core.events import ApprovalEvent, DoneEvent
    from ray.core.orchestrator import Orchestrator
    from ray.db.models import Message

    async with get_sessionmaker()() as session:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow {workflow_id} not found")
        if not workflow.enabled:
            raise ValueError(f"Workflow {workflow_id} is disabled")

        user = await user_service.get_user(session, workflow.user_id)
        user_name = user.name if user else "Sir"

        run = WorkflowRun(
            workflow_id=workflow.id,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        request = RayRequest(
            user_id=workflow.user_id,
            message=workflow.prompt,
            input_modality=Modality.TEXT,
            output_modality=Modality.TEXT,
        )

        orchestrator = Orchestrator()
        message_id: uuid.UUID | None = None
        success = True
        error = ""
        try:
            async for event in orchestrator.run(session, request, user_name=user_name):
                if isinstance(event, ApprovalEvent):
                    # Unattended workflows cannot approve side-effecting tools.
                    success = False
                    error = f"Paused for approval: {event.tool}"
                if isinstance(event, DoneEvent):
                    message_id = event.message_id
        except Exception as exc:
            success = False
            error = str(exc)

        output = ""
        if message_id is not None:
            message = await session.get(Message, message_id)
            if message is not None:
                output = message.content
        if not output and error:
            output = error

        run.success = success
        run.output = output
        run.error = error
        run.finished_at = datetime.now(UTC)

        workflow.last_run_at = run.started_at
        workflow.next_run_at = _compute_next(run.started_at, workflow.interval_minutes)

        await session.commit()
        return run


async def get_due_workflows(session: AsyncSession) -> list[Workflow]:
    """Workflows whose next_run_at has passed and are enabled."""
    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.runs))
        .where(
            Workflow.enabled == True,  # noqa: E712
            Workflow.next_run_at <= datetime.now(UTC),
        )
    )
    return list(result.scalars().unique())
