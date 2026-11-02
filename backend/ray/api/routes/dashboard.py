"""Aggregate endpoints for the dashboard.

The HUD shows several panels at once. One request instead of five keeps the shell
from flashing half-populated panels on load, and keeps the panel list a
server-side decision.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ray.db.session import get_session
from ray.domain.enums import TaskStatus
from ray.schemas import AgentRead, CalendarEventRead, MemoryRead, ProjectRead, TaskRead, UserRead
from ray.security.auth import get_current_user_id
from ray.services import (
    agent_service,
    calendar_service,
    memory_service,
    project_service,
    task_service,
    user_service,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardSummary(BaseModel):
    user: UserRead | None
    projects: list[ProjectRead]
    tasks: list[TaskRead]
    today_events: list[CalendarEventRead]
    memories: list[MemoryRead]
    agents: list[AgentRead]
    overdue_count: int


@router.get("", response_model=DashboardSummary)
async def get_dashboard(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    user = await user_service.get_user(session, user_id)
    projects = await project_service.list_projects(session, user_id)
    tasks = await task_service.list_tasks(session, user_id)
    today_events = await calendar_service.dashboard_events(
        session, user_id, start=day_start, end=day_start + timedelta(days=1)
    )
    memories = await memory_service.list_memories(session, user_id, limit=10)
    agents = await agent_service.list_agents(session, user_id)

    overdue_count = sum(
        1
        for task in tasks
        if task.deadline is not None and task.deadline < now and task.status is not TaskStatus.DONE
    )

    return DashboardSummary(
        user=user,
        projects=projects,
        tasks=tasks,
        today_events=today_events,
        memories=memories,
        agents=agents,
        overdue_count=overdue_count,
    )
