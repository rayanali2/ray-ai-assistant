"""Autonomous workflow scheduler.

A single background loop wakes up every minute, finds workflows whose ``next_run_at``
has passed, and executes them through the same orchestrator a human turn uses.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from ray.db.session import get_sessionmaker
from ray.services import workflow_service

log = structlog.get_logger()

_INTERVAL_SECONDS = 60
_scheduler_task: asyncio.Task[None] | None = None
_background: set[asyncio.Task[None]] = set()


async def _tick() -> None:
    """Find and run any due workflows."""
    try:
        async with get_sessionmaker()() as session:
            workflows = await workflow_service.get_due_workflows(session)
        for workflow in workflows:
            task = asyncio.create_task(_run_workflow(workflow.id))
            _background.add(task)
            task.add_done_callback(_background.discard)
    except Exception as exc:
        log.error("scheduler.tick_failed", error=str(exc))


async def _run_workflow(workflow_id: uuid.UUID) -> None:
    try:
        run = await workflow_service.run_workflow(workflow_id)
        log.info(
            "scheduler.workflow_finished",
            workflow_id=str(workflow_id),
            run_id=str(run.id),
            success=run.success,
        )
    except Exception as exc:
        log.error("scheduler.workflow_failed", workflow_id=str(workflow_id), error=str(exc))


async def _loop() -> None:
    while True:
        await _tick()
        await asyncio.sleep(_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_loop())
        log.info("scheduler.started", interval_seconds=_INTERVAL_SECONDS)


async def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
        log.info("scheduler.stopped")

    if _background:
        for task in list(_background):
            task.cancel()
        await asyncio.gather(*_background, return_exceptions=True)
        _background.clear()
