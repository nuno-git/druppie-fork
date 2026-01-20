"""MCP Registry with Permission Model.

Defines available MCP tools and their permission requirements.
Some tools require approval from specific roles before execution.
"""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ApprovalType(str, Enum):
    """Type of approval required for a tool."""
    NONE = "none"  # No approval needed
    SELF = "self"  # User can self-approve (just confirmation)
    ROLE = "role"  # Specific role must approve
    MULTI = "multi"  # Multiple approvals from different roles


class MCPTool(BaseModel):
    """Definition of an MCP tool with permissions."""

    id: str
    name: str
    description: str
    category: str  # git, docker, filesystem, shell, build

    # Input schema for the tool
    input_schema: dict[str, Any] = Field(default_factory=dict)

    # Permission model
    allowed_roles: list[str] = Field(default_factory=list)  # Empty = all roles
    approval_type: ApprovalType = ApprovalType.NONE
    approval_roles: list[str] = Field(default_factory=list)  # Who can approve

    # Danger level (for UI warnings)
    danger_level: str = "low"  # low, medium, high, critical


class MCPServer(BaseModel):
    """Definition of an MCP server providing tools."""

    id: str
    name: str
    description: str

    # Connection
    transport: str = "internal"  # internal (Python), stdio, http
    command: str | None = None
    url: str | None = None

    # Tools provided
    tools: list[MCPTool] = Field(default_factory=list)

    # Access control
    auth_groups: list[str] = Field(default_factory=list)


# =============================================================================
# MCP TOOL DEFINITIONS
# =============================================================================

GIT_TOOLS = [
    MCPTool(
        id="git.clone",
        name="Clone Repository",
        description="Clone a git repository to workspace",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL"},
                "path": {"type": "string", "description": "Target path"},
            },
            "required": ["url"],
        },
        allowed_roles=[],  # All roles
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git.commit",
        name="Commit Changes",
        description="Commit changes to the repository",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "path": {"type": "string", "description": "Repository path"},
            },
            "required": ["message"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git.push",
        name="Push to Remote",
        description="Push commits to remote repository",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "branch": {"type": "string", "description": "Branch to push"},
            },
        },
        allowed_roles=["developer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
]

FILESYSTEM_TOOLS = [
    MCPTool(
        id="fs.read",
        name="Read File",
        description="Read contents of a file",
        category="filesystem",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="fs.write",
        name="Write File",
        description="Write content to a file",
        category="filesystem",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="fs.list",
        name="List Directory",
        description="List files in a directory",
        category="filesystem",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
            },
            "required": ["path"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
]

DOCKER_TOOLS = [
    MCPTool(
        id="docker.build",
        name="Build Image",
        description="Build a Docker image from Dockerfile",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Build context path"},
                "tag": {"type": "string", "description": "Image tag"},
            },
            "required": ["path", "tag"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.NONE,
        danger_level="medium",
    ),
    MCPTool(
        id="docker.run",
        name="Run Container",
        description="Run a Docker container",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Image to run"},
                "name": {"type": "string", "description": "Container name"},
                "ports": {"type": "object", "description": "Port mappings"},
                "env": {"type": "object", "description": "Environment variables"},
            },
            "required": ["image"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="docker.compose_up",
        name="Docker Compose Up",
        description="Start services defined in docker-compose.yml",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to docker-compose.yml"},
                "services": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["path"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="docker.compose_down",
        name="Docker Compose Down",
        description="Stop and remove docker-compose services",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to docker-compose.yml"},
            },
            "required": ["path"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.NONE,
    ),
]

DEPLOY_TOOLS = [
    MCPTool(
        id="deploy.staging",
        name="Deploy to Staging",
        description="Deploy application to staging environment",
        category="deploy",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "version": {"type": "string", "description": "Version to deploy"},
            },
            "required": ["project_id"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.ROLE,
        approval_roles=["developer", "infra-engineer"],  # Another dev or infra must approve
        danger_level="high",
    ),
    MCPTool(
        id="deploy.production",
        name="Deploy to Production",
        description="Deploy application to production environment",
        category="deploy",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "version": {"type": "string", "description": "Version to deploy"},
            },
            "required": ["project_id"],
        },
        allowed_roles=["infra-engineer", "admin"],
        approval_type=ApprovalType.MULTI,
        approval_roles=["developer", "infra-engineer", "product-owner"],  # Need 2 of 3
        danger_level="critical",
    ),
]

BUILD_TOOLS = [
    MCPTool(
        id="build.npm",
        name="NPM Build",
        description="Run npm build for a Node.js project",
        category="build",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project path"},
                "script": {"type": "string", "description": "NPM script to run", "default": "build"},
            },
            "required": ["path"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="build.python",
        name="Python Build",
        description="Build a Python project (pip install, etc.)",
        category="build",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project path"},
            },
            "required": ["path"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
]

CODE_TOOLS = [
    MCPTool(
        id="code.generate",
        name="Generate Code",
        description="Generate code using LLM",
        category="code",
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What to generate"},
                "language": {"type": "string", "description": "Programming language"},
                "framework": {"type": "string", "description": "Framework to use"},
            },
            "required": ["description"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="code.edit",
        name="Edit Code",
        description="Edit existing code files",
        category="code",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "changes": {"type": "string", "description": "Changes to make"},
            },
            "required": ["path", "changes"],
        },
        allowed_roles=[],
        approval_type=ApprovalType.NONE,
    ),
]

INTERACTION_TOOLS = [
    MCPTool(
        id="interaction.ask_question",
        name="Ask Question",
        description="Ask the user a clarifying question before proceeding. Use this when you need more information to complete a task.",
        category="interaction",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user"},
                "context": {"type": "string", "description": "Additional context about why this question is needed"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of suggested answers/choices for the user",
                },
                "required_for": {"type": "string", "description": "What this information is needed for"},
            },
            "required": ["question"],
        },
        allowed_roles=[],  # All roles can use this
        approval_type=ApprovalType.NONE,  # No approval needed to ask questions
        danger_level="low",
    ),
]


# =============================================================================
# MCP REGISTRY
# =============================================================================

class MCPRegistry:
    """Registry for MCP tools with permission checking."""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, MCPTool] = {}
        self._load_defaults()

    def _load_defaults(self):
        """Load default MCP servers and tools."""
        # Create servers
        servers = [
            MCPServer(
                id="git",
                name="Git",
                description="Git version control operations",
                transport="internal",
                tools=GIT_TOOLS,
            ),
            MCPServer(
                id="filesystem",
                name="Filesystem",
                description="File system operations",
                transport="internal",
                tools=FILESYSTEM_TOOLS,
            ),
            MCPServer(
                id="docker",
                name="Docker",
                description="Docker container operations",
                transport="internal",
                tools=DOCKER_TOOLS,
                auth_groups=["developer", "infra-engineer", "admin"],
            ),
            MCPServer(
                id="deploy",
                name="Deployment",
                description="Deployment operations",
                transport="internal",
                tools=DEPLOY_TOOLS,
                auth_groups=["developer", "infra-engineer", "admin"],
            ),
            MCPServer(
                id="build",
                name="Build",
                description="Build and packaging operations",
                transport="internal",
                tools=BUILD_TOOLS,
            ),
            MCPServer(
                id="code",
                name="Code Generation",
                description="AI-powered code generation",
                transport="internal",
                tools=CODE_TOOLS,
            ),
            MCPServer(
                id="interaction",
                name="User Interaction",
                description="Tools for interacting with users, asking questions, and getting clarification",
                transport="internal",
                tools=INTERACTION_TOOLS,
            ),
        ]

        for server in servers:
            self._servers[server.id] = server
            for tool in server.tools:
                self._tools[tool.id] = tool

    def get_server(self, server_id: str) -> MCPServer | None:
        """Get an MCP server by ID."""
        return self._servers.get(server_id)

    def get_tool(self, tool_id: str) -> MCPTool | None:
        """Get a tool by ID."""
        return self._tools.get(tool_id)

    def list_servers(self, user_roles: list[str] | None = None) -> list[MCPServer]:
        """List servers accessible to user."""
        servers = list(self._servers.values())

        if user_roles is not None:
            # Admin sees everything
            if "admin" in user_roles:
                return servers

            # Filter by auth_groups
            servers = [
                s for s in servers
                if not s.auth_groups or any(r in s.auth_groups for r in user_roles)
            ]

        return servers

    def list_tools(self, user_roles: list[str] | None = None) -> list[MCPTool]:
        """List tools accessible to user."""
        tools = []

        for server in self.list_servers(user_roles):
            for tool in server.tools:
                # Check tool-level permissions
                if tool.allowed_roles and user_roles:
                    if "admin" not in user_roles:
                        if not any(r in tool.allowed_roles for r in user_roles):
                            continue
                tools.append(tool)

        return tools

    def check_permission(
        self,
        tool_id: str,
        user_roles: list[str],
        user_id: str,
    ) -> dict[str, Any]:
        """Check if user can execute a tool.

        Returns:
            {
                "allowed": bool,
                "requires_approval": bool,
                "approval_type": str,
                "approval_roles": list[str],
                "message": str,
            }
        """
        tool = self.get_tool(tool_id)
        if not tool:
            return {
                "allowed": False,
                "requires_approval": False,
                "message": f"Tool '{tool_id}' not found",
            }

        # Check role access
        if tool.allowed_roles and "admin" not in user_roles:
            if not any(r in tool.allowed_roles for r in user_roles):
                return {
                    "allowed": False,
                    "requires_approval": False,
                    "message": f"Requires one of roles: {', '.join(tool.allowed_roles)}",
                }

        # Check approval requirements
        if tool.approval_type == ApprovalType.NONE:
            return {
                "allowed": True,
                "requires_approval": False,
                "message": "No approval required",
            }

        if tool.approval_type == ApprovalType.SELF:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "self",
                "approval_roles": [],
                "message": "Requires your confirmation",
            }

        if tool.approval_type == ApprovalType.ROLE:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "role",
                "approval_roles": tool.approval_roles,
                "message": f"Requires approval from: {', '.join(tool.approval_roles)}",
            }

        if tool.approval_type == ApprovalType.MULTI:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "multi",
                "approval_roles": tool.approval_roles,
                "message": f"Requires multiple approvals from: {', '.join(tool.approval_roles)}",
            }

        return {"allowed": True, "requires_approval": False}

    def get_tools_for_agent(self, agent_id: str) -> list[MCPTool]:
        """Get tools available to a specific agent."""
        # For now, agents have access to all tools
        # In production, this would be based on agent configuration
        return list(self._tools.values())

    def to_dict(self) -> dict[str, Any]:
        """Export registry as dictionary."""
        return {
            "servers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tools": [
                        {
                            "id": t.id,
                            "name": t.name,
                            "description": t.description,
                            "category": t.category,
                            "approval_type": t.approval_type.value,
                            "danger_level": t.danger_level,
                        }
                        for t in s.tools
                    ],
                }
                for s in self._servers.values()
            ]
        }


# Singleton instance
mcp_registry = MCPRegistry()
