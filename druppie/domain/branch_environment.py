"""Branch environment domain models.

Naming convention (matches the rest of the codebase):
- BranchEnvironmentSummary: lightweight, for list views
- BranchEnvironmentDetail: full data, for single-item views (inherits Summary)
- BranchEnvironmentCreate: request body for deploying a branch environment
- BranchEnvironmentListResponse: list wrapper
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class BranchEnvironmentStatus(str, Enum):
    """Lifecycle status of a branch environment."""

    DEPLOYING = "deploying"
    RUNNING = "running"
    FAILED = "failed"
    DELETING = "deleting"


class BranchEnvironmentSummary(BaseModel):
    """Lightweight branch environment for lists and embedding."""

    id: UUID
    branch: str
    slug: str
    namespace: str
    url: str
    image_tag: str | None = None
    status: BranchEnvironmentStatus
    status_message: str | None = None
    created_at: datetime


class BranchEnvironmentDetail(BranchEnvironmentSummary):
    """Full branch environment. Inherits from BranchEnvironmentSummary."""

    owner_id: UUID
    updated_at: datetime | None = None


class BranchEnvironmentCreate(BaseModel):
    """Request body for deploying a new branch environment."""

    branch: str
    image_tag: str | None = None


class BranchEnvironmentListResponse(BaseModel):
    """Branch environment list response."""

    items: list[BranchEnvironmentSummary]
    total: int
