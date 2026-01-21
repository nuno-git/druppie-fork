"""Main Execution Loop for Druppie.

This is the heart of the new architecture:
    User Message
         |
         v
    Router Agent ─── Analyzes intent
         |
         v
    Planner Agent ─── Creates execution plan
         |
         v
    Execute Plan ─── Runs agents/workflows with MCPs
         |
         v
    Router Summary ─── Summarizes results for user

Key principle: Agents can ONLY act through MCPs.
"""

import os
import uuid
from datetime import datetime
from typing import Any, Callable

import structlog
import yaml

from druppie.core.models import (
    AgentDefinition,
    AgentResult,
    ExecutionState,
    ExecutionStatus,
    Intent,
    IntentAction,
    LLMResponse,
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


class MainLoop:
    """Main execution loop for processing user requests.

    Flow:
    1. Router Agent - Analyze user intent
    2. Planner Agent - Create execution plan
    3. Execute - Run agents/workflows through MCPs
    4. Router - Summarize results
    """

    def __init__(
        self,
        llm: BaseLLM | None = None,
        mcp_registry: MCPRegistry | None = None,
        agents_path: str | None = None,
        workflows_path: str | None = None,
    ):
        """Initialize the main loop.

        Args:
            llm: LLM instance (defaults to global service)
            mcp_registry: MCP registry (defaults to global)
            agents_path: Path to agent YAML files
            workflows_path: Path to workflow YAML files
        """
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

    @property
    def llm(self) -> BaseLLM:
        """Get LLM instance."""
        if self._llm is None:
            self._llm = get_llm_service().get_llm()
        return self._llm

    @property
    def mcp_registry(self) -> MCPRegistry:
        """Get MCP registry."""
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
        """Get an agent definition by ID."""
        return self._agents.get(agent_id)

    async def process_message(
        self,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
        user_projects: list[dict] | None = None,
        emit_event: Callable[[dict], None] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the main loop.

        Args:
            message: The user's message
            session_id: Session ID (generated if not provided)
            user_id: Optional user ID
            user_projects: List of user's existing projects
            emit_event: Callback for emitting events
            conversation_history: Previous conversation messages

        Returns:
            Result dict with response, intent, plan, etc.
        """
        session_id = session_id or str(uuid.uuid4())
        total_usage = TokenUsage()
        all_llm_calls = []

        # Configure HITL for this execution
        configure_hitl(emit_event, self._state_manager, session_id)

        def event(title: str, description: str, status: str = "info", data: dict = None):
            if emit_event:
                emit_event({
                    "event_type": "workflow_event",
                    "title": title,
                    "description": description,
                    "status": status,
                    "data": data or {},
                    "timestamp": datetime.utcnow().isoformat(),
                })

        event("Processing request", f"Analyzing: {message[:100]}...", "working")

        # Step 1: Router Agent - Analyze intent
        event("Router Agent", "Analyzing your intent...", "working")

        router_result = await self._run_router(
            message=message,
            user_projects=user_projects or [],
            conversation_history=conversation_history,
        )

        if router_result.token_usage:
            total_usage.add(router_result.token_usage)
        all_llm_calls.extend(router_result.llm_calls)

        # Check for question from router
        if not router_result.success and router_result.data.get("question"):
            event("Router Agent", "Needs clarification", "warning")
            return {
                "success": True,
                "type": "question",
                "question": router_result.data.get("question"),
                "response": router_result.data.get("question"),
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        if not router_result.success:
            return {
                "success": False,
                "error": router_result.error or "Router agent failed",
                "response": f"Error: {router_result.summary}",
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        # Parse intent
        intent = self._parse_intent(message, router_result.data)
        event(
            f"Intent: {intent.action.value}",
            intent.prompt,
            "success",
            {"action": intent.action.value},
        )

        # Handle clarification needed
        if intent.clarification_needed:
            return {
                "success": True,
                "type": "question",
                "question": intent.clarification_question,
                "response": intent.clarification_question,
                "intent": intent.model_dump(),
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        # Handle general chat (direct response)
        if intent.action == IntentAction.GENERAL_CHAT:
            return {
                "success": True,
                "type": "chat",
                "response": intent.answer or intent.prompt,
                "intent": intent.model_dump(),
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        # Step 2: Planner Agent - Create execution plan
        event("Planner Agent", "Creating execution plan...", "working")

        planner_result = await self._run_planner(intent=intent)

        if planner_result.token_usage:
            total_usage.add(planner_result.token_usage)
        all_llm_calls.extend(planner_result.llm_calls)

        if not planner_result.success:
            return {
                "success": False,
                "error": planner_result.error or "Planner agent failed",
                "response": f"Could not create plan: {planner_result.summary}",
                "intent": intent.model_dump(),
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        # Parse plan
        plan = self._parse_plan(session_id, intent, planner_result.data)
        event(
            "Execution Plan Ready",
            plan.name,
            "success",
            {"plan_type": plan.plan_type.value, "steps": len(plan.steps)},
        )

        # Step 3: Execute plan
        event("Executing Plan", f"Running {len(plan.steps)} steps...", "working")

        execution_result = await self._execute_plan(
            plan=plan,
            session_id=session_id,
            emit_event=emit_event,
        )

        # Check for HITL pause
        if execution_result.get("status") == "paused":
            return {
                "success": True,
                "type": "paused",
                "waiting_for": execution_result.get("waiting_for"),
                "question": execution_result.get("question"),
                "approval": execution_result.get("approval"),
                "plan": plan.model_dump(),
                "session_id": session_id,
                "llm_calls": all_llm_calls,
            }

        if execution_result.get("token_usage"):
            total_usage.add(TokenUsage(**execution_result["token_usage"]))
        if execution_result.get("llm_calls"):
            all_llm_calls.extend(execution_result["llm_calls"])

        # Step 4: Summarize results
        event("Summarizing Results", "Preparing response...", "working")

        summary = await self._summarize_results(
            intent=intent,
            plan=plan,
            results=execution_result.get("results", []),
        )

        event("Complete", summary[:100], "success")

        return {
            "success": True,
            "type": "result",
            "response": summary,
            "intent": intent.model_dump(),
            "plan": plan.model_dump(),
            "total_usage": total_usage.model_dump(),
            "session_id": session_id,
            "llm_calls": all_llm_calls,
        }

    async def resume_session(
        self,
        session_id: str,
        user_response: str | None = None,
        approval: bool | None = None,
        user_id: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Resume a paused session.

        Args:
            session_id: Session to resume
            user_response: Response to a question
            approval: True/False for approval requests
            user_id: User ID for approval tracking
            emit_event: Event callback

        Returns:
            Result dict
        """
        # Configure HITL
        configure_hitl(emit_event, self._state_manager, session_id)

        state = self._state_manager.get_state(session_id)
        if not state:
            return {"success": False, "error": "Session not found"}

        if state.status != ExecutionStatus.PAUSED:
            return {"success": False, "error": "Session is not paused"}

        # Resume based on what we're waiting for
        if state.pending_question and user_response is not None:
            state = self._state_manager.resume_with_answer(session_id, user_response)
        elif state.pending_approval and approval is not None:
            state = self._state_manager.resume_with_approval(
                session_id,
                approved=approval,
                user_id=user_id or "unknown",
                user_role="developer",  # TODO: Get from auth
            )

            if not approval:
                return {
                    "success": False,
                    "type": "rejected",
                    "response": "Operation was rejected",
                    "session_id": session_id,
                }

        # Continue execution
        if state.plan:
            result = await self._execute_plan(
                plan=state.plan,
                session_id=session_id,
                emit_event=emit_event,
                start_index=state.current_index,
            )
            return result

        return {"success": False, "error": "No plan to resume"}

    async def _run_router(
        self,
        message: str,
        user_projects: list[dict],
        conversation_history: list[dict] | None = None,
    ) -> AgentResult:
        """Run the router agent to analyze intent."""
        # Get router agent definition
        router = self.get_agent("router")
        if not router:
            # Use default system prompt
            system_prompt = """You are an intent analysis system for Druppie.

Analyze user requests and classify them:
- create_project: User wants to BUILD something NEW
- update_project: User wants to MODIFY something EXISTING
- deploy_project: User wants to DEPLOY a project
- general_chat: Questions, conversation, no action needed

If you need clarification, set clarification_needed=true.

You MUST call the done() tool with your analysis."""
        else:
            system_prompt = router.system_prompt

        # Build context
        projects_context = ""
        if user_projects:
            projects_context = "\n\nUSER'S PROJECTS:\n"
            for proj in user_projects[:10]:
                projects_context += f"- {proj.get('name', 'Unknown')} (ID: {proj.get('id')})\n"

        history_context = ""
        if conversation_history:
            history_context = "\n\nRECENT CONVERSATION:\n"
            for entry in conversation_history[-5:]:
                history_context += f"[{entry.get('role', 'unknown').upper()}]: {entry.get('content', '')[:200]}\n"

        user_prompt = f"""Analyze this request:
{history_context}
{projects_context}

USER REQUEST: {message}

Call done() with:
{{
    "action": "create_project|update_project|deploy_project|general_chat",
    "prompt": "Summarized intent",
    "answer": "Direct answer if general_chat",
    "clarification_needed": true/false,
    "clarification_question": "Question if clarification needed",
    "project_context": {{
        "project_name": "name",
        "target_project_id": "id if updating",
        "app_type": "type",
        "technologies": [],
        "features": []
    }}
}}"""

        return await self._run_agent_with_mcps(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mcps=["hitl"],
        )

    async def _run_planner(self, intent: Intent) -> AgentResult:
        """Run the planner agent to create execution plan."""
        planner = self.get_agent("planner")
        if not planner:
            system_prompt = """You are a planning system for Druppie.

Create execution plans for user requests.
Plans consist of steps that can be:
- agent: Execute an agent with a prompt
- mcp: Call an MCP tool directly

Available agents: developer, architect, reviewer, deployer
Available MCPs: coding, git, docker, hitl

You MUST call done() with your plan."""
        else:
            system_prompt = planner.system_prompt

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

Call done() with:
{{
    "name": "Plan name",
    "description": "What this accomplishes",
    "use_workflow": true/false,
    "workflow_id": "workflow id if using workflow",
    "steps": [
        {{
            "type": "agent",
            "agent_id": "developer",
            "prompt": "What the agent should do"
        }},
        {{
            "type": "mcp",
            "tool": "git:commit",
            "inputs": {{"message": "Initial commit"}}
        }}
    ]
}}"""

        return await self._run_agent_with_mcps(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mcps=["hitl"],
        )

    async def _run_agent_with_mcps(
        self,
        system_prompt: str,
        user_prompt: str,
        mcps: list[str],
        max_iterations: int = 10,
    ) -> AgentResult:
        """Run an agent with MCP tool access.

        This is the core agent execution loop:
        1. Send prompt to LLM with tools
        2. If LLM calls tools, execute them and continue
        3. If LLM calls done/fail, return result
        4. Loop until done or max iterations
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Get tools for the specified MCPs
        tools = self.mcp_registry.to_openai_tools(mcps)

        # Add done/fail tools
        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "done",
                    "description": "Signal task completion with results",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "Summary of what was accomplished"},
                            "artifacts": {"type": "array", "items": {"type": "string"}, "description": "Created files"},
                            "data": {"type": "object", "description": "Structured output data"},
                        },
                        "required": ["summary"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fail",
                    "description": "Signal task failure",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "Why the task failed"},
                        },
                        "required": ["reason"],
                    },
                },
            },
        ])

        llm_calls = []
        total_usage = TokenUsage()

        for iteration in range(max_iterations):
            # Call LLM
            response = await self.llm.achat(messages, tools)

            total_usage.prompt_tokens += response.prompt_tokens
            total_usage.completion_tokens += response.completion_tokens
            total_usage.total_tokens += response.total_tokens

            llm_calls.append({
                "iteration": iteration,
                "tool_calls": len(response.tool_calls),
                "content": response.content[:200] if response.content else None,
            })

            # No tool calls - agent is done with content
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

                # Check for done/fail
                if tool_name == "done":
                    # If data field exists, use it; otherwise use all args as data
                    # This allows agents to call done({...plan...}) directly
                    result_data = tool_args.get("data", {})
                    if not result_data and tool_args:
                        # Use the entire tool_args as data (minus summary/artifacts)
                        result_data = {k: v for k, v in tool_args.items()
                                       if k not in ("summary", "artifacts", "data")}
                    return AgentResult(
                        success=True,
                        summary=tool_args.get("summary", "Task completed"),
                        artifacts=tool_args.get("artifacts", []),
                        data=result_data,
                        token_usage=total_usage,
                        llm_calls=llm_calls,
                    )

                if tool_name == "fail":
                    return AgentResult(
                        success=False,
                        summary=tool_args.get("reason", "Task failed"),
                        error=tool_args.get("reason"),
                        token_usage=total_usage,
                        llm_calls=llm_calls,
                    )

                # Execute MCP tool
                # Convert tool name back to MCP format (hitl_ask -> hitl:ask)
                mcp_tool_name = tool_name.replace("_", ":", 1)
                result = await self.mcp_registry.call_tool(mcp_tool_name, tool_args)

                # Check for HITL pause
                if result.get("status") == "waiting":
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

                # Add tool result to messages
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tool_call.get("id", f"call_{iteration}"),
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": str(tool_args),
                            },
                        }
                    ],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{iteration}"),
                    "content": str(result),
                })

        # Max iterations reached
        return AgentResult(
            success=False,
            summary="Max iterations reached",
            error="Agent did not complete within max iterations",
            token_usage=total_usage,
            llm_calls=llm_calls,
        )

    async def _execute_plan(
        self,
        plan: Plan,
        session_id: str,
        emit_event: Callable[[dict], None] | None = None,
        start_index: int = 0,
    ) -> dict[str, Any]:
        """Execute a plan's steps.

        Returns dict with:
        - status: "completed", "paused", "failed"
        - results: List of step results
        - waiting_for: "question" or "approval" if paused
        """
        results = []
        llm_calls = []
        total_usage = TokenUsage()

        # Create or get execution state
        state = self._state_manager.get_state(session_id)
        if not state:
            state = self._state_manager.create_state(session_id, plan)

        for i, step in enumerate(plan.steps[start_index:], start=start_index):
            state.current_index = i
            self._state_manager.update_state(session_id, state)

            if emit_event:
                emit_event({
                    "event_type": "step_start",
                    "step_id": step.id,
                    "step_type": step.type.value,
                    "step_number": i + 1,
                    "total_steps": len(plan.steps),
                })

            if step.type == StepType.AGENT:
                result = await self._execute_agent_step(step, plan.context)
            elif step.type == StepType.MCP:
                result = await self._execute_mcp_step(step)
            else:
                result = {"success": False, "error": f"Unknown step type: {step.type}"}

            # Check for HITL pause
            if result.get("status") == "waiting":
                state.status = ExecutionStatus.PAUSED
                self._state_manager.update_state(session_id, state)
                return {
                    "status": "paused",
                    "waiting_for": result.get("waiting_for"),
                    "question": result.get("question"),
                    "approval": result.get("approval"),
                    "results": results,
                }

            results.append({
                "step_id": step.id,
                "success": result.get("success", False),
                "output": result,
            })

            if result.get("token_usage"):
                total_usage.add(TokenUsage(**result["token_usage"]))
            if result.get("llm_calls"):
                llm_calls.extend(result["llm_calls"])

            # Update context with step output
            plan.context[f"step_{step.id}"] = result

            if emit_event:
                emit_event({
                    "event_type": "step_complete",
                    "step_id": step.id,
                    "success": result.get("success", False),
                })

            # Check for failure
            if not result.get("success", False):
                state.status = ExecutionStatus.FAILED
                state.error = result.get("error", "Step failed")
                self._state_manager.update_state(session_id, state)
                return {
                    "status": "failed",
                    "error": result.get("error"),
                    "results": results,
                    "token_usage": total_usage.model_dump(),
                    "llm_calls": llm_calls,
                }

        # All steps completed
        state.status = ExecutionStatus.COMPLETED
        self._state_manager.update_state(session_id, state)

        return {
            "status": "completed",
            "results": results,
            "token_usage": total_usage.model_dump(),
            "llm_calls": llm_calls,
        }

    async def _execute_agent_step(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an agent step."""
        agent = self.get_agent(step.agent_id)
        if not agent:
            return {"success": False, "error": f"Agent not found: {step.agent_id}"}

        # Build prompt with context
        prompt = step.prompt or ""
        for key, value in context.items():
            prompt = prompt.replace(f"{{{{ {key} }}}}", str(value))

        result = await self._run_agent_with_mcps(
            system_prompt=agent.system_prompt,
            user_prompt=prompt,
            mcps=agent.mcps,
        )

        return {
            "success": result.success,
            "summary": result.summary,
            "data": result.data,
            "artifacts": result.artifacts,
            "error": result.error,
            "token_usage": result.token_usage.model_dump(),
            "llm_calls": result.llm_calls,
            "status": "waiting" if result.data.get("waiting_for") else None,
            "waiting_for": result.data.get("waiting_for"),
            "question": result.data.get("question"),
        }

    async def _execute_mcp_step(self, step: Step) -> dict[str, Any]:
        """Execute an MCP tool step."""
        if not step.tool:
            return {"success": False, "error": "No tool specified"}

        result = await self.mcp_registry.call_tool(step.tool, step.inputs)
        return result

    async def _summarize_results(
        self,
        intent: Intent,
        plan: Plan,
        results: list[dict],
    ) -> str:
        """Generate a summary of execution results."""
        # Simple summary without LLM call
        successful = sum(1 for r in results if r.get("success", False))
        total = len(results)

        if successful == total:
            return f"Successfully completed {intent.prompt}. All {total} steps executed."
        elif successful > 0:
            return f"Partially completed {intent.prompt}. {successful}/{total} steps succeeded."
        else:
            errors = [r.get("output", {}).get("error", "Unknown") for r in results if not r.get("success")]
            return f"Failed to complete {intent.prompt}. Errors: {'; '.join(errors[:3])}"

    def _parse_intent(self, original_message: str, data: dict) -> Intent:
        """Parse intent from router agent's done() data."""
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
            clarification_needed=data.get("clarification_needed", False),
            clarification_question=data.get("clarification_question"),
            project_context=data.get("project_context") or {},
            deploy_context=data.get("deploy_context") or {},
        )

    def _parse_plan(self, session_id: str, intent: Intent, data: dict) -> Plan:
        """Parse plan from planner agent's done() data."""
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
            context=intent.project_context,
        )


# Global singleton
_main_loop: MainLoop | None = None


def get_main_loop() -> MainLoop:
    """Get the global main loop instance."""
    global _main_loop
    if _main_loop is None:
        _main_loop = MainLoop()
        _main_loop.load_agents()
        _main_loop.load_workflows()
    return _main_loop
