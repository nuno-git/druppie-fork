"""Main Execution Loop for Druppie using LangGraph.

This is the heart of the architecture:
    User Message
         |
         v
    Router Agent ─── Analyzes intent (can ask user via hitl:ask)
         |
         v
    Planner Agent ─── Creates execution plan
         |
         v
    Execute Plan ─── Runs agents/workflows with MCPs
         |
         v
    Summary ─── Returns results to user

Key principle: Agents can ONLY act through MCPs. All communication
with the user goes through hitl:ask, hitl:progress, hitl:done, hitl:fail.
"""

import os
import uuid
from datetime import datetime
from typing import Any, Callable, Literal, TypedDict

import structlog
import yaml
from langgraph.graph import StateGraph, END

from druppie.core.models import (
    AgentDefinition,
    AgentResult,
    ExecutionStatus,
    Intent,
    IntentAction,
    Plan,
    PlanStatus,
    PlanType,
    Step,
    StepType,
    TokenUsage,
    WorkflowDefinition,
)
from druppie.core.state import StateManager
from druppie.llm import get_llm_service, BaseLLM
from druppie.mcps import get_mcp_registry, MCPRegistry
from druppie.mcps.hitl import configure_hitl

logger = structlog.get_logger()


# =============================================================================
# LANGGRAPH STATE
# =============================================================================


class GraphState(TypedDict):
    """State passed through the LangGraph flow."""
    # Input
    message: str
    session_id: str
    user_id: str | None
    user_projects: list[dict]
    conversation_history: list[dict]

    # Router output
    intent: Intent | None

    # Planner output
    plan: Plan | None

    # Execution
    current_step: int
    step_results: list[dict]

    # Output
    response: str | None
    status: str  # running, paused, completed, failed
    waiting_for: str | None  # question, approval
    error: str | None

    # Tracking
    token_usage: dict
    llm_calls: list[dict]
    workflow_events: list[dict]


# =============================================================================
# MAIN LOOP CLASS
# =============================================================================


class MainLoop:
    """Main execution loop using LangGraph.

    The flow is defined as a graph:

    START -> router -> check_router -> planner -> execute -> summarize -> END
                           |
                           v
                      [pause/end if needed]
    """

    def __init__(
        self,
        llm: BaseLLM | None = None,
        mcp_registry: MCPRegistry | None = None,
        agents_path: str | None = None,
        workflows_path: str | None = None,
    ):
        self._llm = llm
        self._mcp_registry = mcp_registry
        self._agents_path = agents_path or os.path.join(
            os.path.dirname(__file__), "..", "agents"
        )
        self._workflows_path = workflows_path or os.path.join(
            os.path.dirname(__file__), "..", "workflows"
        )
        self._state_manager = StateManager()
        self._agents: dict[str, AgentDefinition] = {}
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._emit_event: Callable[[dict], None] | None = None
        self._graph = None

    @property
    def llm(self) -> BaseLLM:
        if self._llm is None:
            self._llm = get_llm_service().get_llm()
        return self._llm

    @property
    def mcp_registry(self) -> MCPRegistry:
        if self._mcp_registry is None:
            self._mcp_registry = get_mcp_registry()
        return self._mcp_registry

    def load_agents(self) -> None:
        """Load agent definitions from YAML files."""
        if not os.path.exists(self._agents_path):
            logger.warning("agents_path_not_found", path=self._agents_path)
            return

        for filename in os.listdir(self._agents_path):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                path = os.path.join(self._agents_path, filename)
                try:
                    with open(path, "r") as f:
                        data = yaml.safe_load(f)
                    agent = AgentDefinition(**data)
                    self._agents[agent.id] = agent
                    logger.debug("agent_loaded", agent_id=agent.id)
                except Exception as e:
                    logger.error("agent_load_error", path=path, error=str(e))

        logger.info("agents_loaded", count=len(self._agents))

    def load_workflows(self) -> None:
        """Load workflow definitions from YAML files."""
        if not os.path.exists(self._workflows_path):
            logger.warning("workflows_path_not_found", path=self._workflows_path)
            return

        for filename in os.listdir(self._workflows_path):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                path = os.path.join(self._workflows_path, filename)
                try:
                    with open(path, "r") as f:
                        data = yaml.safe_load(f)
                    workflow = WorkflowDefinition(**data)
                    self._workflows[workflow.id] = workflow
                    logger.debug("workflow_loaded", workflow_id=workflow.id)
                except Exception as e:
                    logger.error("workflow_load_error", path=path, error=str(e))

        logger.info("workflows_loaded", count=len(self._workflows))

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return self._agents.get(agent_id)

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph flow."""
        graph = StateGraph(GraphState)

        # Add nodes
        graph.add_node("router", self._router_node)
        graph.add_node("planner", self._planner_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("summarize", self._summarize_node)

        # Add edges
        graph.set_entry_point("router")
        graph.add_conditional_edges(
            "router",
            self._route_after_router,
            {
                "planner": "planner",
                "pause": END,
                "end": END,
            }
        )
        graph.add_conditional_edges(
            "planner",
            self._route_after_planner,
            {
                "execute": "execute",
                "pause": END,
                "end": END,
            }
        )
        graph.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {
                "summarize": "summarize",
                "pause": END,
                "end": END,
            }
        )
        graph.add_edge("summarize", END)

        return graph.compile()

    def _emit(self, title: str, description: str, status: str = "info", data: dict = None):
        """Emit a workflow event."""
        if self._emit_event:
            self._emit_event({
                "event_type": "workflow_event",
                "title": title,
                "description": description,
                "status": status,
                "data": data or {},
                "timestamp": datetime.utcnow().isoformat(),
            })

    # =========================================================================
    # GRAPH NODES
    # =========================================================================

    async def _router_node(self, state: GraphState) -> GraphState:
        """Router node: analyze intent using router agent."""
        self._emit("Router Agent", "Analyzing your intent...", "working")

        router = self.get_agent("router")
        if not router:
            state["error"] = "Router agent not found in agents/"
            state["status"] = "failed"
            return state

        # Build context
        context_parts = []
        if state["user_projects"]:
            context_parts.append("USER'S PROJECTS:")
            for proj in state["user_projects"][:10]:
                context_parts.append(f"- {proj.get('name', 'Unknown')} (ID: {proj.get('id')})")

        if state["conversation_history"]:
            context_parts.append("\nRECENT CONVERSATION:")
            for entry in state["conversation_history"][-5:]:
                context_parts.append(f"[{entry.get('role', 'unknown').upper()}]: {entry.get('content', '')[:200]}")

        user_prompt = f"""Analyze this request:
{chr(10).join(context_parts)}

USER REQUEST: {state["message"]}

Use the available tools to:
1. If you need clarification, call hitl:ask with your question
2. When you have analyzed the intent, call hitl:done with the analysis data"""

        result = await self._run_agent(
            agent=router,
            user_prompt=user_prompt,
            session_id=state["session_id"],
        )

        # Update state with result
        state["llm_calls"].extend(result.llm_calls)
        if result.token_usage:
            state["token_usage"]["prompt_tokens"] += result.token_usage.prompt_tokens
            state["token_usage"]["completion_tokens"] += result.token_usage.completion_tokens
            state["token_usage"]["total_tokens"] += result.token_usage.total_tokens

        # Check if waiting for user (hitl:ask was called)
        if result.data.get("waiting_for"):
            state["status"] = "paused"
            state["waiting_for"] = result.data.get("waiting_for")
            state["response"] = result.data.get("question")
            self._emit("Router Agent", "Waiting for user input", "warning")
            return state

        if not result.success:
            state["error"] = result.error or "Router failed"
            state["status"] = "failed"
            return state

        # Parse intent from result data
        state["intent"] = self._parse_intent(state["message"], result.data)
        self._emit(
            f"Intent: {state['intent'].action.value}",
            state["intent"].prompt,
            "success",
            {"action": state["intent"].action.value},
        )

        return state

    async def _planner_node(self, state: GraphState) -> GraphState:
        """Planner node: create execution plan."""
        self._emit("Planner Agent", "Creating execution plan...", "working")

        planner = self.get_agent("planner")
        if not planner:
            state["error"] = "Planner agent not found in agents/"
            state["status"] = "failed"
            return state

        intent = state["intent"]

        # List available agents and workflows
        agents_list = "\n".join([f"- {a}: {self._agents[a].description}" for a in self._agents])
        workflows_list = "\n".join([f"- {w}: {self._workflows[w].description}" for w in self._workflows]) or "None"

        user_prompt = f"""Create an execution plan for:

INTENT: {intent.action.value}
REQUEST: {intent.prompt}
PROJECT CONTEXT: {intent.project_context}

AVAILABLE AGENTS:
{agents_list or "None"}

AVAILABLE WORKFLOWS:
{workflows_list}

When done, call hitl:done with the plan data containing:
- name: Plan name
- description: What this accomplishes
- steps: Array of steps, each with type (agent/mcp), agent_id or tool, and prompt/inputs"""

        result = await self._run_agent(
            agent=planner,
            user_prompt=user_prompt,
            session_id=state["session_id"],
        )

        # Update state
        state["llm_calls"].extend(result.llm_calls)
        if result.token_usage:
            state["token_usage"]["prompt_tokens"] += result.token_usage.prompt_tokens
            state["token_usage"]["completion_tokens"] += result.token_usage.completion_tokens
            state["token_usage"]["total_tokens"] += result.token_usage.total_tokens

        if result.data.get("waiting_for"):
            state["status"] = "paused"
            state["waiting_for"] = result.data.get("waiting_for")
            return state

        if not result.success:
            state["error"] = result.error or "Planner failed"
            state["status"] = "failed"
            return state

        # Parse plan
        state["plan"] = self._parse_plan(state["session_id"], intent, result.data)
        self._emit(
            "Execution Plan Ready",
            state["plan"].name,
            "success",
            {"plan_type": state["plan"].plan_type.value, "steps": len(state["plan"].steps)},
        )

        return state

    async def _execute_node(self, state: GraphState) -> GraphState:
        """Execute node: run plan steps."""
        plan = state["plan"]
        self._emit("Executing Plan", f"Running {len(plan.steps)} steps...", "working")

        for i, step in enumerate(plan.steps[state["current_step"]:], start=state["current_step"]):
            state["current_step"] = i

            self._emit(
                f"Step {i+1}/{len(plan.steps)}",
                f"Executing {step.type.value}: {step.agent_id or step.tool}",
                "working",
            )

            if step.type == StepType.AGENT:
                result = await self._execute_agent_step(step, plan.context, state["session_id"])
            elif step.type == StepType.MCP:
                result = await self._execute_mcp_step(step, state["session_id"])
            else:
                result = {"success": False, "error": f"Unknown step type: {step.type}"}

            # Check for pause
            if result.get("status") == "waiting":
                state["status"] = "paused"
                state["waiting_for"] = result.get("waiting_for")
                return state

            state["step_results"].append({
                "step_id": step.id,
                "success": result.get("success", False),
                "output": result,
            })

            # Update context
            plan.context[f"step_{step.id}"] = result

            if not result.get("success", False):
                state["error"] = result.get("error", "Step failed")
                state["status"] = "failed"
                return state

            self._emit(
                f"Step {i+1} Complete",
                result.get("summary", "Done"),
                "success",
            )

        state["status"] = "completed"
        return state

    async def _summarize_node(self, state: GraphState) -> GraphState:
        """Summarize node: generate final response."""
        self._emit("Summarizing Results", "Preparing response...", "working")

        results = state["step_results"]
        intent = state["intent"]

        successful = sum(1 for r in results if r.get("success", False))
        total = len(results)

        if successful == total:
            state["response"] = f"Successfully completed {intent.prompt}. All {total} steps executed."
        elif successful > 0:
            state["response"] = f"Partially completed {intent.prompt}. {successful}/{total} steps succeeded."
        else:
            errors = [r.get("output", {}).get("error", "Unknown") for r in results if not r.get("success")]
            state["response"] = f"Failed to complete {intent.prompt}. Errors: {'; '.join(errors[:3])}"

        self._emit("Complete", state["response"][:100], "success")
        state["status"] = "completed"
        return state

    # =========================================================================
    # ROUTING FUNCTIONS
    # =========================================================================

    def _route_after_router(self, state: GraphState) -> Literal["planner", "pause", "end"]:
        """Determine next step after router."""
        if state["status"] == "paused":
            return "pause"
        if state["status"] == "failed":
            return "end"
        if not state.get("intent"):
            return "end"

        # General chat doesn't need planning
        if state["intent"].action == IntentAction.GENERAL_CHAT:
            state["response"] = state["intent"].answer or state["intent"].prompt
            state["status"] = "completed"
            return "end"

        return "planner"

    def _route_after_planner(self, state: GraphState) -> Literal["execute", "pause", "end"]:
        """Determine next step after planner."""
        if state["status"] == "paused":
            return "pause"
        if state["status"] == "failed":
            return "end"
        if not state.get("plan") or not state["plan"].steps:
            state["response"] = "No execution steps needed."
            state["status"] = "completed"
            return "end"
        return "execute"

    def _route_after_execute(self, state: GraphState) -> Literal["summarize", "pause", "end"]:
        """Determine next step after execute."""
        if state["status"] == "paused":
            return "pause"
        if state["status"] == "failed":
            return "end"
        return "summarize"

    # =========================================================================
    # AGENT EXECUTION
    # =========================================================================

    async def _run_agent(
        self,
        agent: AgentDefinition,
        user_prompt: str,
        session_id: str,
        max_iterations: int = 10,
    ) -> AgentResult:
        """Run an agent with MCP tool access.

        Agents can ONLY interact through MCP tools:
        - hitl:ask - Ask user a question (pauses execution)
        - hitl:done - Signal completion with data
        - hitl:fail - Signal failure
        - hitl:progress - Send progress updates
        - coding:* - File operations
        - git:* - Git operations
        - docker:* - Docker operations
        """
        messages = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Get ALL tools for the agent's MCPs - no special done/fail, use hitl:done/fail
        tools = self.mcp_registry.to_openai_tools(agent.mcps)

        llm_calls = []
        total_usage = TokenUsage()

        for iteration in range(max_iterations):
            response = await self.llm.achat(messages, tools)

            total_usage.prompt_tokens += response.prompt_tokens
            total_usage.completion_tokens += response.completion_tokens
            total_usage.total_tokens += response.total_tokens

            llm_calls.append({
                "iteration": iteration,
                "tool_calls": len(response.tool_calls),
                "tools": [tc.get("name") for tc in response.tool_calls] if response.tool_calls else [],
                "content": response.content[:200] if response.content else None,
            })

            # No tool calls - shouldn't happen with proper agents
            if not response.tool_calls:
                return AgentResult(
                    success=True,
                    summary=response.content or "Task completed",
                    data={},
                    token_usage=total_usage,
                    llm_calls=llm_calls,
                )

            # Process tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})

                # Convert back to MCP format (hitl_ask -> hitl:ask)
                mcp_tool_name = tool_name.replace("_", ":", 1)

                # Execute MCP tool
                result = await self.mcp_registry.call_tool(
                    mcp_tool_name,
                    tool_args,
                    session_id=session_id,
                )

                # Check for terminal conditions from HITL tools
                if result.get("status") == "waiting":
                    # hitl:ask was called - pause for user
                    return AgentResult(
                        success=False,
                        summary="Waiting for user",
                        data={
                            "waiting_for": result.get("waiting_for"),
                            "question": result.get("question"),
                        },
                        token_usage=total_usage,
                        llm_calls=llm_calls,
                    )

                if result.get("status") == "done":
                    # hitl:done was called - task complete
                    return AgentResult(
                        success=True,
                        summary=result.get("summary", "Task completed"),
                        artifacts=result.get("artifacts", []),
                        data=result.get("data", {}),
                        token_usage=total_usage,
                        llm_calls=llm_calls,
                    )

                if result.get("status") == "failed":
                    # hitl:fail was called - task failed
                    return AgentResult(
                        success=False,
                        summary=result.get("reason", "Task failed"),
                        error=result.get("reason"),
                        token_usage=total_usage,
                        llm_calls=llm_calls,
                    )

                # Add tool result to messages for next iteration
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": tool_call.get("id", f"call_{iteration}"),
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": str(tool_args),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{iteration}"),
                    "content": str(result),
                })

        # Max iterations - agent didn't call hitl:done
        return AgentResult(
            success=False,
            summary="Max iterations reached",
            error="Agent did not complete within max iterations",
            token_usage=total_usage,
            llm_calls=llm_calls,
        )

    async def _execute_agent_step(
        self,
        step: Step,
        context: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        """Execute an agent step from the plan."""
        agent = self.get_agent(step.agent_id)
        if not agent:
            return {"success": False, "error": f"Agent not found: {step.agent_id}"}

        # Build prompt with context substitution
        prompt = step.prompt or ""
        for key, value in context.items():
            prompt = prompt.replace(f"{{{{ {key} }}}}", str(value))

        result = await self._run_agent(agent, prompt, session_id)

        return {
            "success": result.success,
            "summary": result.summary,
            "data": result.data,
            "artifacts": result.artifacts,
            "error": result.error,
            "token_usage": result.token_usage.model_dump() if result.token_usage else {},
            "llm_calls": result.llm_calls,
            "status": "waiting" if result.data.get("waiting_for") else None,
            "waiting_for": result.data.get("waiting_for"),
            "question": result.data.get("question"),
        }

    async def _execute_mcp_step(self, step: Step, session_id: str) -> dict[str, Any]:
        """Execute an MCP tool step from the plan."""
        if not step.tool:
            return {"success": False, "error": "No tool specified"}

        result = await self.mcp_registry.call_tool(step.tool, step.inputs, session_id=session_id)
        return result

    # =========================================================================
    # PARSING HELPERS
    # =========================================================================

    def _parse_intent(self, original_message: str, data: dict) -> Intent:
        """Parse intent from router agent's hitl:done data."""
        action_map = {
            "create_project": IntentAction.CREATE_PROJECT,
            "update_project": IntentAction.UPDATE_PROJECT,
            "deploy_project": IntentAction.DEPLOY_PROJECT,
            "general_chat": IntentAction.GENERAL_CHAT,
        }

        action_str = data.get("action", "general_chat")
        action = action_map.get(action_str, IntentAction.GENERAL_CHAT)

        return Intent(
            initial_prompt=original_message,
            prompt=data.get("prompt", original_message),
            action=action,
            answer=data.get("answer"),
            clarification_needed=False,  # Handled via hitl:ask now
            clarification_question=None,
            project_context=data.get("project_context") or {},
            deploy_context=data.get("deploy_context") or {},
        )

    def _parse_plan(self, session_id: str, intent: Intent, data: dict) -> Plan:
        """Parse plan from planner agent's hitl:done data."""
        steps = []
        for i, step_data in enumerate(data.get("steps", [])):
            step_type = StepType(step_data.get("type", "agent"))
            steps.append(Step(
                id=f"step_{i}",
                type=step_type,
                agent_id=step_data.get("agent_id"),
                prompt=step_data.get("prompt"),
                tool=step_data.get("tool"),
                inputs=step_data.get("inputs", {}),
            ))

        return Plan(
            id=session_id,
            name=data.get("name", f"Plan: {intent.prompt[:50]}"),
            description=data.get("description", ""),
            plan_type=PlanType.WORKFLOW if data.get("use_workflow") else PlanType.AGENTS,
            workflow_id=data.get("workflow_id"),
            intent=intent,
            steps=steps,
            context=intent.project_context.copy() if intent.project_context else {},
        )

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def process_message(
        self,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
        user_projects: list[dict] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the LangGraph flow."""
        session_id = session_id or str(uuid.uuid4())
        self._emit_event = emit_event

        # Configure HITL for this session
        configure_hitl(emit_event, self._state_manager, session_id)

        # Build graph if needed
        if self._graph is None:
            self._graph = self._build_graph()

        # Initial state
        initial_state: GraphState = {
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            "user_projects": user_projects or [],
            "conversation_history": conversation_history or [],
            "intent": None,
            "plan": None,
            "current_step": 0,
            "step_results": [],
            "response": None,
            "status": "running",
            "waiting_for": None,
            "error": None,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "llm_calls": [],
            "workflow_events": [],
        }

        self._emit("Processing request", f"Analyzing: {message[:100]}...", "working")

        # Run the graph
        final_state = await self._graph.ainvoke(initial_state)

        # Build response based on final state
        if final_state["status"] == "paused":
            return {
                "success": True,
                "type": "paused",
                "waiting_for": final_state["waiting_for"],
                "question": final_state.get("response"),
                "response": final_state.get("response"),
                "session_id": session_id,
                "llm_calls": final_state["llm_calls"],
            }

        if final_state["status"] == "failed":
            return {
                "success": False,
                "error": final_state["error"],
                "response": f"Error: {final_state['error']}",
                "session_id": session_id,
                "llm_calls": final_state["llm_calls"],
            }

        return {
            "success": True,
            "type": "result",
            "response": final_state["response"],
            "intent": final_state["intent"].model_dump() if final_state["intent"] else None,
            "plan": final_state["plan"].model_dump() if final_state["plan"] else None,
            "total_usage": final_state["token_usage"],
            "session_id": session_id,
            "llm_calls": final_state["llm_calls"],
        }

    async def resume_session(
        self,
        session_id: str,
        user_response: str | None = None,
        approval: bool | None = None,
        user_id: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume a paused session."""
        self._emit_event = emit_event
        configure_hitl(emit_event, self._state_manager, session_id)

        state = self._state_manager.get_state(session_id)
        if not state:
            return {"success": False, "error": "Session not found"}

        if state.status != ExecutionStatus.PAUSED:
            return {"success": False, "error": "Session is not paused"}

        # Handle response/approval
        if state.pending_question and user_response is not None:
            state = self._state_manager.resume_with_answer(session_id, user_response)
        elif state.pending_approval and approval is not None:
            state = self._state_manager.resume_with_approval(
                session_id,
                approved=approval,
                user_id=user_id or "unknown",
                user_role="developer",
            )
            if not approval:
                return {
                    "success": False,
                    "type": "rejected",
                    "response": "Operation was rejected",
                    "session_id": session_id,
                }

        # TODO: Continue graph execution from where it paused
        # This requires storing graph checkpoint state
        return {"success": True, "message": "Session resumed"}


# =============================================================================
# GLOBAL SINGLETON
# =============================================================================

_main_loop: MainLoop | None = None


def get_main_loop() -> MainLoop:
    """Get the global main loop instance."""
    global _main_loop
    if _main_loop is None:
        _main_loop = MainLoop()
        _main_loop.load_agents()
        _main_loop.load_workflows()
    return _main_loop
