"""Project domain models."""

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import TokenUsage


class DeploymentInfo(BaseModel):
    """Deployment status (from Docker MCP labels)."""
    status: str  # running, stopped
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
    status: str
    created_at: datetime


class ProjectDetail(BaseModel):
    """Full project with stats."""
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    repo_name: str | None
    repo_url: str | None
    status: str
    token_usage: TokenUsage
    session_count: int
    deployment: DeploymentInfo | None
    created_at: datetime
