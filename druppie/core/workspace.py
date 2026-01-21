"""Workspace Service.

Manages git workspaces for sessions. This is the core of the git-first architecture.

Flow:
    1. Session starts -> initialize_workspace()
    2. If project_id: Clone existing repo (feature branch for updates)
    3. If no project_id: Create new project + repo on main branch
    4. Agent writes files via Coding MCP
    5. WorkspaceService auto-commits and pushes changes
"""

import asyncio
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.orm import Session as DBSession

from druppie.core.gitea import GiteaClient, get_gitea_client
from druppie.db.models import Project, Workspace

if TYPE_CHECKING:
    from druppie.db.models import Session

logger = structlog.get_logger()

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")


def sanitize_repo_name(name: str) -> str:
    """Convert a project name to a valid git repository name."""
    # Convert to lowercase, replace spaces with dashes
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name or "project"


class WorkspaceService:
    """Manages git workspaces for sessions."""

    def __init__(self, db: DBSession, gitea: GiteaClient | None = None):
        self.db = db
        self.gitea = gitea or get_gitea_client()
        self.workspace_root = WORKSPACE_ROOT

        # Ensure workspace root exists
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    async def initialize_workspace(
        self,
        session_id: str,
        project_id: str | None,
        user_id: str | None,
        project_name: str | None = None,
    ) -> Workspace:
        """Initialize workspace at conversation start.

        - If project_id: Clone existing repo (feature branch for subsequent updates)
        - If no project_id and project_name: Create new project + repo on main branch

        Args:
            session_id: The session/conversation ID
            project_id: Optional existing project ID to work on
            user_id: User ID (owner)
            project_name: Optional name for new project

        Returns:
            Workspace instance
        """
        logger.info(
            "initialize_workspace",
            session_id=session_id,
            project_id=project_id,
            project_name=project_name,
        )

        # Check if workspace already exists for this session
        existing = self.db.query(Workspace).filter(Workspace.session_id == session_id).first()
        if existing:
            logger.info("workspace_already_exists", workspace_id=existing.id)
            return existing

        workspace_id = str(uuid.uuid4())
        local_path = self.workspace_root / session_id

        # Clean up any existing directory
        if local_path.exists():
            shutil.rmtree(local_path)
        local_path.mkdir(parents=True, exist_ok=True)

        if project_id:
            # Working on existing project - clone and create feature branch
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project not found: {project_id}")

            # Clone the repo
            await self._clone_repo(project.clone_url or project.repo_name, local_path)

            # Create feature branch for this session
            branch_name = f"session-{session_id[:8]}"
            await self._create_branch(local_path, branch_name)

            workspace = Workspace(
                id=workspace_id,
                session_id=session_id,
                project_id=project_id,
                branch=branch_name,
                local_path=str(local_path),
                is_new_project=False,
            )
        else:
            # Creating new project
            project = await self._create_project(
                name=project_name or f"Project {session_id[:8]}",
                description="",
                user_id=user_id,
            )

            # Clone the newly created repo
            await self._clone_repo(project.clone_url or project.repo_name, local_path)

            workspace = Workspace(
                id=workspace_id,
                session_id=session_id,
                project_id=project.id,
                branch="main",
                local_path=str(local_path),
                is_new_project=True,
            )

        self.db.add(workspace)
        self.db.commit()
        self.db.refresh(workspace)

        logger.info(
            "workspace_initialized",
            workspace_id=workspace.id,
            project_id=workspace.project_id,
            branch=workspace.branch,
            local_path=workspace.local_path,
        )

        return workspace

    async def _create_project(
        self,
        name: str,
        description: str,
        user_id: str | None,
    ) -> Project:
        """Create new Gitea repo and project record."""
        repo_name = sanitize_repo_name(name)

        # Ensure unique repo name
        base_name = repo_name
        counter = 1
        while await self.gitea.repo_exists(repo_name):
            repo_name = f"{base_name}-{counter}"
            counter += 1

        # Create repo in Gitea
        result = await self.gitea.create_repo(
            name=repo_name,
            description=description,
            private=False,
            auto_init=True,
        )

        if not result.get("success"):
            raise RuntimeError(f"Failed to create Gitea repo: {result.get('error', result)}")

        # Create project record
        project_id = str(uuid.uuid4())
        project = Project(
            id=project_id,
            name=name,
            description=description,
            repo_name=repo_name,
            repo_url=self.gitea.get_public_url(repo_name),
            clone_url=self.gitea.get_clone_url(repo_name),
            owner_id=user_id,
            status="active",
        )

        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        logger.info(
            "project_created",
            project_id=project.id,
            name=project.name,
            repo_name=project.repo_name,
            repo_url=project.repo_url,
        )

        return project

    async def _clone_repo(self, repo_or_url: str, local_path: Path) -> bool:
        """Clone repo to local path.

        Args:
            repo_or_url: Either a repo name or full clone URL
            local_path: Local directory to clone into

        Returns:
            True if successful
        """
        # If it's just a repo name, get the clone URL
        if not repo_or_url.startswith("http"):
            clone_url = self.gitea.get_clone_url(repo_or_url)
        else:
            clone_url = repo_or_url

        # Clone into the directory
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "clone", clone_url, "."],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error("git_clone_failed", stderr=result.stderr)
                raise RuntimeError(f"Git clone failed: {result.stderr}")

            logger.info("repo_cloned", local_path=str(local_path))
            return True

        except subprocess.TimeoutExpired:
            raise RuntimeError("Git clone timed out")

    async def _create_branch(self, local_path: Path, branch_name: str) -> bool:
        """Create and checkout a new branch.

        Args:
            local_path: Local repo path
            branch_name: Name of the new branch

        Returns:
            True if successful
        """
        try:
            # Create branch
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "checkout", "-b", branch_name],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("git_branch_failed", stderr=result.stderr)
                raise RuntimeError(f"Git branch failed: {result.stderr}")

            # Push the new branch
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "push", "-u", "origin", branch_name],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.warning("git_push_branch_failed", stderr=result.stderr)
                # Non-fatal - branch exists locally

            logger.info("branch_created", branch=branch_name, local_path=str(local_path))
            return True

        except subprocess.TimeoutExpired:
            raise RuntimeError("Git operation timed out")

    async def commit_and_push(
        self,
        workspace: Workspace,
        message: str,
    ) -> bool:
        """Stage all changes, commit, and push.

        Args:
            workspace: Workspace instance
            message: Commit message

        Returns:
            True if successful
        """
        local_path = Path(workspace.local_path)

        if not local_path.exists():
            logger.error("workspace_not_found", local_path=str(local_path))
            return False

        try:
            # Configure git user (for container environment)
            await asyncio.to_thread(
                subprocess.run,
                ["git", "config", "user.email", "druppie@localhost"],
                cwd=str(local_path),
                capture_output=True,
                timeout=10,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["git", "config", "user.name", "Druppie Agent"],
                cwd=str(local_path),
                capture_output=True,
                timeout=10,
            )

            # Stage all changes
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "add", "-A"],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("git_add_failed", stderr=result.stderr)
                return False

            # Check if there are changes to commit
            status_result = await asyncio.to_thread(
                subprocess.run,
                ["git", "status", "--porcelain"],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if not status_result.stdout.strip():
                logger.debug("no_changes_to_commit", local_path=str(local_path))
                return True  # No changes, but not an error

            # Commit
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "commit", "-m", message],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("git_commit_failed", stderr=result.stderr)
                return False

            # Push
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "push"],
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error("git_push_failed", stderr=result.stderr)
                return False

            logger.info(
                "changes_committed_and_pushed",
                workspace_id=workspace.id,
                branch=workspace.branch,
                message=message[:50],
            )
            return True

        except subprocess.TimeoutExpired:
            logger.error("git_operation_timeout", workspace_id=workspace.id)
            return False
        except Exception as e:
            logger.error("git_operation_error", workspace_id=workspace.id, error=str(e))
            return False

    async def merge_to_main(self, workspace: Workspace) -> bool:
        """Merge current branch to main (after approval).

        Args:
            workspace: Workspace instance

        Returns:
            True if successful
        """
        if workspace.branch == "main":
            logger.info("already_on_main", workspace_id=workspace.id)
            return True

        project = self.db.query(Project).filter(Project.id == workspace.project_id).first()
        if not project:
            logger.error("project_not_found", project_id=workspace.project_id)
            return False

        # Merge via Gitea API
        result = await self.gitea.merge_branch(
            repo=project.repo_name,
            head=workspace.branch,
            base="main",
            message=f"Merge {workspace.branch} into main",
        )

        if result.get("success"):
            logger.info(
                "branch_merged",
                workspace_id=workspace.id,
                branch=workspace.branch,
                repo=project.repo_name,
            )
            return True
        else:
            logger.error(
                "merge_failed",
                workspace_id=workspace.id,
                error=result.get("error", result),
            )
            return False

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Get workspace by ID."""
        return self.db.query(Workspace).filter(Workspace.id == workspace_id).first()

    def get_workspace_by_session(self, session_id: str) -> Workspace | None:
        """Get workspace by session ID."""
        return self.db.query(Workspace).filter(Workspace.session_id == session_id).first()

    async def cleanup_workspace(self, workspace: Workspace) -> bool:
        """Clean up local workspace directory.

        Args:
            workspace: Workspace instance

        Returns:
            True if successful
        """
        local_path = Path(workspace.local_path)

        if local_path.exists():
            try:
                shutil.rmtree(local_path)
                logger.info("workspace_cleaned", workspace_id=workspace.id, local_path=str(local_path))
                return True
            except Exception as e:
                logger.error("workspace_cleanup_failed", workspace_id=workspace.id, error=str(e))
                return False

        return True


# Singleton instance management
_workspace_service: WorkspaceService | None = None


def get_workspace_service(db: DBSession) -> WorkspaceService:
    """Get a WorkspaceService instance for the given DB session."""
    # Note: We create a new service per request because it needs a DB session
    return WorkspaceService(db)
