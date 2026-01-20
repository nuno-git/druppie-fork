"""Orchestrator - routes plans to the appropriate execution engine.

The Orchestrator decides whether to:
- Execute a workflow (WorkflowEngine)
- Execute agent tasks directly (AgentRuntime)
"""

from typing import Any

import structlog

from druppie.agents import AgentRuntime
from druppie.core.models import Plan, PlanStatus, PlanType
from druppie.workflows import WorkflowEngine, WorkflowRegistry

logger = structlog.get_logger()


class Orchestrator:
    """Routes plans to the appropriate execution engine.

    Based on the plan type, the orchestrator:
    - WORKFLOW plans → WorkflowEngine
    - AGENTS plans → AgentRuntime
    """

    def __init__(
        self,
        agent_runtime: AgentRuntime,
        workflow_engine: WorkflowEngine,
        workflow_registry: WorkflowRegistry,
    ):
        """Initialize the Orchestrator.

        Args:
            agent_runtime: Runtime for executing agent tasks
            workflow_engine: Engine for executing workflows
            workflow_registry: Registry of workflow definitions
        """
        self.agent_runtime = agent_runtime
        self.workflow_engine = workflow_engine
        self.workflow_registry = workflow_registry
        self.logger = logger.bind(component="orchestrator")

    async def execute(self, plan: Plan) -> Plan:
        """Execute a plan using the appropriate engine.

        Args:
            plan: The plan to execute

        Returns:
            Updated plan with results
        """
        self.logger.info(
            "Executing plan",
            plan_id=plan.id,
            plan_type=plan.plan_type.value,
        )

        if plan.plan_type == PlanType.WORKFLOW:
            return await self._execute_workflow(plan)
        else:
            return await self._execute_agents(plan)

    async def _execute_workflow(self, plan: Plan) -> Plan:
        """Execute a workflow-based plan."""
        if not plan.workflow_id:
            self.logger.error("Workflow plan has no workflow_id")
            plan.status = PlanStatus.FAILED
            return plan

        workflow = self.workflow_registry.get_workflow(plan.workflow_id)
        if not workflow:
            self.logger.error(f"Workflow not found: {plan.workflow_id}")
            plan.status = PlanStatus.FAILED
            return plan

        self.logger.info(
            "Executing workflow",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
        )

        return await self.workflow_engine.execute_from_plan(plan, workflow)

    async def _execute_agents(self, plan: Plan) -> Plan:
        """Execute an agent-based plan."""
        if not plan.tasks:
            self.logger.warning("Agent plan has no tasks")
            plan.status = PlanStatus.COMPLETED
            return plan

        self.logger.info(
            "Executing agent tasks",
            num_tasks=len(plan.tasks),
        )

        return await self.agent_runtime.execute_plan(plan, plan.project_context)
