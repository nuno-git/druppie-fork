"""Builder Service - Builds and runs Docker applications.

TODO: This service needs to be refactored to:
1. Move build logic to Docker MCP
2. Track builds via container labels instead of database
3. Use project_id as the key for port allocation

The Docker MCP already has build/run/stop/logs tools.
This service is kept as a facade that calls Docker MCP.

Current status: Stubbed out - all methods raise NotImplementedError
"""

import os
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy.orm import Session as DBSession

from druppie.db.models import Project

logger = structlog.get_logger()

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))


class BuilderService:
    """Service for building and running Docker applications.

    TODO: Reimplement to use Docker MCP instead of local subprocess calls.
    Builds should be tracked via container labels:
    - druppie.project_id
    - druppie.session_id
    - druppie.app_type
    - druppie.is_preview
    """

    def __init__(self, db: DBSession):
        self.db = db

    async def build_project(
        self,
        project_id: str,
        branch: str = "main",
        is_preview: bool = False,
    ):
        """Build Docker image for project.

        TODO: Call Docker MCP build tool instead.
        """
        raise NotImplementedError(
            "BuilderService needs refactoring - use Docker MCP directly"
        )

    async def run_project(self, build_id: str):
        """Run Docker container from build.

        TODO: Call Docker MCP run tool instead.
        """
        raise NotImplementedError(
            "BuilderService needs refactoring - use Docker MCP directly"
        )

    async def stop_project(self, build_id: str) -> bool:
        """Stop a running container.

        TODO: Call Docker MCP stop tool instead.
        """
        raise NotImplementedError(
            "BuilderService needs refactoring - use Docker MCP directly"
        )

    async def get_logs(self, container_name: str, tail: int = 100) -> str:
        """Get container logs.

        TODO: Call Docker MCP logs tool instead.
        """
        raise NotImplementedError(
            "BuilderService needs refactoring - use Docker MCP directly"
        )


def get_builder_service(db: DBSession) -> BuilderService:
    """Get a BuilderService instance."""
    return BuilderService(db)
