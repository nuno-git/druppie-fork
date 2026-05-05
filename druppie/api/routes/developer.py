"""Developer tool — direct execute_coding_task_pi without LLM agent loop.

The developer page lets power users run execute_coding_task_pi directly with
specific arguments (flow, repo_target, task). This avoids the overhead of
creating a chat session → routing via agents → waiting for the developer
agent LLM to call execute_coding_task_pi.

Flow:
1. Create a minimal session (for user/project context)
2. Create a "developer" agent_run record (for tool_call linkage)
3. Create a tool_call record (for PiCodingRunLiveCard frontend polling)
4. Call execute_coding_task_pi in the background
5. Return session_id + tool_call_id + pi_coding_run_id
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from druppie.api.deps import get_current_user, get_db, get_execution_repository
from druppie.db.database import SessionLocal
from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.repositories import ExecutionRepository, SessionRepository

logger = structlog.get_logger()

router = APIRouter(prefix="/developer", tags=["Developer"])


class DeveloperExecuteRequest(BaseModel):
    task: str = Field(..., description="The task prompt for execute_coding_task_pi")
    flow: str = Field("planner", description="pi_agent flow: planner, router, etc.")
    repo_target: str = Field("project", description="project or druppie_core")
    project_id: str | None = Field(None, description="Project UUID for repo_target=project")


class DeveloperExecuteResponse(BaseModel):
    success: bool
    session_id: str
    tool_call_id: str | None = None
    pi_coding_run_id: str | None = None
    message: str | None = None


@router.post("/execute", response_model=DeveloperExecuteResponse)
async def execute_developer_task(
    request: DeveloperExecuteRequest,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    execution_repo: ExecutionRepository = Depends(get_execution_repository),
) -> DeveloperExecuteResponse:
    """Execute a developer task directly, bypassing the agent LLM loop.

    Creates a minimal session + agent_run + tool_call, then spawns
    execute_coding_task_pi in a background task.
    """
    user_id = UUID(user["sub"])

    if not request.task.strip():
        return DeveloperExecuteResponse(success=False, session_id="", message="Task is required")

    project_id = UUID(request.project_id) if request.project_id else None

    session_repo = SessionRepository(db)
    session = session_repo.create(
        user_id=user_id,
        title=f"Dev: {request.task[:80]}",
        project_id=project_id,
    )
    session_id = session.id

    agent_run = execution_repo.create_agent_run(
        session_id=session_id,
        agent_id="developer",
        status=AgentRunStatus.PENDING,
        planned_prompt=request.task,
        sequence_number=0,
    )
    agent_run_id = agent_run.id

    args = {
        "task": request.task,
        "flow": request.flow,
        "repo_target": request.repo_target,
    }
    # Create a synthetic LLM call so the tool call appears in the session
    # chat's timeline (SessionDetail/ChatHelpers look for tool calls under
    # agent_run.llm_calls[].tool_calls[] — without an LLM call, the tool
    # call exists in the DB but is invisible in the session view).
    messages = [{"role": "user", "content": f"Run {request.flow} task: {request.task}"}]
    response_content = json.dumps({
        "content": "",
        "tool_calls": [{
            "id": "dev_" + uuid4().hex[:8],
            "type": "function",
            "function": {"name": "execute_coding_task_pi", "arguments": json.dumps(args)},
        }],
    })
    llm_call_id = execution_repo.create_llm_call(
        session_id=session_id,
        agent_run_id=agent_run_id,
        provider="manual",
        model="developer-tool",
        messages=messages,
        tools=[{"function": {"name": "execute_coding_task_pi", "description": "Run pi_agent"}}],
    )
    execution_repo.update_llm_response(
        llm_call_id=llm_call_id,
        response_content=response_content,
        response_tool_calls=None,
        completion_tokens=0,
        prompt_tokens=0,
        duration_ms=0,
    )

    tool_call_id = execution_repo.create_tool_call(
        session_id=session_id,
        agent_run_id=agent_run_id,
        mcp_server="builtin",
        tool_name="execute_coding_task_pi",
        arguments=args,
        llm_call_id=llm_call_id,
    )

    execution_repo.update_status(agent_run_id, AgentRunStatus.RUNNING)

    tool_call = execution_repo.get_tool_call(tool_call_id)
    if tool_call:
        tool_call.status = "executing"
        db.add(tool_call)

    db.commit()

    async def _run_background():
        from druppie.agents.execute_coding_task_pi import execute_coding_task_pi
        from druppie.db.models.pi_coding_run import PiCodingRun

        bg_db = SessionLocal()
        bg_task = None
        try:
            bg_execution_repo = ExecutionRepository(bg_db)

            # Fire-and-forget: execute_coding_task_pi spawns a Node subprocess
            # that posts events via ingest endpoint, so the PiCodingRun row
            # updates independently of process exit.
            bg_task = asyncio.create_task(execute_coding_task_pi(
                args=args,
                session_id=session_id,
                agent_run_id=agent_run_id,
                execution_repo=bg_execution_repo,
                tool_call_id=tool_call_id,
            ))

            timeout_s = 600
            poll_interval_s = 3
            terminal = False
            status = "running"
            for _ in range(timeout_s // poll_interval_s):
                await asyncio.sleep(poll_interval_s)
                bg_db.expire_all()  # force fresh read, bypass identity map
                pi_run: PiCodingRun | None = (
                    bg_db.query(PiCodingRun)
                    .filter(PiCodingRun.tool_call_id == tool_call_id)
                    .first()
                )
                if pi_run and pi_run.status in ("succeeded", "failed", "stopped"):
                    terminal = True
                    status = pi_run.status
                    break

            # If pi_agent never created a PiCodingRun row, check if it
            # failed early (before reaching the PiCodingRun.create code).
            if not terminal and bg_task.done():
                try:
                    exc = bg_task.exception()
                    if exc:
                        logger.error("pi_agent_startup_failed", error=str(exc))
                except asyncio.CancelledError:
                    pass

            bg_tc = bg_execution_repo.get_tool_call(tool_call_id)
            if bg_tc:
                if terminal:
                    bg_tc.status = "completed" if status == "succeeded" else "failed"
                else:
                    bg_tc.status = "failed"
                    bg_tc.error_message = "pi_agent did not complete within timeout"
                bg_tc.completed_at = datetime.now(timezone.utc)
                bg_db.add(bg_tc)

            if not terminal and bg_task and not bg_task.done():
                bg_task.cancel()
                try:
                    await bg_task
                except asyncio.CancelledError:
                    pass

            bg_execution_repo.update_status(
                agent_run_id,
                AgentRunStatus.COMPLETED if terminal else AgentRunStatus.FAILED,
            )
            bg_session_repo = SessionRepository(bg_db)
            bg_session_repo.update_status(
                session_id,
                SessionStatus.COMPLETED if terminal else SessionStatus.FAILED,
            )
            bg_db.commit()
        except Exception as e:
            logger.error("developer_execute_failed", error=str(e))
            try:
                bg_execution_repo.update_status(agent_run_id, AgentRunStatus.FAILED)
                bg_db.commit()
            except Exception:
                pass
        finally:
            try:
                bg_db.close()
            except Exception:
                pass

    asyncio.create_task(_run_background())

    pi_coding_run_id = None

    logger.info(
        "developer_execute_started",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        tool_call_id=str(tool_call_id),
        flow=request.flow,
        repo_target=request.repo_target,
    )

    return DeveloperExecuteResponse(
        success=True,
        session_id=str(session_id),
        tool_call_id=str(tool_call_id),
        pi_coding_run_id=pi_coding_run_id,
        message="Developer task started in background",
    )
