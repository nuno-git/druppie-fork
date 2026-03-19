"""Domain models for ATK Copilot agents."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class AtkAgentStatus(str, Enum):
    """Status of an ATK agent."""

    SCAFFOLDED = "scaffolded"
    PROVISIONED = "provisioned"
    DEPLOYED = "deployed"
    SHARED = "shared"
    UNINSTALLED = "uninstalled"
    FAILED = "failed"


class AtkShareInfo(BaseModel):
    """Share record for an ATK agent."""

    id: UUID
    email: str
    scope: str
    shared_at: datetime


class AtkDeploymentLogEntry(BaseModel):
    """Audit log entry for ATK agent actions."""

    id: UUID
    action: str
    environment: str | None
    status: str
    details: str | None
    performed_by: UUID
    performed_at: datetime


class AtkAgentSummary(BaseModel):
    """Lightweight ATK agent for list views."""

    id: UUID
    name: str
    description: str | None
    environment: str
    status: AtkAgentStatus
    project_id: UUID | None
    created_at: datetime


class AtkAgentDetail(AtkAgentSummary):
    """Full ATK agent detail with shares and deployment history."""

    m365_app_id: str | None
    created_by: UUID
    updated_at: datetime | None
    shares: list[AtkShareInfo]
    deployment_logs: list[AtkDeploymentLogEntry]
