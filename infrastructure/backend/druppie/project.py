"""Project Service - Manages projects with Gitea integration.

Each project has:
- A workspace directory for files
- A Gitea repository for version control
- Optional running containers with URLs
"""

import os
import uuid
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import requests
import structlog

from .models import db, Plan

logger = structlog.get_logger()

# Configuration
GITEA_URL = os.getenv("GITEA_URL", "http://localhost:3000")
GITEA_INTERNAL_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "GiteaAdmin123")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
WORKSPACE_PATH = Path(os.getenv("WORKSPACE_PATH", "/app/workspace"))


class Project:
    """Represents a project with Git repository and optional running app."""

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        repo_url: str | None = None,
        app_url: str | None = None,
        created_by: str | None = None,
        created_at: datetime | None = None,
        owner_username: str | None = None,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.repo_url = repo_url
        self.app_url = app_url
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.owner_username = owner_username  # Gitea username (for private repos)

    @property
    def workspace_path(self) -> Path:
        return WORKSPACE_PATH / self.id

    @property
    def gitea_repo_name(self) -> str:
        """Generate a valid Gitea repo name from project name."""
        # Convert to lowercase, replace spaces with hyphens
        name = self.name.lower().replace(" ", "-")
        # Remove invalid characters
        name = "".join(c for c in name if c.isalnum() or c == "-")
        # Ensure it doesn't start with a hyphen
        name = name.lstrip("-")
        # Add project ID suffix for uniqueness
        return f"{name}-{self.id[:8]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "repo_url": self.repo_url,
            "app_url": self.app_url,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "workspace_path": str(self.workspace_path),
            "owner_username": self.owner_username,
        }


class ProjectService:
    """Service for managing projects with Gitea integration."""

    def __init__(self):
        self._session = requests.Session()
        self._session.auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)
        self._session.headers.update({"Content-Type": "application/json"})
        self._ensured_users: set[str] = set()

    def _ensure_gitea_user(self, username: str, email: str) -> str:
        """Ensure a Gitea user exists for the given Keycloak username.

        Creates the user if they don't exist. Returns the username.
        """
        # Skip if already ensured this session
        if username in self._ensured_users:
            return username

        try:
            # Check if user exists
            check_url = f"{GITEA_INTERNAL_URL}/api/v1/users/{username}"
            response = self._session.get(check_url, timeout=10)

            if response.status_code == 200:
                self._ensured_users.add(username)
                logger.info("Gitea user exists", username=username)
                return username

            # Create user via admin API
            create_url = f"{GITEA_INTERNAL_URL}/api/v1/admin/users"
            # Generate a secure password (user won't need it - they login via Keycloak OAuth)
            import secrets
            auto_password = f"Druppie_{secrets.token_hex(16)}"

            user_data = {
                "username": username,
                "email": email or f"{username}@druppie.local",
                "password": auto_password,
                "must_change_password": False,
                "visibility": "private",
            }

            response = self._session.post(create_url, json=user_data, timeout=10)

            if response.status_code in [201, 422]:  # 422 = user already exists
                self._ensured_users.add(username)
                logger.info("Gitea user created/exists", username=username)
                return username

            logger.error("Failed to create Gitea user",
                        username=username,
                        status=response.status_code,
                        response=response.text[:200])

        except Exception as e:
            logger.error("Failed to ensure Gitea user", username=username, error=str(e))

        return username

    def create_project(
        self,
        name: str,
        description: str = "",
        created_by: str | None = None,
        plan_id: str | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> Project:
        """Create a new project with workspace and Gitea repository."""
        project_id = plan_id or str(uuid.uuid4())

        # Determine repo owner - use user's Gitea account if username provided
        owner_username = username if username else GITEA_ORG

        project = Project(
            id=project_id,
            name=name,
            description=description,
            created_by=created_by,
            owner_username=owner_username,
        )

        # Create workspace directory
        project.workspace_path.mkdir(parents=True, exist_ok=True)

        # Create Gitea repository under user's account (private)
        try:
            repo_url = self._create_gitea_repo(project, username, email)
            project.repo_url = repo_url
            logger.info("Created Gitea repository", project_id=project_id, repo_url=repo_url, owner=owner_username)
        except Exception as e:
            logger.error("Failed to create Gitea repository", error=str(e))

        # Initialize git in workspace
        try:
            self._init_git_repo(project)
        except Exception as e:
            logger.error("Failed to initialize git", error=str(e))

        return project

    def _create_gitea_repo(
        self,
        project: Project,
        username: str | None = None,
        email: str | None = None,
    ) -> str:
        """Create a Gitea repository for the project.

        If username is provided, creates a private repo under the user's account.
        Otherwise, creates under the druppie org (legacy behavior).
        """
        repo_name = project.gitea_repo_name

        if username:
            # Ensure the Gitea user exists
            self._ensure_gitea_user(username, email or f"{username}@druppie.local")

            # Check if repo already exists under user
            check_url = f"{GITEA_INTERNAL_URL}/api/v1/repos/{username}/{repo_name}"
            response = self._session.get(check_url, timeout=10)

            if response.status_code == 200:
                logger.info("Repository already exists", repo=repo_name, owner=username)
                return f"{GITEA_URL}/{username}/{repo_name}"

            # Create private repository under user's account via admin API
            create_url = f"{GITEA_INTERNAL_URL}/api/v1/admin/users/{username}/repos"
            repo_data = {
                "name": repo_name,
                "description": project.description[:255] if project.description else "",
                "private": True,  # Private repo for user
                "auto_init": False,
                "default_branch": "main",
            }

            response = self._session.post(create_url, json=repo_data, timeout=10)

            if response.status_code in [201, 409]:
                logger.info("Private repository created", repo=repo_name, owner=username)
                return f"{GITEA_URL}/{username}/{repo_name}"

            logger.error("Failed to create user repository",
                        repo=repo_name,
                        owner=username,
                        status=response.status_code,
                        response=response.text[:200])
            # Don't raise - fall through to return URL anyway
            return f"{GITEA_URL}/{username}/{repo_name}"

        else:
            # Legacy: create under org (for backwards compatibility)
            # Check if repo exists
            check_url = f"{GITEA_INTERNAL_URL}/api/v1/repos/{GITEA_ORG}/{repo_name}"
            response = self._session.get(check_url, timeout=10)

            if response.status_code == 200:
                logger.info("Repository already exists", repo=repo_name)
                return f"{GITEA_URL}/{GITEA_ORG}/{repo_name}"

            # Create repository under org
            create_url = f"{GITEA_INTERNAL_URL}/api/v1/orgs/{GITEA_ORG}/repos"
            repo_data = {
                "name": repo_name,
                "description": project.description[:255] if project.description else "",
                "private": False,
                "auto_init": False,
                "default_branch": "main",
            }

            response = self._session.post(create_url, json=repo_data, timeout=10)

            if response.status_code in [201, 409]:
                logger.info("Repository created", repo=repo_name)
                return f"{GITEA_URL}/{GITEA_ORG}/{repo_name}"

            logger.error("Failed to create repository",
                        repo=repo_name,
                        status=response.status_code,
                        response=response.text[:200])
            return f"{GITEA_URL}/{GITEA_ORG}/{repo_name}"

    def _get_git_remote_url(self, project: Project) -> str:
        """Build git remote URL with embedded credentials for push access."""
        from urllib.parse import urlparse, quote
        parsed = urlparse(GITEA_INTERNAL_URL)

        # URL-encode credentials to handle special characters
        user = quote(GITEA_ADMIN_USER, safe='')
        password = quote(GITEA_ADMIN_PASSWORD, safe='')

        # Determine repo path based on owner
        owner = project.owner_username or GITEA_ORG
        repo_name = project.gitea_repo_name

        # Build URL with embedded credentials: http://user:pass@gitea:3000/owner/repo.git
        return f"{parsed.scheme}://{user}:{password}@{parsed.netloc}/{owner}/{repo_name}.git"

    def _init_git_repo(self, project: Project) -> None:
        """Initialize git repository in workspace and push to Gitea."""
        workspace = project.workspace_path

        # Check if already initialized
        if (workspace / ".git").exists():
            return

        # Initialize git with main as default branch
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )

        # Configure git
        subprocess.run(
            ["git", "config", "user.email", "druppie@druppie.local"],
            cwd=workspace,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Druppie"],
            cwd=workspace,
            capture_output=True,
        )

        # Add remote with embedded credentials for push access
        remote_url = self._get_git_remote_url(project)

        subprocess.run(
            ["git", "remote", "add", "origin", remote_url],
            cwd=workspace,
            capture_output=True,
        )

        logger.info("Initialized git repository", project_id=project.id, owner=project.owner_username)

    def commit_and_push(
        self,
        project: Project,
        message: str = "Update from Druppie",
        author: str | None = None,
    ) -> bool:
        """Commit all changes and push to Gitea."""
        workspace = project.workspace_path

        if not (workspace / ".git").exists():
            self._init_git_repo(project)

        try:
            # Ensure remote URL has credentials (in case it was set up before the fix)
            remote_url = self._get_git_remote_url(project)
            subprocess.run(
                ["git", "remote", "set-url", "origin", remote_url],
                cwd=workspace,
                capture_output=True,
            )

            # Add all files
            subprocess.run(
                ["git", "add", "-A"],
                cwd=workspace,
                capture_output=True,
                check=True,
            )

            # Check if there are changes to commit
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                capture_output=True,
                text=True,
            )

            if not result.stdout.strip():
                logger.info("No changes to commit", project_id=project.id)
                return True

            # Commit
            commit_cmd = ["git", "commit", "-m", message]
            if author:
                commit_cmd.extend(["--author", f"{author} <{author}@druppie.local>"])

            subprocess.run(
                commit_cmd,
                cwd=workspace,
                capture_output=True,
                check=True,
            )

            # Push - credentials are embedded in the remote URL
            result = subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=workspace,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(
                    "Git push failed",
                    project_id=project.id,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
                return False

            logger.info("Committed and pushed changes", project_id=project.id, owner=project.owner_username)
            return True

        except subprocess.CalledProcessError as e:
            logger.error(
                "Git operation failed",
                project_id=project.id,
                error=e.stderr.decode() if e.stderr else str(e),
            )
            return False

    def get_project_for_plan(self, plan_id: str) -> Project | None:
        """Get or create a project for a plan."""
        plan = Plan.query.get(plan_id)
        if not plan:
            return None

        workspace = WORKSPACE_PATH / plan_id
        if not workspace.exists():
            return None

        # Check if we have repo info in plan metadata
        repo_url = None
        app_url = None

        if plan.result:
            repo_url = plan.result.get("repo_url")
            app_url = plan.result.get("app_url")

        return Project(
            id=plan_id,
            name=plan.name,
            description=plan.description or "",
            repo_url=repo_url,
            app_url=app_url,
            created_by=plan.created_by,
            created_at=plan.created_at,
        )

    def list_projects(self, user_id: str | None = None) -> list[Project]:
        """List all projects, optionally filtered by user."""
        projects = []

        # Get all plans that have workspaces
        query = Plan.query.order_by(Plan.created_at.desc())
        if user_id:
            query = query.filter_by(created_by=user_id)

        for plan in query.limit(100).all():
            workspace = WORKSPACE_PATH / plan.id
            if workspace.exists() and any(workspace.iterdir()):
                project = self.get_project_for_plan(plan.id)
                if project:
                    projects.append(project)

        return projects


# Singleton instance
project_service = ProjectService()
