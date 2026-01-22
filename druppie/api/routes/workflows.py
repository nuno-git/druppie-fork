"""Workflow API routes.

Provides endpoints for listing available workflows and triggering them directly.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from druppie.api.deps import get_current_user, get_optional_user
from druppie.workflows import Workflow, WorkflowNotFoundError

logger = structlog.get_logger()

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowInfo(BaseModel):
    """Information about a workflow."""
    id: str
    name: str
    description: str
    inputs: list[str]
    entry_point: str


class WorkflowListResponse(BaseModel):
    """Response with list of workflows."""
    workflows: list[WorkflowInfo]
    count: int


class RunWorkflowRequest(BaseModel):
    """Request to run a workflow."""
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResponse(BaseModel):
    """Response from running a workflow."""
    success: bool
    workflow_id: str
    results: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    error: str | None = None


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    user: dict = Depends(get_optional_user),
) -> WorkflowListResponse:
    """List all available workflows.

    Returns:
        List of workflow definitions with their metadata.
    """
    workflow_ids = Workflow.list_workflows()

    workflows = []
    for wf_id in workflow_ids:
        try:
            wf = Workflow(wf_id)
            workflows.append(
                WorkflowInfo(
                    id=wf.definition.id,
                    name=wf.definition.name,
                    description=wf.definition.description,
                    inputs=wf.definition.inputs,
                    entry_point=wf.definition.entry_point,
                )
            )
        except Exception as e:
            logger.warning("workflow_load_error", workflow_id=wf_id, error=str(e))

    return WorkflowListResponse(workflows=workflows, count=len(workflows))


@router.get("/{workflow_id}", response_model=WorkflowInfo)
async def get_workflow(
    workflow_id: str,
    user: dict = Depends(get_optional_user),
) -> WorkflowInfo:
    """Get details of a specific workflow.

    Args:
        workflow_id: The workflow identifier.

    Returns:
        Workflow definition with metadata.
    """
    try:
        wf = Workflow(workflow_id)
        return WorkflowInfo(
            id=wf.definition.id,
            name=wf.definition.name,
            description=wf.definition.description,
            inputs=wf.definition.inputs,
            entry_point=wf.definition.entry_point,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: str,
    request: RunWorkflowRequest,
    user: dict = Depends(get_current_user),
) -> WorkflowRunResponse:
    """Run a workflow with the given inputs.

    Args:
        workflow_id: The workflow identifier.
        request: Request containing workflow inputs.

    Returns:
        Workflow execution results.
    """
    try:
        wf = Workflow(workflow_id)

        logger.info(
            "workflow_run_requested",
            workflow_id=workflow_id,
            user_id=user.get("sub"),
            inputs=list(request.inputs.keys()),
        )

        result = await wf.run(request.inputs)

        return WorkflowRunResponse(
            success=result.get("success", False),
            workflow_id=workflow_id,
            results=result.get("results", []),
            context=result.get("context", {}),
        )

    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")
    except Exception as e:
        logger.error(
            "workflow_run_error",
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        return WorkflowRunResponse(
            success=False,
            workflow_id=workflow_id,
            error=str(e),
        )
