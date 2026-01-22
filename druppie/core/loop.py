"""Main Execution Loop for Druppie using LangGraph.

This is the heart of the architecture - a minimal graph that orchestrates agents.

Flow:
    User Message
         |
         v
    Workspace Init ─── Clone/create repo (git-first)
         |
         v
    Router Agent ─── Analyzes intent
         |
         v
    Planner Agent ─── Creates execution plan
         |
         v
    Execute ─── Runs agents/workflows from plan
         |
         v
    Done

Key principle: The loop just defines graph structure.
All execution logic is in Agent and Workflow classes.
All HITL (pause/resume) is handled by LangGraph's interrupt() in MCP tools.
Workspace is initialized at conversation start (git-first architecture).
"""

import os
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Generator, TypedDict

import structlog
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from druppie.agents import Agent
from druppie.workflows import Workflow
from druppie.core.execution_context import (
    ExecutionContext,
    set_current_context,
    get_current_context,
    clear_current_context,
)
from druppie.core.mcp_client import get_mcp_client

logger = structlog.get_logger()


# =============================================================================
# DATABASE SESSION HELPER
# =============================================================================


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with guaranteed cleanup.

    This ensures database connections are always properly closed, even when
    exceptions occur. Using this instead of `next(get_db())` prevents
    connection pool exhaustion.

    Usage:
        with db_session() as db:
            # use db...
            db.commit()  # if needed
        # db is automatically closed here

    Yields:
        SQLAlchemy Session instance
    """
    from druppie.api.deps import get_db

    db_gen = get_db()
    db = next(db_gen)
    try:
        yield db
    except Exception as e:
        logger.error("db_session_error", error=str(e), error_type=type(e).__name__)
        raise
    finally:
        try:
            # Try to exhaust the generator to trigger its finally block
            next(db_gen, None)
        except StopIteration:
            pass
        # Explicit close as safety net (idempotent operation)
        db.close()


# =============================================================================
# GRAPH STATE
# =============================================================================


class GraphState(TypedDict):
    """State passed through the LangGraph flow."""
    # Input
    message: str
    session_id: str
    user_id: str | None

    # Workspace context (set after initialization)
    workspace_id: str | None
    project_id: str | None
    workspace_path: str | None
    branch: str | None

    # Router output
    intent: dict | None

    # Planner output
    plan: dict | None

    # Execution results
    results: list[dict]

    # Final response
    response: str | None
    error: str | None


# =============================================================================
# GRAPH NODES
# =============================================================================


async def router_node(state: GraphState) -> dict:
    """Run the router agent to analyze intent.

    The router can call hitl:ask if it needs clarification.
    This automatically pauses via LangGraph's interrupt().
    """
    message = state.get("message", "")
    logger.info("router_node_start", message=message[:100] if message else "(no message)")

    # Emit step event
    ctx = get_current_context()
    if ctx:
        ctx.emit("step_started", {"step": "router", "description": "Analyzing your request..."})

    try:
        result = await Agent("router").run(message)
        logger.info("router_node_complete", action=result.get("action"))
        if ctx:
            ctx.emit("step_completed", {"step": "router", "action": result.get("action")})
        return {"intent": result}
    except Exception as e:
        logger.error("router_node_error", error=str(e))
        if ctx:
            ctx.emit("step_error", {"step": "router", "error": str(e)})
        return {"error": f"Router failed: {e}"}


async def planner_node(state: GraphState) -> dict:
    """Run the planner agent to create an execution plan.

    The planner can call hitl:ask if it needs more info.
    """
    intent = state.get("intent")
    logger.info("planner_node_start", intent=intent)

    ctx = get_current_context()
    if ctx:
        ctx.emit("step_started", {"step": "planner", "description": "Creating execution plan..."})

    if not state.get("intent"):
        return {"error": "No intent from router"}

    # Check if this is just a chat response (no planning needed)
    if state["intent"].get("action") == "general_chat":
        if ctx:
            ctx.emit("step_completed", {"step": "planner", "action": "general_chat"})
        return {
            "plan": None,
            "response": state["intent"].get("answer", state["intent"].get("prompt", "")),
        }

    try:
        prompt = f"""Create a plan for:
Action: {state['intent'].get('action')}
Request: {state['intent'].get('prompt')}
Context: {state['intent'].get('project_context', {})}"""

        result = await Agent("planner").run(prompt)
        steps_count = len(result.get("steps", []))
        logger.info("planner_node_complete", steps=steps_count)
        if ctx:
            ctx.emit("step_completed", {"step": "planner", "steps_count": steps_count})
        return {"plan": result}
    except Exception as e:
        logger.error("planner_node_error", error=str(e))
        if ctx:
            ctx.emit("step_error", {"step": "planner", "error": str(e)})
        return {"error": f"Planner failed: {e}"}


async def execute_node(state: GraphState) -> dict:
    """Execute the plan steps.

    Each step can be an agent call or an MCP tool call.
    Agents can pause via hitl:ask or hitl:approve.
    """
    logger.info("execute_node_start")

    ctx = get_current_context()

    if not state.get("plan"):
        return {"results": [], "response": state.get("response", "No plan to execute")}

    plan = state["plan"]
    results = []

    # Pass workspace context to agents so they know where to work
    context = {
        "workspace_id": state.get("workspace_id"),
        "workspace_path": state.get("workspace_path"),
        "project_id": state.get("project_id"),
        "branch": state.get("branch"),
    }

    if ctx:
        ctx.emit("execution_started", {
            "plan_name": plan.get("name", "Unnamed plan"),
            "total_steps": len(plan.get("steps", [])),
        })

    # Check if this is a workflow
    if plan.get("workflow_id"):
        try:
            if ctx:
                ctx.emit("workflow_started", {"workflow_id": plan["workflow_id"]})
            workflow_result = await Workflow(plan["workflow_id"]).run(
                plan.get("inputs", {})
            )
            if ctx:
                ctx.emit("workflow_completed", {"workflow_id": plan["workflow_id"]})
            return {
                "results": workflow_result.get("results", []),
                "response": f"Workflow {plan['workflow_id']} completed",
            }
        except Exception as e:
            logger.error("workflow_error", workflow=plan["workflow_id"], error=str(e))
            if ctx:
                ctx.emit("workflow_error", {"workflow_id": plan["workflow_id"], "error": str(e)})
            return {"error": f"Workflow failed: {e}"}

    # Execute individual steps
    total_steps = len(plan.get("steps", []))
    for i, step in enumerate(plan.get("steps", [])):
        step_type = step.get("type", "agent")
        step_id = step.get("id", f"step_{i}")
        agent_id = step.get("agent_id") if step_type == "agent" else None

        logger.info("execute_step", step_id=step_id, step_type=step_type)

        if ctx:
            ctx.step_started(step_id, step_type, agent_id)
            ctx.emit("step_progress", {
                "current_step": i + 1,
                "total_steps": total_steps,
                "step_id": step_id,
                "step_type": step_type,
                "agent_id": agent_id,
                "description": step.get("prompt", step.get("tool", ""))[:100],
            })

        try:
            if step_type == "agent":
                prompt = step.get("prompt", "")
                result = await Agent(agent_id).run(prompt, context)
            elif step_type == "mcp":
                tool = step.get("tool")
                inputs = step.get("inputs", {})

                if ctx:
                    # Use MCPClient for HTTP calls to MCP microservices
                    # Parse tool name first (format: server:tool)
                    if ":" in tool:
                        server, tool_name = tool.split(":", 1)
                    else:
                        server = "coding"
                        tool_name = tool

                    with db_session() as db:
                        try:
                            mcp_client = get_mcp_client(db)
                            result = await mcp_client.call_tool(server, tool_name, inputs, ctx)

                            # Check if paused for approval
                            if result.get("status") == "paused":
                                # Return paused state - execution will resume after approval
                                return {
                                    "results": results,
                                    "response": f"Waiting for approval: {result.get('tool')}",
                                    "paused": True,
                                    "approval_id": result.get("approval_id"),
                                }
                        except Exception as mcp_error:
                            logger.error(
                                "mcp_tool_call_error",
                                step_id=step_id,
                                tool=tool,
                                server=server,
                                error=str(mcp_error),
                                error_type=type(mcp_error).__name__,
                            )
                            raise
                else:
                    result = {"error": "No execution context available for MCP call"}
            else:
                result = {"error": f"Unknown step type: {step_type}"}

            results.append({"step_id": step_id, "success": True, "result": result})
            context[step_id] = result

            if ctx:
                ctx.step_completed(step_id, success=True)

        except Exception as e:
            logger.error("step_error", step_id=step_id, error=str(e))
            results.append({"step_id": step_id, "success": False, "error": str(e)})
            if ctx:
                ctx.step_completed(step_id, success=False)
                ctx.emit("step_error", {"step_id": step_id, "error": str(e)})
            # Continue or stop based on step configuration
            if not step.get("continue_on_error", False):
                break

    # Generate response
    successful = sum(1 for r in results if r.get("success"))
    total = len(results)

    if successful == total and total > 0:
        response = f"Successfully completed all {total} steps"
    elif successful > 0:
        response = f"Completed {successful}/{total} steps"
    else:
        response = "Failed to complete steps"

    if ctx:
        ctx.emit("execution_completed", {
            "successful_steps": successful,
            "total_steps": total,
        })

    return {"results": results, "response": response}


# =============================================================================
# ROUTING FUNCTIONS
# =============================================================================


def route_after_router(state: GraphState) -> str:
    """Determine next step after router."""
    if state.get("error"):
        return "end"
    if not state.get("intent"):
        return "end"
    return "planner"


def route_after_planner(state: GraphState) -> str:
    """Determine next step after planner."""
    if state.get("error"):
        return "end"
    if state.get("response"):  # Already have a response (general_chat)
        return "end"
    if not state.get("plan") or not state["plan"].get("steps"):
        return "end"
    return "execute"


# =============================================================================
# GRAPH BUILDER
# =============================================================================


def build_graph(checkpointer=None):
    """Build the LangGraph flow.

    Args:
        checkpointer: Optional checkpointer for state persistence.
                     If None, uses in-memory checkpointer.

    Returns:
        Compiled graph
    """
    builder = StateGraph(GraphState)

    # Add nodes
    builder.add_node("router", router_node)
    builder.add_node("planner", planner_node)
    builder.add_node("execute", execute_node)

    # Add edges
    builder.set_entry_point("router")
    builder.add_conditional_edges(
        "router",
        route_after_router,
        {"planner": "planner", "end": END}
    )
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {"execute": "execute", "end": END}
    )
    builder.add_edge("execute", END)

    # Compile with checkpointer
    if checkpointer is None:
        checkpointer = MemorySaver()

    return builder.compile(checkpointer=checkpointer)


# =============================================================================
# MAIN LOOP CLASS (for API compatibility)
# =============================================================================


class MainLoop:
    """Main execution loop.

    This is a thin wrapper around the LangGraph flow for API compatibility.
    """

    def __init__(self, checkpointer=None):
        self._checkpointer = checkpointer or MemorySaver()
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_graph(self._checkpointer)
        return self._graph

    async def process_message(
        self,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the LangGraph flow.

        Args:
            message: User's message
            session_id: Session ID (used as thread_id for LangGraph)
            user_id: User ID for context
            project_id: Optional existing project ID to work on
            project_name: Optional name for new project (used if project_id not provided)
            emit_event: Callback for real-time events

        Returns:
            Response dict with results
        """
        session_id = session_id or str(uuid.uuid4())

        # Create execution context for tracking
        exec_ctx = ExecutionContext(
            session_id=session_id,
            user_id=user_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        # Save session first (required for workspace foreign key)
        await self._save_session(session_id, user_id, "initializing", message, exec_ctx)

        # Initialize workspace (git-first architecture)
        workspace_info = await self._initialize_workspace(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            project_name=project_name,
            exec_ctx=exec_ctx,
        )

        # LangGraph config (thread_id enables persistence)
        config = {"configurable": {"thread_id": session_id}}

        # Initial state
        initial_state: GraphState = {
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            "workspace_id": workspace_info.get("workspace_id"),
            "project_id": workspace_info.get("project_id"),
            "workspace_path": workspace_info.get("workspace_path"),
            "branch": workspace_info.get("branch"),
            "intent": None,
            "plan": None,
            "results": [],
            "response": None,
            "error": None,
        }

        logger.info("main_loop_start", session=session_id, message=message[:100], workspace=workspace_info)

        # Emit start event
        exec_ctx.emit("processing_started", {"message_preview": message[:100]})

        try:
            # Save session to database
            await self._save_session(session_id, user_id, "active", message, exec_ctx)

            # Run the graph
            final_state = await self.graph.ainvoke(initial_state, config=config)

            # Check for interrupt (question/approval pending)
            if "__interrupt__" in final_state:
                interrupt_data = final_state["__interrupt__"]
                await self._save_session(session_id, user_id, "paused", message, exec_ctx, final_state)
                clear_current_context()
                return {
                    "success": True,
                    "type": "interrupt",
                    "interrupt": interrupt_data,
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                    "llm_calls": exec_ctx.llm_calls,
                }

            # Check for error
            if final_state.get("error"):
                await self._save_session(session_id, user_id, "failed", message, exec_ctx, final_state)
                clear_current_context()
                return {
                    "success": False,
                    "error": final_state["error"],
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                    "llm_calls": exec_ctx.llm_calls,
                }

            # Success
            await self._save_session(session_id, user_id, "completed", message, exec_ctx, final_state)
            exec_ctx.emit("processing_completed", {"response_preview": str(final_state.get("response", ""))[:100]})
            clear_current_context()

            return {
                "success": True,
                "type": "result",
                "response": final_state.get("response"),
                "intent": final_state.get("intent"),
                "plan": final_state.get("plan"),
                "results": final_state.get("results", []),
                "session_id": session_id,
                "workspace_id": exec_ctx.workspace_id,
                "project_id": exec_ctx.project_id,
                "branch": exec_ctx.branch,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

        except Exception as e:
            logger.error("main_loop_error", error=str(e))
            await self._save_session(session_id, user_id, "failed", message, exec_ctx, error=str(e))
            clear_current_context()
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

    async def resume_session(
        self,
        session_id: str,
        response: Any,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume a paused session with user's response.

        Args:
            session_id: Session ID to resume
            response: User's response to the interrupt
            emit_event: Callback for real-time events

        Returns:
            Response dict with results
        """
        from langgraph.types import Command

        # Create execution context for tracking
        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        config = {"configurable": {"thread_id": session_id}}

        logger.info("main_loop_resume", session=session_id)

        try:
            # Resume with user's response
            final_state = await self.graph.ainvoke(
                Command(resume=response),
                config=config,
            )

            # Check for another interrupt
            if "__interrupt__" in final_state:
                clear_current_context()
                return {
                    "success": True,
                    "type": "interrupt",
                    "interrupt": final_state["__interrupt__"],
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                    "llm_calls": exec_ctx.llm_calls,
                }

            if final_state.get("error"):
                clear_current_context()
                return {
                    "success": False,
                    "error": final_state["error"],
                    "session_id": session_id,
                    "workflow_events": exec_ctx.workflow_events,
                    "llm_calls": exec_ctx.llm_calls,
                }

            clear_current_context()
            return {
                "success": True,
                "type": "result",
                "response": final_state.get("response"),
                "intent": final_state.get("intent"),
                "plan": final_state.get("plan"),
                "results": final_state.get("results", []),
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

        except Exception as e:
            logger.error("main_loop_resume_error", error=str(e))
            clear_current_context()
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

    async def _initialize_workspace(
        self,
        session_id: str,
        user_id: str | None,
        project_id: str | None,
        project_name: str | None,
        exec_ctx: ExecutionContext,
    ) -> dict[str, Any]:
        """Initialize workspace for the session (git-first architecture).

        - If project_id is provided, clones existing repo with feature branch
        - If project_name is provided, creates new project with repo on main
        - If neither, creates a project with auto-generated name

        After creating the workspace, registers it with the MCP coding server
        so that coding tools (read_file, write_file, etc.) can access it.

        Args:
            session_id: Session ID
            user_id: User ID
            project_id: Optional existing project ID
            project_name: Optional name for new project
            exec_ctx: Execution context for events

        Returns:
            Dict with workspace info (workspace_id, project_id, workspace_path, branch)
        """
        try:
            from druppie.core.workspace import get_workspace_service, WORKSPACE_ROOT

            exec_ctx.emit("workspace_initializing", {
                "project_id": project_id,
                "project_name": project_name,
            })

            with db_session() as db:
                workspace_service = get_workspace_service(db)

                # Initialize workspace (creates project/repo if needed)
                workspace = await workspace_service.initialize_workspace(
                    session_id=session_id,
                    project_id=project_id,
                    user_id=user_id,
                    project_name=project_name,
                )

                # Update execution context with workspace info
                exec_ctx.set_workspace(
                    workspace_id=workspace.id,
                    project_id=workspace.project_id,
                    workspace_path=workspace.local_path,
                    branch=workspace.branch,
                )

                db.commit()

                # Register workspace with MCP coding server
                # The MCP server uses a different mount path for the same volume
                # Backend: /app/workspace -> MCP: /workspaces
                mcp_workspace_path = workspace.local_path.replace(
                    str(WORKSPACE_ROOT), "/workspaces"
                )

                await self._register_workspace_with_mcp(
                    workspace_id=workspace.id,
                    workspace_path=mcp_workspace_path,
                    project_id=workspace.project_id,
                    branch=workspace.branch,
                    user_id=user_id,
                    session_id=session_id,
                    exec_ctx=exec_ctx,
                )

                logger.info(
                    "workspace_initialized",
                    workspace_id=workspace.id,
                    project_id=workspace.project_id,
                    branch=workspace.branch,
                    mcp_path=mcp_workspace_path,
                )

                return {
                    "workspace_id": workspace.id,
                    "project_id": workspace.project_id,
                    "workspace_path": workspace.local_path,
                    "branch": workspace.branch,
                    "is_new_project": workspace.is_new_project,
                }

        except Exception as e:
            logger.error(
                "workspace_initialization_failed",
                error=str(e),
                error_type=type(e).__name__,
                session_id=session_id,
                project_id=project_id,
            )
            exec_ctx.emit("workspace_error", {"error": str(e)})
            # Return empty workspace info - execution can continue without workspace
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
        project_id: str,
        branch: str,
        user_id: str | None,
        session_id: str,
        exec_ctx: ExecutionContext,
    ) -> None:
        """Register workspace with MCP coding server.

        The MCP coding server maintains an in-memory registry of workspaces.
        This must be called after backend workspace initialization so that
        coding tools (read_file, write_file, etc.) can find the workspace.

        Args:
            workspace_id: Workspace ID from backend
            workspace_path: Path to workspace (using MCP server's mount path)
            project_id: Project ID
            branch: Current git branch
            user_id: User ID
            session_id: Session ID
            exec_ctx: Execution context for logging
        """
        try:
            with db_session() as db:
                mcp_client = get_mcp_client(db)

                result = await mcp_client._execute_tool(
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

                if result.get("success"):
                    logger.info(
                        "workspace_registered_with_mcp",
                        workspace_id=workspace_id,
                        mcp_path=workspace_path,
                    )
                else:
                    logger.warning(
                        "workspace_mcp_registration_failed",
                        workspace_id=workspace_id,
                        error=result.get("error"),
                    )

        except Exception as e:
            # Log but don't fail - workspace still exists, just MCP might not find it
            logger.warning(
                "workspace_mcp_registration_error",
                workspace_id=workspace_id,
                error=str(e),
            )

    async def _save_session(
        self,
        session_id: str,
        user_id: str | None,
        status: str,
        message: str,
        exec_ctx: ExecutionContext,
        final_state: dict = None,
        error: str = None,
    ) -> None:
        """Save session to database.

        Args:
            session_id: Session ID
            user_id: User ID
            status: Session status (active, paused, completed, failed)
            message: Original user message
            exec_ctx: Execution context with events and calls
            final_state: Final graph state
            error: Error message if any
        """
        try:
            from druppie.db.crud import upsert_session

            # Build state to store
            state = {
                "context": {
                    "message": message,
                    "name": f"Chat: {message[:30]}...",
                    "response": final_state.get("response") if final_state else None,
                },
                "workspace": {
                    "workspace_id": exec_ctx.workspace_id,
                    "project_id": exec_ctx.project_id,
                    "workspace_path": exec_ctx.workspace_path,
                    "branch": exec_ctx.branch,
                },
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
                "intent": final_state.get("intent") if final_state else None,
                "plan": final_state.get("plan") if final_state else None,
                "results": final_state.get("results") if final_state else None,
                "error": error,
            }

            with db_session() as db:
                upsert_session(
                    db,
                    session_id,
                    user_id,
                    status,
                    state,
                    project_id=exec_ctx.project_id,
                    workspace_id=exec_ctx.workspace_id,
                )
                db.commit()

            logger.debug("session_saved", session_id=session_id, status=status)

        except Exception as e:
            logger.error(
                "session_save_error",
                session_id=session_id,
                status=status,
                error=str(e),
                error_type=type(e).__name__,
            )


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
