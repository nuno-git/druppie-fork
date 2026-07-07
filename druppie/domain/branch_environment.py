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
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class BranchEnvironmentStatus(str, Enum):
    """Lifecycle status of a branch environment."""

    DEPLOYING = "deploying"
    RUNNING = "running"
    FAILED = "failed"
    DELETING = "deleting"


class BranchEnvironmentSummary(BaseModel):
    """Lightweight branch environment for lists and embedding.

    ``id`` is the environment slug (the environment's directory in the GitOps
    repo is the source of truth; there is no database row).
    """

    id: str
    branch: str
    slug: str
    namespace: str
    url: str
    image_tag: str | None = None
    status: BranchEnvironmentStatus
    status_message: str | None = None
    created_at: datetime
    # Where the env's Vault-sourced app secrets come from: "colab-dev" (borrowed
    # defaults) or "developer" (the deployer's own druppie/developers/<user> map).
    secrets_source: str | None = None
    # Optional per-env dev workspace (code-server behind a Keycloak oauth2-proxy).
    workspace_enabled: bool = False
    workspace_url: str | None = None
    workspace_status: str | None = None


class BranchEnvironmentDetail(BranchEnvironmentSummary):
    """Full branch environment. Inherits from BranchEnvironmentSummary."""

    # None when the owner annotation is missing/unreadable (then admin-only).
    owner_id: UUID | None = None
    updated_at: datetime | None = None


class BranchEnvironmentCreate(BaseModel):
    """Request body for deploying a new branch environment."""

    branch: str
    image_tag: str | None = None
    # "developer" syncs the deployer's own Vault map (druppie/developers/<user>,
    # self-service via the Vault UI); default borrows the colab-dev LLM keys.
    secrets_source: Literal["colab-dev", "developer"] = "colab-dev"


class BranchEnvironmentListResponse(BaseModel):
    """Branch environment list response."""

    items: list[BranchEnvironmentSummary]
    total: int
