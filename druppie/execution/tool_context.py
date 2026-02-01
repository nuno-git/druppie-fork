"""Tool Context - resolves context paths for argument injection.

This module provides the ToolContext class that resolves paths like:
- session.id
- session.branch_name
- project.repo_name
- project.repo_owner
- user.id

Used by the declarative injection system to inject values from the database
into tool arguments at execution time.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

logger = structlog.get_logger()


class ToolContext:
    """Context for resolving injection paths.

    Lazily loads and caches database objects to resolve paths like
    session.id, project.repo_name, user.id.

    Usage:
        context = ToolContext(db, session_id)
        repo_name = context.resolve("project.repo_name")
        user_id = context.resolve("user.id")
    """

    def __init__(self, db: "DBSession", session_id: UUID | str | None):
        """Initialize context with database session and session ID.

        Args:
            db: Database session for queries
            session_id: Session ID to resolve context from
        """
        self.db = db
        self._session_id = UUID(session_id) if isinstance(session_id, str) else session_id

        # Cache for loaded objects
        self._session = None
        self._project = None
        self._user = None
        self._loaded: dict[str, bool] = {}

    @property
    def session(self):
        """Lazy load session from database."""
        if "session" not in self._loaded:
            self._loaded["session"] = True
            if self._session_id:
                from druppie.db.models import Session
                self._session = (
                    self.db.query(Session)
                    .filter(Session.id == self._session_id)
                    .first()
                )
        return self._session

    @property
    def project(self):
        """Lazy load project from session."""
        if "project" not in self._loaded:
            self._loaded["project"] = True
            if self.session and self.session.project_id:
                from druppie.db.models import Project
                self._project = (
                    self.db.query(Project)
                    .filter(Project.id == self.session.project_id)
                    .first()
                )
        return self._project

    @property
    def user(self):
        """Lazy load user from session."""
        if "user" not in self._loaded:
            self._loaded["user"] = True
            if self.session and self.session.user_id:
                from druppie.db.models import User
                self._user = (
                    self.db.query(User)
                    .filter(User.id == self.session.user_id)
                    .first()
                )
        return self._user

    def resolve(self, path: str) -> Any:
        """Resolve a dotted path to a value.

        Supported paths:
        - session.id
        - session.user_id
        - session.project_id
        - session.branch_name
        - project.id
        - project.repo_name
        - project.repo_owner
        - project.name
        - user.id
        - user.username

        Args:
            path: Dotted path like "project.repo_name"

        Returns:
            Resolved value or None if not found
        """
        parts = path.split(".", 1)
        if len(parts) != 2:
            logger.warning("invalid_context_path", path=path)
            return None

        obj_name, attr_name = parts

        # Get the object
        obj = None
        if obj_name == "session":
            obj = self.session
        elif obj_name == "project":
            obj = self.project
        elif obj_name == "user":
            obj = self.user
        else:
            logger.warning("unknown_context_object", object=obj_name, path=path)
            return None

        if obj is None:
            logger.warning("context_object_not_found", object=obj_name, path=path)
            return None

        # Get the attribute
        value = getattr(obj, attr_name, None)

        # Convert UUIDs to strings
        if isinstance(value, UUID):
            value = str(value)

        logger.info(
            "context_resolved",
            path=path,
            value=value[:50] if isinstance(value, str) and len(value) > 50 else value,
        )
        return value

    def resolve_all(self, paths: dict[str, str]) -> dict[str, Any]:
        """Resolve multiple paths at once.

        Args:
            paths: Map of parameter name to context path
                   e.g., {"repo_name": "project.repo_name"}

        Returns:
            Map of parameter name to resolved value (only non-None values)
        """
        result = {}
        for param_name, path in paths.items():
            value = self.resolve(path)
            if value is not None:
                result[param_name] = value
        return result
