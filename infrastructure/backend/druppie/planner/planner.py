"""Planner for generating execution plans.

The Planner takes analyzed intent and decides:
- Which workflow to use (for complex tasks like creating projects)
- OR which agents to assign tasks to (for simpler tasks)

It does NOT create detailed action steps - agents decide that themselves.
"""

import json
import re
import uuid
from datetime import datetime

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from druppie.core.models import (
    AgentDefinition,
    AgentTask,
    Intent,
    IntentAction,
    Plan,
    PlanStatus,
    PlanType,
    TaskStatus,
    TokenUsage,
    WorkflowDefinition,
)

logger = structlog.get_logger()


def create_planner_prompt(
    intent: Intent,
    agents: list[AgentDefinition],
    workflows: list[WorkflowDefinition],
) -> str:
    """Create the system prompt for plan generation."""

    # Format agent descriptions
    agent_descriptions = []
    for agent in agents:
        mcps_str = ", ".join(agent.mcps) if agent.mcps else "none"
        agent_descriptions.append(
            f"- {agent.id}: {agent.description} (MCPs: {mcps_str})"
        )
    agents_section = (
        "\n".join(agent_descriptions) if agent_descriptions else "No agents available"
    )

    # Format workflow descriptions
    workflow_descriptions = []
    for wf in workflows:
        keywords = ", ".join(wf.trigger_keywords) if wf.trigger_keywords else "none"
        workflow_descriptions.append(
            f"- {wf.id}: {wf.description} (keywords: {keywords})"
        )
    workflows_section = (
        "\n".join(workflow_descriptions)
        if workflow_descriptions
        else "No workflows available"
    )

    return f"""You are a planning system for Druppie, an AI governance platform.

Based on the user's intent, decide whether to:
1. Use a WORKFLOW (for complex, multi-step tasks like creating a new project)
2. Assign AGENTS directly (for simpler tasks that need specific expertise)

## Available Workflows:
{workflows_section}

## Available Agents:
{agents_section}

## User Intent:
Action: {intent.action.value}
Request: {intent.prompt}
Project Context: {json.dumps(intent.project_context)}

## Decision Rules:
- For CREATE_PROJECT: Prefer using the coding_workflow if available
- For UPDATE_PROJECT: Select specific agents with natural language tasks
- For simple fixes: Just assign the developer agent
- For design tasks: Assign the architect agent

## Response Format:
If using a WORKFLOW:
{{
    "use_workflow": true,
    "workflow_id": "coding_workflow",
    "name": "Short plan name",
    "description": "What this plan will accomplish"
}}

If using AGENTS directly:
{{
    "use_workflow": false,
    "name": "Short plan name",
    "description": "What this plan will accomplish",
    "tasks": [
        {{
            "agent_id": "developer",
            "description": "Natural language description of what the agent should do",
            "depends_on": []
        }},
        {{
            "agent_id": "architect",
            "description": "Create architecture documentation for the project",
            "depends_on": ["task_0"]
        }}
    ]
}}

IMPORTANT:
- Task descriptions should be natural language, NOT specific actions
- Agents will decide HOW to accomplish their tasks autonomously
- Use depends_on with task IDs (task_0, task_1, etc.) for parallel execution control
"""


class Planner:
    """Generates execution plans from user intent.

    The Planner decides between:
    - Using a predefined workflow (for complex tasks)
    - Assigning agents directly (for simpler tasks)

    It does NOT create detailed step-by-step actions.
    Agents and workflows handle that autonomously.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        agents: dict[str, AgentDefinition] | None = None,
        workflows: dict[str, WorkflowDefinition] | None = None,
        max_retries: int = 3,
        debug: bool = False,
    ):
        """Initialize the Planner.

        Args:
            llm: LangChain chat model for plan generation
            agents: Dictionary of available agents by ID
            workflows: Dictionary of available workflows by ID
            max_retries: Maximum retries for plan generation
            debug: Enable debug logging
        """
        self.llm = llm
        self.agents = agents or {}
        self.workflows = workflows or {}
        self.max_retries = max_retries
        self.debug = debug
        self.logger = logger.bind(component="planner")

    def set_agents(self, agents: dict[str, AgentDefinition]) -> None:
        """Update the available agents."""
        self.agents = agents

    def set_workflows(self, workflows: dict[str, WorkflowDefinition]) -> None:
        """Update the available workflows."""
        self.workflows = workflows

    async def create_plan(
        self,
        plan_id: str,
        intent: Intent,
    ) -> tuple[Plan, TokenUsage]:
        """Create an execution plan from the intent.

        Args:
            plan_id: Unique identifier for the plan
            intent: Analyzed user intent

        Returns:
            Tuple of (Plan, TokenUsage)
        """
        self.logger.info(
            "creating_plan",
            plan_id=plan_id,
            action=intent.action.value,
        )

        total_usage = TokenUsage()

        # Generate the plan with retries
        plan = None
        for attempt in range(self.max_retries):
            try:
                plan, gen_usage = await self._generate_plan(plan_id, intent)
                total_usage.add(gen_usage)
                break

            except Exception as e:
                self.logger.warning(
                    "plan_generation_attempt_failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt == self.max_retries - 1:
                    # Create fallback plan
                    plan = self._create_fallback_plan(plan_id, intent)

        if plan is None:
            plan = self._create_fallback_plan(plan_id, intent)

        plan.total_usage = total_usage
        return plan, total_usage

    async def _generate_plan(
        self,
        plan_id: str,
        intent: Intent,
    ) -> tuple[Plan, TokenUsage]:
        """Internal method to generate plan using LLM."""

        prompt = create_planner_prompt(
            intent=intent,
            agents=list(self.agents.values()),
            workflows=list(self.workflows.values()),
        )

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Create a plan for: {intent.prompt}"),
        ]

        response = await self.llm.ainvoke(messages)
        content = response.content

        # Parse the JSON response
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            raise ValueError("No JSON found in response")

        data = json.loads(json_match.group())

        # Determine plan type
        if data.get("use_workflow", False):
            # Workflow-based plan
            workflow_id = data.get("workflow_id")
            if workflow_id not in self.workflows:
                raise ValueError(f"Unknown workflow: {workflow_id}")

            plan = Plan(
                id=plan_id,
                name=data.get("name", f"Plan: {intent.prompt[:50]}"),
                description=data.get("description", ""),
                plan_type=PlanType.WORKFLOW,
                status=PlanStatus.PENDING,
                intent=intent,
                workflow_id=workflow_id,
                project_context=intent.project_context,
                created_at=datetime.utcnow(),
            )

        else:
            # Agent-based plan
            tasks = []
            for i, task_data in enumerate(data.get("tasks", [])):
                task_id = f"task_{i}"
                agent_id = task_data.get("agent_id", "developer")

                # Validate agent exists
                if agent_id not in self.agents:
                    self.logger.warning(
                        "unknown_agent_in_plan",
                        agent_id=agent_id,
                    )
                    continue

                # Convert depends_on from task names to task IDs
                depends_on = task_data.get("depends_on", [])

                task = AgentTask(
                    id=task_id,
                    agent_id=agent_id,
                    description=task_data.get("description", "Complete the assigned task"),
                    depends_on=depends_on,
                    context=intent.project_context,
                    status=TaskStatus.PENDING,
                )
                tasks.append(task)

            plan = Plan(
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

        # Calculate token usage
        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
            usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

        self.logger.info(
            "plan_generated",
            plan_id=plan_id,
            plan_type=plan.plan_type.value,
            num_tasks=len(plan.tasks) if plan.plan_type == PlanType.AGENTS else 0,
            workflow_id=plan.workflow_id if plan.plan_type == PlanType.WORKFLOW else None,
        )

        return plan, usage

    def _create_fallback_plan(self, plan_id: str, intent: Intent) -> Plan:
        """Create a simple fallback plan when LLM fails."""
        self.logger.warning("creating_fallback_plan", plan_id=plan_id)

        # Default: assign developer agent for create/update actions
        if intent.action in (IntentAction.CREATE_PROJECT, IntentAction.UPDATE_PROJECT):
            task = AgentTask(
                id="task_0",
                agent_id="developer",
                description=intent.prompt,
                context=intent.project_context,
                status=TaskStatus.PENDING,
            )
            return Plan(
                id=plan_id,
                name=f"Fallback Plan: {intent.prompt[:50]}",
                description="Fallback plan - LLM planning failed",
                plan_type=PlanType.AGENTS,
                status=PlanStatus.PENDING,
                intent=intent,
                tasks=[task],
                project_context=intent.project_context,
            )

        # For general chat, no tasks needed
        return Plan(
            id=plan_id,
            name="General Response",
            description="No action required",
            plan_type=PlanType.AGENTS,
            status=PlanStatus.COMPLETED,
            intent=intent,
            tasks=[],
        )
