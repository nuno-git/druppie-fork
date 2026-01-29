"""User repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..db.models import User, UserRole


class UserRepository(BaseRepository):
    """Database access for users."""

    def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return self.db.query(User).filter_by(id=user_id).first()

    def get_by_username(self, username: str) -> User | None:
        """Get user by username."""
        return self.db.query(User).filter_by(username=username).first()

    def get_or_create(
        self,
        user_id: UUID,
        username: str,
        email: str | None = None,
        display_name: str | None = None,
        roles: list[str] | None = None,
    ) -> User:
        """Get or create a user (for Keycloak sync).

        Handles the case where a user exists with the same username but
        different ID (e.g., from manual DB seeding). In that case, updates
        the existing user's ID to match Keycloak's UUID.

        Args:
            user_id: Keycloak user ID (UUID)
            username: Username
            email: Email address
            display_name: Display name
            roles: List of role names

        Returns:
            User model
        """
        # First, try to find by Keycloak UUID
        user = self.get_by_id(user_id)
        if user:
            # Update fields if changed
            if username and user.username != username:
                user.username = username
            if email and user.email != email:
                user.email = email
            if display_name and user.display_name != display_name:
                user.display_name = display_name
            self.db.flush()
            return user

        # Not found by ID - check if username exists with different ID
        # This handles the case where users were seeded with wrong UUIDs
        existing_by_username = self.get_by_username(username) if username else None
        if existing_by_username:
            # User exists with different ID - update to Keycloak's UUID
            # This requires updating the primary key, which SQLAlchemy handles
            old_id = existing_by_username.id
            existing_by_username.id = user_id
            if email and existing_by_username.email != email:
                existing_by_username.email = email
            if display_name and existing_by_username.display_name != display_name:
                existing_by_username.display_name = display_name
            # Update any related user_roles
            self.db.query(UserRole).filter_by(user_id=old_id).update({"user_id": user_id})
            self.db.flush()
            return existing_by_username

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
