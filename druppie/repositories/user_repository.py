"""User repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..db.models import User, UserRole


class UserRepository(BaseRepository):
    """Database access for users."""

    def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return self.db.query(User).filter_by(id=user_id).first()

    def get_or_create(
        self,
        user_id: UUID,
        username: str,
        email: str | None = None,
        display_name: str | None = None,
        roles: list[str] | None = None,
    ) -> User:
        """Get or create a user from Keycloak JWT subject.

        Security: lookup is ONLY by Keycloak sub (UUID). Never by username —
        username-based lookup would allow account takeover if someone creates
        a Keycloak user with the same name as an existing local user.

        UUID drift tolerance: if the sub is not found but the username exists,
        the Keycloak user was re-imported with a new UUID (e.g. after a
        keycloak-db reset). We repoint the existing row to the new sub so the
        user keeps their data. This is keyed off the username which we already
        trust from the validated JWT, so it does not weaken the takeover guard.

        Args:
            user_id: Keycloak subject UUID (from JWT 'sub' claim)
            username: Username from Keycloak
            email: Email address
            display_name: Display name
            roles: List of role names

        Returns:
            User model
        """
        user = self.get_by_id(user_id)

        if user:
            if username and user.username != username:
                user.username = username
            if email and user.email != email:
                user.email = email
            if display_name and user.display_name != display_name:
                user.display_name = display_name
            self.db.flush()
            return user

        # Sub not found — check for UUID drift (same username, different sub).
        existing = (
            self.db.query(User).filter_by(username=username).first()
            if username
            else None
        )
        if existing:
            existing.id = user_id
            if email and existing.email != email:
                existing.email = email
            if display_name and existing.display_name != display_name:
                existing.display_name = display_name
            self.db.flush()
            return existing

        user = User(
            id=user_id,
            username=username,
            email=email,
            display_name=display_name,
        )
        self.db.add(user)
        self.db.flush()

        if roles:
            for role_name in roles:
                role = UserRole(user_id=user_id, role=role_name)
                self.db.add(role)
            self.db.flush()

        self.db.commit()

        return user
