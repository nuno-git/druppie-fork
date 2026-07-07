"""Branch environment database model.

A branch environment is a full, isolated Druppie stack deployed for a git
branch in its own Kubernetes namespace on the RKE2 cluster (what
``scripts/deploy-branch-env.sh`` does manually). Each environment is reachable
at ``druppie-<slug>.rijnland.dev`` and is tracked here for status, teardown,
and CI-driven upgrades.
"""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class BranchEnvironment(Base):
    """A per-branch Druppie stack deployed in its own namespace."""

    __tablename__ = "branch_environments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    branch = Column(String(255), nullable=False, unique=True)  # git branch, e.g. "feature/foo"
    slug = Column(String(63), nullable=False, unique=True)  # DNS-1123 label derived from branch
    namespace = Column(String(63), nullable=False, unique=True)  # druppie-<slug>
    url = Column(String(255), nullable=False)  # https://druppie-<slug>.rijnland.dev
    image_tag = Column(String(255), nullable=True)  # image tag deployed for all components
    status = Column(String(32), default="deploying")  # deploying, running, failed, deleting
    status_message = Column(String(1024), nullable=True)  # last error / progress message
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "branch": self.branch,
            "slug": self.slug,
            "namespace": self.namespace,
            "url": self.url,
            "image_tag": self.image_tag,
            "status": self.status,
            "status_message": self.status_message,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
