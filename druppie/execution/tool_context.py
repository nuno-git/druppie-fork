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

import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

logger = structlog.get_logger()


SENSITIVE_PATHS = {"user.entra_token"}


class ToolContext:
    """Context for resolving injection paths.

    Lazily loads and caches database objects to resolve paths like
    session.id, project.repo_name, user.id.

    Usage:
        context = ToolContext(db, session_id)
        repo_name = context.resolve("project.repo_name")
        user_id = context.resolve("user.id")
    """

    def __init__(self, db: "DBSession", session_id: UUID | str | None, agent_run_id: UUID | str | None = None):
        """Initialize context with database session and session ID.

        Args:
            db: Database session for queries
            session_id: Session ID to resolve context from
            agent_run_id: Agent run ID for agent-level context resolution
        """
        self.db = db
        self._session_id = UUID(session_id) if isinstance(session_id, str) else session_id
        self._agent_run_id = UUID(agent_run_id) if isinstance(agent_run_id, str) else agent_run_id

        # Cache for loaded objects
        self._session = None
        self._project = None
        self._user = None
        self._agent_run = None
        self._agent = None
        self._loaded: dict[str, bool] = {}

        # Entra ID token (set via authorize-entra endpoint, never persisted)
        self._entra_token: str | None = None
        self._entra_token_exp: float | None = None

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

    @property
    def agent_run(self):
        if "agent_run" not in self._loaded:
            self._loaded["agent_run"] = True
            if self._agent_run_id:
                from druppie.db.models import AgentRun
                self._agent_run = (
                    self.db.query(AgentRun)
                    .filter(AgentRun.id == self._agent_run_id)
                    .first()
                )
        return self._agent_run

    @property
    def agent(self):
        if "agent" not in self._loaded:
            self._loaded["agent"] = True
            if self.agent_run and self.agent_run.agent_id:
                from druppie.agents.definition_loader import AgentDefinitionLoader
                loader = AgentDefinitionLoader()
                try:
                    self._agent = loader.load(self.agent_run.agent_id)
                except Exception:
                    self._agent = None
        return self._agent

    def set_entra_token(self, token: str) -> None:
        """Set the Entra ID access token (provided via /authorize-entra)."""
        self._entra_token = token
        try:
            import base64, json
            payload = token.split(".")[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            claims = json.loads(base64.urlsafe_b64decode(payload))
            self._entra_token_exp = claims.get("exp")
        except Exception:
            self._entra_token_exp = None

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
        - user.entra_token (in-memory only, set via authorize-entra)

        Args:
            path: Dotted path like "project.repo_name"

        Returns:
            Resolved value or None if not found
        """
        # Special case: user.entra_token is in-memory, not a DB attribute
        if path == "user.entra_token":
            if self._entra_token and self._entra_token_exp:
                if time.time() > self._entra_token_exp - 60:
                    logger.warning("entra_token_expired_in_context", expires_at=self._entra_token_exp)
                    return None
            elif self._entra_token and not self._entra_token_exp:
                logger.warning("entra_token_missing_exp", note="token returned without expiry validation")
            log_value = "<redacted>" if self._entra_token else None
            logger.info("context_resolved", path=path, value=log_value)
            return self._entra_token

        parts = path.split(".", 1)
        if len(parts) != 2:
            logger.warning("invalid_context_path", path=path)
            return None

        obj_name, attr_name = parts

        if obj_name == "agent" and attr_name == "git_scope":
            agent = self.agent
            if agent:
                mcps = getattr(agent, 'mcps', {})
                if isinstance(mcps, dict):
                    for _server_name, config in mcps.items():
                        if isinstance(config, dict) and "git" in config:
                            return config["git"]
            return None

        if obj_name == "agent" and attr_name == "coding_networks":
            agent = self.agent
            if agent:
                coding_config = getattr(agent, 'mcps', {}).get("coding")
                if isinstance(coding_config, dict):
                    networks = coding_config.get("networks", [])
                    if networks:
                        return networks
            return None

        obj = None
        if obj_name == "session":
            obj = self.session
        elif obj_name == "project":
            obj = self.project
        elif obj_name == "user":
            obj = self.user
        elif obj_name == "agent":
            obj = self.agent
        elif obj_name == "agent_run":
            obj = self.agent_run
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

        log_value = "<redacted>" if path in SENSITIVE_PATHS and value else value
        if isinstance(log_value, str) and len(log_value) > 50:
            log_value = log_value[:50]
        logger.info("context_resolved", path=path, value=log_value)
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
