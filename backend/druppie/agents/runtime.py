"""Agent Runtime - orchestrates autonomous agents.

The AgentRuntime executes agent tasks with:
- Parallel execution based on depends_on relationships
- Result aggregation and context passing
- Error handling and status tracking
"""

import asyncio
from datetime import datetime
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel

from druppie.core.models import (
    AgentResult,
    AgentTask,
    Plan,
    PlanStatus,
    TaskStatus,
)
from druppie.mcp import MCPClient, MCPRegistry
from druppie.registry import AgentRegistry

from .agent import Agent
from .a2a import A2AProtocol

logger = structlog.get_logger()


class AgentRuntime:
    """Runtime for executing autonomous agents.

    Responsibilities:
    - Instantiate agents with their MCP tools
    - Execute tasks assigned to agents
    - Handle parallel execution based on dependencies
    - Collect and aggregate results
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        mcp_registry: MCPRegistry,
        agent_registry: AgentRegistry,
        llm: BaseChatModel,
        emit_event: callable = None,
    ):
        """Initialize the AgentRuntime.

        Args:
            mcp_client: Client for invoking MCP tools
            mcp_registry: Registry of available MCP servers
            agent_registry: Registry of agent definitions
            llm: LangChain chat model for agents
            emit_event: Optional callback to emit real-time events
        """
        self.mcp_client = mcp_client
        self.mcp_registry = mcp_registry
        self.agent_registry = agent_registry
        self.llm = llm
        self.emit_event = emit_event
        self.a2a = A2AProtocol()
        self.logger = logger.bind(component="agent_runtime")

        # Collect LLM calls from all agent executions
        self.all_llm_calls: list[dict] = []

    async def execute_plan(
        self,
        plan: Plan,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Execute a plan by running all agent tasks.

        Tasks are executed in parallel when their dependencies are satisfied.
        Results are passed as context to dependent tasks.

        Args:
            plan: The plan to execute
            context: Initial context for all tasks

        Returns:
            Updated plan with results
        """
        context = context or {}
        context.update(plan.project_context)

        self.logger.info(
            "Starting plan execution",
            plan_id=plan.id,
            num_tasks=len(plan.tasks),
        )

        plan.status = PlanStatus.RUNNING

        # Execute tasks until all are done
        while True:
            # Find tasks ready to run (pending with satisfied dependencies)
            ready_tasks = self._get_ready_tasks(plan)

            if not ready_tasks:
                # Check if any tasks are still running
                running = [t for t in plan.tasks if t.status == TaskStatus.RUNNING]
                if running:
                    # Wait a bit for running tasks to complete
                    await asyncio.sleep(0.1)
                    continue
                break  # All done

            self.logger.info(
                f"Executing {len(ready_tasks)} ready tasks in parallel"
            )

            # Execute ready tasks in parallel
            await asyncio.gather(
                *[
                    self._execute_task(task, plan, context)
                    for task in ready_tasks
                ]
            )

        # Determine final plan status
        failed = any(t.status == TaskStatus.FAILED for t in plan.tasks)
        plan.status = PlanStatus.FAILED if failed else PlanStatus.COMPLETED

        self.logger.info(
            "Plan execution completed",
            plan_id=plan.id,
            status=plan.status.value,
        )

        return plan

    def _get_ready_tasks(self, plan: Plan) -> list[AgentTask]:
        """Get tasks that are ready to execute.

        A task is ready when:
        - Its status is PENDING
        - All its dependencies are COMPLETED
        """
        ready = []
        for task in plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue

            # Check dependencies
            deps_satisfied = all(
                self._get_task(plan, dep_id).status == TaskStatus.COMPLETED
                for dep_id in task.depends_on
                if self._get_task(plan, dep_id) is not None
            )

            if deps_satisfied:
                ready.append(task)

        return ready

    def _get_task(self, plan: Plan, task_id: str) -> AgentTask | None:
        """Get a task by ID."""
        for task in plan.tasks:
            if task.id == task_id:
                return task
        return None

    async def _execute_task(
        self,
        task: AgentTask,
        plan: Plan,
        context: dict[str, Any],
    ) -> None:
        """Execute a single task.

        Args:
            task: The task to execute
            plan: The parent plan
            context: Global context
        """
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        self.logger.info(
            "Executing task",
            task_id=task.id,
            agent_id=task.agent_id,
        )

        try:
            # Get agent definition
            agent_def = self.agent_registry.get_agent(task.agent_id)
            if not agent_def:
                raise ValueError(f"Agent not found: {task.agent_id}")

            # Create agent instance with emit_event callback
            agent = Agent(
                definition=agent_def,
                mcp_client=self.mcp_client,
                mcp_registry=self.mcp_registry,
                llm=self.llm,
                emit_event=self.emit_event,
            )

            # Build task context from dependencies
            task_context = dict(context)
            task_context.update(task.context)

            # Add results from dependencies
            for dep_id in task.depends_on:
                dep_task = self._get_task(plan, dep_id)
                if dep_task and dep_task.result:
                    task_context[f"result_{dep_id}"] = {
                        "success": dep_task.result.success,
                        "summary": dep_task.result.summary,
                        "data": dep_task.result.data,
                        "artifacts": dep_task.result.artifacts,
                    }

            # Execute the agent
            result = await agent.execute(task.description, task_context)

            # Collect LLM calls from this agent
            if result.llm_calls:
                self.all_llm_calls.extend(result.llm_calls)

            # Store result
            task.result = result
            task.status = (
                TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            )

            # Update plan token usage
            if result.token_usage:
                plan.total_usage.add(result.token_usage)

            self.logger.info(
                "Task completed",
                task_id=task.id,
                success=result.success,
                summary=result.summary[:100] if result.summary else None,
            )

        except Exception as e:
            self.logger.error(
                "Task execution failed",
                task_id=task.id,
                error=str(e),
            )
            task.result = AgentResult(
                success=False,
                summary=f"Execution failed: {e}",
                error=str(e),
            )
            task.status = TaskStatus.FAILED

        finally:
            task.completed_at = datetime.utcnow()

    async def execute_single_task(
        self,
        agent_id: str,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a single task without a plan.

        Useful for one-off agent invocations.

        Args:
            agent_id: The agent to use
            description: Task description
            context: Optional context

        Returns:
            AgentResult from the agent
        """
        agent_def = self.agent_registry.get_agent(agent_id)
        if not agent_def:
            return AgentResult(
                success=False,
                summary=f"Agent not found: {agent_id}",
                error="Agent not found",
            )

        agent = Agent(
            definition=agent_def,
            mcp_client=self.mcp_client,
            mcp_registry=self.mcp_registry,
            llm=self.llm,
            emit_event=self.emit_event,
        )

        result = await agent.execute(description, context or {})

        # Collect LLM calls
        if result.llm_calls:
            self.all_llm_calls.extend(result.llm_calls)

        return result
