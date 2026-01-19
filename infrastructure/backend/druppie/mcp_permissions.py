"""MCP Permission Management System.

Handles permission checking and approval workflows for MCP tool execution.

Permission Levels:
- auto: Tool runs immediately without approval (for read operations)
- user_approve: User who triggered must confirm (for writes)
- role_approve: Specific role must approve (for critical operations)
"""

from typing import Any, Optional

from .config import load_mcp_permissions


class MCPPermissionManager:
    """Manages MCP tool permissions and approval workflows."""

    def __init__(self):
        self._config = load_mcp_permissions()
        self._role_permissions = self._build_role_permissions()
        self._tool_levels = self._build_tool_levels()

    def _build_role_permissions(self) -> dict[str, list[str]]:
        """Build role -> MCP permissions mapping."""
        result = {}

        for role in self._config.get("roles", []):
            role_name = role.get("name")
            permissions = role.get("mcpPermissions", [])
            result[role_name] = permissions

        return result

    def _build_tool_levels(self) -> dict[str, str]:
        """Build tool -> permission level mapping."""
        result = {}
        levels = self._config.get("mcpPermissionLevels", {})

        for level, tools in levels.items():
            for tool in tools:
                result[tool] = level

        return result

    def get_permissions_for_roles(self, roles: list[str]) -> list[str]:
        """Get all MCP permissions for a set of roles."""
        permissions = set()

        for role in roles:
            role_perms = self._role_permissions.get(role, [])
            for perm in role_perms:
                if perm.endswith(".*"):
                    # Wildcard permission
                    prefix = perm[:-2]
                    permissions.add(perm)
                else:
                    permissions.add(perm)

        return sorted(permissions)

    def get_permission_level(self, tool_name: str) -> str:
        """Get permission level for a tool."""
        # Check exact match
        if tool_name in self._tool_levels:
            return self._tool_levels[tool_name]

        # Check prefix match (e.g., "git.clone" matches "git.*")
        parts = tool_name.split(".")
        if len(parts) >= 2:
            prefix = parts[0] + ".*"
            for configured_tool, level in self._tool_levels.items():
                if configured_tool == prefix:
                    return level

        # Default to role_approve for unknown tools (safer)
        return "roleApprove"

    def get_required_role(self, tool_name: str) -> Optional[str]:
        """Get the role required to approve a tool execution."""
        # Check approval workflows
        workflows = self._config.get("approvalWorkflows", {})

        for workflow_id, workflow in workflows.items():
            mcp_tools = workflow.get("mcpTools", [])
            if tool_name in mcp_tools:
                approvals = workflow.get("requiredApprovals", [])
                if approvals:
                    return approvals[0].get("role")

        # Derive from tool name
        prefix = tool_name.split(".")[0]
        role_map = {
            "docker": "infra-engineer",
            "git": "developer",
            "filesystem": "developer",
            "shell": "developer",
        }

        return role_map.get(prefix, "admin")

    def check_permission(
        self, tool_name: str, user_roles: list[str], user_id: str
    ) -> dict[str, Any]:
        """Check if a user can execute an MCP tool.

        Returns:
            {
                "allowed": bool,
                "requires_approval": bool,
                "approval_type": str,  # "none", "user", "role"
                "required_role": str | None,
                "reason": str
            }
        """
        # Admin can do anything
        if "admin" in user_roles:
            return {
                "allowed": True,
                "requires_approval": False,
                "approval_type": "none",
                "required_role": None,
                "reason": "Admin has full access",
            }

        # Check if user's roles grant permission
        user_permissions = self.get_permissions_for_roles(user_roles)
        has_permission = False

        for perm in user_permissions:
            if perm == tool_name:
                has_permission = True
                break
            elif perm.endswith(".*"):
                prefix = perm[:-2]
                if tool_name.startswith(prefix + "."):
                    has_permission = True
                    break

        if not has_permission:
            return {
                "allowed": False,
                "requires_approval": False,
                "approval_type": "none",
                "required_role": None,
                "reason": f"Role does not have permission for {tool_name}",
            }

        # Check permission level
        level = self.get_permission_level(tool_name)

        if level == "auto":
            return {
                "allowed": True,
                "requires_approval": False,
                "approval_type": "none",
                "required_role": None,
                "reason": "Auto-approved (read operation)",
            }

        elif level == "userApprove":
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "user",
                "required_role": None,
                "reason": "Requires user confirmation",
            }

        else:  # roleApprove
            required_role = self.get_required_role(tool_name)
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "role",
                "required_role": required_role,
                "reason": f"Requires approval from {required_role}",
            }

    def get_all_permissions(self) -> dict[str, Any]:
        """Get all permission configurations."""
        return {
            "roles": self._role_permissions,
            "toolLevels": self._tool_levels,
            "approvalWorkflows": self._config.get("approvalWorkflows", {}),
        }

    def get_permission(self, tool_name: str) -> Optional[dict[str, Any]]:
        """Get permission info for a specific tool."""
        level = self.get_permission_level(tool_name)
        required_role = self.get_required_role(tool_name)

        return {
            "tool": tool_name,
            "level": level,
            "requiredRole": required_role,
        }

    def get_approval_workflow(self, workflow_id: str) -> Optional[dict[str, Any]]:
        """Get approval workflow configuration."""
        workflows = self._config.get("approvalWorkflows", {})
        return workflows.get(workflow_id)
