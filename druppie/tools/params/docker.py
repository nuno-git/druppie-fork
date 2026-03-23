"""Parameter models for docker MCP tools.

These define the parameter types for validation. Descriptions come from
mcp_config.yaml - these models are purely for type-safe validation.

Hidden parameters (session_id, repo_name, repo_owner, user_id, project_id)
are injected at runtime and not included here.
"""

from pydantic import BaseModel, Field


class DockerBuildParams(BaseModel):
    image_name: str = Field(description="Name for the built image (e.g., myapp:latest)")
    git_url: str | None = Field(default=None, description="Full git URL to clone (alternative to repo_name)")
    branch: str | None = Field(default=None, description="Git branch (default: main)")
    dockerfile: str | None = Field(default=None, description="Dockerfile name (default: Dockerfile)")
    build_args: dict[str, str] | None = Field(default=None, description="Docker build arguments as key-value pairs")


class DockerRunParams(BaseModel):
    image_name: str = Field(description="Docker image to run")
    container_name: str = Field(description="Name for the container")
    container_port: int = Field(description="Container port from Dockerfile EXPOSE (e.g., 80 for nginx, 3000 for node)")
    port: int | None = Field(default=None, description="Host port (auto-assigned from 9100-9199 if not provided)")
    env_vars: dict[str, str] | None = Field(default=None, description="Environment variables as key-value pairs")
    volumes: list[str] | None = Field(default=None, description="Volume mounts (format: 'host:container')")
    command: str | None = Field(default=None, description="Override command")


class DockerStopParams(BaseModel):
    container_name: str = Field(description="Name of container to stop")
    remove: bool = Field(default=True, description="Whether to remove container after stopping")


class DockerLogsParams(BaseModel):
    container_name: str = Field(description="Name of container to get logs from")
    tail: int | None = Field(default=100, description="Number of lines to show")


class DockerRemoveParams(BaseModel):
    container_name: str = Field(description="Name of container to remove")
    force: bool = Field(default=False, description="Force remove running container")


class DockerListContainersParams(BaseModel):
    all: bool = Field(default=False, description="Include stopped containers")
    project_id: str | None = Field(default=None, description="Filter by druppie.project_id label")
    session_id: str | None = Field(default=None, description="Filter by druppie.session_id label")
    user_id: str | None = Field(default=None, description="Filter by druppie.user_id label")


class DockerInspectParams(BaseModel):
    container_name: str = Field(description="Name of container to inspect")


class DockerExecCommandParams(BaseModel):
    container_name: str = Field(description="Name of container")
    command: str = Field(description="Command to execute")
    workdir: str | None = Field(default=None, description="Working directory inside container")


class DockerComposeUpParams(BaseModel):
    # Note: repo_name, repo_owner, session_id, project_id, user_id are injected
    # at runtime (same as DockerBuildParams/DockerRunParams) — not included here.
    git_url: str | None = Field(default=None, description="Full git URL")
    branch: str = Field(default="main", description="Git branch to deploy")
    compose_project_name: str | None = Field(default=None, description="Compose project name")


class DockerComposeDownParams(BaseModel):
    compose_project_name: str = Field(..., description="Compose project name to stop")
    remove_volumes: bool = Field(default=True, description="Remove associated volumes")
