"""Job domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ..domain.common import JobRunStatus


class JobDefinitionSummary(BaseModel):
    """Lightweight job definition for lists."""
    id: UUID
    job_id: str
    name: str
    description: str | None = None
    schedule: str
    agent_id: str
    approval_required: bool
    required_role: str | None = None
    enabled: bool
    last_triggered_at: datetime | None = None
    created_at: datetime


class JobDefinitionDetail(JobDefinitionSummary):
    """Full job definition. Inherits from JobDefinitionSummary."""
    prompt: str
    config: dict | None = None
    yaml_path: str | None = None
    updated_at: datetime | None = None


class JobRunSummary(BaseModel):
    """Lightweight job run for lists."""
    id: UUID
    job_definition_id: UUID
    session_id: UUID | None = None
    agent_run_id: UUID | None = None
    trigger_type: str
    status: JobRunStatus
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    required_role: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None


class JobRunDetail(JobRunSummary):
    """Full job run with logs. Inherits from JobRunSummary."""
    logs: str | None = None


class JobRunList(BaseModel):
    """Paginated list of job runs."""
    items: list[JobRunSummary]
    total: int
    page: int
    limit: int


class JobDefinitionList(BaseModel):
    """List of job definitions."""
    items: list[JobDefinitionDetail]
    total: int
