"""Project domain models."""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import TYPE_CHECKING

from .common import TokenUsage, DeploymentStatus

if TYPE_CHECKING:
    from .session import SessionSummary


class DeploymentInfo(BaseModel):
    """Deployment status (embedded in ProjectDetail)."""
    status: DeploymentStatus
    container_name: str
    app_url: str | None
    host_port: int | None
    started_at: datetime | None


class DeploymentSummary(BaseModel):
    """Deployment summary for list views (includes project info)."""
    id: UUID
    project_id: UUID
    project_name: str
    container_name: str | None
    host_port: int | None
    app_url: str | None
    status: str
    started_at: datetime | None


class ProjectSummary(BaseModel):
    """Lightweight project for lists and embedding."""
    id: UUID
    name: str
    description: str | None
    repo_url: str | None
    username: str | None = None
    created_at: datetime


class ProjectDetail(ProjectSummary):
    """Full project with stats. Inherits from ProjectSummary."""
    owner_id: UUID
    repo_name: str | None
    token_usage: TokenUsage
    session_count: int
    deployment: DeploymentInfo | None
    # Recent sessions linked to this project
    sessions: list["SessionSummary"] = []
