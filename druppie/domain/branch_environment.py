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

from pydantic import BaseModel


class BranchEnvironmentStatus(str, Enum):
    """Lifecycle status of a branch environment."""

    DEPLOYING = "deploying"
    RUNNING = "running"
    FAILED = "failed"
    DELETING = "deleting"


class PipelineStageStatus(str, Enum):
    """Status of a single stage in the deploy pipeline."""

    PENDING = "pending"
    BUSY = "busy"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage(BaseModel):
    """One node in the deploy pipeline visual.

    ``id`` is a stable machine key (commit/flux/source/secrets/helm/workloads/
    live for deploys; commit-removed/pruning for teardowns); ``name`` is the
    human label shown under the node.
    """

    id: str
    name: str
    status: PipelineStageStatus
    # Error/context message; shown in the failure callout under the pipeline.
    message: str | None = None
    # Short progress hint for busy stages, e.g. "7/12 deployments ready".
    detail: str | None = None


class BranchEnvironmentPipeline(BaseModel):
    """Live deploy pipeline for one branch environment (derived, not stored)."""

    env_id: str
    status: BranchEnvironmentStatus
    stages: list[PipelineStage]


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
    # Recovery mode: workspace + Keycloak only, no gitea/druppie-db/modules.
    recovery_mode: bool = False
    # When False, CI/CD will skip updating the image tag on push — the
    # environment stays on its current image until manually redeployed.
    auto_deploy_enabled: bool = True


class BranchEnvironmentDetail(BranchEnvironmentSummary):
    """Full branch environment. Inherits from BranchEnvironmentSummary."""

    # None when the owner annotation is missing/unreadable (then admin-only).
    owner_id: UUID | None = None
    updated_at: datetime | None = None


class BranchEnvironmentCreate(BaseModel):
    """Request body for deploying a new branch environment."""

    branch: str
    image_tag: str | None = None
    # Vault path prefix for env secrets. "colab-dev" → druppie/colab-dev/*,
    # any other value maps to druppie/developers/<value>/* (e.g. "robbe" →
    # druppie/developers/robbe/*). Default borrows the colab-dev LLM keys.
    secrets_source: str = "colab-dev"
    # Recovery mode: workspace + Keycloak only, no gitea/druppie-db/modules.
    recovery_mode: bool = False
    # When False, CI/CD skips the auto-upgrade on push.
    auto_deploy_enabled: bool = True


class PullRequestInfo(BaseModel):
    """Merge-back pull request status for a branch environment.

    Describes the PR that merges the env's feature branch into the base branch
    it was created from (``BRANCH_ENV_APP_BASE_BRANCH``, default colab-dev).
    ``exists`` is False when no such PR is open/closed yet — the head/base
    branch names are still filled in so the UI can label the "open PR" action.
    """

    exists: bool = False
    number: int | None = None
    url: str | None = None
    title: str | None = None
    # Gitea PR state: "open" or "closed" (a merged PR is closed + merged=True).
    state: str | None = None
    merged: bool = False
    # Gitea's computed mergeability; None while it is still being calculated.
    mergeable: bool | None = None
    head_branch: str | None = None
    base_branch: str | None = None
    created_at: datetime | None = None


class BranchEnvironmentListResponse(BaseModel):
    """Branch environment list response."""

    items: list[BranchEnvironmentSummary]
    total: int
