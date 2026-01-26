"""Main execution loop for Druppie AI Governance Platform.

This module orchestrates the AI agent workflow:
1. Router classifies user intent
2. Planner creates execution plan (stored in workflow_steps)
3. Steps execute in order (agents, approvals, etc.)
4. Pauses for approvals/HITL questions
5. Resumes from DB state when approval/answer received

NO JSON state storage - everything is in normalized PostgreSQL tables.
"""

import structlog
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from druppie.core.config import get_settings
from druppie.core.execution_context import (
    ExecutionContext,
    CancelledException,
    set_current_context,
    get_current_context,
    clear_current_context,
)
from druppie.db import (
    # Models
    Session,
    Workflow,
    WorkflowStep,
    AgentRun,
    Message,
    Approval,
    HitlQuestion,
    Workspace,
    # CRUD functions
    create_session,
    get_session,
    update_session,
    update_session_tokens,
    create_workflow,
    get_workflow,
    get_workflow_for_session,
    update_workflow,
    update_workflow_step,
    create_agent_run,
    get_agent_run,
    get_active_agent_run,
    update_agent_run,
    update_agent_run_tokens,
    create_message,
    get_messages_for_session,
    get_messages_for_agent_run,
    create_approval,
    get_approval,
    get_pending_approval_for_tool_call,
    update_approval,
    resolve_approval,
    list_pending_approvals,
    create_hitl_question,
    get_hitl_question,
    get_pending_hitl_question,
    answer_hitl_question,
    update_hitl_question_state,
    get_workflow,
    create_workspace,
    get_workspace,
    get_workspace_for_session,
    create_llm_call,
    get_llm_calls_for_session,
)
from druppie.db.database import get_db


logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# DATABASE SESSION HELPER
# =============================================================================


@contextmanager
def db_session():
    """Get a database session with proper cleanup."""
    db = next(get_db())
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# STATE RECONSTRUCTION FROM DATABASE
# =============================================================================


def get_execution_state(db: DBSession, session_id: UUID) -> dict[str, Any]:
    """Build execution state from normalized database tables.

    This replaces the JSON session.state approach. All state is derived
    from properly normalized tables.

    Returns:
        Dict with:
        - session: Session record
        - workflow: Current workflow (if any)
        - steps: List of workflow steps
        - current_step: Current step index
        - workspace: Workspace info
        - messages: Recent messages
        - pending_approval: Approval we're waiting for (if any)
        - pending_question: HITL question we're waiting for (if any)
        - hitl_answers: Previous HITL Q&A for this workflow
    """
    session = get_session(db, session_id)
    if not session:
        return {"error": "Session not found"}

    workflow = get_workflow_for_session(db, session_id)

    # Get workflow steps if workflow exists
    steps = []
    if workflow:
        steps = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_index.asc())
            .all()
        )

    # Get workspace
    workspace = get_workspace_for_session(db, session_id)

    # Get pending approval or HITL question
    pending_approval = (
        db.query(Approval)
        .filter(Approval.session_id == session_id, Approval.status == "pending")
        .first()
    )

    pending_question = get_pending_hitl_question(db, session_id)

    # Get previous HITL Q&A for context
    hitl_answers = (
        db.query(HitlQuestion)
        .filter(HitlQuestion.session_id == session_id, HitlQuestion.status == "answered")
        .order_by(HitlQuestion.created_at.asc())
        .all()
    )

    # Get recent messages
    messages = get_messages_for_session(db, session_id, limit=50)

    return {
        "session": session,
        "workflow": workflow,
        "steps": steps,
        "current_step": workflow.current_step if workflow else 0,
        "workspace": workspace,
        "messages": messages,
        "pending_approval": pending_approval,
        "pending_question": pending_question,
        "hitl_answers": hitl_answers,
    }


def build_plan_from_workflow(workflow: Workflow, steps: list[WorkflowStep]) -> dict:
    """Convert workflow/steps records to plan dict for agent execution."""
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "status": workflow.status,
        "current_step": workflow.current_step,
        "steps": [
            {
                "id": str(step.id),
                "index": step.step_index,
                "agent_id": step.agent_id,
                "description": step.description,
                "status": step.status,
                "result": step.result_summary,
            }
            for step in steps
        ],
    }


def build_context_from_workspace(workspace: Workspace | None) -> dict:
    """Build execution context dict from workspace record."""
    if not workspace:
        return {}

    return {
        "workspace_id": str(workspace.id) if workspace.id else None,
        "project_id": str(workspace.project_id) if workspace.project_id else None,
        "workspace_path": workspace.local_path,
        "branch": workspace.branch,
    }


def build_clarifications_from_hitl(hitl_answers: list[HitlQuestion]) -> list[dict]:
    """Build clarification history from HITL Q&A records."""
    return [
        {
            "question_id": str(q.id),
            "question": q.question,
            "answer": q.answer,
            "agent_id": q.agent_run.agent_id if q.agent_run else None,
        }
        for q in hitl_answers
        if q.answer  # Only include answered questions
    ]


# =============================================================================
# MCP CLIENT
# =============================================================================


def get_mcp_client(db: DBSession):
    """Get the MCP client for tool execution."""
    from druppie.core.mcp_client import MCPClient
    return MCPClient(db)


# =============================================================================
# AGENT EXECUTION
# =============================================================================


def _persist_agent_data(
    db: DBSession,
    agent_run: AgentRun,
    exec_ctx: ExecutionContext,
    iteration_count: int,
    status: str,
    completed_at: datetime | None = None,
) -> None:
    """Persist LLM calls and update agent_run stats after agent execution.

    Args:
        db: Database session
        agent_run: The agent run record to update
        exec_ctx: ExecutionContext with collected LLM calls
        iteration_count: Number of LLM iterations
        status: New status for agent_run
        completed_at: Completion timestamp (if completed)
    """
    from uuid import UUID as UUIDType

    # Persist LLM calls for this agent run
    agent_id = agent_run.agent_id
    agent_prompt_tokens = 0
    agent_completion_tokens = 0

    for llm_call in exec_ctx.llm_calls:
        # Only persist LLM calls for this specific agent
        if llm_call.get("agent_id") != agent_id:
            continue

        # Check if already persisted (to avoid duplicates on resume)
        if llm_call.get("_persisted"):
            continue

        usage = llm_call.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        # Extract full request/response data for debugging
        response = llm_call.get("response", {})
        response_content = response.get("content") if response else None
        response_tool_calls = response.get("tool_calls") if response else None

        create_llm_call(
            db,
            session_id=UUIDType(exec_ctx.session_id),
            agent_run_id=agent_run.id,
            provider=llm_call.get("provider", "unknown"),
            model=llm_call.get("model", "unknown"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=llm_call.get("duration_ms"),
            request_messages=llm_call.get("messages"),
            response_content=response_content,
            response_tool_calls=response_tool_calls,
            tools_provided=llm_call.get("tools"),
        )

        agent_prompt_tokens += prompt_tokens
        agent_completion_tokens += completion_tokens

        # Mark as persisted to avoid duplicates
        llm_call["_persisted"] = True

    # Update agent_run with stats
    update_agent_run(
        db,
        agent_run.id,
        status=status,
        completed_at=completed_at,
    )

    # Update agent_run token counts
    if agent_prompt_tokens > 0 or agent_completion_tokens > 0:
        update_agent_run_tokens(
            db,
            agent_run.id,
            prompt_tokens=agent_prompt_tokens,
            completion_tokens=agent_completion_tokens,
        )

        # Also update session tokens incrementally
        # This ensures tokens are saved even when execution pauses for approval/HITL
        from uuid import UUID as UUIDType2
        update_session_tokens(
            db,
            UUIDType2(exec_ctx.session_id),
            agent_prompt_tokens,
            agent_completion_tokens,
        )

    # Update iteration count via direct update
    agent_run.iteration_count = iteration_count
    db.commit()

    logger.debug(
        "agent_data_persisted",
        agent_id=agent_id,
        agent_run_id=str(agent_run.id),
        iteration_count=iteration_count,
        prompt_tokens=agent_prompt_tokens,
        completion_tokens=agent_completion_tokens,
    )


async def run_agent(
    db: DBSession,
    agent_id: str,
    prompt: str,
    context: dict,
    exec_ctx: ExecutionContext,
    parent_run_id: UUID | None = None,
    workflow_step_id: UUID | None = None,
    workflow_id: UUID | None = None,
    step_index: int | None = None,
) -> dict[str, Any]:
    """Run an agent with the given prompt and context.

    Creates an agent_run record, executes the agent, and returns the result.
    If the agent pauses for approval or HITL, returns paused state.

    Args:
        db: Database session
        agent_id: ID of the agent to run (router, planner, architect, developer, etc.)
        prompt: The prompt/instruction for the agent
        context: Execution context (workspace info, previous results, etc.)
        exec_ctx: ExecutionContext for events and tracking
        parent_run_id: Parent agent run (for context chain)
        workflow_step_id: Associated workflow step (if any)
        workflow_id: Workflow this agent is part of (for resume)
        step_index: Step index in the workflow (for resume)

    Returns:
        Dict with result, or paused state with approval_id/question_id
    """
    from druppie.agents.runtime import Agent

    # Create agent run record
    agent_run = create_agent_run(
        db,
        session_id=UUID(exec_ctx.session_id),
        agent_id=agent_id,
        workflow_step_id=workflow_step_id,
        parent_run_id=parent_run_id,
    )
    exec_ctx.current_agent_run_id = str(agent_run.id)

    exec_ctx.emit("agent_started", {
        "agent_id": agent_id,
        "agent_run_id": str(agent_run.id),
    })

    logger.info(
        "agent_run_started",
        session_id=exec_ctx.session_id,
        agent_id=agent_id,
        agent_run_id=str(agent_run.id),
    )

    try:
        # Run the agent with workflow info for resume support
        agent = Agent(agent_id)
        result = await agent.run(
            prompt,
            context,
            workflow_id=str(workflow_id) if workflow_id else None,
            workflow_step=step_index,
        )

        # Check if paused for approval or HITL
        if isinstance(result, dict):
            if result.get("paused"):
                # Agent paused - update status and persist data collected so far
                iteration_count = result.get("iteration", 0) + 1
                is_hitl = result.get("question_id") is not None
                _persist_agent_data(
                    db, agent_run, exec_ctx, iteration_count,
                    status="paused_hitl" if is_hitl else "paused_tool",
                )

                # If paused for HITL question, save the agent_state for resume
                if is_hitl and result.get("agent_state"):
                    question_id = result.get("question_id")
                    update_hitl_question_state(
                        db, UUID(question_id), result["agent_state"]
                    )
                    logger.info(
                        "saved_agent_state_for_hitl",
                        question_id=question_id,
                        agent_id=agent_id,
                    )

                # If paused for MCP tool approval, update the approval with agent_state
                approval_id = result.get("approval_id")
                if approval_id and result.get("agent_state"):
                    update_approval(
                        db, approval_id, {"agent_state": result["agent_state"]}
                    )
                    logger.info(
                        "saved_agent_state_for_approval",
                        approval_id=approval_id,
                        agent_id=agent_id,
                    )

                exec_ctx.emit("agent_paused", {
                    "agent_id": agent_id,
                    "agent_run_id": str(agent_run.id),
                    "approval_id": result.get("approval_id"),
                    "question_id": result.get("question_id"),
                })

                return result

        # Agent completed successfully - persist LLM calls and update stats
        # Count iterations from llm_calls for this agent
        llm_calls_for_agent = [
            c for c in exec_ctx.llm_calls if c.get("agent_id") == agent_id
        ]
        iteration_count = len(llm_calls_for_agent)

        _persist_agent_data(
            db, agent_run, exec_ctx, iteration_count,
            status="completed",
            completed_at=datetime.now(timezone.utc),
        )

        exec_ctx.emit("agent_completed", {
            "agent_id": agent_id,
            "agent_run_id": str(agent_run.id),
            "result_preview": str(result)[:200] if result else None,
            "iterations": iteration_count,
        })

        return {"success": True, "result": result}

    except CancelledException:
        update_agent_run(db, agent_run.id, status="failed")
        raise

    except Exception as e:
        logger.error(
            "agent_run_failed",
            agent_id=agent_id,
            agent_run_id=str(agent_run.id),
            error=str(e),
            exc_info=True,
        )
        update_agent_run(db, agent_run.id, status="failed")

        exec_ctx.emit("agent_error", {
            "agent_id": agent_id,
            "agent_run_id": str(agent_run.id),
            "error": str(e),
        })

        return {"success": False, "error": str(e)}


# =============================================================================
# WORKFLOW EXECUTION
# =============================================================================


async def execute_workflow_steps(
    db: DBSession,
    workflow: Workflow,
    steps: list[WorkflowStep],
    context: dict,
    exec_ctx: ExecutionContext,
    start_from: int = 0,
) -> dict[str, Any]:
    """Execute workflow steps from a given starting point.

    Processes steps in order:
    - Agent steps: Run the agent
    - Approval steps: Create approval request and pause
    - MCP steps: Execute MCP tool directly

    Returns when:
    - All steps complete (success)
    - An error occurs (failure)
    - Paused for approval/HITL (interrupt)

    Args:
        db: Database session
        workflow: The workflow to execute
        steps: List of workflow steps
        context: Execution context (workspace info, previous results)
        exec_ctx: ExecutionContext for events
        start_from: Step index to start from (for resume)

    Returns:
        Dict with success/error/paused state
    """
    results = []

    # Build results from already-completed steps
    for step in steps[:start_from]:
        if step.status == "completed":
            results.append({
                "step_id": str(step.id),
                "agent_id": step.agent_id,
                "success": True,
                "result": step.result_summary,
            })

    # Update workflow status
    update_workflow(db, workflow.id, status="running")

    exec_ctx.emit("workflow_started", {
        "workflow_id": str(workflow.id),
        "workflow_name": workflow.name,
        "total_steps": len(steps),
        "starting_from": start_from,
    })

    try:
        for i in range(start_from, len(steps)):
            exec_ctx.check_cancelled()

            step = steps[i]
            step_type = _get_step_type(step.agent_id)

            logger.info(
                "executing_step",
                session_id=exec_ctx.session_id,
                workflow_id=str(workflow.id),
                step_index=i,
                step_id=str(step.id),
                agent_id=step.agent_id,
                step_type=step_type,
            )

            # Update current step in workflow
            update_workflow(db, workflow.id, current_step=i)

            # Update step status
            update_workflow_step(
                db,
                step.id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )

            exec_ctx.emit("step_started", {
                "step_index": i,
                "step_id": str(step.id),
                "agent_id": step.agent_id,
                "description": step.description,
                "total_steps": len(steps),
            })

            try:
                if step_type == "approval":
                    # Create approval request and pause
                    result = await _handle_approval_step(db, step, context, exec_ctx)
                    if result.get("paused"):
                        return result

                elif step_type == "agent":
                    # Run the agent with workflow info for resume support
                    result = await run_agent(
                        db=db,
                        agent_id=step.agent_id,
                        prompt=step.description or "",
                        context=context,
                        exec_ctx=exec_ctx,
                        workflow_step_id=step.id,
                        workflow_id=workflow.id,
                        step_index=i,
                    )

                    if result.get("paused"):
                        return result

                    if not result.get("success"):
                        # Step failed
                        update_workflow_step(
                            db,
                            step.id,
                            status="failed",
                            result_summary=result.get("error", "Unknown error"),
                            completed_at=datetime.now(timezone.utc),
                        )

                        exec_ctx.emit("step_failed", {
                            "step_index": i,
                            "step_id": str(step.id),
                            "error": result.get("error"),
                        })

                        # Stop workflow on error (unless continue_on_error)
                        break

                    # Step succeeded
                    step_result = result.get("result")
                    result_summary = _summarize_result(step_result)

                    update_workflow_step(
                        db,
                        step.id,
                        status="completed",
                        result_summary=result_summary,
                        completed_at=datetime.now(timezone.utc),
                    )

                    results.append({
                        "step_id": str(step.id),
                        "agent_id": step.agent_id,
                        "success": True,
                        "result": step_result,
                    })

                    # Add result to context for next steps
                    context[f"step_{i}_result"] = step_result

                else:
                    # Unknown step type - skip
                    logger.warning("unknown_step_type", agent_id=step.agent_id)
                    update_workflow_step(db, step.id, status="skipped")

                exec_ctx.emit("step_completed", {
                    "step_index": i,
                    "step_id": str(step.id),
                    "agent_id": step.agent_id,
                    "success": True,
                })

            except CancelledException:
                raise
            except Exception as e:
                logger.error(
                    "step_execution_error",
                    step_id=str(step.id),
                    error=str(e),
                    exc_info=True,
                )

                update_workflow_step(
                    db,
                    step.id,
                    status="failed",
                    result_summary=str(e),
                    completed_at=datetime.now(timezone.utc),
                )

                exec_ctx.emit("step_failed", {
                    "step_index": i,
                    "step_id": str(step.id),
                    "error": str(e),
                })

                break

        # Workflow completed
        update_workflow(db, workflow.id, status="completed")

        exec_ctx.emit("workflow_completed", {
            "workflow_id": str(workflow.id),
            "successful_steps": len([r for r in results if r.get("success")]),
            "total_steps": len(steps),
        })

        return {
            "success": True,
            "results": results,
            "workflow_id": str(workflow.id),
        }

    except CancelledException:
        update_workflow(db, workflow.id, status="failed")
        raise
    except Exception as e:
        logger.error(
            "workflow_execution_error",
            workflow_id=str(workflow.id),
            error=str(e),
            exc_info=True,
        )
        update_workflow(db, workflow.id, status="failed")
        return {"success": False, "error": str(e)}


def _get_step_type(agent_id: str) -> str:
    """Determine step type from agent_id."""
    if agent_id.startswith("approval"):
        return "approval"
    return "agent"


def _summarize_result(result: Any) -> str:
    """Create a summary of a step result for storage."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result[:1000]
    if isinstance(result, dict):
        if "content" in result:
            return str(result["content"])[:1000]
        if "response" in result:
            return str(result["response"])[:1000]
        if "url" in result:
            return f"URL: {result['url']}"
    return str(result)[:1000]


async def _handle_approval_step(
    db: DBSession,
    step: WorkflowStep,
    context: dict,
    exec_ctx: ExecutionContext,
) -> dict[str, Any]:
    """Handle an approval step - create approval and pause."""
    # Extract approval info from step description
    approval_message = step.description or "Approval required to continue"

    # Create approval record
    # Note: create_approval expects session_id as the second positional argument
    approval = create_approval(
        db,
        UUID(exec_ctx.session_id),  # session_id as positional arg
        approval_type="workflow_step",
        workflow_step_id=step.id,
        title=f"Step Approval: {step.agent_id}",
        description=approval_message,
        required_role="developer",  # Default role
    )

    # Update step status
    update_workflow_step(db, step.id, status="waiting_approval")

    # Update session status
    update_session(db, UUID(exec_ctx.session_id), status="paused_approval")

    exec_ctx.emit("approval_required", {
        "approval_id": str(approval.id),
        "approval_type": "workflow_step",
        "message": approval_message,
        "step_id": str(step.id),
    })

    return {
        "success": True,
        "paused": True,
        "approval_id": str(approval.id),
        "message": f"Waiting for approval: {approval_message}",
    }


# =============================================================================
# MAIN LOOP CLASS
# =============================================================================


class MainLoop:
    """Main execution loop for Druppie."""

    def __init__(self):
        pass

    async def process_message(
        self,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Process a user message.

        Main entry point for new messages. Creates session if needed,
        initializes workspace, runs router/planner, and executes workflow.

        Args:
            message: User's message
            session_id: Existing session ID (or None for new session)
            user_id: User ID
            project_id: Project ID (for existing project)
            project_name: Project name (for new project)
            emit_event: Callback for real-time events

        Returns:
            Dict with response, session_id, and execution state
        """
        # Create or get session
        with db_session() as db:
            if session_id:
                session = get_session(db, UUID(session_id))
                if not session:
                    # Create session with the provided session_id so frontend can track it
                    session = create_session(
                        db,
                        user_id=UUID(user_id) if user_id else None,
                        project_id=UUID(project_id) if project_id else None,
                        title=message[:100],
                        session_id=UUID(session_id),
                    )
            else:
                session = create_session(
                    db,
                    user_id=UUID(user_id) if user_id else None,
                    project_id=UUID(project_id) if project_id else None,
                    title=message[:100],
                )

            session_id = str(session.id)

        # Create execution context
        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        try:
            exec_ctx.emit("processing_started", {"message": message[:200]})

            # Initialize workspace
            workspace_info = await self._initialize_workspace(
                session_id=session_id,
                user_id=user_id,
                project_id=project_id,
                project_name=project_name,
                exec_ctx=exec_ctx,
            )

            # Build context for agents
            context = {
                **workspace_info,
                "session_id": session_id,
                "user_id": user_id,
                "message": message,
            }

            # Save user message to DB
            with db_session() as db:
                create_message(
                    db,
                    session_id=UUID(session_id),
                    role="user",
                    content=message,
                )

            # Run router to classify intent
            exec_ctx.emit("router_started", {})

            with db_session() as db:
                router_result = await run_agent(
                    db=db,
                    agent_id="router",
                    prompt=message,
                    context=context,
                    exec_ctx=exec_ctx,
                )

            if not router_result.get("success"):
                return await self._handle_error(
                    session_id,
                    exec_ctx,
                    router_result.get("error", "Router failed"),
                )

            intent = _extract_intent(router_result.get("result"))
            exec_ctx.emit("router_completed", {"intent": intent})

            logger.info(
                "intent_classified",
                session_id=session_id,
                intent=intent,
            )

            # Handle based on intent
            if intent == "simple_response":
                # Direct response, no planning needed
                response = _extract_response(router_result.get("result"))
                return await self._complete_session(
                    session_id,
                    exec_ctx,
                    response,
                )

            if intent == "needs_clarification":
                # Router asked HITL question
                if router_result.get("paused"):
                    return {
                        "success": True,
                        "type": "interrupt",
                        "response": "Waiting for clarification",
                        "paused": True,
                        "question_id": router_result.get("question_id"),
                        "session_id": session_id,
                    }

            # Run planner to create workflow
            exec_ctx.emit("planner_started", {})

            with db_session() as db:
                planner_result = await run_agent(
                    db=db,
                    agent_id="planner",
                    prompt=f"User request: {message}\n\nContext: {context}",
                    context=context,
                    exec_ctx=exec_ctx,
                )

            if not planner_result.get("success"):
                return await self._handle_error(
                    session_id,
                    exec_ctx,
                    planner_result.get("error", "Planner failed"),
                )

            # Create workflow from planner output
            plan = _extract_plan(planner_result.get("result"))

            with db_session() as db:
                workflow = create_workflow(
                    db,
                    session_id=UUID(session_id),
                    name=plan.get("name", "Execution Plan"),
                    steps=[
                        {
                            "agent_id": step.get("agent_id", step.get("type", "unknown")),
                            "description": step.get("prompt", step.get("description", "")),
                        }
                        for step in plan.get("steps", [])
                    ],
                )
                exec_ctx.current_workflow_id = str(workflow.id)

                # Get the created steps
                steps = (
                    db.query(WorkflowStep)
                    .filter(WorkflowStep.workflow_id == workflow.id)
                    .order_by(WorkflowStep.step_index.asc())
                    .all()
                )

            exec_ctx.emit("planner_completed", {
                "workflow_id": str(workflow.id),
                "workflow_name": workflow.name,
                "step_count": len(steps),
            })

            # Execute workflow
            with db_session() as db:
                workflow = get_workflow(db, workflow.id)
                steps = (
                    db.query(WorkflowStep)
                    .filter(WorkflowStep.workflow_id == workflow.id)
                    .order_by(WorkflowStep.step_index.asc())
                    .all()
                )

                result = await execute_workflow_steps(
                    db=db,
                    workflow=workflow,
                    steps=steps,
                    context=context,
                    exec_ctx=exec_ctx,
                )

            if result.get("paused"):
                return {
                    "success": True,
                    "type": "interrupt",
                    "response": result.get("message", "Execution paused"),
                    "paused": True,
                    "approval_id": result.get("approval_id"),
                    "question_id": result.get("question_id"),
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                }

            if not result.get("success"):
                return await self._handle_error(
                    session_id,
                    exec_ctx,
                    result.get("error", "Workflow execution failed"),
                )

            # Build final response
            response = _build_final_response(result.get("results", []))
            return await self._complete_session(session_id, exec_ctx, response)

        except CancelledException:
            logger.info("execution_cancelled", session_id=session_id)
            return {
                "success": False,
                "error": "Execution was cancelled",
                "cancelled": True,
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
            }
        except Exception as e:
            logger.error(
                "process_message_error",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return await self._handle_error(session_id, exec_ctx, str(e))
        finally:
            clear_current_context()

    async def resume_from_approval(
        self,
        session_id: str,
        approval_id: str,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume execution after an approval is granted.

        Reconstructs execution state from DB and continues from
        the current workflow step.

        Args:
            session_id: Session ID
            approval_id: ID of the approved approval
            emit_event: Callback for real-time events

        Returns:
            Dict with response/paused state
        """
        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        try:
            with db_session() as db:
                # Get execution state from DB
                state = get_execution_state(db, UUID(session_id))

                if state.get("error"):
                    return {"success": False, "error": state["error"]}

                workflow = state["workflow"]
                if not workflow:
                    return {"success": False, "error": "No workflow found for session"}

                steps = state["steps"]
                workspace = state["workspace"]

                # Build context
                context = build_context_from_workspace(workspace)
                context["session_id"] = session_id

                # Add HITL clarifications to context
                clarifications = build_clarifications_from_hitl(state["hitl_answers"])
                if clarifications:
                    context["clarifications"] = clarifications

                # Update workspace info in exec_ctx
                if workspace:
                    exec_ctx.workspace_id = str(workspace.id)
                    exec_ctx.project_id = str(workspace.project_id) if workspace.project_id else None
                    exec_ctx.workspace_path = workspace.local_path
                    exec_ctx.branch = workspace.branch

                exec_ctx.emit("execution_resumed", {
                    "approval_id": approval_id,
                    "workflow_id": str(workflow.id),
                    "current_step": workflow.current_step,
                })

                # Update session status
                update_session(db, UUID(session_id), status="active")

                # Continue from current step + 1 (approval step was completed)
                resume_from = workflow.current_step + 1

                result = await execute_workflow_steps(
                    db=db,
                    workflow=workflow,
                    steps=steps,
                    context=context,
                    exec_ctx=exec_ctx,
                    start_from=resume_from,
                )

            if result.get("paused"):
                return {
                    "success": True,
                    "type": "interrupt",
                    "response": result.get("message", "Execution paused"),
                    "paused": True,
                    "approval_id": result.get("approval_id"),
                    "question_id": result.get("question_id"),
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                }

            if not result.get("success"):
                return await self._handle_error(
                    session_id,
                    exec_ctx,
                    result.get("error", "Workflow execution failed"),
                )

            response = _build_final_response(result.get("results", []))
            return await self._complete_session(session_id, exec_ctx, response)

        except CancelledException:
            return {
                "success": False,
                "error": "Execution was cancelled",
                "cancelled": True,
                "session_id": session_id,
            }
        except Exception as e:
            logger.error(
                "resume_from_approval_error",
                session_id=session_id,
                approval_id=approval_id,
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
        finally:
            clear_current_context()

    async def resume_from_step_approval(
        self,
        session_id: str,
        agent_state: dict,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume execution after an MCP tool approval is granted.

        Uses the saved agent_state to resume the agent from where it paused.
        The tool result is in agent_state["last_tool_result"] if the tool
        was already executed.

        Args:
            session_id: Session ID
            agent_state: Saved agent state with tool result
            emit_event: Callback for real-time events

        Returns:
            Dict with response/paused state
        """
        from druppie.agents.runtime import Agent

        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        try:
            with db_session() as db:
                # Get workspace info to set up context
                workspace = get_workspace_for_session(db, UUID(session_id))
                if workspace:
                    exec_ctx.workspace_id = str(workspace.id)
                    exec_ctx.project_id = str(workspace.project_id) if workspace.project_id else None
                    exec_ctx.workspace_path = workspace.local_path
                    exec_ctx.branch = workspace.branch

                # Restore HITL clarifications if available
                hitl_clarifications = agent_state.get("hitl_clarifications", [])
                if hitl_clarifications:
                    exec_ctx.hitl_clarifications = hitl_clarifications

                # Get the tool result from agent_state
                last_tool_result = agent_state.get("last_tool_result", {})
                tool_result = last_tool_result.get("result", {"success": True})

                # Get agent ID and restore agent
                agent_id = agent_state.get("agent_id")
                if not agent_id:
                    return {"success": False, "error": "No agent_id in saved state"}

                logger.info(
                    "resuming_agent_from_step_approval",
                    session_id=session_id,
                    agent_id=agent_id,
                    tool=last_tool_result.get("tool"),
                    workflow_id=agent_state.get("workflow_id"),
                    workflow_step=agent_state.get("workflow_step"),
                )

                exec_ctx.emit("execution_resumed", {
                    "agent_id": agent_id,
                    "reason": "mcp_tool_approved",
                    "tool": last_tool_result.get("tool"),
                })

                # Update session status
                update_session(db, UUID(session_id), status="active")

                # Create and resume agent
                agent = Agent(agent_id)
                result = await agent.resume_from_approval(agent_state, tool_result)

                # Check if agent paused again
                if result.get("paused"):
                    # Update session status
                    if result.get("approval_id"):
                        update_session(db, UUID(session_id), status="paused_approval")
                    elif result.get("question_id"):
                        update_session(db, UUID(session_id), status="paused_question")
                        # Save agent_state to the new question for resumption
                        if result.get("agent_state"):
                            update_hitl_question_state(
                                db, UUID(result["question_id"]), result["agent_state"]
                            )

                    return {
                        "success": True,
                        "type": "interrupt",
                        "response": result.get("question") or "Execution paused for approval",
                        "paused": True,
                        "approval_id": result.get("approval_id"),
                        "question_id": result.get("question_id"),
                        "session_id": session_id,
                        "workflow_events": exec_ctx.workflow_events,
                    }

                # Agent completed - check if we need to continue workflow
                workflow_id = agent_state.get("workflow_id")
                workflow_step = agent_state.get("workflow_step")

                if workflow_id and workflow_step is not None:
                    # Get workflow and continue from next step
                    workflow = get_workflow(db, UUID(workflow_id))
                    if workflow:
                        steps = workflow.steps
                        context = build_context_from_workspace(workspace)
                        context["session_id"] = session_id
                        context["previous_result"] = result

                        # Add HITL clarifications to context
                        state = get_execution_state(db, UUID(session_id))
                        clarifications = build_clarifications_from_hitl(state.get("hitl_answers", []))
                        if clarifications:
                            context["clarifications"] = clarifications

                        # Move to next step
                        next_step = workflow_step + 1
                        workflow.current_step = next_step
                        db.commit()

                        logger.info(
                            "continuing_workflow_after_agent",
                            session_id=session_id,
                            workflow_id=workflow_id,
                            next_step=next_step,
                            total_steps=len(steps),
                        )

                        # Continue workflow from next step
                        workflow_result = await execute_workflow_steps(
                            db=db,
                            workflow=workflow,
                            steps=steps,
                            context=context,
                            exec_ctx=exec_ctx,
                            start_from=next_step,
                        )

                        if workflow_result.get("paused"):
                            return {
                                "success": True,
                                "type": "interrupt",
                                "response": workflow_result.get("message", "Execution paused"),
                                "paused": True,
                                "approval_id": workflow_result.get("approval_id"),
                                "question_id": workflow_result.get("question_id"),
                                "session_id": session_id,
                                "workflow_events": exec_ctx.workflow_events,
                            }

                        if not workflow_result.get("success"):
                            return await self._handle_error(
                                session_id,
                                exec_ctx,
                                workflow_result.get("error", "Workflow execution failed"),
                            )

                        response = _build_final_response(workflow_result.get("results", []))
                        return await self._complete_session(session_id, exec_ctx, response)

                # No workflow or standalone agent - return result
                response = _build_final_response([result])
                return await self._complete_session(session_id, exec_ctx, response)

        except CancelledException:
            return {
                "success": False,
                "error": "Execution was cancelled",
                "cancelled": True,
                "session_id": session_id,
            }
        except Exception as e:
            logger.error(
                "resume_from_step_approval_error",
                session_id=session_id,
                agent_id=agent_state.get("agent_id"),
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
        finally:
            clear_current_context()

    async def resume_session(
        self,
        session_id: str,
        response: dict,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume a session with a tool response (fallback for old-style approvals).

        This is used when there's no saved agent_state and we just need to
        continue the workflow from the next step.

        Args:
            session_id: Session ID
            response: Tool result to pass to next step
            emit_event: Callback for real-time events

        Returns:
            Dict with response/paused state
        """
        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        try:
            with db_session() as db:
                # Get execution state from DB
                state = get_execution_state(db, UUID(session_id))

                if state.get("error"):
                    return {"success": False, "error": state["error"]}

                workflow = state["workflow"]
                if not workflow:
                    # No workflow - just complete the session
                    return await self._complete_session(
                        session_id,
                        exec_ctx,
                        _build_final_response([response]),
                    )

                steps = state["steps"]
                workspace = state["workspace"]

                # Build context
                context = build_context_from_workspace(workspace)
                context["session_id"] = session_id
                context["previous_result"] = response

                # Add HITL clarifications
                clarifications = build_clarifications_from_hitl(state["hitl_answers"])
                if clarifications:
                    context["clarifications"] = clarifications

                # Update workspace info in exec_ctx
                if workspace:
                    exec_ctx.workspace_id = str(workspace.id)
                    exec_ctx.project_id = str(workspace.project_id) if workspace.project_id else None
                    exec_ctx.workspace_path = workspace.local_path
                    exec_ctx.branch = workspace.branch

                # Update session status
                update_session(db, UUID(session_id), status="active")

                # Continue from next step
                resume_from = workflow.current_step + 1

                result = await execute_workflow_steps(
                    db=db,
                    workflow=workflow,
                    steps=steps,
                    context=context,
                    exec_ctx=exec_ctx,
                    start_from=resume_from,
                )

            if result.get("paused"):
                return {
                    "success": True,
                    "type": "interrupt",
                    "response": result.get("message", "Execution paused"),
                    "paused": True,
                    "approval_id": result.get("approval_id"),
                    "question_id": result.get("question_id"),
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                }

            if not result.get("success"):
                return await self._handle_error(
                    session_id,
                    exec_ctx,
                    result.get("error", "Workflow execution failed"),
                )

            final_response = _build_final_response(result.get("results", []))
            return await self._complete_session(session_id, exec_ctx, final_response)

        except CancelledException:
            return {
                "success": False,
                "error": "Execution was cancelled",
                "cancelled": True,
                "session_id": session_id,
            }
        except Exception as e:
            logger.error(
                "resume_session_error",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
        finally:
            clear_current_context()

    async def resume_from_question_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume execution after a HITL question is answered.

        Uses the agent_state stored in the question to resume the agent
        from where it paused. If the agent is part of a workflow, continues
        the workflow after the agent completes.

        Args:
            session_id: Session ID
            question_id: ID of the answered question
            answer: User's answer
            emit_event: Callback for real-time events

        Returns:
            Dict with response/paused state
        """
        from druppie.agents.runtime import Agent

        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        try:
            with db_session() as db:
                # Get the question with its agent_state
                question = get_hitl_question(db, UUID(question_id))
                if not question:
                    return {"success": False, "error": f"Question {question_id} not found"}

                # Mark question as answered
                answer_hitl_question(db, UUID(question_id), answer)

                # Get workspace for context
                workspace = get_workspace_for_session(db, UUID(session_id))
                if workspace:
                    exec_ctx.workspace_id = str(workspace.id)
                    exec_ctx.project_id = str(workspace.project_id) if workspace.project_id else None
                    exec_ctx.workspace_path = workspace.local_path
                    exec_ctx.branch = workspace.branch

                exec_ctx.emit("question_answered", {
                    "question_id": question_id,
                    "answer": answer[:200],
                })

                # Update session status
                update_session(db, UUID(session_id), status="active")

                agent_state = question.agent_state
                if agent_state:
                    # Resume agent from saved state
                    agent_id = agent_state.get("agent_id")
                    workflow_id = agent_state.get("workflow_id")
                    workflow_step = agent_state.get("workflow_step")

                    logger.info(
                        "resuming_agent_from_state",
                        agent_id=agent_id,
                        workflow_id=workflow_id,
                        workflow_step=workflow_step,
                    )

                    agent = Agent(agent_id)
                    result = await agent.resume(agent_state, answer)

                    # Check if agent paused again
                    if result.get("paused"):
                        is_hitl = result.get("question_id") is not None

                        # Save agent state to the appropriate record
                        if is_hitl and result.get("agent_state"):
                            # Save state to new HITL question
                            new_question_id = result.get("question_id")
                            update_hitl_question_state(
                                db, UUID(new_question_id), result["agent_state"]
                            )
                            logger.info(
                                "saved_agent_state_for_hitl_on_resume",
                                question_id=new_question_id,
                                agent_id=agent_id,
                            )

                        # Handle MCP tool approval - save agent_state
                        new_approval_id = result.get("approval_id")
                        if new_approval_id and result.get("agent_state"):
                            update_approval(
                                db, new_approval_id, {"agent_state": result["agent_state"]}
                            )
                            logger.info(
                                "saved_agent_state_for_approval_on_resume",
                                approval_id=new_approval_id,
                                agent_id=agent_id,
                            )

                        status = "paused_hitl" if is_hitl else "paused_approval"
                        update_session(db, UUID(session_id), status=status)

                        return {
                            "success": True,
                            "type": "interrupt",
                            "response": result.get("question", result.get("message", "Execution paused")),
                            "paused": True,
                            "question_id": result.get("question_id"),
                            "approval_id": new_approval_id,
                            "session_id": session_id,
                            "workflow_events": exec_ctx.workflow_events,
                        }

                    # Agent completed - check if we need to continue workflow
                    if workflow_id and workflow_step is not None:
                        # Get workflow and continue from next step
                        workflow = get_workflow(db, UUID(workflow_id))
                        if workflow:
                            steps = workflow.steps  # Use relationship
                            context = build_context_from_workspace(workspace)
                            context["session_id"] = session_id
                            # Add the agent result to context for next step
                            context["previous_result"] = result

                            # Move to next step
                            next_step = workflow_step + 1
                            workflow.current_step = next_step
                            db.commit()

                            # Continue workflow from next step
                            workflow_result = await execute_workflow_steps(
                                db=db,
                                workflow=workflow,
                                steps=steps,
                                context=context,
                                exec_ctx=exec_ctx,
                                start_from=next_step,
                            )

                            if workflow_result.get("paused"):
                                return {
                                    "success": True,
                                    "type": "interrupt",
                                    "response": workflow_result.get("message", "Execution paused"),
                                    "paused": True,
                                    "approval_id": workflow_result.get("approval_id"),
                                    "question_id": workflow_result.get("question_id"),
                                    "session_id": session_id,
                                    "workflow_events": exec_ctx.workflow_events,
                                }

                            if not workflow_result.get("success"):
                                return await self._handle_error(
                                    session_id,
                                    exec_ctx,
                                    workflow_result.get("error", "Workflow execution failed"),
                                )

                            response = _build_final_response(workflow_result.get("results", []))
                            return await self._complete_session(session_id, exec_ctx, response)

                    # No workflow - agent completed standalone
                    response = _build_final_response([result])
                    return await self._complete_session(session_id, exec_ctx, response)

                else:
                    # No agent_state - fall back to old behavior (restart workflow)
                    logger.warning(
                        "no_agent_state_for_question",
                        question_id=question_id,
                        session_id=session_id,
                    )

                    # Get execution state from DB
                    state = get_execution_state(db, UUID(session_id))
                    if state.get("error"):
                        return {"success": False, "error": state["error"]}

                    workflow = state["workflow"]

                    # Build context with clarifications
                    context = build_context_from_workspace(workspace)
                    context["session_id"] = session_id
                    clarifications = build_clarifications_from_hitl(state["hitl_answers"])
                    clarifications.append({
                        "question_id": question_id,
                        "question": question.question,
                        "answer": answer,
                        "agent_id": question.agent_run.agent_id if question.agent_run else None,
                    })
                    context["clarifications"] = clarifications

                    if workflow:
                        steps = state["steps"]
                        result = await execute_workflow_steps(
                            db=db,
                            workflow=workflow,
                            steps=steps,
                            context=context,
                            exec_ctx=exec_ctx,
                            start_from=workflow.current_step,
                        )

                        if result.get("paused"):
                            return {
                                "success": True,
                                "type": "interrupt",
                                "response": result.get("message", "Execution paused"),
                                "paused": True,
                                "approval_id": result.get("approval_id"),
                                "question_id": result.get("question_id"),
                                "session_id": session_id,
                                "workflow_events": exec_ctx.workflow_events,
                            }

                        if not result.get("success"):
                            return await self._handle_error(
                                session_id,
                                exec_ctx,
                                result.get("error", "Workflow execution failed"),
                            )

                        response = _build_final_response(result.get("results", []))
                    else:
                        # No workflow - restart with clarification
                        messages = state["messages"]
                        original_message = next(
                            (m.content for m in messages if m.role == "user"),
                            "",
                        )
                        return await self.process_message(
                            message=f"{original_message}\n\nUser clarification: {answer}",
                            session_id=session_id,
                            user_id=str(state["session"].user_id) if state["session"].user_id else None,
                            project_id=str(workspace.project_id) if workspace and workspace.project_id else None,
                            emit_event=emit_event,
                        )

                    return await self._complete_session(session_id, exec_ctx, response)

        except CancelledException:
            return {
                "success": False,
                "error": "Execution was cancelled",
                "cancelled": True,
                "session_id": session_id,
            }
        except Exception as e:
            logger.error(
                "resume_from_question_error",
                session_id=session_id,
                question_id=question_id,
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
        finally:
            clear_current_context()

    async def _initialize_workspace(
        self,
        session_id: str,
        user_id: str | None,
        project_id: str | None,
        project_name: str | None,
        exec_ctx: ExecutionContext,
    ) -> dict[str, Any]:
        """Initialize workspace for the session."""
        try:
            from druppie.core.workspace import get_workspace_service, WORKSPACE_ROOT

            with db_session() as db:
                # Check if workspace already exists
                existing = get_workspace_for_session(db, UUID(session_id))
                if existing:
                    exec_ctx.set_workspace(
                        workspace_id=str(existing.id),
                        project_id=str(existing.project_id) if existing.project_id else None,
                        workspace_path=existing.local_path,
                        branch=existing.branch,
                    )
                    return {
                        "workspace_id": str(existing.id),
                        "project_id": str(existing.project_id) if existing.project_id else None,
                        "workspace_path": existing.local_path,
                        "branch": existing.branch,
                    }

                # Initialize new workspace
                exec_ctx.emit("workspace_initializing", {
                    "project_id": project_id,
                    "project_name": project_name,
                })

                workspace_service = get_workspace_service(db)
                workspace = await workspace_service.initialize_workspace(
                    session_id=session_id,
                    project_id=project_id,
                    user_id=user_id,
                    project_name=project_name,
                )

                exec_ctx.set_workspace(
                    workspace_id=str(workspace.id),
                    project_id=str(workspace.project_id) if workspace.project_id else None,
                    workspace_path=workspace.local_path,
                    branch=workspace.branch,
                )

                # Link project to session so it appears in chat UI
                if workspace.project_id:
                    update_session(db, UUID(session_id), project_id=workspace.project_id)

                db.commit()

                # Register with MCP servers
                mcp_path = workspace.local_path.replace(str(WORKSPACE_ROOT), "/workspaces")
                await self._register_workspace_with_mcp(
                    workspace_id=str(workspace.id),
                    workspace_path=mcp_path,
                    project_id=str(workspace.project_id) if workspace.project_id else None,
                    branch=workspace.branch,
                    user_id=user_id,
                    session_id=session_id,
                    exec_ctx=exec_ctx,
                )

                return {
                    "workspace_id": str(workspace.id),
                    "project_id": str(workspace.project_id) if workspace.project_id else None,
                    "workspace_path": workspace.local_path,
                    "branch": workspace.branch,
                }

        except Exception as e:
            logger.error(
                "workspace_initialization_failed",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            exec_ctx.emit("workspace_error", {"error": str(e)})
            return {
                "workspace_id": None,
                "project_id": project_id,
                "workspace_path": None,
                "branch": None,
            }

    async def _register_workspace_with_mcp(
        self,
        workspace_id: str,
        workspace_path: str,
        project_id: str | None,
        branch: str,
        user_id: str | None,
        session_id: str,
        exec_ctx: ExecutionContext,
    ) -> None:
        """Register workspace with MCP servers."""
        try:
            with db_session() as db:
                mcp_client = get_mcp_client(db)

                # Register with coding MCP
                await mcp_client._execute_tool(
                    server="coding",
                    tool="register_workspace",
                    args={
                        "workspace_id": workspace_id,
                        "workspace_path": workspace_path,
                        "project_id": project_id,
                        "branch": branch,
                        "user_id": user_id,
                        "session_id": session_id,
                    },
                    context=exec_ctx,
                )

                # Register with docker MCP
                await mcp_client._execute_tool(
                    server="docker",
                    tool="register_workspace",
                    args={
                        "workspace_id": workspace_id,
                        "workspace_path": workspace_path,
                        "project_id": project_id,
                        "branch": branch,
                    },
                    context=exec_ctx,
                )

        except Exception as e:
            logger.warning(
                "workspace_mcp_registration_error",
                workspace_id=workspace_id,
                error=str(e),
            )

    async def _handle_error(
        self,
        session_id: str,
        exec_ctx: ExecutionContext,
        error: str,
    ) -> dict[str, Any]:
        """Handle an error - update session and return error response."""
        with db_session() as db:
            update_session(db, UUID(session_id), status="failed")

        exec_ctx.emit("execution_error", {"error": error})

        return {
            "success": False,
            "error": error,
            "session_id": session_id,
            "workflow_events": exec_ctx.workflow_events,
        }

    async def _complete_session(
        self,
        session_id: str,
        exec_ctx: ExecutionContext,
        response: str,
    ) -> dict[str, Any]:
        """Complete the session successfully."""
        with db_session() as db:
            update_session(db, UUID(session_id), status="completed")

            # Save assistant response
            create_message(
                db,
                session_id=UUID(session_id),
                role="assistant",
                content=response,
            )

            # NOTE: Token usage is now updated incrementally in _persist_agent_data
            # to ensure tokens are saved even when execution pauses for approval/HITL

        exec_ctx.emit("execution_completed", {
            "response_preview": response[:200] if response else None,
        })

        return {
            "success": True,
            "type": "result",
            "response": response,
            "session_id": session_id,
            "workflow_events": exec_ctx.workflow_events,
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _extract_intent(result: Any) -> str:
    """Extract intent from router result."""
    if isinstance(result, dict):
        return result.get("intent", result.get("classification", "execute_plan"))
    if isinstance(result, str):
        # Try to parse intent from text
        result_lower = result.lower()
        if "clarification" in result_lower or "question" in result_lower:
            return "needs_clarification"
        if "simple" in result_lower or "direct" in result_lower:
            return "simple_response"
    return "execute_plan"


def _extract_response(result: Any) -> str:
    """Extract response text from agent result."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("content", result.get("response", str(result)))
    return str(result)


def _extract_plan(result: Any) -> dict:
    """Extract plan from planner result."""
    if isinstance(result, dict):
        if "plan" in result:
            return result["plan"]
        if "steps" in result:
            return result
        return {
            "name": result.get("name", "Execution Plan"),
            "steps": result.get("steps", []),
        }
    return {"name": "Execution Plan", "steps": []}


def _build_final_response(results: list[dict]) -> str:
    """Build a final response from step results."""
    if not results:
        return "Task completed."

    # Try to find a meaningful response from results
    for result in reversed(results):
        step_result = result.get("result")
        if isinstance(step_result, dict):
            if step_result.get("url"):
                return (
                    f"**Deployment Complete!**\n\n"
                    f"- **URL**: {step_result['url']}\n"
                    f"- **Container**: {step_result.get('container_name', 'N/A')}"
                )
            if step_result.get("content"):
                return step_result["content"]
            if step_result.get("response"):
                return step_result["response"]
        elif isinstance(step_result, str) and len(step_result) > 20:
            return step_result

    # Default response
    successful = sum(1 for r in results if r.get("success"))
    return f"Completed {successful}/{len(results)} steps successfully."


# =============================================================================
# SINGLETON
# =============================================================================


_main_loop: MainLoop | None = None


def get_main_loop() -> MainLoop:
    """Get the global main loop instance."""
    global _main_loop
    if _main_loop is None:
        _main_loop = MainLoop()
    return _main_loop
