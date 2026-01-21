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
from typing import Any, Callable, TypedDict

import structlog
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from druppie.agents import Agent
from druppie.workflows import Workflow
from druppie.mcps.hitl import configure_hitl
from druppie.core.execution_context import (
    ExecutionContext,
    set_current_context,
    get_current_context,
    clear_current_context,
)
from druppie.core.mcp_client import get_mcp_client

logger = structlog.get_logger()


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
    logger.info("router_node_start", message=state["message"][:100])

    # Emit step event
    ctx = get_current_context()
    if ctx:
        ctx.emit("step_started", {"step": "router", "description": "Analyzing your request..."})

    try:
        result = await Agent("router").run(state["message"])
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
    logger.info("planner_node_start", intent=state["intent"])

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
    context = {}

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

                # Check if we should use HTTP-based MCPClient (for microservices)
                use_http_mcp = os.getenv("USE_MCP_MICROSERVICES", "false").lower() == "true"

                if use_http_mcp and ctx:
                    # Use MCPClient for HTTP calls to MCP microservices
                    from druppie.api.deps import get_db

                    db = next(get_db())
                    try:
                        mcp_client = get_mcp_client(db)

                        # Parse tool name (format: server:tool)
                        if ":" in tool:
                            server, tool_name = tool.split(":", 1)
                        else:
                            server = "coding"
                            tool_name = tool

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
                    finally:
                        db.close()
                else:
                    # Use in-process MCP registry (legacy mode)
                    from druppie.mcps import get_mcp_registry
                    result = await get_mcp_registry().call_tool(tool, inputs)
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

        # Configure HITL for this session
        configure_hitl(emit_event, session_id)

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

        configure_hitl(emit_event, session_id)

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
            from druppie.core.workspace import get_workspace_service
            from druppie.api.deps import get_db

            exec_ctx.emit("workspace_initializing", {
                "project_id": project_id,
                "project_name": project_name,
            })

            # Get database session
            db = next(get_db())
            try:
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

                logger.info(
                    "workspace_initialized",
                    workspace_id=workspace.id,
                    project_id=workspace.project_id,
                    branch=workspace.branch,
                )

                return {
                    "workspace_id": workspace.id,
                    "project_id": workspace.project_id,
                    "workspace_path": workspace.local_path,
                    "branch": workspace.branch,
                    "is_new_project": workspace.is_new_project,
                }

            finally:
                db.close()

        except Exception as e:
            logger.error("workspace_initialization_failed", error=str(e))
            exec_ctx.emit("workspace_error", {"error": str(e)})
            # Return empty workspace info - execution can continue without workspace
            return {
                "workspace_id": None,
                "project_id": project_id,
                "workspace_path": None,
                "branch": None,
            }

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
            from druppie.api.deps import get_db

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

            # Get database session
            db = next(get_db())
            try:
                upsert_session(db, session_id, user_id, status, state)
                db.commit()
            finally:
                db.close()

            logger.debug("session_saved", session_id=session_id, status=status)

        except Exception as e:
            logger.error("session_save_error", session_id=session_id, error=str(e))


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
