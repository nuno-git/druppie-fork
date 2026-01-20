"""Workflow Engine for executing predefined workflows.

Workflows are sequences of steps that can be:
- MCP calls (direct tool invocation)
- Agent tasks (autonomous execution)
- Conditional branches

This engine executes workflows step-by-step with:
- Template variable substitution
- Error handling and retry logic
- Flow control (on_success, on_failure)
"""

import json
import re
import uuid
from datetime import datetime
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel

from druppie.agents import AgentRuntime
from druppie.core.models import (
    AgentTask,
    Plan,
    PlanStatus,
    PlanType,
    TaskStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepType,
)
from druppie.mcp import MCPClient

logger = structlog.get_logger()


class WorkflowEngine:
    """Engine for executing predefined workflows.

    Workflows are sequences of steps for complex operations like:
    - Coding: clone → branch → TDD → code → push → build → e2e
    - Deployment: build → test → deploy → verify

    Each step can be:
    - MCP: Direct tool invocation
    - Agent: Autonomous agent execution
    """

    def __init__(
        self,
        agent_runtime: AgentRuntime,
        mcp_client: MCPClient,
    ):
        """Initialize the WorkflowEngine.

        Args:
            agent_runtime: Runtime for executing agent tasks
            mcp_client: Client for invoking MCP tools
        """
        self.agent_runtime = agent_runtime
        self.mcp_client = mcp_client
        self.logger = logger.bind(component="workflow_engine")

    async def execute(
        self,
        workflow: WorkflowDefinition,
        input_data: dict[str, Any],
    ) -> WorkflowRun:
        """Execute a workflow.

        Args:
            workflow: The workflow definition to execute
            input_data: Initial input data (variables for templates)

        Returns:
            WorkflowRun with results
        """
        run = WorkflowRun(
            id=f"run-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow.id,
            status="running",
            trigger_input=input_data,
            context=dict(input_data),
        )

        self.logger.info(
            "Starting workflow execution",
            workflow_id=workflow.id,
            run_id=run.id,
        )

        current_step_id = workflow.entry_point

        while current_step_id:
            step = workflow.steps.get(current_step_id)
            if not step:
                self.logger.error(f"Step not found: {current_step_id}")
                break

            run.current_step_id = current_step_id

            self.logger.info(
                "Executing workflow step",
                step_id=current_step_id,
                step_name=step.name,
                step_type=step.type.value,
            )

            try:
                # Execute the step
                result = await self._execute_step(step, run.context)

                # Store result in context
                run.context[f"step_{step.id}"] = result

                # Determine next step
                current_step_id = step.on_success

                # Reset retry count on success
                step.retry_count = 0

            except Exception as e:
                self.logger.error(
                    "Workflow step failed",
                    step_id=current_step_id,
                    error=str(e),
                )

                # Store error in context
                run.context[f"step_{step.id}"] = {"error": str(e)}

                # Check retry
                if step.retry_count < step.max_retries:
                    step.retry_count += 1
                    self.logger.info(
                        f"Retrying step ({step.retry_count}/{step.max_retries})"
                    )
                    continue  # Retry same step

                # Move to failure handler
                current_step_id = step.on_failure

        # Determine final status
        if current_step_id is None:
            # Reached end successfully
            run.status = "completed"
        else:
            # Ended due to failure without handler
            run.status = "failed"

        run.completed_at = datetime.utcnow()

        self.logger.info(
            "Workflow execution completed",
            workflow_id=workflow.id,
            run_id=run.id,
            status=run.status,
        )

        return run

    async def _execute_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single workflow step.

        Args:
            step: The step to execute
            context: Current workflow context

        Returns:
            Step result
        """
        if step.type == WorkflowStepType.MCP:
            return await self._execute_mcp_step(step, context)
        elif step.type == WorkflowStepType.AGENT:
            return await self._execute_agent_step(step, context)
        elif step.type == WorkflowStepType.CONDITION:
            return await self._execute_condition_step(step, context)
        else:
            raise ValueError(f"Unknown step type: {step.type}")

    async def _execute_mcp_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an MCP tool step."""
        if not step.mcp_tool:
            raise ValueError(f"MCP step {step.id} has no tool defined")

        # Resolve parameter templates
        params = self._resolve_templates(step.params, context)

        self.logger.debug(
            "Invoking MCP tool",
            tool=step.mcp_tool,
            params=params,
        )

        result = await self.mcp_client.invoke(step.mcp_tool, params)

        return result

    async def _execute_agent_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an agent task step."""
        if not step.agent_id:
            raise ValueError(f"Agent step {step.id} has no agent_id defined")

        # Resolve task template
        task_description = step.task_template or step.name
        task_description = self._resolve_template_string(task_description, context)

        self.logger.debug(
            "Executing agent task",
            agent_id=step.agent_id,
            task=task_description[:100],
        )

        # Execute via agent runtime
        result = await self.agent_runtime.execute_single_task(
            agent_id=step.agent_id,
            description=task_description,
            context=context,
        )

        return {
            "success": result.success,
            "summary": result.summary,
            "data": result.data,
            "artifacts": result.artifacts,
            "error": result.error,
        }

    async def _execute_condition_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a conditional step (not yet implemented)."""
        # For now, just return success
        return {"condition_result": True}

    def _resolve_templates(
        self,
        params: dict[str, str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve parameter templates with context values.

        Supports {variable} syntax for simple substitution
        and {step_id.field} for accessing step results.
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_template_string(value, context)
            else:
                resolved[key] = value
        return resolved

    def _resolve_template_string(
        self,
        template: str,
        context: dict[str, Any],
    ) -> str:
        """Resolve a single template string."""
        if "{" not in template:
            return template

        # Find all {variable} patterns
        pattern = r"\{([^}]+)\}"

        def replace_var(match: re.Match) -> str:
            var_path = match.group(1)

            # Handle nested paths like step_clone.path
            parts = var_path.split(".")
            value = context

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = ""
                    break

            return str(value) if value else ""

        return re.sub(pattern, replace_var, template)

    async def execute_from_plan(
        self,
        plan: Plan,
        workflow: WorkflowDefinition,
    ) -> Plan:
        """Execute a workflow from a plan.

        Args:
            plan: The plan that triggered this workflow
            workflow: The workflow to execute

        Returns:
            Updated plan with workflow results
        """
        plan.status = PlanStatus.RUNNING

        # Execute the workflow
        run = await self.execute(workflow, plan.project_context)

        # Store run in plan
        plan.workflow_run = run

        # Update plan status based on workflow result
        plan.status = (
            PlanStatus.COMPLETED if run.status == "completed" else PlanStatus.FAILED
        )

        return plan
