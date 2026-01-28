"""Workspace Service.

TODO: This service needs to be refactored to:
1. Move workspace management to Coding MCP
2. Remove Workspace database model dependency
3. Workspace lifecycle is managed by Coding MCP (clone, register_workspace)

The Coding MCP already has:
- register_workspace: Register a workspace path
- clone_repo: Clone git repos
- list_dir: List files
- read_file/write_file: File operations
- commit_and_push: Git operations

Current status: Stubbed out - all methods raise NotImplementedError
"""

import os
from pathlib import Path

import structlog
from sqlalchemy.orm import Session as DBSession

from druppie.core.gitea import GiteaClient, get_gitea_client
from druppie.db.models import Project

logger = structlog.get_logger()

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")


class WorkspaceService:
    """Manages git workspaces for sessions.

    TODO: Reimplement to use Coding MCP instead.
    The Coding MCP manages workspace lifecycle:
    - Cloning repos
    - Managing workspace paths
    - File operations
    - Git commit/push
    """

    def __init__(self, db: DBSession, gitea: GiteaClient | None = None):
        self.db = db
        self.gitea = gitea or get_gitea_client()
        self.workspace_root = WORKSPACE_ROOT
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    async def initialize_workspace(
        self,
        session_id: str,
        project_id: str | None,
        user_id: str | None,
        project_name: str | None = None,
    ):
        """Initialize workspace at conversation start.

        TODO: Call Coding MCP register_workspace/clone_repo instead.
        """
        raise NotImplementedError(
            "WorkspaceService needs refactoring - use Coding MCP directly"
        )

    async def commit_and_push(self, workspace_id: str, message: str) -> bool:
        """Stage all changes, commit, and push.

        TODO: Call Coding MCP commit_and_push tool instead.
        """
        raise NotImplementedError(
            "WorkspaceService needs refactoring - use Coding MCP directly"
        )

    async def merge_to_main(self, workspace_id: str) -> bool:
        """Merge current branch to main.

        TODO: Call Gitea API via Coding MCP.
        """
        raise NotImplementedError(
            "WorkspaceService needs refactoring - use Coding MCP directly"
        )

    def get_workspace_path(self, session_id: str) -> Path | None:
        """Get workspace path for a session.

        Uses convention: WORKSPACE_ROOT / session_id
        """
        path = self.workspace_root / session_id
        return path if path.exists() else None


def get_workspace_service(db: DBSession) -> WorkspaceService:
    """Get a WorkspaceService instance."""
    return WorkspaceService(db)
