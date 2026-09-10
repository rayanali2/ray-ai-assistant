import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ray.db.session import get_session
from ray.schemas import (
    WorkflowCreate,
    WorkflowRead,
    WorkflowRunSummary,
    WorkflowUpdate,
)
from ray.security.auth import get_current_user_id
from ray.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowRead]:
    workflows = await workflow_service.list_workflows(session, user_id)
    return [WorkflowRead.model_validate(w) for w in workflows]


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    workflow = await workflow_service.create_workflow(session, user_id, data)
    return WorkflowRead.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    workflow = await workflow_service.get_workflow(session, user_id, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return WorkflowRead.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    workflow = await workflow_service.update_workflow(session, user_id, workflow_id, data)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return WorkflowRead.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    if not await workflow_service.delete_workflow(session, user_id, workflow_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


@router.post("/{workflow_id}/run", response_model=WorkflowRunSummary)
async def run_workflow(
    workflow_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRunSummary:
    workflow = await workflow_service.get_workflow(session, user_id, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    run = await workflow_service.run_workflow(workflow_id)
    return WorkflowRunSummary(
        workflow_id=workflow.id,
        run_id=run.id,
        success=bool(run.success),
        output=run.output,
        error=run.error,
    )
