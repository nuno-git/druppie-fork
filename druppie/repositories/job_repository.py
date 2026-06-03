"""Job repository for database access."""

from datetime import datetime
from uuid import UUID

from .base import BaseRepository
from ..domain.job import (
    JobDefinitionDetail,
    JobDefinitionList,
    JobRunDetail,
    JobRunList,
    JobRunSummary,
)
from ..db.models.job import JobDefinition, JobDefinitionConfig, JobRun
from ..domain.common import JobRunStatus


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
        config: dict | None,
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
        if config:
            for key, value in config.items():
                self.db.add(
                    JobDefinitionConfig(
                        job_definition_id=definition.id,
                        config_key=key,
                        config_value=str(value) if value is not None else None,
                    )
                )
        return definition

    def get_definition_by_job_id(self, job_id: str) -> JobDefinition | None:
        return self.db.query(JobDefinition).filter(JobDefinition.job_id == job_id).first()

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
        updates = {"status": status}
        if error_message is not None:
            updates["error_message"] = error_message
        if logs is not None:
            updates["logs"] = logs
        if status in {JobRunStatus.COMPLETED.value, JobRunStatus.FAILED.value, JobRunStatus.CANCELLED.value, JobRunStatus.REJECTED.value}:
            from ..db.models.base import utcnow
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
                (JobDefinition.last_triggered_at == None)
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
            config={
                cfg.config_key: cfg.config_value
                for cfg in (definition.configs or [])
            } or None,
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
        )

    def to_job_run_detail(self, run: JobRun) -> JobRunDetail:
        return JobRunDetail(
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
        )
