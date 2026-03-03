"""Sandbox session repository for ownership lookups."""

from uuid import UUID

from .base import BaseRepository
from ..db.models import SandboxSession


class SandboxSessionRepository(BaseRepository):
    """Database access for sandbox session ownership mappings."""

    def create(
        self,
        sandbox_session_id: str,
        user_id: UUID,
        session_id: UUID | None = None,
        git_proxy_key: str | None = None,
        git_provider: str | None = None,
        git_repo_owner: str | None = None,
        git_repo_name: str | None = None,
        webhook_secret: str | None = None,
    ) -> SandboxSession:
        """Register a sandbox session ownership mapping.

        Idempotent: returns existing record if sandbox_session_id already registered.
        """
        existing = self.get_by_sandbox_id(sandbox_session_id)
        if existing:
            return existing

        mapping = SandboxSession(
            sandbox_session_id=sandbox_session_id,
            user_id=user_id,
            session_id=session_id,
            git_proxy_key=git_proxy_key,
            git_provider=git_provider,
            git_repo_owner=git_repo_owner,
            git_repo_name=git_repo_name,
            webhook_secret=webhook_secret,
        )
        self.db.add(mapping)
        self.db.flush()
        return mapping

    def get_by_sandbox_id(self, sandbox_session_id: str) -> SandboxSession | None:
        """Look up ownership by sandbox control plane session ID."""
        return (
            self.db.query(SandboxSession)
            .filter_by(sandbox_session_id=sandbox_session_id)
            .first()
        )

    def get_by_proxy_key(self, proxy_key: str) -> SandboxSession | None:
        """Look up a sandbox session by its git proxy key."""
        return (
            self.db.query(SandboxSession)
            .filter_by(git_proxy_key=proxy_key)
            .first()
        )

    def get_webhook_secret(self, sandbox_session_id: str) -> str | None:
        """Return the per-session webhook secret, or None if not found."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session:
            return session.webhook_secret
        return None

    def update_tool_call_id(self, sandbox_session_id: str, tool_call_id: UUID) -> None:
        """Link a sandbox session to its tool call for direct lookup."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session:
            session.tool_call_id = tool_call_id
            self.db.flush()

    def invalidate_proxy_key(self, sandbox_session_id: str) -> None:
        """Clear the git proxy key so the proxy URL stops working."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session and session.git_proxy_key:
            session.git_proxy_key = None
            self.db.flush()
