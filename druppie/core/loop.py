"""Main Execution Loop for Druppie using LangGraph.

This is the heart of the architecture - a minimal graph that orchestrates agents.

Flow:
    User Message
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
"""

import uuid
from typing import Any, Callable, TypedDict

import structlog
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from druppie.agents import Agent
from druppie.workflows import Workflow
from druppie.mcps.hitl import configure_hitl

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

    try:
        result = await Agent("router").run(state["message"])
        logger.info("router_node_complete", action=result.get("action"))
        return {"intent": result}
    except Exception as e:
        logger.error("router_node_error", error=str(e))
        return {"error": f"Router failed: {e}"}


async def planner_node(state: GraphState) -> dict:
    """Run the planner agent to create an execution plan.

    The planner can call hitl:ask if it needs more info.
    """
    logger.info("planner_node_start", intent=state["intent"])

    if not state.get("intent"):
        return {"error": "No intent from router"}

    # Check if this is just a chat response (no planning needed)
    if state["intent"].get("action") == "general_chat":
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
        logger.info("planner_node_complete", steps=len(result.get("steps", [])))
        return {"plan": result}
    except Exception as e:
        logger.error("planner_node_error", error=str(e))
        return {"error": f"Planner failed: {e}"}


async def execute_node(state: GraphState) -> dict:
    """Execute the plan steps.

    Each step can be an agent call or an MCP tool call.
    Agents can pause via hitl:ask or hitl:approve.
    """
    logger.info("execute_node_start")

    if not state.get("plan"):
        return {"results": [], "response": state.get("response", "No plan to execute")}

    plan = state["plan"]
    results = []
    context = {}

    # Check if this is a workflow
    if plan.get("workflow_id"):
        try:
            workflow_result = await Workflow(plan["workflow_id"]).run(
                plan.get("inputs", {})
            )
            return {
                "results": workflow_result.get("results", []),
                "response": f"Workflow {plan['workflow_id']} completed",
            }
        except Exception as e:
            logger.error("workflow_error", workflow=plan["workflow_id"], error=str(e))
            return {"error": f"Workflow failed: {e}"}

    # Execute individual steps
    for i, step in enumerate(plan.get("steps", [])):
        step_type = step.get("type", "agent")
        step_id = step.get("id", f"step_{i}")

        logger.info("execute_step", step_id=step_id, step_type=step_type)

        try:
            if step_type == "agent":
                agent_id = step.get("agent_id")
                prompt = step.get("prompt", "")
                result = await Agent(agent_id).run(prompt, context)
            elif step_type == "mcp":
                from druppie.mcps import get_mcp_registry
                tool = step.get("tool")
                inputs = step.get("inputs", {})
                result = await get_mcp_registry().call_tool(tool, inputs)
            else:
                result = {"error": f"Unknown step type: {step_type}"}

            results.append({"step_id": step_id, "success": True, "result": result})
            context[step_id] = result

        except Exception as e:
            logger.error("step_error", step_id=step_id, error=str(e))
            results.append({"step_id": step_id, "success": False, "error": str(e)})
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
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the LangGraph flow.

        Args:
            message: User's message
            session_id: Session ID (used as thread_id for LangGraph)
            user_id: User ID for context
            emit_event: Callback for real-time events

        Returns:
            Response dict with results
        """
        session_id = session_id or str(uuid.uuid4())

        # Configure HITL for this session
        configure_hitl(emit_event, session_id)

        # LangGraph config (thread_id enables persistence)
        config = {"configurable": {"thread_id": session_id}}

        # Initial state
        initial_state: GraphState = {
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            "intent": None,
            "plan": None,
            "results": [],
            "response": None,
            "error": None,
        }

        logger.info("main_loop_start", session=session_id, message=message[:100])

        try:
            # Run the graph
            final_state = await self.graph.ainvoke(initial_state, config=config)

            # Check for interrupt (question/approval pending)
            if "__interrupt__" in final_state:
                interrupt_data = final_state["__interrupt__"]
                return {
                    "success": True,
                    "type": "interrupt",
                    "interrupt": interrupt_data,
                    "session_id": session_id,
                }

            # Check for error
            if final_state.get("error"):
                return {
                    "success": False,
                    "error": final_state["error"],
                    "session_id": session_id,
                }

            # Success
            return {
                "success": True,
                "type": "result",
                "response": final_state.get("response"),
                "intent": final_state.get("intent"),
                "plan": final_state.get("plan"),
                "results": final_state.get("results", []),
                "session_id": session_id,
            }

        except Exception as e:
            logger.error("main_loop_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
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
                return {
                    "success": True,
                    "type": "interrupt",
                    "interrupt": final_state["__interrupt__"],
                    "session_id": session_id,
                }

            if final_state.get("error"):
                return {
                    "success": False,
                    "error": final_state["error"],
                    "session_id": session_id,
                }

            return {
                "success": True,
                "type": "result",
                "response": final_state.get("response"),
                "intent": final_state.get("intent"),
                "plan": final_state.get("plan"),
                "results": final_state.get("results", []),
                "session_id": session_id,
            }

        except Exception as e:
            logger.error("main_loop_resume_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
            }


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
