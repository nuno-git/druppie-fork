"""Job service for scheduled cron jobs."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import UUID

import structlog
import yaml

try:
    from croniter import croniter
except ImportError:
    croniter = None

from ..repositories import JobRepository, SessionRepository, ExecutionRepository
from ..domain.job import JobDefinitionList, JobDefinitionDetail, JobRunList, JobRunDetail
from ..db.models.job import JobDefinition, JobDefinitionConfig
from ..domain.common import AgentRunStatus, SessionStatus

logger = structlog.get_logger()

DEFAULT_JOBS_DIR = os.path.join(os.path.dirname(__file__), "..", "jobs", "definitions")


class JobService:
    def __init__(
        self,
        job_repo: JobRepository,
        session_repo: SessionRepository,
        execution_repo: ExecutionRepository,
        approval_repo: Optional["ApprovalRepository"] = None,
    ):
        self.job_repo = job_repo
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.approval_repo = approval_repo

    def load_definitions_from_yaml(self, directory: str | None = None) -> JobDefinitionList:
        jobs_dir = directory or os.path.abspath(DEFAULT_JOBS_DIR)
        if not os.path.isdir(jobs_dir):
            logger.info("jobs_definitions_dir_not_found", path=jobs_dir)
            return self.list_definitions()

        seen_job_ids: set[str] = set()
        for filename in os.listdir(jobs_dir):
            if not filename.endswith(".yaml"):
                continue
            filepath = os.path.join(jobs_dir, filename)
            try:
                with open(filepath, "r") as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    logger.warning("job_yaml_empty_or_invalid", file=filename)
                    continue
                job_id = data.get("id")
                if not job_id:
                    logger.warning("job_yaml_missing_id", file=filename)
                    continue
                seen_job_ids.add(job_id)
                existing = self.job_repo.get_definition_by_job_id(job_id)
                if existing:
                    self._update_definition_from_yaml(existing, data, filepath)
                else:
                    self.job_repo.create_definition(
                        job_id=job_id,
                        name=data.get("name", job_id),
                        description=data.get("description"),
                        schedule=data.get("schedule", "0 0 * * *"),
                        agent_id=data.get("agent_id", "developer"),
                        prompt=data.get("prompt", ""),
                        approval_required=data.get("approval_required", False),
                        required_role=data.get("required_role"),
                        config=data.get("config"),
                        enabled=data.get("enabled", True),
                        yaml_path=filepath,
                    )
            except Exception as e:
                logger.error("job_yaml_load_failed", file=filename, error=str(e))

        self.job_repo.commit()

        existing = self.list_definitions()
        for definition in existing.items:
            if definition.job_id not in seen_job_ids and definition.yaml_path:
                self.job_repo.delete_definition_by_job_id(definition.job_id)
        self.job_repo.commit()

        return self.list_definitions()

    def _update_definition_from_yaml(
        self, definition: JobDefinition, data: dict, filepath: str
    ) -> None:
        definition.name = data.get("name", definition.name)
        definition.description = data.get("description", definition.description)
        definition.schedule = data.get("schedule", definition.schedule)
        definition.agent_id = data.get("agent_id", definition.agent_id)
        definition.prompt = data.get("prompt", definition.prompt)
        definition.approval_required = data.get("approval_required", definition.approval_required)
        definition.required_role = data.get("required_role", definition.required_role)
        new_config = data.get("config")
        if new_config is not None:
            definition.configs = []
            for key, value in new_config.items():
                definition.configs.append(
                    JobDefinitionConfig(
                        config_key=key,
                        config_value=str(value) if value is not None else None,
                    )
                )
        definition.enabled = data.get("enabled", True) if data.get("enabled") is not None else definition.enabled
        definition.yaml_path = filepath

    def list_definitions(self) -> JobDefinitionList:
        return self.job_repo.list_definitions()

    def get_definition(self, definition_id: UUID) -> JobDefinitionDetail | None:
        definition = self.job_repo.get_definition_by_id(definition_id)
        if not definition:
            return None
        return self.job_repo._to_definition_detail(definition)

    def get_job_run(self, run_id: UUID) -> JobRunDetail | None:
        run = self.job_repo.get_job_run_by_id(run_id)
        if not run:
            return None
        return self.job_repo._to_job_run_detail(run)

    def handle_rejected_job_approval(self, agent_run_id: UUID, session_id: UUID) -> None:
        from ..domain.common import AgentRunStatus, SessionStatus
        job_run = self.job_repo.get_job_run_by_agent_run_id(agent_run_id)
        if job_run:
            self.job_repo.update_job_run_status(job_run.id, "rejected")
        self.session_repo.update_status(
            session_id, SessionStatus.FAILED, error_message="Job approval rejected"
        )
        self.execution_repo.update_status(agent_run_id, AgentRunStatus.FAILED)
        self.execution_repo.commit()

    def list_job_runs(
        self,
        job_definition_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> JobRunList:
        return self.job_repo.list_job_runs(job_definition_id, status, page, limit)

    def trigger_job(self, definition_id: UUID, user_id: UUID | None = None, trigger_type: str = "manual") -> JobRunDetail:
        definition = self.job_repo.get_definition_by_id(definition_id)
        if not definition:
            from ..api.errors import NotFoundError
            raise NotFoundError("job_definition", str(definition_id))

        run = self.job_repo.create_job_run(
            job_definition_id=definition_id,
            session_id=None,
            trigger_type=trigger_type,
            status="pending",
        )
        self.job_repo.commit()

        session = self.session_repo.create(
            user_id=user_id,
            title=f"Job: {definition.name}",
            intent="scheduled_job",
        )

        next_seq = self.execution_repo.get_next_sequence_number(session.id)
        agent_run = self.execution_repo.create_agent_run(
            session_id=session.id,
            agent_id=definition.agent_id,
            status=AgentRunStatus.PENDING,
            planned_prompt=definition.prompt,
            sequence_number=next_seq,
        )
        self.execution_repo.commit()

        self.job_repo.set_job_run_session(run.id, session.id, agent_run.id)
        self.job_repo.commit()

        if definition.approval_required:
            if self.approval_repo is None:
                raise RuntimeError("approval_repo required for approval-gated jobs")
            approval = self.approval_repo.create(
                session_id=session.id,
                agent_run_id=agent_run.id,
                tool_call_id=None,
                mcp_server="jobs",
                tool_name="execute_job",
                arguments={"job_id": definition.job_id, "prompt": definition.prompt},
                required_role=definition.required_role or "admin",
            )
            self.approval_repo.commit()
            self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_TOOL)
            self.session_repo.update_status(session.id, SessionStatus.PAUSED_APPROVAL)
            self.execution_repo.commit()
            self.job_repo.update_job_run_status(run.id, "waiting_approval")
            self.job_repo.commit()
            logger.info(
                "job_approval_required",
                job_run_id=str(run.id),
                approval_id=str(approval.id),
                required_role=definition.required_role,
            )
            return self.job_repo._to_job_run_detail(run)

        logger.info(
            "job_triggered",
            job_run_id=str(run.id),
            job_definition_id=str(definition_id),
            session_id=str(session.id),
            trigger_type=trigger_type,
        )

        return self.job_repo._to_job_run_detail(run)

    def execute_job_in_background(self, job_run_id: UUID, session_id: UUID) -> None:
        from ..core.background_tasks import create_session_task, run_session_task

        async def _execute(ctx):
            from ..repositories import JobRepository
            job_repo = JobRepository(ctx.db)
            job_repo.update_job_run_status(job_run_id, "running")
            job_repo.commit()

            try:
                await ctx.orchestrator.execute_pending_runs(session_id)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "job_execution_failed",
                    job_run_id=str(job_run_id),
                    session_id=str(session_id),
                    error=error_msg,
                )
                try:
                    ctx.session_repo.update_status(session_id, SessionStatus.FAILED, error_message=error_msg[:2000])
                    ctx.session_repo.commit()
                except Exception as db_err:
                    logger.error(
                        "job_status_update_failed_after_failure",
                        session_id=str(session_id),
                        error=str(db_err),
                    )

            final_session = ctx.session_repo.get_by_id(session_id)
            if final_session:
                final_status = "completed" if final_session.status == SessionStatus.COMPLETED else "failed"
                from ..repositories import JobRepository
                job_repo = JobRepository(ctx.db)
                job_repo.update_job_run_status(job_run_id, final_status)
                job_repo.commit()

        create_session_task(
            session_id,
            run_session_task(session_id, _execute, "job_execution"),
            name=f"job_execution-{session_id}",
        )


class JobScheduler:
    def __init__(self, job_service_factory: Callable[[Any], JobService]):
        self._job_service_factory = job_service_factory
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="job-scheduler")
        logger.info("job_scheduler_started")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("job_scheduler_stopped")

    async def _loop(self) -> None:
        try:
            while self._running:
                await self._check_jobs()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("job_scheduler_loop_cancelled")

    async def _check_jobs(self) -> None:
        from ..db.database import SessionLocal
        db = SessionLocal()
        try:
            job_service = self._job_service_factory(db)
            definitions = job_service.list_definitions()
            now = datetime.now(timezone.utc)
            for definition in definitions.items:
                if not definition.enabled:
                    continue
                should_run, last_scheduled = self._should_run(definition, now)
                if not should_run:
                    continue
                claimed = job_service.job_repo.claim_job_trigger(
                    definition.id, last_scheduled, now
                )
                if not claimed:
                    logger.info(
                        "job_scheduler_claim_lost",
                        job_id=definition.job_id,
                        hint="another_instance_triggered",
                    )
                    continue
                logger.info("job_scheduler_triggering", job_id=definition.job_id)
                try:
                    run = job_service.trigger_job(definition.id, trigger_type="scheduled")
                    if run.session_id and run.status != "waiting_approval":
                        job_service.execute_job_in_background(run.id, run.session_id)
                    logger.info(
                        "job_scheduler_triggered",
                        job_id=definition.job_id,
                        job_run_id=str(run.id),
                    )
                except Exception as e:
                    logger.error(
                        "job_scheduler_trigger_failed",
                        job_id=definition.job_id,
                        error=str(e),
                    )
        except Exception as e:
            logger.error("job_scheduler_check_failed", error=str(e))
        finally:
            db.close()

    def _should_run(self, definition: Any, now: datetime) -> tuple[bool, datetime | None]:
        if croniter is None:
            logger.warning("croniter_not_installed", hint="pip install croniter")
            return False, None

        try:
            itr = croniter(definition.schedule, now)
            last_scheduled = itr.get_prev(datetime)
        except Exception as e:
            logger.error("cron_parse_failed", job_id=definition.job_id, error=str(e))
            return False, None

        last_run = definition.last_triggered_at
        if last_run is None:
            return True, last_scheduled
        return last_run < last_scheduled, last_scheduled
