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
    """Deployment status (from Docker MCP labels)."""
    status: DeploymentStatus
    container_name: str
    app_url: str | None
    host_port: int | None
    started_at: datetime | None


class ProjectSummary(BaseModel):
    """Lightweight project for lists and embedding."""
    id: UUID
    name: str
    description: str | None
    repo_url: str | None
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
