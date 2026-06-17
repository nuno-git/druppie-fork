"""Sessions API routes.

Clean architecture version - routes are thin and delegate to services.

Routes handle:
- HTTP request/response
- Authentication extraction
- Calling services

Services handle:
- Permission checks
- Business logic
- Calling repositories

This file went from 776 lines to ~80 lines by moving logic to services/repositories.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from uuid import UUID
import structlog

from druppie.api.deps import (
    get_current_user,
    get_user_roles,
    get_session_service,
    get_execution_repository,
)
from druppie.services import SessionService
from druppie.domain import SessionDetail, SessionStatus
from druppie.core.background_tasks import create_session_task, run_session_task, SessionTaskConflict

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/sessions")
async def list_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """List sessions for current user.

    Returns paginated list of session summaries for the sidebar/listing.
    Admins can see all sessions; regular users only see their own.

    Query Parameters:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        status: Optional status filter (active, completed, failed, etc.)

    Returns:
        Paginated list of SessionSummary objects
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Admin can see all sessions
    if "admin" in user_roles:
        user_id = None  # Don't filter by user

    sessions, total = service.list_for_user(
        user_id=user_id,
        page=page,
        limit=limit,
        status=status,
        user_roles=user_roles,
    )

    return {
        "items": sessions,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
) -> SessionDetail:
    """Get complete session detail with chat timeline.

    Returns the full session including:
    - Basic session info (title, status, token usage)
    - Project info if associated
    - Chat timeline with messages and agent runs

    The chat timeline is a chronological list of:
    - system_message: Initial system prompt
    - user_message: User inputs
    - agent_run: Agent executions with LLM calls and tool executions
    - assistant_message: Final agent responses

    Authorization:
    - Session owner can view
    - Admins can view any session
    - Users with pending approvals for this session can view

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User cannot access this session
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    detail = service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    logger.info("session_retrieved", session_id=str(session_id), user_id=str(user_id))
    return detail


class DeleteSessionsRequest(BaseModel):
    """Body for session deletion."""
    session_ids: list[UUID] | None = None


@router.delete("/sessions")
async def delete_sessions(
    body: DeleteSessionsRequest | None = Body(None),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Delete sessions.

    Unified endpoint for single and batch deletion:
    - If session_ids is provided, deletes those specific sessions.
    - If session_ids is omitted/null, deletes all sessions for the user (admins: all sessions).

    Returns:
        Success confirmation with count of deleted sessions
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    if body and body.session_ids is not None:
        count = service.delete_many(body.session_ids, user_id, user_roles)
    else:
        if "admin" in user_roles:
            user_id = None
        count = service.delete_all_for_user(user_id)

    logger.info("sessions_deleted", user_id=str(user["sub"]), count=count)
    return {"success": True, "deleted_count": count}


# =============================================================================
# UNIFIED RETRY
# =============================================================================


class RetryRequest(BaseModel):
    """Optional body for retry endpoint."""
    planned_prompt: str | None = None


async def _run_retry_background(
    session_id: UUID,
    agent_run_id: UUID,
    planned_prompt: str | None = None,
) -> None:
    """Unified retry background task.

    For top-level runs (no parent): rolls back target + subsequent runs and re-executes pipeline.
    For nested runs (any depth): resets target + later siblings, clears parent state,
    re-runs the sibling chain, then resumes the parent via continue_run().
    """

    async def task(ctx):
        from druppie.core.mcp_config import get_mcp_config
        from druppie.execution.mcp_http import MCPHttp
        from druppie.services import RevertService

        mcp_http = MCPHttp(get_mcp_config())
        revert_service = RevertService(ctx.execution_repo, ctx.session_repo, mcp_http)

        agent_run = ctx.execution_repo.get_by_id_for_session(agent_run_id, session_id)

        if agent_run.parent_run_id is None:
            # Top-level run: rollback + re-execute pipeline
            result = await revert_service.retry_from_run(
                session_id, agent_run_id, planned_prompt=planned_prompt,
            )
            logger.info("retry_revert_complete", session_id=str(session_id), result=result)
            for warning in result.get("warnings", []):
                logger.warning("retry_revert_warning", session_id=str(session_id), warning=warning)
            await ctx.orchestrator.execute_pending_runs(session_id)
        else:
            # Nested run: reset target only, keep paused siblings, run ALL in parallel
            result = await revert_service.retry_nested_subagent_run(
                session_id, agent_run_id, planned_prompt=planned_prompt,
            )
            logger.info("retry_nested_reset_complete", session_id=str(session_id), result=result)

            parent_run_id = UUID(result["parent_run_id"])

            from druppie.db.models.agent_run import AgentRun as AgentRunModel
            from druppie.agents.runtime_v2 import AgentV2 as Agent
            from druppie.domain.common import AgentRunStatus
            import asyncio

            # Query siblings BEFORE launching anything so we know the full set
            paused_siblings = (
                ctx.execution_repo.db.query(AgentRunModel)
                .filter(
                    AgentRunModel.session_id == session_id,
                    AgentRunModel.parent_run_id == parent_run_id,
                    AgentRunModel.id != agent_run_id,
                    AgentRunModel.status == AgentRunStatus.PAUSED_USER.value,
                )
                .order_by(AgentRunModel.created_at)
                .all()
            )

            agent_run = ctx.execution_repo.get_by_id_for_session(agent_run_id, session_id)
            target_prompt = planned_prompt if planned_prompt is not None else (agent_run.planned_prompt or "")

            async def _run_in_own_db(run_id, agent_id, prompt, is_continue):
                from druppie.db.database import SessionLocal
                from druppie.repositories import ExecutionRepository, SessionRepository
                from druppie.execution import Orchestrator

                db = SessionLocal()
                try:
                    orch = Orchestrator(
                        session_repo=SessionRepository(db),
                        execution_repo=ExecutionRepository(db),
                        project_repo=ctx.project_repo,
                        question_repo=ctx.question_repo,
                    )
                    ctx_build = orch.build_project_context(session_id)
                    if is_continue:
                        orch.execution_repo.update_status(run_id, AgentRunStatus.RUNNING)
                        orch.execution_repo.commit()
                        ag = Agent(agent_id, db=db, session_id=str(session_id))
                        res = await ag.continue_run(
                            session_id=session_id,
                            agent_run_id=run_id,
                            context=ctx_build,
                        )
                        return orch._handle_agent_resume_result(
                            session_id, run_id, res, agent_id=agent_id,
                        )
                    else:
                        return await orch.run_agent(
                            session_id=session_id,
                            agent_run_id=run_id,
                            agent_id=agent_id,
                            prompt=prompt,
                            context=ctx_build,
                        )
                finally:
                    db.close()

            tasks = [
                _run_in_own_db(agent_run_id, agent_run.agent_id, target_prompt, False)
            ] + [
                _run_in_own_db(s.id, s.agent_id, None, True)
                for s in paused_siblings
            ]

            all_results = await asyncio.gather(*tasks)

            if any(r == "paused" for r in all_results):
                return

            # All children done — patch subagents ToolCall and resume parent
            ctx.session_repo.db.expire_all()
            ctx.orchestrator._patch_paused_subagents_tool_call(parent_run_id, session_id)
            ctx.execution_repo.update_status(parent_run_id, AgentRunStatus.RUNNING)
            ctx.session_repo.update_status(session_id, SessionStatus.ACTIVE)
            ctx.execution_repo.commit()

            parent_run = ctx.execution_repo.get_by_id(parent_run_id)
            parent_agent = Agent(parent_run.agent_id, db=ctx.execution_repo.db)
            parent_context = ctx.orchestrator.build_project_context(session_id)
            parent_result = await parent_agent.continue_run(
                session_id=session_id,
                agent_run_id=parent_run_id,
                context=parent_context,
            )
            parent_status = ctx.orchestrator._handle_agent_resume_result(
                session_id, parent_run_id, parent_result, agent_id=parent_run.agent_id,
            )

            if parent_status == "paused":
                ctx.session_repo.db.expire_all()
                refreshed_parent = ctx.execution_repo.get_by_id(parent_run_id)
                chain_done = await ctx.orchestrator._walk_parent_chain(
                    session_id, refreshed_parent, ctx.execution_repo.db,
                )
                if chain_done:
                    await ctx.orchestrator.execute_pending_runs(session_id)
            else:
                ctx.session_repo.db.expire_all()
                next_pending = ctx.execution_repo.get_next_pending(session_id)
                if next_pending:
                    await ctx.orchestrator.execute_pending_runs(session_id)
                else:
                    ctx.session_repo.update_status(session_id, SessionStatus.COMPLETED)
                    ctx.session_repo.commit()

    await run_session_task(session_id, task, "retry_background")


@router.post("/sessions/{session_id}/retry/{agent_run_id}")
async def retry_run(
    session_id: UUID,
    agent_run_id: UUID,
    body: RetryRequest | None = Body(None),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Unified retry endpoint.

    For top-level runs (no parent), rolls back target + subsequent runs and re-executes pipeline.
    For nested runs (any depth), re-runs that single agent standalone.

    Args:
        session_id: Session containing the run to retry
        agent_run_id: Agent run to retry

    Returns:
        Success response with session_id
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Atomically lock and transition session to ACTIVE
    try:
        service.lock_for_retry(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "retry_requested",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        user_id=str(user_id),
    )

    try:
        create_session_task(
            session_id,
            _run_retry_background(
                session_id=session_id,
                agent_run_id=agent_run_id,
                planned_prompt=body.planned_prompt if body else None,
            ),
            name=f"retry-{session_id}",
            skip_lock=True,
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start retry background task")
        raise

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Retry started",
    }


# =============================================================================
# REDIRECT AGENT RUN
# =============================================================================


class RedirectRequest(BaseModel):
    """Body for redirect endpoint."""
    target_agent: str
    prompt: str | None = None


async def _run_redirect_background(
    session_id: UUID,
    agent_run_id: UUID,
    target_agent: str,
    prompt: str | None = None,
) -> None:
    """Redirect an agent run to a different agent in background.

    Stops the current run, changes it to the target agent, resets subsequent
    runs, and re-executes the pipeline.
    """

    async def task(ctx):
        from druppie.core.mcp_config import get_mcp_config
        from druppie.execution.mcp_http import MCPHttp
        from druppie.services import RevertService

        mcp_http = MCPHttp(get_mcp_config())
        revert_service = RevertService(ctx.execution_repo, ctx.session_repo, mcp_http)

        # Revert the target run and all subsequent runs
        result = await revert_service.retry_from_run(
            session_id, agent_run_id, planned_prompt=prompt,
        )
        logger.info("redirect_revert_complete", session_id=str(session_id), result=result)

        # Change the agent_id on the target run
        ctx.execution_repo.redirect_run(agent_run_id, target_agent, new_prompt=prompt)
        ctx.execution_repo.commit()
        logger.info(
            "redirect_agent_changed",
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
            target_agent=target_agent,
        )

        # Re-execute the pipeline
        await ctx.orchestrator.execute_pending_runs(session_id)

    await run_session_task(session_id, task, "redirect_background")


@router.post("/sessions/{session_id}/redirect/{agent_run_id}")
async def redirect_run(
    session_id: UUID,
    agent_run_id: UUID,
    body: RedirectRequest,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Redirect an agent run to a different agent.

    Stops the current/completed run, changes it to the target agent,
    resets all subsequent runs, and re-executes the pipeline.
    This is an atomic "stop + change agent + retry" operation.

    Args:
        session_id: Session containing the run to redirect
        agent_run_id: Agent run to redirect
        body: Target agent ID and optional new prompt
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    try:
        service.lock_for_retry(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "redirect_requested",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        target_agent=body.target_agent,
        user_id=str(user_id),
    )

    try:
        create_session_task(
            session_id,
            _run_redirect_background(
                session_id=session_id,
                agent_run_id=agent_run_id,
                target_agent=body.target_agent,
                prompt=body.prompt,
            ),
            name=f"redirect-{session_id}",
            skip_lock=True,
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start redirect background task")
        raise

    return {
        "success": True,
        "session_id": str(session_id),
        "message": f"Redirect to {body.target_agent} started",
    }


class ResumeRequest(BaseModel):
    """Optional body for resume endpoint."""
    contexts: dict[str, str] | None = None


async def _run_resume_background(
    session_id: UUID,
    contexts: dict[str, str] | None = None,
) -> None:
    """Resume a paused session in background."""

    async def task(ctx):
        await ctx.orchestrator.resume_paused_session(
            session_id,
            contexts=contexts,
        )

    await run_session_task(session_id, task, "resume_background")


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: UUID,
    body: ResumeRequest | None = Body(None),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Resume a paused session.

    Spawns a background task that continues the paused agent run
    and then executes remaining pending runs.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Only the session owner or an admin can control the session.
    service.require_owner_or_admin(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Atomically lock and transition session to ACTIVE
    try:
        service.lock_for_resume(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "resume_session_requested",
        session_id=str(session_id),
        user_id=str(user_id),
    )

    try:
        create_session_task(
            session_id,
            _run_resume_background(
                session_id=session_id,
                contexts=body.contexts if body else None,
            ),
            name=f"resume-{session_id}",
            skip_lock=True,
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start resume background task")
        raise

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session resuming",
    }


@router.get("/sessions/{session_id}/resumable")
async def get_resumable_runs(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    execution_repo=Depends(get_execution_repository),
    user: dict = Depends(get_current_user),
):
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    service.require_owner_or_admin(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    from druppie.db.models.agent_run import AgentRun as AgentRunModel
    from druppie.domain.common import AgentRunStatus

    db_runs = (
        execution_repo.db.query(AgentRunModel)
        .filter(
            AgentRunModel.session_id == session_id,
            AgentRunModel.status == AgentRunStatus.PAUSED_USER.value,
        )
        .order_by(AgentRunModel.sequence_number)
        .all()
    )

    if not db_runs:
        return {"runs": [], "leaf_ids": []}

    paused_ids = {r.id for r in db_runs}

    parent_depth: dict = {}
    def compute_depth(run_id):
        if run_id in parent_depth:
            return parent_depth[run_id]
        run = next((r for r in db_runs if r.id == run_id), None)
        if not run or run.parent_run_id is None:
            parent_depth[run_id] = 0
            return 0
        d = compute_depth(run.parent_run_id) + 1
        parent_depth[run_id] = d
        return d

    runs_out = []
    leaf_ids = []
    for r in db_runs:
        has_paused_child = any(
            child.parent_run_id == r.id and child.id in paused_ids
            for child in db_runs
        )
        is_leaf = not has_paused_child
        if is_leaf:
            leaf_ids.append(str(r.id))

        runs_out.append({
            "id": str(r.id),
            "agent_id": r.agent_id,
            "status": r.status,
            "parent_run_id": str(r.parent_run_id) if r.parent_run_id else None,
            "planned_prompt": r.planned_prompt,
            "sequence_number": r.sequence_number,
            "depth": compute_depth(r.id),
            "is_leaf": is_leaf,
        })

    return {"runs": runs_out, "leaf_ids": leaf_ids}
