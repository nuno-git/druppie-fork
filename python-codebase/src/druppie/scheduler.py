"""Scheduler for running workflows on a schedule.

Uses APScheduler for cron-based scheduling.
"""

from datetime import datetime
from typing import Any, Callable
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog

from druppie.core.models import WorkflowDefinition, WorkflowRun
from druppie.store import FileStore

logger = structlog.get_logger()


class WorkflowScheduler:
    """Scheduler for workflow execution.

    Manages scheduled workflows and triggers them at the right time.
    """

    def __init__(
        self,
        store: FileStore,
        execute_func: Callable[[WorkflowDefinition, dict[str, Any]], Any],
    ):
        """
        Args:
            store: Storage backend
            execute_func: Function to call when executing a workflow
        """
        self.store = store
        self.execute_func = execute_func
        self.scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # workflow_id -> job_id

    def start(self) -> None:
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("Workflow scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Workflow scheduler stopped")

    async def load_scheduled_workflows(self) -> None:
        """Load and schedule all workflows with schedules."""
        workflows = await self.store.list_workflows(status="production")

        for workflow in workflows:
            if workflow.schedule:
                self.schedule_workflow(workflow)

        logger.info("Loaded scheduled workflows", count=len(self._jobs))

    def schedule_workflow(self, workflow: WorkflowDefinition) -> None:
        """Add or update a workflow schedule."""
        if not workflow.schedule:
            logger.warning("Workflow has no schedule", workflow_id=workflow.id)
            return

        # Remove existing job if any
        if workflow.id in self._jobs:
            self.scheduler.remove_job(self._jobs[workflow.id])

        # Parse cron expression
        try:
            trigger = CronTrigger.from_crontab(workflow.schedule)
        except ValueError as e:
            logger.error(
                "Invalid cron expression",
                workflow_id=workflow.id,
                schedule=workflow.schedule,
                error=str(e),
            )
            return

        # Add job
        job = self.scheduler.add_job(
            self._execute_workflow,
            trigger=trigger,
            args=[workflow],
            id=f"workflow-{workflow.id}",
            name=f"Workflow: {workflow.name}",
            replace_existing=True,
        )

        self._jobs[workflow.id] = job.id

        logger.info(
            "Workflow scheduled",
            workflow_id=workflow.id,
            schedule=workflow.schedule,
            next_run=job.next_run_time,
        )

    def unschedule_workflow(self, workflow_id: str) -> None:
        """Remove a workflow from the schedule."""
        if workflow_id in self._jobs:
            self.scheduler.remove_job(self._jobs[workflow_id])
            del self._jobs[workflow_id]
            logger.info("Workflow unscheduled", workflow_id=workflow_id)

    async def _execute_workflow(self, workflow: WorkflowDefinition) -> None:
        """Execute a scheduled workflow."""
        logger.info("Executing scheduled workflow", workflow_id=workflow.id)

        # Create a run record
        run = WorkflowRun(
            id=f"run-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow.id,
            trigger_input={"triggered_by": "schedule"},
        )
        await self.store.save_run(run)

        try:
            # Execute the workflow
            await self.execute_func(workflow, run.trigger_input)

            run.status = "completed"
            run.completed_at = datetime.utcnow()

            logger.info(
                "Scheduled workflow completed",
                workflow_id=workflow.id,
                run_id=run.id,
            )

        except Exception as e:
            run.status = "failed"
            run.completed_at = datetime.utcnow()

            logger.error(
                "Scheduled workflow failed",
                workflow_id=workflow.id,
                run_id=run.id,
                error=str(e),
            )

        finally:
            await self.store.save_run(run)

    def get_next_run_times(self) -> dict[str, datetime | None]:
        """Get next run times for all scheduled workflows."""
        result = {}
        for workflow_id, job_id in self._jobs.items():
            job = self.scheduler.get_job(job_id)
            result[workflow_id] = job.next_run_time if job else None
        return result
