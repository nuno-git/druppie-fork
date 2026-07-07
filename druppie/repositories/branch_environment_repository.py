"""Branch environment repository for database access.

Mirrors the dev_vm_repository.py pattern: extends BaseRepository, returns
domain models via private ``_to_summary`` / ``_to_detail`` mappers, and uses
the inherited ``self.db`` session.
"""

from uuid import UUID

from ..db.models import BranchEnvironment
from ..domain import BranchEnvironmentDetail, BranchEnvironmentSummary
from .base import BaseRepository


class BranchEnvironmentRepository(BaseRepository):
    """Database access for branch environments."""

    def get_by_id(self, env_id: UUID) -> BranchEnvironment | None:
        """Get raw branch environment model."""
        return self.db.query(BranchEnvironment).filter_by(id=env_id).first()

    def get_by_branch(self, branch: str) -> BranchEnvironment | None:
        """Get raw branch environment model by git branch."""
        return self.db.query(BranchEnvironment).filter_by(branch=branch).first()

    def create(
        self,
        branch: str,
        slug: str,
        namespace: str,
        url: str,
        owner_id: UUID,
        image_tag: str | None = None,
        status: str = "deploying",
    ) -> BranchEnvironment:
        """Create a new branch environment record."""
        env = BranchEnvironment(
            branch=branch,
            slug=slug,
            namespace=namespace,
            url=url,
            owner_id=owner_id,
            image_tag=image_tag,
            status=status,
        )
        self.db.add(env)
        self.db.flush()
        return env

    def update(self, env_id: UUID, **fields: object) -> None:
        """Update branch environment fields by id."""
        if not fields:
            return
        self.db.query(BranchEnvironment).filter_by(id=env_id).update(fields)

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[BranchEnvironmentSummary], int]:
        """List all branch environments."""
        query = self.db.query(BranchEnvironment)
        total = query.count()
        envs = (
            query.order_by(BranchEnvironment.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(env) for env in envs], total

    def get_detail(self, env_id: UUID) -> BranchEnvironmentDetail | None:
        """Get full branch environment detail."""
        env = self.get_by_id(env_id)
        if not env:
            return None
        return self._to_detail(env)

    def delete(self, env_id: UUID) -> None:
        """Delete branch environment record."""
        self.db.query(BranchEnvironment).filter_by(id=env_id).delete()

    def _to_summary(self, env: BranchEnvironment) -> BranchEnvironmentSummary:
        """Convert branch environment model to summary domain object."""
        return BranchEnvironmentSummary(
            id=env.id,
            branch=env.branch,
            slug=env.slug,
            namespace=env.namespace,
            url=env.url,
            image_tag=env.image_tag,
            status=env.status,
            status_message=env.status_message,
            created_at=env.created_at,
        )

    def _to_detail(self, env: BranchEnvironment) -> BranchEnvironmentDetail:
        """Convert branch environment model to detail domain object."""
        return BranchEnvironmentDetail(
            id=env.id,
            branch=env.branch,
            slug=env.slug,
            namespace=env.namespace,
            url=env.url,
            image_tag=env.image_tag,
            status=env.status,
            status_message=env.status_message,
            created_at=env.created_at,
            owner_id=env.owner_id,
            updated_at=env.updated_at,
        )
