"""Agent test tool — run any agent directly in an empty session.

The agent testing page lets power users pick any agent from YAML definitions
and run it directly with a custom prompt. The agent runs with full capability:
done(), subagents(), all its MCP tools, and sandbox if configured.

Flow:
1. Create a minimal session (for DB storage / event persistence)
2. Create an agent_run record for the selected agent
3. Return session_id + agent_run_id immediately
4. Run the agent via AgentV2 in a background task
5. Frontend polls the agent run status until completion
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from druppie.api.deps import get_current_user, get_db, get_execution_repository
from druppie.api.routes.agents import load_agent_definitions
from druppie.domain.common import AgentRunStatus
from druppie.repositories import ExecutionRepository, SessionRepository

logger = structlog.get_logger()

router = APIRouter(prefix="/agent-test", tags=["Agent Test"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class AgentTestExecuteRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID from YAML definition")
    prompt: str = Field(..., description="The task prompt to give the agent")
    project_id: str | None = Field(None, description="Project UUID, required if agent has git: current_project")


class AgentTestExecuteResponse(BaseModel):
    success: bool
    session_id: str
    agent_run_id: str | None = None
    message: str | None = None


class AgentTestRunResponse(BaseModel):
    status: str
    agent_id: str
    error_message: str | None = None


# =============================================================================
# HELPERS
# =============================================================================


def _get_agent_git_scope(agent_id: str) -> str | None:
    """Return the git_scope for an agent, or None if no sandbox."""
    agents = load_agent_definitions()
    for a in agents:
        if a.id == agent_id:
            return a.git_scope
    return None


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/execute", response_model=AgentTestExecuteResponse)
async def execute_agent_test(
    request: AgentTestExecuteRequest,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    execution_repo: ExecutionRepository = Depends(get_execution_repository),
) -> AgentTestExecuteResponse:
    """Run any agent directly with a custom prompt.

    Creates a minimal session + agent_run, then spawns the agent via
    AgentV2 in a background task. The frontend polls for completion.
    """
    user_id = UUID(user["sub"])

    # Validate prompt
    if not request.prompt.strip():
        return AgentTestExecuteResponse(success=False, session_id="", message="Prompt is required")

    # Validate agent exists
    agent_defs = load_agent_definitions()
    agent_def = None
    for a in agent_defs:
        if a.id == request.agent_id:
            agent_def = a
            break

    if not agent_def:
        return AgentTestExecuteResponse(
            success=False, session_id="",
            message=f"Agent '{request.agent_id}' not found in definitions",
        )

    # Check git scope requirements
    project_id = UUID(request.project_id) if request.project_id else None
    if agent_def.git_scope == "current_project" and not project_id:
        return AgentTestExecuteResponse(
            success=False, session_id="",
            message=f"Agent '{request.agent_id}' requires a project (git scope: current_project)",
        )

    # Create minimal session
    session_repo = SessionRepository(db)
    session = session_repo.create(
        user_id=user_id,
        title=f"Agent Test: {request.agent_id}",
        project_id=project_id,
    )
    session_id = session.id

    # Create agent_run
    agent_run = execution_repo.create_agent_run(
        session_id=session_id,
        agent_id=request.agent_id,
        status=AgentRunStatus.PENDING,
        planned_prompt=request.prompt,
        sequence_number=0,
    )
    agent_run_id = agent_run.id
    db.commit()

    # Run agent in background via orchestrator (handles execution, pause,
    # completion, session status, and follow-up pending runs from make_plan)
    from druppie.core.background_tasks import create_tracked_task, run_session_task

    async def task(ctx):
        await ctx.orchestrator.execute_pending_runs(session_id)

    create_tracked_task(
        run_session_task(session_id, task, "agent_test_background"),
        name=f"agent-test-{session_id}",
    )

    return AgentTestExecuteResponse(
        success=True,
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        message=f"Agent '{request.agent_id}' started",
    )


@router.get("/runs/{agent_run_id}", response_model=AgentTestRunResponse)
async def get_agent_test_run(
    agent_run_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    execution_repo: ExecutionRepository = Depends(get_execution_repository),
) -> AgentTestRunResponse:
    """Get the status and result of an agent test run."""
    run_id = UUID(agent_run_id)
    agent_run = execution_repo.get_by_id(run_id)

    if not agent_run:
        from druppie.api.errors import NotFoundError
        raise NotFoundError("agent_run", agent_run_id)

    return AgentTestRunResponse(
        status=agent_run.status.value if hasattr(agent_run.status, "value") else agent_run.status,
        agent_id=agent_run.agent_id,
        error_message=getattr(agent_run, "error_message", None),
    )
