"""Planner for generating execution plans.

The Planner takes analyzed intent and generates a step-by-step execution plan.
It selects appropriate agents and creates steps with proper dependencies.
"""

import json
import structlog
from datetime import datetime
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from druppie.core.models import (
    Intent,
    IntentAction,
    Plan,
    PlanStatus,
    Step,
    StepStatus,
    AgentDefinition,
    TokenUsage,
)

logger = structlog.get_logger()


def create_planner_prompt(
    intent: Intent,
    agents: list[AgentDefinition],
    available_tools: list[str],
) -> str:
    """Create the system prompt for plan generation."""

    agent_descriptions = []
    for agent in agents:
        skills_str = ", ".join(agent.skills) if agent.skills else "general"
        tools_str = ", ".join(agent.tools) if agent.tools else "none"
        agent_descriptions.append(
            f"- {agent.id}: {agent.name}\n"
            f"  Type: {agent.type.value}\n"
            f"  Description: {agent.description}\n"
            f"  Skills: {skills_str}\n"
            f"  Tools: {tools_str}"
        )

    agents_section = "\n".join(agent_descriptions) if agent_descriptions else "No agents available"
    tools_section = ", ".join(available_tools) if available_tools else "No tools available"

    return f"""You are a planning system for Druppie, a governance AI platform.

Your task is to create an execution plan based on the user's intent.
The plan should consist of steps that will be executed by specialized agents.

## Available Agents:
{agents_section}

## Available MCP Tools:
{tools_section}

## User Intent:
Action: {intent.action.value}
Category: {intent.category}
Request: {intent.prompt}

## Instructions:
1. Select the most appropriate agents for this task
2. Create a sequence of steps that achieve the user's goal
3. Each step should have:
   - agent_id: which agent executes this step
   - action: what action to perform (use agent skills)
   - params: parameters for the action (see action-specific params below)
   - depends_on: list of step IDs this step depends on (0-indexed)
4. Ensure steps are ordered logically with proper dependencies
5. Keep the plan focused and efficient

## Action-Specific Parameters:
- create_repo: {{"name": "project-name", "language": "python"}}
- write_code: {{"description": "detailed description of what to implement", "language": "python", "framework": "flask/fastapi/etc"}}
- create_user_stories: {{"feature": "feature description"}}
- design_architecture: {{"requirements": ["list of requirements"]}}

## Response Format:
Respond ONLY with valid JSON:
{{
    "name": "Short plan name",
    "description": "Brief description of what the plan does",
    "selected_agents": ["agent_id1", "agent_id2"],
    "steps": [
        {{
            "agent_id": "developer",
            "action": "create_repo",
            "params": {{"name": "project-name", "language": "python"}},
            "depends_on": []
        }},
        {{
            "agent_id": "architect",
            "action": "design_architecture",
            "params": {{"requirements": ["..."]}}
            "depends_on": [0]
        }}
    ]
}}"""


class Planner:
    """Generates execution plans from user intent.

    The Planner:
    1. Selects relevant agents based on the intent
    2. Creates a sequence of steps with dependencies
    3. Validates the plan structure
    """

    def __init__(
        self,
        llm: BaseChatModel,
        agents: dict[str, AgentDefinition] | None = None,
        max_agent_selection: int = 3,
        max_retries: int = 3,
        debug: bool = False,
    ):
        """Initialize the Planner.

        Args:
            llm: LangChain chat model for plan generation
            agents: Dictionary of available agents by ID
            max_agent_selection: Maximum number of agents to select
            max_retries: Maximum retries for plan generation
            debug: Enable debug logging
        """
        self.llm = llm
        self.agents = agents or {}
        self.max_agent_selection = max_agent_selection
        self.max_retries = max_retries
        self.debug = debug
        self.logger = logger.bind(component="planner")

    def set_agents(self, agents: dict[str, AgentDefinition]) -> None:
        """Update the available agents."""
        self.agents = agents

    async def select_agents(
        self,
        intent: Intent,
        available_tools: list[str],
    ) -> tuple[list[str], TokenUsage]:
        """Select relevant agents for the intent.

        Uses LLM to identify which agents are best suited for the task.
        """
        if not self.agents:
            return [], TokenUsage()

        agent_list = "\n".join(
            f"- {a.id}: {a.name} - {a.description}"
            for a in self.agents.values()
        )

        prompt = f"""Select the most relevant agents for this task.

Available agents:
{agent_list}

User request: {intent.prompt}
Action type: {intent.action.value}
Category: {intent.category}

Select up to {self.max_agent_selection} agents that should work on this task.
Respond with ONLY a JSON array of agent IDs, e.g.: ["developer", "architect"]"""

        messages = [
            SystemMessage(content="You are an agent selection system. Select the best agents for the task."),
            HumanMessage(content=prompt),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content

            # Parse agent IDs
            import re
            json_match = re.search(r'\[[\s\S]*?\]', content)
            if json_match:
                agent_ids = json.loads(json_match.group())
                # Validate agent IDs exist
                agent_ids = [aid for aid in agent_ids if aid in self.agents]
            else:
                agent_ids = []

            # Calculate token usage
            usage = TokenUsage()
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
                usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

            self.logger.info("agents_selected", agent_ids=agent_ids)
            return agent_ids, usage

        except Exception as e:
            self.logger.error("agent_selection_failed", error=str(e))
            # Fallback: select developer agent if available
            if "developer" in self.agents:
                return ["developer"], TokenUsage()
            return [], TokenUsage()

    async def create_plan(
        self,
        plan_id: str,
        intent: Intent,
        available_tools: list[str] | None = None,
    ) -> tuple[Plan, TokenUsage]:
        """Create an execution plan from the intent.

        Args:
            plan_id: Unique identifier for the plan
            intent: Analyzed user intent
            available_tools: List of available MCP tools

        Returns:
            Tuple of (Plan, TokenUsage)
        """
        self.logger.info(
            "creating_plan",
            plan_id=plan_id,
            action=intent.action.value,
        )

        available_tools = available_tools or []
        total_usage = TokenUsage()

        # Select relevant agents
        selected_agent_ids, select_usage = await self.select_agents(intent, available_tools)
        total_usage.add(select_usage)

        if not selected_agent_ids:
            # No agents selected - create minimal plan
            return Plan(
                id=plan_id,
                name=f"Plan: {intent.prompt[:50]}",
                description="No agents available for this task",
                status=PlanStatus.FAILED,
                intent=intent,
                steps=[],
                selected_agents=[],
            ), total_usage

        # Get selected agent definitions
        selected_agents = [self.agents[aid] for aid in selected_agent_ids if aid in self.agents]

        # Expand with sub-agents
        all_agent_ids = set(selected_agent_ids)
        for agent in selected_agents:
            for sub_id in agent.sub_agents:
                if sub_id in self.agents:
                    all_agent_ids.add(sub_id)

        all_agents = [self.agents[aid] for aid in all_agent_ids]

        # Generate the plan with retries
        plan = None
        for attempt in range(self.max_retries):
            try:
                plan, gen_usage = await self._generate_plan(
                    plan_id=plan_id,
                    intent=intent,
                    agents=all_agents,
                    available_tools=available_tools,
                )
                total_usage.add(gen_usage)

                if plan.steps:
                    break

            except Exception as e:
                self.logger.warning(
                    "plan_generation_attempt_failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt == self.max_retries - 1:
                    raise

        if plan is None:
            plan = Plan(
                id=plan_id,
                name=f"Plan: {intent.prompt[:50]}",
                description="Failed to generate plan",
                status=PlanStatus.FAILED,
                intent=intent,
                steps=[],
                selected_agents=list(all_agent_ids),
            )

        plan.total_usage = total_usage
        return plan, total_usage

    async def _generate_plan(
        self,
        plan_id: str,
        intent: Intent,
        agents: list[AgentDefinition],
        available_tools: list[str],
    ) -> tuple[Plan, TokenUsage]:
        """Internal method to generate plan using LLM."""

        prompt = create_planner_prompt(intent, agents, available_tools)

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Create a plan for: {intent.prompt}"),
        ]

        response = await self.llm.ainvoke(messages)
        content = response.content

        # Parse the JSON response
        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            raise ValueError("No JSON found in response")

        data = json.loads(json_match.group())

        # Create steps from response
        steps = []
        for i, step_data in enumerate(data.get("steps", [])):
            step = Step(
                id=i,
                agent_id=step_data.get("agent_id", "unknown"),
                action=step_data.get("action", "unknown"),
                params=step_data.get("params", {}),
                depends_on=step_data.get("depends_on", []),
                status=StepStatus.PENDING,
            )
            steps.append(step)

        # Validate dependencies
        steps = self._validate_dependencies(steps)

        plan = Plan(
            id=plan_id,
            name=data.get("name", f"Plan: {intent.prompt[:50]}"),
            description=data.get("description", ""),
            status=PlanStatus.PENDING,
            intent=intent,
            steps=steps,
            selected_agents=data.get("selected_agents", []),
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
            num_steps=len(steps),
            selected_agents=plan.selected_agents,
        )

        return plan, usage

    def _validate_dependencies(self, steps: list[Step]) -> list[Step]:
        """Validate and fix step dependencies.

        - Ensures dependencies reference valid step IDs
        - Removes circular dependencies
        - Ensures sequential execution within same agent
        """
        num_steps = len(steps)

        for step in steps:
            # Filter out invalid dependencies
            step.depends_on = [
                dep for dep in step.depends_on
                if 0 <= dep < num_steps and dep != step.id
            ]

        # Ensure sequential execution within same agent
        agent_last_step: dict[str, int] = {}
        for step in steps:
            if step.agent_id in agent_last_step:
                last_step_id = agent_last_step[step.agent_id]
                if last_step_id not in step.depends_on:
                    step.depends_on.append(last_step_id)
            agent_last_step[step.agent_id] = step.id

        return steps

    async def update_plan(
        self,
        plan: Plan,
        feedback: str,
        available_tools: list[str] | None = None,
    ) -> tuple[Plan, TokenUsage]:
        """Update a plan based on feedback or new information.

        Args:
            plan: Existing plan to update
            feedback: User feedback or new requirements
            available_tools: Updated list of available tools

        Returns:
            Tuple of (updated Plan, TokenUsage)
        """
        self.logger.info("updating_plan", plan_id=plan.id, feedback=feedback[:100])

        # Create a new intent incorporating the feedback
        updated_intent = Intent(
            initial_prompt=plan.intent.initial_prompt if plan.intent else "",
            prompt=f"{plan.intent.prompt if plan.intent else ''}\n\nUpdate: {feedback}",
            action=plan.intent.action if plan.intent else IntentAction.UPDATE_PROJECT,
            category=plan.intent.category if plan.intent else "unknown",
            language=plan.intent.language if plan.intent else "en",
        )

        # Generate updated plan
        new_plan, usage = await self.create_plan(
            plan_id=plan.id,
            intent=updated_intent,
            available_tools=available_tools,
        )

        # Preserve completed steps
        completed_steps = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        if completed_steps:
            # Merge: keep completed steps, add new pending steps
            max_completed_id = max(s.id for s in completed_steps)
            for new_step in new_plan.steps:
                new_step.id = max_completed_id + new_step.id + 1
                new_step.depends_on = [
                    d + max_completed_id + 1 for d in new_step.depends_on
                ]

            new_plan.steps = completed_steps + new_plan.steps

        return new_plan, usage
