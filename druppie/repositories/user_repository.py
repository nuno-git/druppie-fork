"""User repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..db.models import User, UserRole

# Druppie application roles defined in Keycloak (iac/realm.yaml, iac/users.yaml).
# Realm-level built-ins such as offline_access / uma_authorization /
# default-roles-druppie are excluded so the user_roles table only carries the
# app roles that role-targeted features (HITL notifications, approvals) match on.
APP_ROLES = frozenset({
    "admin",
    "developer",
    "architect",
    "business_analyst",
    "infra-engineer",
    "product-owner",
    "compliance-officer",
    "viewer",
    "user",
})


class UserRepository(BaseRepository):
    """Database access for users."""

    def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return self.db.query(User).filter_by(id=user_id).first()

    def get_by_role(self, role: str) -> list[User]:
        """Return all users that have ``role``."""
        return (
            self.db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .filter(UserRole.role == role)
            .all()
        )

    def sync_roles(self, user_id: UUID, roles: list[str]) -> None:
        """Reconcile a user's app-role set to match ``roles``.

        Only APP_ROLES are considered; Keycloak built-ins are ignored. Adds
        missing roles and removes stale ones so the table reflects the token.
        """
        target = {r for r in roles if r in APP_ROLES}
        existing = {
            r.role
            for r in self.db.query(UserRole).filter(UserRole.user_id == user_id).all()
        }
        for role in target - existing:
            self.db.add(UserRole(user_id=user_id, role=role))
        for role in existing - target:
            self.db.query(UserRole).filter(
                UserRole.user_id == user_id, UserRole.role == role
            ).delete(synchronize_session=False)
        self.db.flush()


    def get_or_create(
        self,
        user_id: UUID,
        username: str,
        email: str | None = None,
        display_name: str | None = None,
        roles: list[str] | None = None,
    ) -> User:
        """Get or create a user (for Keycloak sync).

        Args:
            user_id: Keycloak user ID (UUID)
            username: Username
            email: Email address
            display_name: Display name
            roles: List of role names

        Returns:
            User model
        """
        user = self.get_by_id(user_id)
        if not user and username:
            # User might exist with a different ID — lookup by username
            user = self.db.query(User).filter_by(username=username).first()

        if user:
            if user.id != user_id:
                user.id = user_id
            if username and user.username != username:
                user.username = username
            if email and user.email != email:
                user.email = email
            if display_name and user.display_name != display_name:
                user.display_name = display_name
            self.db.flush()
            return user

        # Create new user
        user = User(
            id=user_id,
            username=username,
            email=email,
            display_name=display_name,
        )
        self.db.add(user)
        self.db.flush()

        # Add roles
        if roles:
            for role_name in roles:
                role = UserRole(user_id=user_id, role=role_name)
                self.db.add(role)
            self.db.flush()

        return user
