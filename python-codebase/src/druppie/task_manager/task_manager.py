"""Task Manager for orchestrating plan execution.

The Task Manager is the runtime orchestrator that executes plans step by step.
It manages dependencies, handles errors, and supports user interaction.
"""

import asyncio
import structlog
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable
from dataclasses import dataclass, field

from druppie.core.models import (
    Plan,
    PlanStatus,
    Step,
    StepStatus,
    TokenUsage,
)
from druppie.executor import Dispatcher, ExecutorResult
from druppie.store import FileStore

logger = structlog.get_logger()


class TaskStatus(str, Enum):
    """Status of a task."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A running task that executes a plan."""

    id: str
    plan: Plan
    status: TaskStatus = TaskStatus.PENDING

    # For user interaction
    input_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Execution control
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Context passed to executors
    context: dict[str, Any] = field(default_factory=dict)

    # Output callback for streaming
    output_callback: Callable[[str], None] | None = None


class TaskManager:
    """Orchestrates plan execution.

    The TaskManager:
    1. Manages running tasks
    2. Executes steps in dependency order
    3. Handles user input for HITL steps
    4. Tracks progress and results
    """

    def __init__(
        self,
        dispatcher: Dispatcher,
        store: FileStore | None = None,
    ):
        """Initialize the TaskManager.

        Args:
            dispatcher: Executor dispatcher for step execution
            store: File store for persisting plans
        """
        self.dispatcher = dispatcher
        self.store = store
        self.tasks: dict[str, Task] = {}
        self.logger = logger.bind(component="task_manager")

    async def start_task(
        self,
        plan: Plan,
        context: dict[str, Any] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> Task:
        """Start executing a plan as a task.

        Args:
            plan: The plan to execute
            context: Initial context for executors
            output_callback: Callback for streaming output

        Returns:
            The created Task
        """
        # Build context with workspace path
        task_context = context or {}

        # Set files path from store if available
        if self.store:
            files_dir = self.store.get_plan_files_dir(plan.id)
            task_context["workspace_path"] = str(files_dir)  # For backward compat
            task_context["files_path"] = str(files_dir)
            task_context["plan_dir"] = str(self.store.get_plan_dir(plan.id))

        task = Task(
            id=plan.id,
            plan=plan,
            status=TaskStatus.PENDING,
            context=task_context,
            output_callback=output_callback,
        )

        self.tasks[task.id] = task

        self.logger.info(
            "starting_task",
            task_id=task.id,
            plan_name=plan.name,
            num_steps=len(plan.steps),
            workspace=task_context.get("workspace_path"),
        )

        # Start execution in background
        asyncio.create_task(self._run_task(task))

        return task

    async def _run_task(self, task: Task) -> None:
        """Execute a task (plan) step by step."""
        task.status = TaskStatus.RUNNING
        task.plan.status = PlanStatus.RUNNING
        task.plan.updated_at = datetime.utcnow()

        try:
            await self._execute_loop(task)

            # Check final status
            failed_steps = [s for s in task.plan.steps if s.status == StepStatus.FAILED]
            if failed_steps:
                task.status = TaskStatus.FAILED
                task.plan.status = PlanStatus.FAILED
            else:
                task.status = TaskStatus.COMPLETED
                task.plan.status = PlanStatus.COMPLETED

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.plan.status = PlanStatus.CANCELLED
            self.logger.info("task_cancelled", task_id=task.id)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.plan.status = PlanStatus.FAILED
            self.logger.error("task_failed", task_id=task.id, error=str(e))

        finally:
            task.plan.updated_at = datetime.utcnow()
            if self.store:
                await self.store.save_plan(task.plan)

            self.logger.info(
                "task_finished",
                task_id=task.id,
                status=task.status.value,
            )

    async def _execute_loop(self, task: Task) -> None:
        """Main execution loop for a task."""
        plan = task.plan

        while not task.cancel_event.is_set():
            # Find next executable step
            step = self._find_next_step(plan)

            if step is None:
                # No more steps to execute
                break

            # Check if cancelled
            if task.cancel_event.is_set():
                break

            # Execute the step
            await self._execute_step(task, step)

            # Save progress
            if self.store:
                await self.store.save_plan(plan)

    def _find_next_step(self, plan: Plan) -> Step | None:
        """Find the next step that can be executed.

        A step can be executed when:
        - Its status is PENDING
        - All its dependencies are COMPLETED
        """
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue

            # Check dependencies
            deps_satisfied = all(
                self._get_step_by_id(plan, dep_id).status == StepStatus.COMPLETED
                for dep_id in step.depends_on
                if self._get_step_by_id(plan, dep_id) is not None
            )

            if deps_satisfied:
                return step

        return None

    def _get_step_by_id(self, plan: Plan, step_id: int) -> Step | None:
        """Get a step by its ID."""
        for step in plan.steps:
            if step.id == step_id:
                return step
        return None

    async def _execute_step(self, task: Task, step: Step) -> None:
        """Execute a single step."""
        self.logger.info(
            "executing_step",
            task_id=task.id,
            step_id=step.id,
            action=step.action,
            agent_id=step.agent_id,
        )

        step.status = StepStatus.RUNNING
        step.started_at = datetime.utcnow()

        # Output progress
        if task.output_callback:
            task.output_callback(f"[Step {step.id}] Executing: {step.action}")

        try:
            # Check if step requires human approval
            if step.requires_approval:
                await self._handle_approval(task, step)
                if step.status != StepStatus.RUNNING:
                    return

            # Execute with dispatcher
            result = await self.dispatcher.execute(step, task.context)

            # Update step
            if result.success:
                step.status = StepStatus.COMPLETED
                step.result = result.result
                self.logger.info(
                    "step_completed",
                    task_id=task.id,
                    step_id=step.id,
                )
            else:
                step.status = StepStatus.FAILED
                step.error = result.error
                self.logger.error(
                    "step_failed",
                    task_id=task.id,
                    step_id=step.id,
                    error=result.error,
                )

            # Track token usage
            if result.usage:
                step.usage = result.usage
                task.plan.total_usage.add(result.usage)

            # Output messages
            if result.output_messages and task.output_callback:
                for msg in result.output_messages:
                    task.output_callback(msg)

            # Update context with result
            if result.result:
                task.context[f"step_{step.id}_result"] = result.result

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            self.logger.error(
                "step_exception",
                task_id=task.id,
                step_id=step.id,
                error=str(e),
            )

        finally:
            step.completed_at = datetime.utcnow()

    async def _handle_approval(self, task: Task, step: Step) -> None:
        """Handle human-in-the-loop approval for a step."""
        self.logger.info(
            "waiting_approval",
            task_id=task.id,
            step_id=step.id,
            assigned_group=step.assigned_group,
        )

        step.status = StepStatus.WAITING_INPUT
        task.status = TaskStatus.WAITING_INPUT
        task.plan.status = PlanStatus.WAITING_INPUT

        if task.output_callback:
            task.output_callback(
                f"[Step {step.id}] Waiting for approval from: {step.assigned_group or 'any'}"
            )

        # Save state while waiting
        if self.store:
            await self.store.save_plan(task.plan)

        # Wait for input
        try:
            approval = await asyncio.wait_for(
                task.input_queue.get(),
                timeout=None,  # No timeout for approval
            )

            if approval.get("approved"):
                step.approved_by = approval.get("user", "unknown")
                step.status = StepStatus.RUNNING
                task.status = TaskStatus.RUNNING
                task.plan.status = PlanStatus.RUNNING
                self.logger.info(
                    "step_approved",
                    task_id=task.id,
                    step_id=step.id,
                    approved_by=step.approved_by,
                )
            else:
                step.status = StepStatus.SKIPPED
                step.error = approval.get("reason", "Rejected by user")
                self.logger.info(
                    "step_rejected",
                    task_id=task.id,
                    step_id=step.id,
                )

        except asyncio.CancelledError:
            step.status = StepStatus.CANCELLED
            raise

    async def submit_input(
        self,
        task_id: str,
        step_id: int,
        input_data: dict[str, Any],
    ) -> bool:
        """Submit user input for a waiting step.

        Args:
            task_id: The task ID
            step_id: The step ID waiting for input
            input_data: The input data (e.g., {"approved": True, "user": "john"})

        Returns:
            True if input was submitted successfully
        """
        task = self.tasks.get(task_id)
        if not task:
            self.logger.warning("task_not_found", task_id=task_id)
            return False

        if task.status != TaskStatus.WAITING_INPUT:
            self.logger.warning(
                "task_not_waiting",
                task_id=task_id,
                status=task.status.value,
            )
            return False

        await task.input_queue.put(input_data)
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel

        Returns:
            True if task was cancelled
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        task.cancel_event.set()
        self.logger.info("task_cancel_requested", task_id=task_id)
        return True

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def get_pending_tasks(self) -> list[Task]:
        """Get all tasks waiting for input."""
        return [
            task for task in self.tasks.values()
            if task.status == TaskStatus.WAITING_INPUT
        ]

    async def stream_output(self, task_id: str) -> AsyncIterator[str]:
        """Stream output from a task.

        This is a simple implementation using a queue.
        For production, consider using SSE or WebSockets.
        """
        task = self.tasks.get(task_id)
        if not task:
            return

        output_queue: asyncio.Queue[str] = asyncio.Queue()

        original_callback = task.output_callback
        task.output_callback = lambda msg: output_queue.put_nowait(msg)

        try:
            while task.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING_INPUT):
                try:
                    msg = await asyncio.wait_for(output_queue.get(), timeout=1.0)
                    yield msg
                except asyncio.TimeoutError:
                    continue

            # Drain remaining messages
            while not output_queue.empty():
                yield output_queue.get_nowait()

        finally:
            task.output_callback = original_callback
