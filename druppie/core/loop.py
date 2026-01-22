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
from datetime import datetime, timezone
from typing import Any, Callable, Generator, TypedDict

import structlog
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from druppie.agents import Agent
from druppie.workflows import Workflow
from druppie.core.execution_context import (
    ExecutionContext,
    CancelledException,
    set_current_context,
    get_current_context,
    clear_current_context,
)
from druppie.core.mcp_client import get_mcp_client

logger = structlog.get_logger()


# =============================================================================
# PROJECT NAME EXTRACTION
# =============================================================================


def extract_project_name_from_message(message: str) -> str | None:
    """Extract a friendly project name from the user's message.

    This is used when no project_name is provided, to generate a meaningful
    name instead of using UUID-based names like "Project 2a161".

    Examples:
        "Create a to-do app" -> "to-do-app"
        "Build a weather dashboard" -> "weather-dashboard"
        "Make a simple calculator" -> "simple-calculator"
        "Write a Python script for data analysis" -> "data-analysis"

    Args:
        message: User's message describing what they want to build

    Returns:
        A friendly project name, or None if extraction fails
    """
    import re

    message_lower = message.lower().strip()

    # Common patterns for project requests
    # Pattern: "create/build/make/write a [adjective] <project name> [with/using/for...]"
    patterns = [
        # "create a to-do app", "build a weather dashboard"
        r"(?:create|build|make|write|develop|generate)\s+(?:a\s+)?(?:simple\s+|basic\s+|new\s+)?(.+?)(?:\s+(?:app|application|website|web app|webapp|site|service|api|tool|script|program|project|dashboard|system|platform))?(?:\s+(?:with|using|for|in|that|which)|\s*$)",
        # "to-do app", "weather dashboard" (direct object)
        r"^(?:a\s+)?(?:simple\s+|basic\s+|new\s+)?(.+?)\s+(?:app|application|website|web app|webapp|site|service|api|tool|script|program|project|dashboard|system|platform)(?:\s|$)",
        # Just grab the main nouns if nothing else matches
        r"(?:create|build|make|write|develop)\s+(?:a\s+)?(.+?)(?:\s+(?:with|using|for|in|that|which)|\s*$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            name = match.group(1).strip()

            # Clean up the name
            # Remove common filler words at the start
            name = re.sub(r"^(?:a|an|the|my|new|simple|basic)\s+", "", name)

            # Remove technical details at the end
            name = re.sub(r"\s+(?:using|with|in|for|that|which).*$", "", name)

            # Convert to slug format
            name = name.strip()
            name = re.sub(r"[^a-z0-9\s-]", "", name)  # Keep only alphanumeric, space, hyphen
            name = re.sub(r"[\s_]+", "-", name)  # Replace spaces/underscores with hyphens
            name = re.sub(r"-+", "-", name)  # Collapse multiple hyphens
            name = name.strip("-")

            # Limit length
            if len(name) > 50:
                # Try to cut at word boundary
                name = name[:50].rsplit("-", 1)[0]

            if name and len(name) >= 2:
                return name

    return None


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
        logger.error("db_session_error", error=str(e), error_type=type(e).__name__, exc_info=True)
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

    # Check for cancellation before starting
    if ctx:
        ctx.check_cancelled()
        ctx.emit("step_started", {"step": "router", "description": "Analyzing your request..."})

    try:
        result = await Agent("router").run(message)

        # Extract action and validate structure
        action = result.get("action", "general_chat")
        prompt = result.get("prompt", message)
        answer = result.get("answer")
        project_context = result.get("project_context", {})

        # Ensure we have a properly structured intent
        intent = {
            "action": action,
            "prompt": prompt,
            "answer": answer,
            "project_context": project_context,
        }

        logger.info(
            "router_node_complete",
            action=action,
            prompt_preview=prompt[:100] if prompt else "",
            has_answer=answer is not None,
            has_context=bool(project_context),
        )

        if ctx:
            ctx.emit("step_completed", {
                "step": "router",
                "action": action,
                "prompt": prompt,
                "has_answer": answer is not None,
                "project_name": project_context.get("project_name") if project_context else None,
            })

        return {"intent": intent}
    except Exception as e:
        logger.error("router_node_error", error=str(e), exc_info=True)
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

    # Check for cancellation before starting
    if ctx:
        ctx.check_cancelled()
        ctx.emit("step_started", {"step": "planner", "description": "Creating execution plan..."})

    if not state.get("intent"):
        return {"error": "No intent from router"}

    # Check if this is just a chat response (no planning needed)
    action = state["intent"].get("action", "general_chat")
    if action == "general_chat":
        answer = state["intent"].get("answer") or state["intent"].get("prompt", "")
        logger.info("planner_node_general_chat", answer_preview=str(answer)[:100])
        if ctx:
            ctx.emit("step_completed", {
                "step": "planner",
                "action": "general_chat",
                "skipped": True,
                "reason": "Direct chat response, no plan needed",
            })
        return {
            "plan": None,
            "response": answer,
        }

    try:
        # Build comprehensive prompt for planner
        project_context = state["intent"].get("project_context", {})
        prompt_parts = [
            f"Action: {action}",
            f"User Request: {state['intent'].get('prompt', '')}",
        ]

        if project_context:
            prompt_parts.append(f"Project Context: {project_context}")

        # Include workspace info if available
        if state.get("workspace_id"):
            prompt_parts.append(f"Workspace ID: {state.get('workspace_id')}")
        if state.get("workspace_path"):
            prompt_parts.append(f"Workspace Path: {state.get('workspace_path')}")
        if state.get("branch"):
            prompt_parts.append(f"Branch: {state.get('branch')}")

        prompt = "Create an execution plan for:\n" + "\n".join(prompt_parts)

        logger.debug("planner_prompt", prompt=prompt)

        result = await Agent("planner").run(prompt)

        # Validate plan structure
        plan_name = result.get("name", "Unnamed Plan")
        steps = result.get("steps", [])
        workflow_id = result.get("workflow_id")

        # Ensure plan has required fields
        plan = {
            "name": plan_name,
            "description": result.get("description", ""),
            "workflow_id": workflow_id,
            "steps": steps,
            "inputs": result.get("inputs", {}),
        }

        logger.info(
            "planner_node_complete",
            plan_name=plan_name,
            steps_count=len(steps),
            has_workflow=workflow_id is not None,
        )

        if ctx:
            ctx.emit("step_completed", {
                "step": "planner",
                "plan_name": plan_name,
                "steps_count": len(steps),
                "workflow_id": workflow_id,
                "steps_preview": [
                    {"id": s.get("id"), "type": s.get("type"), "agent_id": s.get("agent_id")}
                    for s in steps[:5]  # Preview first 5 steps
                ],
            })

        return {"plan": plan}

    except Exception as e:
        logger.error("planner_node_error", error=str(e), exc_info=True)
        if ctx:
            ctx.emit("step_error", {"step": "planner", "error": str(e)})
        return {"error": f"Planner failed: {e}"}


async def execute_node(state: GraphState) -> dict:
    """Execute the plan steps.

    Each step can be an agent call or an MCP tool call.
    Agents can pause via hitl:ask or hitl:approve.
    """
    logger.info("execute_node_start", plan=state.get("plan", {}).get("name"))

    ctx = get_current_context()

    # Check for cancellation before starting
    if ctx:
        ctx.check_cancelled()

    if not state.get("plan"):
        logger.debug("execute_node_no_plan", response=state.get("response"))
        return {"results": [], "response": state.get("response", "No plan to execute")}

    plan = state["plan"]
    results = []

    # Pass workspace context to agents so they know where to work
    # This is critical for agents to know where files should be created
    context = {
        "workspace_id": state.get("workspace_id"),
        "workspace_path": state.get("workspace_path"),
        "project_id": state.get("project_id"),
        "branch": state.get("branch"),
        "session_id": state.get("session_id"),  # For HITL tools
    }

    logger.debug("execute_node_context", context=context)

    if ctx:
        ctx.emit("execution_started", {
            "plan_name": plan.get("name", "Unnamed plan"),
            "total_steps": len(plan.get("steps", [])),
            "workspace_id": context.get("workspace_id"),
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
            logger.error("workflow_error", workflow=plan["workflow_id"], error=str(e), exc_info=True)
            if ctx:
                ctx.emit("workflow_error", {"workflow_id": plan["workflow_id"], "error": str(e)})
            return {"error": f"Workflow failed: {e}"}

    # Execute individual steps
    total_steps = len(plan.get("steps", []))
    for i, step in enumerate(plan.get("steps", [])):
        # Check for cancellation before each step
        if ctx:
            ctx.check_cancelled()

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

                logger.info(
                    "execute_agent_step",
                    step_id=step_id,
                    agent_id=agent_id,
                    prompt_preview=prompt[:100] if prompt else "",
                    workspace_id=context.get("workspace_id"),
                )

                if ctx:
                    ctx.emit("agent_starting", {
                        "step_id": step_id,
                        "agent_id": agent_id,
                        "prompt": prompt,
                    })

                result = await Agent(agent_id).run(prompt, context)

                # Check if agent returned paused state (for approval)
                if isinstance(result, dict) and result.get("paused"):
                    approval_id = result.get("approval_id")
                    logger.info("agent_paused", step_id=step_id, agent_id=agent_id, approval_id=approval_id)

                    # Update the approval with plan execution state so we can resume properly
                    # This is critical - MCP tool approvals need the same state as step approvals
                    if approval_id:
                        try:
                            from druppie.db.crud import update_approval
                            with db_session() as db:
                                update_approval(
                                    db,
                                    approval_id,
                                    {
                                        "agent_state": {
                                            "plan": plan,
                                            "current_step": i,
                                            "results": results,
                                            "context": context,
                                            "agent_id": agent_id,  # Track which agent was running
                                        },
                                    },
                                )
                                db.commit()
                                logger.info(
                                    "approval_state_saved",
                                    approval_id=approval_id,
                                    step_id=step_id,
                                    current_step=i,
                                )
                        except Exception as e:
                            logger.error(
                                "approval_state_save_failed",
                                approval_id=approval_id,
                                error=str(e),
                            )

                    if ctx:
                        ctx.emit("agent_paused", {
                            "step_id": step_id,
                            "agent_id": agent_id,
                            "approval_id": approval_id,
                        })
                    return {
                        "results": results,
                        "response": f"Waiting for approval in step {step_id}",
                        "paused": True,
                        "approval_id": approval_id,
                    }

                logger.info(
                    "execute_agent_complete",
                    step_id=step_id,
                    agent_id=agent_id,
                    result_type=type(result).__name__,
                )

                if ctx:
                    ctx.emit("agent_completed", {
                        "step_id": step_id,
                        "agent_id": agent_id,
                        "result_preview": str(result)[:200] if result else "",
                    })

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

                    # Inject context into inputs based on server type
                    if server == "coding" and "workspace_id" not in inputs:
                        if context.get("workspace_id"):
                            inputs["workspace_id"] = context["workspace_id"]
                    if server == "hitl" and "session_id" not in inputs:
                        if context.get("session_id"):
                            inputs["session_id"] = context["session_id"]
                    if server == "docker" and "workspace_id" not in inputs:
                        if context.get("workspace_id"):
                            inputs["workspace_id"] = context["workspace_id"]

                    logger.debug(
                        "mcp_step_inputs",
                        step_id=step_id,
                        tool=tool,
                        inputs=inputs,
                    )

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
                                exc_info=True,
                            )
                            raise
                else:
                    result = {"error": "No execution context available for MCP call"}
            elif step_type == "approval":
                # Approval checkpoint - pause and wait for user approval
                approval_message = step.get("message", "Approval required to continue")
                required_roles = step.get("required_roles", ["developer", "admin"])
                approval_context = step.get("context", {})

                logger.info(
                    "approval_checkpoint",
                    step_id=step_id,
                    message=approval_message,
                    required_roles=required_roles,
                )

                if ctx:
                    # Create approval request
                    from druppie.db.crud import create_approval
                    with db_session() as db:
                        approval = create_approval(
                            db,
                            {
                                "session_id": context.get("session_id"),
                                "tool_name": f"approval:{step_id}",
                                "arguments": {"message": approval_message, **approval_context},
                                "required_roles": required_roles,
                                "description": approval_message,
                                "agent_state": {
                                    "plan": plan,
                                    "current_step": i,
                                    "results": results,
                                    "context": context,
                                },
                            }
                        )

                    # Emit approval required event directly (not wrapped as workflow_event)
                    # This ensures the frontend receives it with type="approval_required"
                    if ctx.emit_event:
                        ctx.emit_event({
                            "type": "approval_required",
                            "session_id": context.get("session_id"),
                            "approval_id": str(approval.id),
                            "message": approval_message,
                            "required_roles": required_roles,
                            "step_id": step_id,
                            "context": approval_context,
                        })
                    # Also store it as a workflow event for the timeline
                    ctx.emit("approval_required", {
                        "approval_id": str(approval.id),
                        "message": approval_message,
                        "required_roles": required_roles,
                        "step_id": step_id,
                        "context": approval_context,
                    })

                    # Return paused state
                    return {
                        "results": results,
                        "response": f"Waiting for approval: {approval_message}",
                        "paused": True,
                        "approval_id": str(approval.id),
                    }
                else:
                    # No context - skip approval
                    result = {"approved": True, "skipped": True}

            else:
                result = {"error": f"Unknown step type: {step_type}"}

            results.append({"step_id": step_id, "success": True, "result": result})
            context[step_id] = result

            if ctx:
                ctx.step_completed(step_id, success=True)

        except Exception as e:
            logger.error("step_error", step_id=step_id, error=str(e), exc_info=True)
            results.append({"step_id": step_id, "success": False, "error": str(e)})
            if ctx:
                ctx.step_completed(step_id, success=False)
                ctx.emit("step_error", {"step_id": step_id, "error": str(e)})
            # Continue or stop based on step configuration
            if not step.get("continue_on_error", False):
                break

    # Generate response - prefer agent's final response (e.g., deployer with URL)
    successful = sum(1 for r in results if r.get("success"))
    total = len(results)

    # Try to find a meaningful agent response to show the user
    # Deployer agent should return the deployment URL
    final_agent_response = None
    for r in reversed(results):  # Check most recent results first
        if r.get("success") and isinstance(r.get("result"), dict):
            result_data = r["result"]
            # Check if this is an agent response with text content
            # Agent returns {"content": "..."} when output is text (not JSON)
            if isinstance(result_data.get("content"), str) and len(result_data["content"]) > 20:
                final_agent_response = result_data["content"]
                break
            if isinstance(result_data.get("response"), str) and len(result_data["response"]) > 20:
                final_agent_response = result_data["response"]
                break
            # Check for URL in docker run result
            if result_data.get("url"):
                final_agent_response = f"**Deployment Complete!**\n\n- **URL**: {result_data['url']}\n- **Container**: {result_data.get('container_name', 'N/A')}\n- **Port**: {result_data.get('port', 'N/A')}"
                break

    if final_agent_response:
        response = final_agent_response
    elif successful == total and total > 0:
        response = f"Successfully completed all {total} steps"
    elif successful > 0:
        response = f"Completed {successful}/{total} steps"
    else:
        response = "Failed to complete steps"

    if ctx:
        ctx.emit("execution_completed", {
            "successful_steps": successful,
            "total_steps": total,
            "final_response": response[:200] if response else None,
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
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the LangGraph flow.

        Args:
            message: User's message
            session_id: Session ID (used as thread_id for LangGraph)
            user_id: User ID for context
            project_id: Optional existing project ID to work on
            project_name: Optional name for new project (used if project_id not provided)
            emit_event: Callback for real-time events
            conversation_history: Previous conversation messages for context

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

        # Load existing messages from session state or use provided history
        existing_messages = await self._load_messages(session_id)
        if not existing_messages and conversation_history:
            # Use provided history if no stored messages
            existing_messages = conversation_history

        # Add new user message
        messages = list(existing_messages) if existing_messages else []
        messages.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Store messages in context for later saving
        exec_ctx.messages = messages

        # Save session first (required for workspace foreign key)
        await self._save_session(session_id, user_id, "initializing", message, exec_ctx)

        # Extract friendly project name from message if not provided
        # This prevents ugly names like "Project 2a161" and instead uses
        # friendly names like "to-do-app" based on the user's request
        effective_project_name = project_name
        if not project_id and not project_name:
            extracted_name = extract_project_name_from_message(message)
            if extracted_name:
                effective_project_name = extracted_name
                logger.info(
                    "extracted_project_name",
                    message_preview=message[:50],
                    extracted_name=extracted_name,
                )

        # Initialize workspace (git-first architecture)
        workspace_info = await self._initialize_workspace(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            project_name=effective_project_name,
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

            # Success - add assistant message to history with workflow events
            response_text = final_state.get("response", "")
            if response_text and exec_ctx.messages is not None:
                exec_ctx.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    # Attach workflow events to this message for persistence
                    "workflow_events": exec_ctx.workflow_events.copy(),
                    "llm_calls": exec_ctx.llm_calls.copy(),
                })

            await self._save_session(session_id, user_id, "completed", message, exec_ctx, final_state)
            exec_ctx.emit("processing_completed", {"response_preview": str(response_text)[:100]})
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
                "project_name": exec_ctx.project_name,
                "branch": exec_ctx.branch,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

        except CancelledException:
            # User cancelled the execution
            logger.info("main_loop_cancelled", session_id=session_id)
            await self._save_session(session_id, user_id, "cancelled", message, exec_ctx)
            clear_current_context()
            return {
                "success": False,
                "error": "Execution was cancelled by user",
                "cancelled": True,
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

        except Exception as e:
            logger.error("main_loop_error", error=str(e), exc_info=True)
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
            logger.error("main_loop_resume_error", error=str(e), exc_info=True)
            clear_current_context()
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

    async def resume_from_step_approval(
        self,
        session_id: str,
        agent_state: dict,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume plan execution from a step approval checkpoint.

        This is called when:
        1. A step approval (type: "approval") is approved - continue from NEXT step
        2. An MCP tool approval is approved - continue from SAME step (re-run agent)

        Args:
            session_id: Session ID
            agent_state: Saved state from the approval containing:
                - plan: The execution plan
                - current_step: Index of the approval step (0-indexed)
                - results: Results from steps before the approval
                - context: Workspace/session context
                - agent_id: (optional) If present, this was an MCP tool approval
                - last_tool_result: (optional) Result of the just-executed approved tool
            emit_event: Callback for real-time events

        Returns:
            Response dict with results
        """
        # Create execution context for tracking
        exec_ctx = ExecutionContext(
            session_id=session_id,
            emit_event=emit_event,
        )
        set_current_context(exec_ctx)

        # Extract saved state
        plan = agent_state.get("plan", {})
        current_step_idx = agent_state.get("current_step", 0)
        results = agent_state.get("results", [])
        context = agent_state.get("context", {})
        last_tool_result = agent_state.get("last_tool_result")

        # Check if this was an MCP tool approval (has agent_id) or step approval
        is_mcp_tool_approval = "agent_id" in agent_state

        # Update execution context with workspace info
        exec_ctx.workspace_id = context.get("workspace_id")
        exec_ctx.project_id = context.get("project_id")
        exec_ctx.workspace_path = context.get("workspace_path")
        exec_ctx.branch = context.get("branch")

        # Store the last tool result so MCPClient can return it instead of re-executing
        # Also add it to context so the agent knows what happened with the approved tool
        if last_tool_result:
            exec_ctx.completed_tool_results = exec_ctx.completed_tool_results if hasattr(exec_ctx, "completed_tool_results") else {}
            tool_key = last_tool_result.get("tool", "")
            exec_ctx.completed_tool_results[tool_key] = last_tool_result.get("result")

            # CRITICAL: Add the tool result to context so agent knows the approved tool succeeded
            # This prevents the agent from trying to re-do work that was already completed
            tool_result = last_tool_result.get("result", {})
            context["last_approved_tool"] = tool_key
            context["last_tool_result"] = tool_result

            # If this was docker:run, explicitly add the URL to context
            if tool_key == "docker:run" and isinstance(tool_result, dict):
                if tool_result.get("success") and tool_result.get("url"):
                    context["deployment_url"] = tool_result.get("url")
                    context["deployment_complete"] = True
                    context["container_name"] = tool_result.get("container_name")
                    context["container_id"] = tool_result.get("container_id")

                    # SHORT-CIRCUIT: Deployment is complete! Don't re-run agent.
                    # The agent would try to call more tools, but we already have the result.
                    logger.info(
                        "deployment_complete_short_circuit",
                        session_id=session_id,
                        deployment_url=tool_result.get("url"),
                        container_name=tool_result.get("container_name"),
                    )

                    # Build deployment success response
                    deployment_response = (
                        f"**Deployment Complete!**\n\n"
                        f"- **URL**: {tool_result.get('url')}\n"
                        f"- **Container**: {tool_result.get('container_name', 'N/A')}\n"
                        f"- **Image**: {tool_result.get('image_name', 'N/A')}\n"
                        f"- **Port**: {tool_result.get('port', 'N/A')}\n"
                        f"- **Status**: Running\n\n"
                        f"To view logs: `docker logs {tool_result.get('container_name')}`\n"
                        f"To stop: `docker stop {tool_result.get('container_name')}`"
                    )

                    # Add the deployment result to results
                    results.append({
                        "step_id": f"step_{current_step_idx}",
                        "success": True,
                        "result": tool_result,
                    })

                    exec_ctx.emit("deployment_complete", {
                        "url": tool_result.get("url"),
                        "container_name": tool_result.get("container_name"),
                        "container_id": tool_result.get("container_id"),
                    })

                    exec_ctx.emit("execution_completed", {
                        "successful_steps": len(results),
                        "total_steps": len(plan.get("steps", [])),
                        "final_response": deployment_response[:200],
                    })

                    # Save session state with final response for persistence
                    # This ensures the deployment info is available on page reload
                    try:
                        from druppie.db.crud import update_session, get_session
                        with db_session() as db:
                            existing_session = get_session(db, session_id)
                            if existing_session:
                                existing_state = existing_session.state or {}
                                existing_messages = existing_state.get("messages", [])

                                # Add deployment completion message
                                existing_messages.append({
                                    "role": "assistant",
                                    "content": deployment_response,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "workflow_events": exec_ctx.workflow_events,
                                    "llm_calls": exec_ctx.llm_calls,
                                    "deployment_url": tool_result.get("url"),
                                    "container_name": tool_result.get("container_name"),
                                })

                                # Update context with final response
                                existing_context = existing_state.get("context", {})
                                existing_context["response"] = deployment_response
                                existing_context["deployment_url"] = tool_result.get("url")
                                existing_context["deployment_complete"] = True

                                update_session(
                                    db,
                                    session_id,
                                    status="completed",
                                    state={
                                        **existing_state,
                                        "messages": existing_messages,
                                        "context": existing_context,
                                        "workflow_events": exec_ctx.workflow_events,
                                        "llm_calls": exec_ctx.llm_calls,
                                    },
                                )
                                db.commit()
                                logger.info(
                                    "session_state_saved_on_deployment_complete",
                                    session_id=session_id,
                                    deployment_url=tool_result.get("url"),
                                )
                    except Exception as e:
                        logger.warning(
                            "failed_to_save_session_state_on_deployment",
                            session_id=session_id,
                            error=str(e),
                        )

                    clear_current_context()
                    return {
                        "success": True,
                        "type": "result",
                        "response": deployment_response,
                        "results": results,
                        "session_id": session_id,
                        "deployment_url": tool_result.get("url"),
                        "container_name": tool_result.get("container_name"),
                        "workflow_events": exec_ctx.workflow_events,
                        "llm_calls": exec_ctx.llm_calls,
                    }

        steps = plan.get("steps", [])
        total_steps = len(steps)

        # For MCP tool approvals: re-run the current step (agent might need more tools)
        # For step approvals: continue from the next step
        if is_mcp_tool_approval:
            start_step = current_step_idx  # Re-run current step
        else:
            start_step = current_step_idx + 1  # Skip to next step

        logger.info(
            "resume_from_step_approval",
            session_id=session_id,
            current_step=current_step_idx,
            start_step=start_step,
            total_steps=total_steps,
            plan_name=plan.get("name"),
            is_mcp_tool_approval=is_mcp_tool_approval,
            has_last_tool_result=last_tool_result is not None,
        )

        exec_ctx.emit("execution_resumed", {
            "plan_name": plan.get("name", "Unnamed plan"),
            "resumed_from_step": start_step,
            "total_steps": total_steps,
        })

        try:
            # Execute remaining steps
            for i in range(start_step, total_steps):
                # Check for cancellation before each step
                exec_ctx.check_cancelled()

                step = steps[i]
                step_type = step.get("type", "agent")
                step_id = step.get("id", f"step_{i}")
                agent_id = step.get("agent_id") if step_type == "agent" else None

                logger.info("execute_step_after_approval", step_id=step_id, step_type=step_type)

                exec_ctx.step_started(step_id, step_type, agent_id)
                exec_ctx.emit("step_progress", {
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

                        logger.info(
                            "execute_agent_step_resumed",
                            step_id=step_id,
                            agent_id=agent_id,
                            prompt_preview=prompt[:100] if prompt else "",
                        )

                        exec_ctx.emit("agent_starting", {
                            "step_id": step_id,
                            "agent_id": agent_id,
                            "prompt": prompt,
                        })

                        result = await Agent(agent_id).run(prompt, context)

                        # Check if agent returned paused state (for another approval)
                        if isinstance(result, dict) and result.get("paused"):
                            approval_id = result.get("approval_id")
                            logger.info("agent_paused_again", step_id=step_id, agent_id=agent_id, approval_id=approval_id)

                            # CRITICAL: Save agent_state to approval for proper resume
                            # This is the same pattern used in execute_plan()
                            if approval_id:
                                try:
                                    from druppie.db.crud import update_approval
                                    with db_session() as db:
                                        update_approval(
                                            db,
                                            approval_id,
                                            {
                                                "agent_state": {
                                                    "plan": plan,
                                                    "current_step": i,
                                                    "results": results,
                                                    "context": context,
                                                    "agent_id": agent_id,  # Track which agent was running
                                                },
                                            },
                                        )
                                        db.commit()
                                        logger.info(
                                            "approval_state_saved_on_resume",
                                            approval_id=approval_id,
                                            step_id=step_id,
                                            current_step=i,
                                        )
                                except Exception as e:
                                    logger.error(
                                        "approval_state_save_failed_on_resume",
                                        approval_id=approval_id,
                                        error=str(e),
                                    )

                            exec_ctx.emit("agent_paused", {
                                "step_id": step_id,
                                "agent_id": agent_id,
                                "approval_id": approval_id,
                            })
                            clear_current_context()
                            return {
                                "success": True,
                                "type": "interrupt",
                                "response": f"Waiting for approval in step {step_id}",
                                "paused": True,
                                "approval_id": result.get("approval_id"),
                                "session_id": session_id,
                                "workflow_events": exec_ctx.workflow_events,
                                "llm_calls": exec_ctx.llm_calls,
                            }

                        exec_ctx.emit("agent_completed", {
                            "step_id": step_id,
                            "agent_id": agent_id,
                            "result_preview": str(result)[:200] if result else "",
                        })

                    elif step_type == "mcp":
                        tool = step.get("tool")
                        inputs = step.get("inputs", {})

                        # Parse tool name (format: server:tool)
                        if ":" in tool:
                            server, tool_name = tool.split(":", 1)
                        else:
                            server = "coding"
                            tool_name = tool

                        # Inject context into inputs
                        if server == "coding" and "workspace_id" not in inputs:
                            if context.get("workspace_id"):
                                inputs["workspace_id"] = context["workspace_id"]
                        if server == "hitl" and "session_id" not in inputs:
                            if context.get("session_id"):
                                inputs["session_id"] = context["session_id"]
                        if server == "docker" and "workspace_id" not in inputs:
                            if context.get("workspace_id"):
                                inputs["workspace_id"] = context["workspace_id"]

                        with db_session() as db:
                            mcp_client = get_mcp_client(db)
                            result = await mcp_client.call_tool(server, tool_name, inputs, exec_ctx)

                            # Check if paused for approval
                            if result.get("status") == "paused":
                                clear_current_context()
                                return {
                                    "success": True,
                                    "type": "interrupt",
                                    "response": f"Waiting for approval: {result.get('tool')}",
                                    "paused": True,
                                    "approval_id": result.get("approval_id"),
                                    "session_id": session_id,
                                    "workflow_events": exec_ctx.workflow_events,
                                    "llm_calls": exec_ctx.llm_calls,
                                }

                    elif step_type == "approval":
                        # Another approval checkpoint
                        approval_message = step.get("message", "Approval required to continue")
                        required_roles = step.get("required_roles", ["developer", "admin"])
                        approval_context = step.get("context", {})

                        logger.info(
                            "another_approval_checkpoint",
                            step_id=step_id,
                            message=approval_message,
                        )

                        # Create approval request
                        from druppie.db.crud import create_approval
                        with db_session() as db:
                            approval = create_approval(
                                db,
                                {
                                    "session_id": session_id,
                                    "tool_name": f"approval:{step_id}",
                                    "arguments": {"message": approval_message, **approval_context},
                                    "required_roles": required_roles,
                                    "description": approval_message,
                                    "agent_state": {
                                        "plan": plan,
                                        "current_step": i,
                                        "results": results,
                                        "context": context,
                                    },
                                }
                            )

                        # Emit approval required event
                        if exec_ctx.emit_event:
                            exec_ctx.emit_event({
                                "type": "approval_required",
                                "session_id": session_id,
                                "approval_id": str(approval.id),
                                "message": approval_message,
                                "required_roles": required_roles,
                                "step_id": step_id,
                                "context": approval_context,
                            })

                        clear_current_context()
                        return {
                            "success": True,
                            "type": "interrupt",
                            "response": f"Waiting for approval: {approval_message}",
                            "paused": True,
                            "approval_id": str(approval.id),
                            "session_id": session_id,
                            "workflow_events": exec_ctx.workflow_events,
                            "llm_calls": exec_ctx.llm_calls,
                        }
                    else:
                        result = {"error": f"Unknown step type: {step_type}"}

                    results.append({"step_id": step_id, "success": True, "result": result})
                    context[step_id] = result
                    exec_ctx.step_completed(step_id, success=True)

                except CancelledException:
                    raise
                except Exception as e:
                    logger.error("step_error_after_approval", step_id=step_id, error=str(e), exc_info=True)
                    results.append({"step_id": step_id, "success": False, "error": str(e)})
                    exec_ctx.step_completed(step_id, success=False)
                    exec_ctx.emit("step_error", {"step_id": step_id, "error": str(e)})
                    if not step.get("continue_on_error", False):
                        break

            # Generate response - prefer agent's final response (e.g., deployer with URL)
            successful = sum(1 for r in results if r.get("success"))
            total = len(results)

            # Try to find a meaningful agent response to show the user
            final_agent_response = None
            for r in reversed(results):  # Check most recent results first
                if r.get("success") and isinstance(r.get("result"), dict):
                    result_data = r["result"]
                    # Check if this is an agent response with text content
                    # Agent returns {"content": "..."} when output is text (not JSON)
                    if isinstance(result_data.get("content"), str) and len(result_data["content"]) > 20:
                        final_agent_response = result_data["content"]
                        break
                    if isinstance(result_data.get("response"), str) and len(result_data["response"]) > 20:
                        final_agent_response = result_data["response"]
                        break
                    # Check for URL in docker run result
                    if result_data.get("url"):
                        final_agent_response = f"**Deployment Complete!**\n\n- **URL**: {result_data['url']}\n- **Container**: {result_data.get('container_name', 'N/A')}\n- **Port**: {result_data.get('port', 'N/A')}"
                        break

            if final_agent_response:
                response = final_agent_response
            elif successful == total and total > 0:
                response = f"Successfully completed all {total} steps"
            elif successful > 0:
                response = f"Completed {successful}/{total} steps"
            else:
                response = "Failed to complete steps"

            exec_ctx.emit("execution_completed", {
                "successful_steps": successful,
                "total_steps": total,
                "final_response": response[:200] if response else None,
            })

            clear_current_context()
            return {
                "success": True,
                "type": "result",
                "response": response,
                "results": results,
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

        except CancelledException:
            logger.info("step_approval_resume_cancelled", session_id=session_id)
            clear_current_context()
            return {
                "success": False,
                "error": "Execution was cancelled by user",
                "cancelled": True,
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }
        except Exception as e:
            logger.error("step_approval_resume_error", error=str(e), exc_info=True)
            clear_current_context()
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "workflow_events": exec_ctx.workflow_events,
                "llm_calls": exec_ctx.llm_calls,
            }

    async def _load_messages(self, session_id: str) -> list[dict]:
        """Load existing messages from session state.

        Args:
            session_id: Session ID to load messages from

        Returns:
            List of message dicts or empty list if no session/messages
        """
        try:
            from druppie.db.crud import get_session

            with db_session() as db:
                session = get_session(db, session_id)
                if session and session.state:
                    return session.state.get("messages", [])
        except Exception as e:
            logger.warning("load_messages_error", session_id=session_id, error=str(e))
        return []

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

        Only emits workspace_initializing/workspace_initialized events on first
        message of a session. Subsequent messages reuse the existing workspace.

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
            from druppie.db.crud import get_workspace_by_session

            # Check if workspace already exists for this session (subsequent messages)
            with db_session() as db:
                existing_workspace = get_workspace_by_session(db, session_id)
                if existing_workspace:
                    # Workspace already exists - skip initialization events
                    logger.info(
                        "workspace_reusing_existing",
                        session_id=session_id,
                        workspace_id=existing_workspace.id,
                    )

                    # Get project name for the existing workspace
                    from druppie.db.models import Project
                    existing_project_name = None
                    if existing_workspace.project_id:
                        project_record = db.query(Project).filter(
                            Project.id == existing_workspace.project_id
                        ).first()
                        if project_record:
                            existing_project_name = project_record.name

                    # Update execution context with existing workspace info (silently, no events)
                    exec_ctx.workspace_id = existing_workspace.id
                    exec_ctx.project_id = existing_workspace.project_id
                    exec_ctx.project_name = existing_project_name
                    exec_ctx.workspace_path = existing_workspace.local_path
                    exec_ctx.branch = existing_workspace.branch

                    # Re-register with MCP (in case server restarted)
                    mcp_workspace_path = existing_workspace.local_path.replace(
                        str(WORKSPACE_ROOT), "/workspaces"
                    )
                    await self._register_workspace_with_mcp(
                        workspace_id=existing_workspace.id,
                        workspace_path=mcp_workspace_path,
                        project_id=existing_workspace.project_id,
                        branch=existing_workspace.branch,
                        user_id=user_id,
                        session_id=session_id,
                        exec_ctx=exec_ctx,
                    )

                    return {
                        "workspace_id": existing_workspace.id,
                        "project_id": existing_workspace.project_id,
                        "project_name": existing_project_name,
                        "workspace_path": existing_workspace.local_path,
                        "branch": existing_workspace.branch,
                        "is_new_project": False,
                        "reused": True,
                    }

            # First message in session - emit initialization events
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

                # Get the actual project name from the database
                # (may differ from input if sanitized or unique suffix added)
                from druppie.db.models import Project
                actual_project_name = None
                if workspace.project_id:
                    project_record = db.query(Project).filter(
                        Project.id == workspace.project_id
                    ).first()
                    if project_record:
                        actual_project_name = project_record.name

                # Update execution context with workspace info
                exec_ctx.set_workspace(
                    workspace_id=workspace.id,
                    project_id=workspace.project_id,
                    workspace_path=workspace.local_path,
                    branch=workspace.branch,
                    project_name=actual_project_name,
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
                    "project_name": actual_project_name,
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
                exc_info=True,
            )
            exec_ctx.emit("workspace_error", {"error": str(e)})
            # Return empty workspace info - execution can continue without workspace
            return {
                "workspace_id": None,
                "project_id": project_id,
                "project_name": None,
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
        """Register workspace with MCP servers (coding and docker).

        The MCP servers maintain in-memory registries of workspaces.
        This must be called after backend workspace initialization so that
        tools (read_file, write_file, docker build, etc.) can find the workspace.

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

                # Register with coding MCP
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
                        "workspace_registered_with_coding_mcp",
                        workspace_id=workspace_id,
                        mcp_path=workspace_path,
                    )
                else:
                    logger.warning(
                        "workspace_coding_mcp_registration_failed",
                        workspace_id=workspace_id,
                        error=result.get("error"),
                    )

                # Also register with Docker MCP for docker:build to find workspace
                docker_result = await mcp_client._execute_tool(
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

                if docker_result.get("success"):
                    logger.info(
                        "workspace_registered_with_docker_mcp",
                        workspace_id=workspace_id,
                        mcp_path=workspace_path,
                    )
                else:
                    logger.warning(
                        "workspace_docker_mcp_registration_failed",
                        workspace_id=workspace_id,
                        error=docker_result.get("error"),
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
                "messages": exec_ctx.messages,  # Store full conversation history
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
                exc_info=True,
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
