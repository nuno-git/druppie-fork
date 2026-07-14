"""Job repository for database access."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func

from ..db.models.job import JobDefinition, JobRun
from ..db.models.llm_call import LlmCall
from ..domain.common import JobRunStatus
from ..domain.job import (
    JobDefinitionDetail,
    JobDefinitionList,
    JobRunDetail,
    JobRunList,
    JobRunSummary,
    JobRunUsage,
)
from .base import BaseRepository


class JobRepository(BaseRepository):
    """Database access for scheduled jobs."""

    def create_definition(
        self,
        job_id: str,
        name: str,
        description: str | None,
        schedule: str,
        agent_id: str,
        prompt: str,
        approval_required: bool,
        required_role: str | None,
        enabled: bool,
        yaml_path: str | None,
    ) -> JobDefinition:
        definition = JobDefinition(
            job_id=job_id,
            name=name,
            description=description,
            schedule=schedule,
            agent_id=agent_id,
            prompt=prompt,
            approval_required=approval_required,
            required_role=required_role,
            enabled=enabled,
            yaml_path=yaml_path,
        )
        self.db.add(definition)
        self.db.flush()
        return definition

    def get_definition_by_job_id(self, job_id: str) -> JobDefinition | None:
        return self.db.query(JobDefinition).filter(JobDefinition.job_id == job_id).first()

    def update_definition_from_yaml(
        self, job_id: str, data: dict, yaml_path: str
    ) -> bool:
        """Update an existing definition from YAML data. Returns False if absent."""
        definition = self.get_definition_by_job_id(job_id)
        if not definition:
            return False
        definition.name = data.get("name", definition.name)
        definition.description = data.get("description", definition.description)
        definition.schedule = data.get("schedule", definition.schedule)
        definition.agent_id = data.get("agent_id", definition.agent_id)
        definition.prompt = data.get("prompt", definition.prompt)
        definition.approval_required = data.get("approval_required", definition.approval_required)
        definition.required_role = data.get("required_role", definition.required_role)
        definition.enabled = data.get("enabled", True) if data.get("enabled") is not None else definition.enabled
        definition.yaml_path = yaml_path
        return True

    def get_definition_by_id(self, definition_id: UUID) -> JobDefinition | None:
        return self.db.query(JobDefinition).filter(JobDefinition.id == definition_id).first()

    def list_definitions(self) -> JobDefinitionList:
        definitions = self.db.query(JobDefinition).order_by(JobDefinition.name).all()
        return JobDefinitionList(
            items=[self.to_definition_detail(d) for d in definitions],
            total=len(definitions),
        )

    def delete_definition_by_job_id(self, job_id: str) -> None:
        self.db.query(JobDefinition).filter(JobDefinition.job_id == job_id).delete(
            synchronize_session=False
        )

    def has_active_runs_for_definition(self, definition_id: UUID) -> bool:
        """Check if a job definition has any runs that are not terminal.

        Active statuses: pending, running, waiting_approval.
        """
        active_statuses = {
            JobRunStatus.PENDING.value,
            JobRunStatus.RUNNING.value,
            JobRunStatus.WAITING_APPROVAL.value,
        }
        return (
            self.db.query(JobRun)
            .filter(
                JobRun.job_definition_id == definition_id,
                JobRun.status.in_(active_statuses),
            )
            .first()
            is not None
        )

    def create_job_run(
        self,
        job_definition_id: UUID,
        session_id: UUID | None,
        trigger_type: str,
        status: str,
    ) -> JobRun:
        run = JobRun(
            job_definition_id=job_definition_id,
            session_id=session_id,
            trigger_type=trigger_type,
            status=status,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def get_job_run_by_id(self, run_id: UUID) -> JobRun | None:
        return self.db.query(JobRun).filter(JobRun.id == run_id).first()

    def get_job_run_by_agent_run_id(self, agent_run_id: UUID) -> JobRun | None:
        return self.db.query(JobRun).filter(JobRun.agent_run_id == agent_run_id).first()

    def update_job_run_status(
        self,
        run_id: UUID,
        status: str,
        error_message: str | None = None,
        logs: str | None = None,
    ) -> None:
        from ..db.models.base import utcnow
        updates = {"status": status}
        if error_message is not None:
            updates["error_message"] = error_message
        if logs is not None:
            updates["logs"] = logs
        if status == JobRunStatus.RUNNING.value:
            updates["started_at"] = utcnow()
        if status in {JobRunStatus.COMPLETED.value, JobRunStatus.FAILED.value, JobRunStatus.CANCELLED.value, JobRunStatus.REJECTED.value}:
            updates["completed_at"] = utcnow()
        self.db.query(JobRun).filter(JobRun.id == run_id).update(updates)

    def set_job_run_session(
        self,
        run_id: UUID,
        session_id: UUID,
        agent_run_id: UUID | None = None,
    ) -> None:
        updates = {"session_id": session_id}
        if agent_run_id:
            updates["agent_run_id"] = agent_run_id
        self.db.query(JobRun).filter(JobRun.id == run_id).update(updates)

    def set_job_run_approval_required(
        self,
        run_id: UUID,
        required_role: str,
    ) -> None:
        self.db.query(JobRun).filter(JobRun.id == run_id).update(
            {"required_role": required_role}
        )

    def set_job_run_approved(self, run_id: UUID, user_id: UUID) -> None:
        """Record who approved a run and when."""
        from ..db.models.base import utcnow
        self.db.query(JobRun).filter(JobRun.id == run_id).update(
            {"approved_by": user_id, "approved_at": utcnow()}
        )

    def get_system_user_id(self) -> UUID | None:
        """Lookup the 'admin' user to own sessions created by scheduled jobs."""
        from ..db.models.user import User
        admin = self.db.query(User).filter_by(username="admin").first()
        return admin.id if admin else None

    def get_pending_approval_runs(
        self, roles: list[str] | None = None
    ) -> list[JobRun]:
        query = self.db.query(JobRun).filter(
            JobRun.status == JobRunStatus.WAITING_APPROVAL.value
        )
        if roles is not None:
            query = query.filter(JobRun.required_role.in_(roles))
        return query.order_by(JobRun.created_at.desc()).all()

    def list_job_runs(
        self,
        job_definition_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> JobRunList:
        query = self.db.query(JobRun)
        if job_definition_id:
            query = query.filter(JobRun.job_definition_id == job_definition_id)
        if status:
            query = query.filter(JobRun.status == status)

        total = query.count()
        runs = (
            query
            .order_by(JobRun.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return JobRunList(
            items=[self.to_job_run_summary(r) for r in runs],
            total=total,
            page=page,
            limit=limit,
        )

    def mark_job_run_finalized_by_agent_run_id(
        self,
        agent_run_id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Mark a job_run as finalized by its linked agent_run_id.

        Used by the orchestrator to sync job_run status after an approval-gated
        job completes or fails, without querying JobRun directly.
        """
        updates = {"status": status}
        if error_message is not None:
            updates["error_message"] = error_message
        if status in {JobRunStatus.COMPLETED.value, JobRunStatus.FAILED.value, JobRunStatus.CANCELLED.value, JobRunStatus.REJECTED.value}:
            from ..db.models.base import utcnow
            updates["completed_at"] = utcnow()
        self.db.query(JobRun).filter(JobRun.agent_run_id == agent_run_id).update(updates)

    def get_stuck_runs(
        self,
        status: str,
        older_than: datetime,
    ) -> list[JobRun]:
        """Return runs that have been in a given status for longer than the cutoff."""
        return (
            self.db.query(JobRun)
            .filter(JobRun.status == status, JobRun.started_at < older_than)
            .all()
        )

    def claim_job_trigger(
        self,
        definition_id: UUID,
        last_scheduled: datetime,
        now: datetime,
    ) -> bool:
        """Atomically claim the right to trigger a scheduled job.

        Uses an UPDATE ... WHERE compare-and-swap so only one instance
        wins when multiple servers race for the same scheduled slot.
        Returns True if this caller won the claim.
        """
        from ..db.models.job import JobDefinition
        result = (
            self.db.query(JobDefinition)
            .filter(
                JobDefinition.id == definition_id,
                (JobDefinition.last_triggered_at.is_(None))
                | (JobDefinition.last_triggered_at < last_scheduled),
            )
            .update({"last_triggered_at": now})
        )
        return result == 1

    def touch_definition_trigger_time(self, definition_id: UUID) -> None:
        """Update last_triggered_at to now (for manual or post-approval triggers)."""
        from ..db.models.base import utcnow
        self.db.query(JobDefinition).filter(
            JobDefinition.id == definition_id
        ).update({"last_triggered_at": utcnow()})

    def to_definition_detail(self, definition: JobDefinition) -> JobDefinitionDetail:
        return JobDefinitionDetail(
            id=definition.id,
            job_id=definition.job_id,
            name=definition.name,
            description=definition.description,
            schedule=definition.schedule,
            agent_id=definition.agent_id,
            approval_required=definition.approval_required or False,
            required_role=definition.required_role,
            prompt=definition.prompt,
            enabled=definition.enabled if definition.enabled is not None else True,
            yaml_path=definition.yaml_path,
            last_triggered_at=definition.last_triggered_at,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
        )

    def to_job_run_summary(self, run: JobRun) -> JobRunSummary:
        return JobRunSummary(
            id=run.id,
            job_definition_id=run.job_definition_id,
            session_id=run.session_id,
            agent_run_id=run.agent_run_id,
            trigger_type=run.trigger_type,
            status=run.status,
            error_message=run.error_message,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            required_role=run.required_role,
            approved_by=run.approved_by,
            approved_at=run.approved_at,
            rejection_reason=run.rejection_reason,
        )

    def get_job_run_usage(self, session_id: UUID | None) -> JobRunUsage | None:
        """Aggregate the LLM usage of a run's session (cost per run)."""
        if not session_id:
            return None
        row = (
            self.db.query(
                func.count(LlmCall.id),
                func.coalesce(func.sum(LlmCall.prompt_tokens), 0),
                func.coalesce(func.sum(LlmCall.completion_tokens), 0),
                func.coalesce(func.sum(LlmCall.total_tokens), 0),
                func.coalesce(func.sum(LlmCall.duration_ms), 0),
                func.coalesce(
                    func.sum(case((LlmCall.fallback_used.is_(True), 1), else_=0)), 0
                ),
            )
            .filter(LlmCall.session_id == session_id)
            .one()
        )
        if not row[0]:
            return None
        models = [
            f"{provider}/{model}"
            for provider, model in self.db.query(LlmCall.provider, LlmCall.model)
            .filter(LlmCall.session_id == session_id)
            .distinct()
        ]
        return JobRunUsage(
            llm_calls=row[0],
            prompt_tokens=row[1],
            completion_tokens=row[2],
            total_tokens=row[3],
            duration_ms=row[4],
            fallback_calls=row[5],
            models=models,
        )

    def to_job_run_detail(self, run: JobRun) -> JobRunDetail:
        return JobRunDetail(
            usage=self.get_job_run_usage(run.session_id),
            id=run.id,
            job_definition_id=run.job_definition_id,
            session_id=run.session_id,
            agent_run_id=run.agent_run_id,
            trigger_type=run.trigger_type,
            status=run.status,
            error_message=run.error_message,
            logs=run.logs,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            required_role=run.required_role,
            approved_by=run.approved_by,
            approved_at=run.approved_at,
            rejection_reason=run.rejection_reason,
        )
