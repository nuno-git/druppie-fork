"""User repository for database access."""

import logging
from uuid import UUID

from .base import BaseRepository
from ..db.models import User, UserRole

logger = logging.getLogger(__name__)


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
        """Get or create a user (for Keycloak sync).

        Looks up by Keycloak subject UUID first, then by username as fallback.
        Never mutates the primary key — existing user identity is authoritative.

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
            user = self.db.query(User).filter_by(username=username).first()

        if user:
            if user.id != user_id:
                logger.warning(
                    "user_id_mismatch_existing_user",
                    db_id=str(user.id),
                    keycloak_sub=str(user_id),
                    username=username,
                )
            if username and user.username != username:
                user.username = username
            if email and user.email != email:
                user.email = email
            if display_name and user.display_name != display_name:
                user.display_name = display_name
            self.db.flush()
            return user

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

        return user
