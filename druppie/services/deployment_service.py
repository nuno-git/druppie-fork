"""Deployment service - Bridge to Docker MCP."""

from uuid import UUID
import structlog

from ..repositories import ProjectRepository
from ..domain import DeploymentInfo
from ..api.errors import AuthorizationError, ExternalServiceError

logger = structlog.get_logger()


class DeploymentService:
    """Bridge to Docker MCP for deployment operations."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        mcp_client,  # MCPClient instance
    ):
        self.project_repo = project_repo
        self.mcp_client = mcp_client

    async def list_for_user(self, user_id: UUID) -> list[DeploymentInfo]:
        """List all running deployments for user's projects."""
        projects, _ = self.project_repo.list_for_user(user_id, limit=100, offset=0)

        deployments = []
        for project in projects:
            result = await self.mcp_client.call_tool(
                "docker",
                "list_containers",
                {"project_id": str(project.id)},
            )
            if result.get("success") and result.get("containers"):
                for container in result["containers"]:
                    deployments.append(self._container_to_deployment(container, project))

        return deployments

    async def stop(
        self,
        container_name: str,
        user_id: UUID,
    ) -> dict:
        """Stop a container (with ownership check)."""
        # Verify ownership via labels
        if not await self._user_owns_container(container_name, user_id):
            raise AuthorizationError("Can only stop your own containers")

        result = await self.mcp_client.call_tool(
            "docker",
            "stop",
            {"container_name": container_name},
        )

        if not result.get("success"):
            raise ExternalServiceError("docker", result.get("error", "Failed to stop"))

        logger.info("container_stopped", container_name=container_name, by_user=str(user_id))
        return {"success": True, "status": "stopped"}

    async def get_logs(
        self,
        container_name: str,
        user_id: UUID,
        tail: int = 100,
    ) -> dict:
        """Get container logs (with ownership check)."""
        if not await self._user_owns_container(container_name, user_id):
            raise AuthorizationError("Can only view logs for your own containers")

        result = await self.mcp_client.call_tool(
            "docker",
            "logs",
            {"container_name": container_name, "tail": tail},
        )

        if not result.get("success"):
            raise ExternalServiceError("docker", result.get("error", "Failed to get logs"))

        return {
            "container_name": container_name,
            "logs": result.get("logs", ""),
        }

    async def _user_owns_container(self, container_name: str, user_id: UUID) -> bool:
        """Check if user owns the container via project_id label."""
        result = await self.mcp_client.call_tool(
            "docker",
            "inspect",
            {"container_name": container_name},
        )
        if not result.get("success"):
            return False

        labels = result.get("labels", {})
        project_id = labels.get("druppie.project_id")
        if not project_id:
            return False

        project = self.project_repo.get_by_id(UUID(project_id))
        return project is not None and project.owner_id == user_id

    def _container_to_deployment(self, container: dict, project) -> DeploymentInfo:
        """Convert Docker container info to DeploymentInfo."""
        return DeploymentInfo(
            status=container.get("status", "unknown"),
            container_name=container.get("name", ""),
            app_url=container.get("app_url"),
            host_port=container.get("host_port"),
            started_at=container.get("started_at"),
        )
