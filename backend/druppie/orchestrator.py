"""Chat Orchestrator - Main entry point for processing user requests.

This orchestrator follows clean architecture principles:
1. All agents use the same pattern (YAML definition + AgentRuntime)
2. Context is injected via prompt templating
3. Structured output via done(data={...}) tool
4. MCPs only for side effects

Flow:
    User Message
         │
         ▼
    ┌─────────────┐
    │   Router    │ ─── Analyzes intent, can ask questions
    │   Agent     │ ─── Returns: Intent (via done(data=...))
    └─────────────┘
         │
         ▼
    ┌─────────────┐
    │   Planner   │ ─── Creates execution plan
    │   Agent     │ ─── Returns: Plan (via done(data=...))
    └─────────────┘
         │
         ▼
    ┌─────────────┐
    │  Executor   │ ─── Runs agents/workflows from plan
    └─────────────┘
         │
         ▼
      Result
"""

import json
import os
from datetime import datetime
from typing import Any, Callable

import structlog

from druppie.agents import AgentRuntime
from druppie.core.models import (
    AgentResult,
    AgentTask,
    Intent,
    IntentAction,
    Plan,
    PlanStatus,
    PlanType,
    TaskStatus,
    TokenUsage,
)
from druppie.llm_service import LLMService
from druppie.mcp import MCPClient, MCPRegistry
from druppie.registry import AgentRegistry
from druppie.workflows import WorkflowRegistry

logger = structlog.get_logger()


class ChatOrchestrator:
    """Orchestrates the chat flow using standard agents.

    All agents (router, planner, executor agents) use the same
    Agent class and are defined in YAML. Context is passed via
    the task description or context dict.
    """

    def __init__(self):
        """Initialize the orchestrator."""
        self._llm = None
        self._agent_registry = None
        self._workflow_registry = None
        self._mcp_registry = None
        self._mcp_client = None
        self._agent_runtime = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy initialization of components."""
        if self._initialized:
            return

        registry_path = os.getenv("REGISTRY_PATH", "/app/registry")

        # Initialize LLM via LLMService (auto-selects provider)
        self._llm_service = LLMService()
        self._llm = self._llm_service.get_llm()

        # Load registries
        self._agent_registry = AgentRegistry(registry_path)
        self._agent_registry.load()

        self._workflow_registry = WorkflowRegistry(registry_path)
        self._workflow_registry.load()

        self._mcp_registry = MCPRegistry(registry_path)
        self._mcp_registry.load()

        # Initialize MCP client
        self._mcp_client = MCPClient(self._mcp_registry)

        # Agent runtime will be created per-call to pass emit_event
        self._agent_runtime = None

        self._initialized = True

        logger.info(
            "orchestrator_initialized",
            agents=len(self._agent_registry.list_agents()),
            workflows=len(self._workflow_registry.list_workflows()),
        )

    async def process_message(
        self,
        message: str,
        user_id: str | None = None,
        user_projects: list[dict] | None = None,
        plan_id: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the agent pipeline.

        Args:
            message: The user's message
            user_id: Optional user ID
            user_projects: List of user's existing projects for context
            plan_id: Optional plan ID for continuing conversations
            emit_event: Callback for emitting workflow events
            conversation_history: Previous conversation messages for context

        Returns:
            Result dict with response, intent, plan, etc.
        """
        self._ensure_initialized()

        total_usage = TokenUsage()
        all_llm_calls = []

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

        # Create agent runtime with emit_event for this request
        self._agent_runtime = AgentRuntime(
            mcp_client=self._mcp_client,
            mcp_registry=self._mcp_registry,
            agent_registry=self._agent_registry,
            llm=self._llm,
            emit_event=emit_event,
        )

        event("Processing your request", f"Analyzing: {message[:100]}...", "working")

        # Step 1: Router Agent - Analyze intent
        event("Router Agent", "Analyzing your intent...", "working")

        intent_result = await self._run_router_agent(
            message=message,
            user_projects=user_projects or [],
            conversation_history=conversation_history,
        )

        if intent_result.token_usage:
            total_usage.add(intent_result.token_usage)

        # Collect LLM calls from router
        if intent_result.llm_calls:
            all_llm_calls.extend(intent_result.llm_calls)

        event("Router Agent", f"Completed analysis", "success", {"action": intent_result.data.get("action", "unknown") if intent_result.data else "unknown"})

        # Check if agent needs to ask a question (via ask_human tool)
        if not intent_result.success and intent_result.data and intent_result.data.get("question"):
            question = intent_result.data.get("question")
            event("Router Agent", f"Needs clarification", "warning", {"question": question})
            return {
                "success": True,
                "type": "question",
                "question": question,
                "response": question,
                "intent": None,
                "llm_calls": all_llm_calls,
            }

        if not intent_result.success:
            return {
                "success": False,
                "error": intent_result.error or "Router agent failed",
                "response": f"I encountered an error: {intent_result.summary}",
                "llm_calls": all_llm_calls,
            }

        # Parse intent from agent result
        intent_data = intent_result.data or {}
        intent = self._parse_intent(message, intent_data)

        event(
            f"Intent: {intent.action.value}",
            intent.prompt,
            "success",
            {"action": intent.action.value, "project_context": intent.project_context},
        )

        # Check if router needs to ask a question
        if intent.action == IntentAction.GENERAL_CHAT and intent.clarification_needed:
            return {
                "success": True,
                "type": "question",
                "question": intent.clarification_question,
                "response": intent.clarification_question,
                "intent": intent,
                "llm_calls": all_llm_calls,
            }

        # Handle general chat (direct response)
        if intent.action == IntentAction.GENERAL_CHAT:
            return {
                "success": True,
                "type": "chat",
                "response": intent.answer or intent.prompt,
                "intent": intent,
                "llm_calls": all_llm_calls,
            }

        # Step 2: Planner Agent - Create execution plan
        event("Planner Agent", "Creating execution plan...", "working")

        plan_result = await self._run_planner_agent(intent=intent)

        if plan_result.token_usage:
            total_usage.add(plan_result.token_usage)

        # Collect LLM calls from planner
        if plan_result.llm_calls:
            all_llm_calls.extend(plan_result.llm_calls)

        event("Planner Agent", f"Plan created", "success", {"plan": plan_result.data.get("name", "unknown") if plan_result.data else "unknown"})

        if not plan_result.success:
            return {
                "success": False,
                "error": plan_result.error or "Planner agent failed",
                "response": f"I couldn't create a plan: {plan_result.summary}",
                "intent": intent,
                "llm_calls": all_llm_calls,
            }

        # Parse plan from agent result
        plan_data = plan_result.data or {}
        plan = self._parse_plan(plan_id or "plan", intent, plan_data)

        event(
            "Execution Plan Ready",
            plan.name,
            "success",
            {
                "plan_type": plan.plan_type.value,
                "workflow_id": plan.workflow_id,
                "tasks": [{"agent_id": t.agent_id, "description": t.description} for t in plan.tasks],
            },
        )

        # Return the plan for execution by the caller
        # (plans.py handles the actual execution and Git/Docker operations)
        return {
            "success": True,
            "type": "action",
            "intent": intent,
            "plan": plan,
            "total_usage": total_usage,
            "llm_calls": all_llm_calls,
        }

    async def _run_router_agent(
        self,
        message: str,
        user_projects: list[dict],
        conversation_history: list[dict] | None = None,
    ) -> AgentResult:
        """Run the router agent to analyze intent.

        Context (user_projects and conversation_history) is injected into the task description.
        """
        # Build context string for user projects
        projects_context = ""
        if user_projects:
            projects_context = "\n\nUSER'S EXISTING PROJECTS:\n"
            for proj in user_projects[:10]:
                projects_context += f"- {proj.get('name', 'Unknown')} (ID: {proj.get('id', 'Unknown')})"
                if proj.get("repo_url"):
                    projects_context += f" - {proj['repo_url']}"
                projects_context += "\n"

        # Build conversation history context
        history_context = ""
        if conversation_history:
            history_context = "\n\nCONVERSATION HISTORY (most recent exchanges):\n"
            for entry in conversation_history[-10:]:  # Last 10 messages
                role = entry.get("role", "unknown")
                content = entry.get("content", "")[:300]  # Truncate long messages
                history_context += f"[{role.upper()}]: {content}\n"
                if entry.get("result_summary"):
                    history_context += f"  → Result: {entry['result_summary'][:200]}\n"
            history_context += "\nIMPORTANT: If the user's request refers to something from the conversation history (like 'add to it', 'update', 'now please', 'also add'), treat it as UPDATE_PROJECT for the recently created/mentioned project.\n"

        # Build task description with context
        task = f"""Analyze this user request and determine the intent.
{history_context}
USER REQUEST:
{message}
{projects_context}

Analyze the request and call done() with your analysis in the data field:
{{
    "action": "create_project|update_project|ask_question|general_chat",
    "prompt": "Summarized intent",
    "answer": "Direct answer if general_chat, otherwise null",
    "clarification_needed": false,
    "clarification_question": null,
    "project_context": {{
        "project_name": "name",
        "target_project_id": "id if updating existing project",
        "app_type": "type of application",
        "technologies": ["list"],
        "features": ["list"]
    }}
}}"""

        return await self._agent_runtime.execute_single_task(
            agent_id="router_agent",
            description=task,
            context={},
        )

    async def _run_planner_agent(
        self,
        intent: Intent,
    ) -> AgentResult:
        """Run the planner agent to create an execution plan.

        Available agents and workflows are injected into the task.
        """
        # Build agents list
        agents_info = []
        for agent_def in self._agent_registry.list_agents():
            agents_info.append(f"- {agent_def.id}: {agent_def.description}")

        # Build workflows list
        workflows_info = []
        for wf_def in self._workflow_registry.list_workflows():
            workflows_info.append(f"- {wf_def.id}: {wf_def.description}")

        task = f"""Create an execution plan for this request.

USER INTENT:
Action: {intent.action.value}
Request: {intent.prompt}
Project Context: {json.dumps(intent.project_context)}

AVAILABLE AGENTS:
{chr(10).join(agents_info) or 'None'}

AVAILABLE WORKFLOWS:
{chr(10).join(workflows_info) or 'None'}

PLANNING RULES:
- For CREATE_PROJECT: Use workflow_id "development_workflow" or "coding"
- For UPDATE_PROJECT: Use workflow_id "update_workflow"
- For simple tasks: Assign agents directly

Call done() with your plan in the data field:
{{
    "use_workflow": true/false,
    "workflow_id": "workflow_id if use_workflow is true",
    "name": "Short plan name",
    "description": "What this plan will accomplish",
    "tasks": [
        {{
            "agent_id": "agent_id",
            "description": "What this agent should do",
            "depends_on": []
        }}
    ]
}}"""

        return await self._agent_runtime.execute_single_task(
            agent_id="planner_agent",
            description=task,
            context={"intent": intent.model_dump()},
        )

    def _parse_intent(self, original_message: str, data: dict) -> Intent:
        """Parse intent from router agent's done() data."""
        action_map = {
            "create_project": IntentAction.CREATE_PROJECT,
            "update_project": IntentAction.UPDATE_PROJECT,
            "ask_question": IntentAction.GENERAL_CHAT,  # Map to general_chat with clarification
            "general_chat": IntentAction.GENERAL_CHAT,
        }

        action_str = data.get("action", "general_chat")
        action = action_map.get(action_str, IntentAction.GENERAL_CHAT)

        # Handle ask_question as clarification needed
        clarification_needed = action_str == "ask_question" or data.get("clarification_needed", False)

        return Intent(
            initial_prompt=original_message,
            prompt=data.get("prompt", original_message),
            action=action,
            language=data.get("language", "en"),
            answer=data.get("answer"),
            clarification_needed=clarification_needed,
            clarification_question=data.get("clarification_question") or data.get("prompt") if clarification_needed else None,
            project_context=data.get("project_context") or {},  # Handle None explicitly
        )

    def _parse_plan(self, plan_id: str, intent: Intent, data: dict) -> Plan:
        """Parse plan from planner agent's done() data."""
        if data.get("use_workflow", False):
            return Plan(
                id=plan_id,
                name=data.get("name", f"Plan: {intent.prompt[:50]}"),
                description=data.get("description", ""),
                plan_type=PlanType.WORKFLOW,
                status=PlanStatus.PENDING,
                intent=intent,
                workflow_id=data.get("workflow_id"),
                project_context=intent.project_context,
                created_at=datetime.utcnow(),
            )

        # Agent-based plan
        tasks = []
        for i, task_data in enumerate(data.get("tasks", [])):
            tasks.append(AgentTask(
                id=f"task_{i}",
                agent_id=task_data.get("agent_id", "developer"),
                description=task_data.get("description", "Complete the task"),
                depends_on=task_data.get("depends_on", []),
                context=intent.project_context,
                status=TaskStatus.PENDING,
            ))

        return Plan(
            id=plan_id,
            name=data.get("name", f"Plan: {intent.prompt[:50]}"),
            description=data.get("description", ""),
            plan_type=PlanType.AGENTS,
            status=PlanStatus.PENDING,
            intent=intent,
            tasks=tasks,
            project_context=intent.project_context,
            created_at=datetime.utcnow(),
        )


# Global singleton
chat_orchestrator = ChatOrchestrator()
