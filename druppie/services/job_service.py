"""Job service for scheduled cron jobs."""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import structlog
import yaml
from croniter import CroniterBadDateError, croniter

from ..core.background_tasks import create_session_task, run_session_task
from ..domain.common import AgentRunStatus, JobRunStatus, SessionStatus
from ..domain.job import JobDefinitionDetail, JobDefinitionList, JobRunDetail, JobRunList
from ..repositories import ExecutionRepository, JobRepository, SessionRepository

logger = structlog.get_logger()

DEFAULT_JOBS_DIR = os.path.join(os.path.dirname(__file__), "..", "jobs", "definitions")

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _apply_job_env_overrides(data: dict) -> dict:
    """Apply per-deployment env overrides to a YAML job definition.

    JOB_<ID>_ENABLED and JOB_<ID>_SCHEDULE (id uppercased, e.g.
    JOB_PR_REVIEW_JOB_ENABLED) override the YAML values, so the same image
    can run a job enabled in one environment and disabled in another —
    the YAML stays the single default, the HelmRelease decides per env.
    """
    prefix = f"JOB_{re.sub(r'[^A-Z0-9]', '_', str(data['id']).upper())}_"

    enabled_raw = os.getenv(f"{prefix}ENABLED", "").strip().lower()
    if enabled_raw in _TRUTHY | _FALSY:
        data["enabled"] = enabled_raw in _TRUTHY
        # Mark this as an ops kill-switch so it stays authoritative on every
        # YAML re-sync. Without this marker a file's `enabled` only seeds a new
        # definition and never overwrites a user pause/resume (see
        # JobRepository.update_definition_from_yaml).
        data["_enabled_from_env"] = True
        logger.info("job_enabled_env_override", job_id=data["id"], enabled=data["enabled"])
    elif enabled_raw:
        logger.warning(
            "job_enabled_env_override_invalid",
            job_id=data["id"],
            value=enabled_raw,
            hint="expected true/false; keeping YAML value",
        )

    schedule = os.getenv(f"{prefix}SCHEDULE", "").strip()
    if schedule:
        data["schedule"] = schedule
        logger.info("job_schedule_env_override", job_id=data["id"], schedule=schedule)

    return data


class JobService:
    def __init__(
        self,
        job_repo: JobRepository,
        session_repo: SessionRepository,
        execution_repo: ExecutionRepository,
    ):
        self.job_repo = job_repo
        self.session_repo = session_repo
        self.execution_repo = execution_repo

    def _validate_job_data(self, data: dict, filepath: str) -> list[str]:
        """Validate a job definition loaded from YAML. Returns list of error messages."""
        errors: list[str] = []

        name = data.get("name")
        if not name or not str(name).strip():
            errors.append("name is required and must be non-empty")

        schedule = data.get("schedule")
        if not schedule or not str(schedule).strip():
            errors.append("schedule is required")
        else:
            try:
                # Construction validates syntax; get_next() additionally rejects
                # syntactically-valid-but-impossible dates (e.g. "0 0 31 2 *" =
                # Feb 31), which otherwise pass here and then make the scheduler
                # raise CroniterBadDateError on every tick.
                croniter(str(schedule)).get_next()
            except (ValueError, CroniterBadDateError):
                errors.append(f"invalid cron schedule: '{schedule}'")

        agent_id = data.get("agent_id")
        if not agent_id or not str(agent_id).strip():
            errors.append("agent_id is required")
        else:
            from ..agents.definition_loader import AgentDefinitionLoader

            # Agents live in subdirectories (general/, coding/core/, ...), so
            # search recursively — a flat path check would reject valid agents.
            agent_file = AgentDefinitionLoader._find_agent_yaml(str(agent_id))
            if not agent_file:
                definitions_path = AgentDefinitionLoader._get_definitions_path()
                errors.append(
                    f"agent_id '{agent_id}' not found (searched {definitions_path})"
                )

        prompt = data.get("prompt")
        if not prompt or not str(prompt).strip():
            errors.append("prompt is required and must be non-empty")

        return errors

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
                # Env overrides before validation, so an overridden cron
                # schedule is validated like a YAML one.
                data = _apply_job_env_overrides(data)
                validation_errors = self._validate_job_data(data, filepath)
                if validation_errors:
                    for error in validation_errors:
                        logger.error(
                            "job_yaml_validation_failed",
                            file=filename,
                            job_id=job_id,
                            error=error,
                        )
                    # The YAML file is present but invalid (e.g. an impossible
                    # or env-overridden bad cron). Mark it seen so the orphan
                    # sweep below does NOT treat it as deleted-from-disk and
                    # CASCADE-delete the existing definition + all its run
                    # history. We skip the update, keeping the last-good row.
                    seen_job_ids.add(job_id)
                    continue
                seen_job_ids.add(job_id)
                updated = self.job_repo.update_definition_from_yaml(job_id, data, filepath)
                if not updated:
                    self.job_repo.create_definition(
                        job_id=job_id,
                        name=data.get("name", job_id),
                        description=data.get("description"),
                        schedule=data.get("schedule", "0 0 * * *"),
                        agent_id=data.get("agent_id", "developer"),
                        prompt=data.get("prompt", ""),
                        approval_required=data.get("approval_required", False),
                        required_role=data.get("required_role"),
                        enabled=data.get("enabled", True),
                        yaml_path=filepath,
                    )
            except Exception as e:
                logger.error("job_yaml_load_failed", file=filename, error=str(e))

        self.job_repo.commit()

        existing = self.list_definitions()
        for definition in existing.items:
            if definition.job_id not in seen_job_ids and definition.yaml_path:
                if self.job_repo.has_active_runs_for_definition(definition.id):
                    logger.warning(
                        "orphan_definition_skipped_active_runs",
                        job_id=definition.job_id,
                        hint="definition_has_active_runs",
                    )
                    continue
                self.job_repo.delete_definition_by_job_id(definition.job_id)
        self.job_repo.commit()

        return self.list_definitions()

    def list_definitions(self) -> JobDefinitionList:
        return self.job_repo.list_definitions()

    def get_definition(self, definition_id: UUID) -> JobDefinitionDetail | None:
        definition = self.job_repo.get_definition_by_id(definition_id)
        if not definition:
            return None
        return self.job_repo.to_definition_detail(definition)

    def set_enabled(self, definition_id: UUID, enabled: bool) -> JobDefinitionDetail:
        """Pause (enabled=False) or resume (enabled=True) a schedule.

        The scheduler skips definitions with enabled=False, so this is the
        pause/resume for the cron trigger. Manual "Run Now" still works while
        paused. Persists in the DB and survives redeploys (YAML re-sync no
        longer overwrites a user-set value).
        """
        from ..api.errors import NotFoundError

        definition = self.job_repo.set_definition_enabled(definition_id, enabled)
        if not definition:
            raise NotFoundError("job_definition", str(definition_id))
        self.job_repo.commit()
        logger.info(
            "job_definition_enabled_changed",
            job_definition_id=str(definition_id),
            enabled=enabled,
        )
        return self.job_repo.to_definition_detail(definition)

    def get_job_run(self, run_id: UUID) -> JobRunDetail | None:
        run = self.job_repo.get_job_run_by_id(run_id)
        if not run:
            return None
        return self.job_repo.to_job_run_detail(run)

    def get_pending_approval_runs(self, user_roles: list[str], user_id: UUID | None = None) -> list[JobRunDetail]:
        if "admin" in user_roles:
            roles = None
        else:
            roles = user_roles
        runs = self.job_repo.get_pending_approval_runs(roles)
        return [self.job_repo.to_job_run_detail(r) for r in runs]

    def list_job_runs(
        self,
        job_definition_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> JobRunList:
        return self.job_repo.list_job_runs(job_definition_id, status, page, limit)

    def _get_system_user_id(self) -> UUID | None:
        """Lookup the 'admin' user to own sessions created by scheduled jobs."""
        return self.job_repo.get_system_user_id()

    def trigger_job(self, definition_id: UUID, user_id: UUID | None = None, trigger_type: str = "manual") -> JobRunDetail:
        """Create a new job run, session, and agent run for a job definition.

        If the job requires approval, an approval record is created and the
        agent run is paused until a user with the required role approves it.
        Otherwise, the caller must invoke execute_job_in_background() to run
        the agent in a background task.

        Args:
            definition_id: The UUID of the job definition to trigger.
            user_id: Optional user ID (e.g. admin who clicked "Run Now").
                     Scheduled triggers pass None.
            trigger_type: "manual" or "scheduled".

        Returns:
            JobRunDetail for the newly created run.

        Raises:
            NotFoundError: If the job definition does not exist.
        """
        definition = self.job_repo.get_definition_by_id(definition_id)
        if not definition:
            from ..api.errors import NotFoundError
            raise NotFoundError("job_definition", str(definition_id))

        run = self.job_repo.create_job_run(
            job_definition_id=definition_id,
            session_id=None,
            trigger_type=trigger_type,
            status=JobRunStatus.PENDING,
        )
        self.job_repo.commit()

        if user_id is None and trigger_type == "scheduled":
            system_user_id = self._get_system_user_id()
            if system_user_id:
                user_id = system_user_id

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
        run = self.job_repo.get_job_run_by_id(run.id)

        if definition.approval_required:
            self.job_repo.set_job_run_approval_required(run.id, definition.required_role or "admin")
            self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_TOOL)
            self.session_repo.update_status(session.id, SessionStatus.PAUSED_APPROVAL)
            self.execution_repo.commit()
            self.job_repo.update_job_run_status(run.id, JobRunStatus.WAITING_APPROVAL)
            self.job_repo.commit()
            logger.info(
                "job_approval_required",
                job_run_id=str(run.id),
                required_role=definition.required_role,
            )
            return self.job_repo.to_job_run_detail(run)

        self.job_repo.touch_definition_trigger_time(definition_id)
        self.job_repo.commit()

        logger.info(
            "job_triggered",
            job_run_id=str(run.id),
            job_definition_id=str(definition_id),
            session_id=str(session.id),
            trigger_type=trigger_type,
        )

        return self.job_repo.to_job_run_detail(run)

    def approve_job_run(
        self,
        job_run_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> JobRunDetail:
        from ..api.errors import AuthorizationError, ConflictError, NotFoundError

        run = self.job_repo.get_job_run_by_id(job_run_id)
        if not run:
            raise NotFoundError("job_run", str(job_run_id))

        if run.status != JobRunStatus.WAITING_APPROVAL.value:
            raise ConflictError(f"Job run is not waiting for approval ({run.status})")

        required_role = run.required_role or "admin"
        if "admin" not in user_roles and required_role not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to approve",
                required_roles=[required_role],
            )

        self.job_repo.set_job_run_approved(job_run_id, user_id)

        if run.session_id:
            self.session_repo.update_status(run.session_id, SessionStatus.ACTIVE)
        if run.agent_run_id:
            self.execution_repo.update_status(run.agent_run_id, AgentRunStatus.PENDING)
        self.execution_repo.commit()

        logger.info(
            "job_run_approved",
            job_run_id=str(job_run_id),
            approved_by=str(user_id),
        )

        self.execute_job_in_background(run.id, run.session_id)
        return self.job_repo.to_job_run_detail(run)

    def reject_job_run(
        self,
        job_run_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        reason: str,
    ) -> JobRunDetail:
        from ..api.errors import AuthorizationError, ConflictError, NotFoundError

        run = self.job_repo.get_job_run_by_id(job_run_id)
        if not run:
            raise NotFoundError("job_run", str(job_run_id))

        if run.status != JobRunStatus.WAITING_APPROVAL.value:
            raise ConflictError(f"Job run is not waiting for approval ({run.status})")

        required_role = run.required_role or "admin"
        if "admin" not in user_roles and required_role not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to reject",
                required_roles=[required_role],
            )

        self.job_repo.update_job_run_status(
            run.id, JobRunStatus.REJECTED, error_message=reason
        )
        self.session_repo.update_status(
            run.session_id, SessionStatus.FAILED, error_message=f"Job rejected: {reason}"
        )
        if run.agent_run_id:
            self.execution_repo.update_status(run.agent_run_id, AgentRunStatus.FAILED)
        self.execution_repo.commit()
        self.job_repo.commit()

        logger.info(
            "job_run_rejected",
            job_run_id=str(job_run_id),
            rejected_by=str(user_id),
            reason=reason,
        )

        return self.job_repo.to_job_run_detail(run)

    def execute_job_in_background(self, job_run_id: UUID, session_id: UUID) -> None:
        async def _execute(ctx):
            job_repo = JobRepository(ctx.db)
            job_repo.update_job_run_status(job_run_id, JobRunStatus.RUNNING)
            job_repo.commit()

            try:
                await asyncio.wait_for(
                    ctx.orchestrator.execute_pending_runs(session_id),
                    timeout=1800,
                )
            except asyncio.TimeoutError:
                error_msg = "Job timed out after 30 minutes"
                logger.error(
                    "job_execution_timeout",
                    job_run_id=str(job_run_id),
                    session_id=str(session_id),
                    error=error_msg,
                )
                try:
                    job_repo.update_job_run_status(
                        job_run_id, JobRunStatus.FAILED, error_message=error_msg
                    )
                    job_repo.commit()
                    ctx.session_repo.update_status(
                        session_id, SessionStatus.FAILED, error_message=error_msg
                    )
                    ctx.session_repo.commit()
                except Exception as db_err:
                    logger.error(
                        "job_status_update_failed_after_timeout",
                        session_id=str(session_id),
                        error=str(db_err),
                    )
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "job_execution_failed",
                    job_run_id=str(job_run_id),
                    session_id=str(session_id),
                    error=error_msg,
                )
                try:
                    job_repo.update_job_run_status(
                        job_run_id, JobRunStatus.FAILED, error_message=error_msg[:2000]
                    )
                    job_repo.commit()
                    ctx.session_repo.update_status(
                        session_id, SessionStatus.FAILED, error_message=error_msg[:2000]
                    )
                    ctx.session_repo.commit()
                except Exception as db_err:
                    logger.error(
                        "job_status_update_failed_after_failure",
                        session_id=str(session_id),
                        error=str(db_err),
                    )

            final_session = ctx.session_repo.get_by_id(session_id)
            if final_session and final_session.status in {
                SessionStatus.COMPLETED.value, SessionStatus.FAILED.value
            }:
                final_status = (
                    JobRunStatus.COMPLETED
                    if final_session.status == SessionStatus.COMPLETED.value
                    else JobRunStatus.FAILED
                )
                job_repo.update_job_run_status(
                    job_run_id, final_status, error_message=final_session.error_message
                )
                job_repo.commit()

        create_session_task(
            session_id,
            run_session_task(session_id, _execute, "job_execution"),
            name=f"job_execution-{session_id}",
            skip_lock=True,
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
                pending_jobs = await asyncio.to_thread(self._check_jobs)
                for run_id, session_id in pending_jobs:
                    try:
                        self._execute_job_in_background(run_id, session_id)
                    except Exception as e:
                        logger.error(
                            "job_scheduler_background_task_failed",
                            job_run_id=str(run_id),
                            error=str(e),
                        )
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("job_scheduler_loop_cancelled")

    def _check_jobs(self) -> list[tuple[UUID, UUID]]:
        """Synchronous check for jobs that should run now.

        Called from the async scheduler loop via asyncio.to_thread so
        synchronous DB calls don't block the event loop.

        Returns a list of (job_run_id, session_id) tuples for jobs that
        need background execution. The caller schedules the tasks on the
        event loop so asyncio.create_task works.
        """
        from ..db.database import SessionLocal
        db = SessionLocal()
        pending_runs: list[tuple[UUID, UUID]] = []
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
                # Don't stack runs of the same definition. A run can take up to
                # the 30-min execution timeout, longer than a tight cron gap
                # (e.g. pr_review_job's */20), so a new tick can fire while the
                # previous run is still active. Two concurrent PR-review rounds
                # would each find no sticky comment and both create one, so the
                # reviews stack — exactly what the marker dedup is meant to
                # prevent. Skip WITHOUT claiming: last_triggered_at stays put,
                # so the slot is retried on the next tick once the run finishes
                # (no missed round). claim_job_trigger's CAS still guards the
                # multi-instance race; this guards the single-instance overlap.
                if job_service.job_repo.has_active_runs_for_definition(definition.id):
                    logger.info(
                        "job_scheduler_skip_active_run",
                        job_id=definition.job_id,
                        hint="previous_run_still_active",
                    )
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
                    run = job_service.trigger_job(
                        definition.id, trigger_type="scheduled"
                    )
                    if run.session_id and run.status != JobRunStatus.WAITING_APPROVAL.value:
                        pending_runs.append((run.id, run.session_id))
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
        return pending_runs

    def _execute_job_in_background(self, job_run_id: UUID, session_id: UUID) -> None:
        async def _execute(ctx):
            job_repo = JobRepository(ctx.db)
            job_repo.update_job_run_status(job_run_id, JobRunStatus.RUNNING)
            job_repo.commit()

            try:
                await asyncio.wait_for(
                    ctx.orchestrator.execute_pending_runs(session_id),
                    timeout=1800,
                )
            except asyncio.TimeoutError:
                error_msg = "Job timed out after 30 minutes"
                logger.error(
                    "job_execution_timeout",
                    job_run_id=str(job_run_id),
                    session_id=str(session_id),
                    error=error_msg,
                )
                try:
                    job_repo.update_job_run_status(
                        job_run_id, JobRunStatus.FAILED, error_message=error_msg
                    )
                    job_repo.commit()
                    ctx.session_repo.update_status(
                        session_id, SessionStatus.FAILED, error_message=error_msg
                    )
                    ctx.session_repo.commit()
                except Exception as db_err:
                    logger.error(
                        "job_status_update_failed_after_timeout",
                        session_id=str(session_id),
                        error=str(db_err),
                    )
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "job_execution_failed",
                    job_run_id=str(job_run_id),
                    session_id=str(session_id),
                    error=error_msg,
                )
                try:
                    job_repo.update_job_run_status(
                        job_run_id, JobRunStatus.FAILED, error_message=error_msg[:2000]
                    )
                    job_repo.commit()
                    ctx.session_repo.update_status(
                        session_id, SessionStatus.FAILED, error_message=error_msg[:2000]
                    )
                    ctx.session_repo.commit()
                except Exception as db_err:
                    logger.error(
                        "job_status_update_failed_after_failure",
                        session_id=str(session_id),
                        error=str(db_err),
                    )

            final_session = ctx.session_repo.get_by_id(session_id)
            if final_session and final_session.status in {
                SessionStatus.COMPLETED.value, SessionStatus.FAILED.value
            }:
                final_status = (
                    JobRunStatus.COMPLETED
                    if final_session.status == SessionStatus.COMPLETED.value
                    else JobRunStatus.FAILED
                )
                job_repo.update_job_run_status(
                    job_run_id, final_status, error_message=final_session.error_message
                )
                job_repo.commit()

        create_session_task(
            session_id,
            run_session_task(session_id, _execute, "job_execution"),
            name=f"job_execution-{session_id}",
            skip_lock=True,
        )

    def _should_run(self, definition: JobDefinitionDetail, now: datetime) -> tuple[bool, datetime | None]:
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
