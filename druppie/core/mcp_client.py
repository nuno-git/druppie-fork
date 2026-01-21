"""MCP Client - HTTP client for MCP servers with approval checking.

This client:
1. Loads MCP configuration from mcp_config.yaml
2. Checks tool approval requirements before execution
3. Pauses execution and creates approval records when needed
4. Executes tools via HTTP to MCP server containers
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx
import redis
import structlog
import yaml

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession
    from druppie.core.execution_context import ExecutionContext

logger = structlog.get_logger()


class MCPClient:
    """HTTP client for MCP servers with approval checking."""

    def __init__(self, db: "DBSession", redis_url: str | None = None):
        """Initialize MCP client.

        Args:
            db: Database session
            redis_url: Redis URL for pub/sub events
        """
        self.db = db
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis: redis.Redis | None = None
        self._config: dict | None = None

    @property
    def redis(self) -> redis.Redis:
        """Get Redis client (lazy initialization)."""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    @property
    def config(self) -> dict:
        """Load MCP configuration (cached)."""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> dict:
        """Load MCP configuration from YAML file."""
        config_path = Path(__file__).parent / "mcp_config.yaml"
        with open(config_path) as f:
            content = f.read()

        # Substitute environment variables
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
            content = content.replace(f"${{{key}:-", f"{{{key}:-")

        # Handle default values ${VAR:-default}
        import re

        def replace_default(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.getenv(var_name, default)

        content = re.sub(r"\$\{(\w+):-([^}]+)\}", replace_default, content)

        return yaml.safe_load(content)

    def get_mcp_url(self, server: str) -> str:
        """Get URL for an MCP server."""
        mcp = self.config.get("mcps", {}).get(server, {})
        return mcp.get("url", f"http://mcp-{server}:9001")

    def get_tool_config(self, server: str, tool: str) -> dict:
        """Get tool configuration including approval requirements."""
        mcp = self.config.get("mcps", {}).get(server, {})
        for t in mcp.get("tools", []):
            if t["name"] == tool:
                return t
        return {}

    def requires_approval(self, server: str, tool: str) -> tuple[bool, list[str], str]:
        """Check if tool requires approval and what roles can approve.

        Returns:
            Tuple of (requires_approval, required_roles, danger_level)
        """
        config = self.get_tool_config(server, tool)
        return (
            config.get("requires_approval", False),
            config.get("required_roles", []),
            config.get("danger_level", "low"),
        )

    def user_has_role(self, user_roles: list[str], required_roles: list[str]) -> bool:
        """Check if user has any of the required roles."""
        if not required_roles:
            return True
        if "admin" in user_roles:
            return True
        return any(role in user_roles for role in required_roles)

    async def call_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Call MCP tool, checking for approval requirements.

        IMPORTANT: AI executes tools, so user ALWAYS confirms for
        approval-required tools (even if user has the role).

        Args:
            server: MCP server name (coding, docker, hitl)
            tool: Tool name
            args: Tool arguments
            context: Execution context with session/user info

        Returns:
            Tool result or paused status if approval required
        """
        needs_approval, required_roles, danger_level = self.requires_approval(server, tool)

        if needs_approval:
            # ALWAYS request approval - AI is executing, user must confirm
            return await self._request_approval(
                server, tool, args, required_roles, danger_level, context
            )

        # No approval needed for this tool
        return await self._execute_tool(server, tool, args, context)

    async def _execute_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute tool via HTTP to MCP server."""
        url = self.get_mcp_url(server)

        logger.info(
            "mcp_tool_executing",
            server=server,
            tool=tool,
            url=url,
            session_id=context.session_id,
        )

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                # FastMCP uses POST /tools/{tool_name}
                response = await client.post(
                    f"{url}/tools/{tool}",
                    json=args,
                    headers={
                        "Content-Type": "application/json",
                        "X-Session-ID": context.session_id or "",
                        "X-User-ID": context.user_id or "",
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        "mcp_tool_completed",
                        server=server,
                        tool=tool,
                        success=result.get("success", True),
                    )
                    return result
                else:
                    error_msg = f"MCP call failed: {response.status_code} {response.text}"
                    logger.error(
                        "mcp_tool_failed",
                        server=server,
                        tool=tool,
                        status=response.status_code,
                        error=response.text,
                    )
                    return {"success": False, "error": error_msg}

        except httpx.TimeoutException:
            logger.error("mcp_tool_timeout", server=server, tool=tool)
            return {"success": False, "error": "MCP call timed out"}
        except Exception as e:
            logger.error("mcp_tool_error", server=server, tool=tool, error=str(e))
            return {"success": False, "error": str(e)}

    async def _request_approval(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        required_roles: list[str],
        danger_level: str,
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Request approval and pause execution."""
        from druppie.db import crud

        tool_name = f"{server}:{tool}"

        # Create approval record in DB
        approval_id = str(uuid.uuid4())
        approval = crud.create_approval(
            self.db,
            {
                "id": approval_id,
                "session_id": context.session_id,
                "tool_name": tool_name,
                "arguments": args,
                "required_roles": required_roles or ["developer", "admin"],
                "danger_level": danger_level,
                "description": f"Execute {tool_name} with args: {json.dumps(args)[:200]}",
                "status": "pending",
                "agent_state": context.get_state() if hasattr(context, "get_state") else None,
            },
        )

        logger.info(
            "approval_requested",
            approval_id=approval_id,
            tool=tool_name,
            session_id=context.session_id,
            required_roles=required_roles,
        )

        # Emit event to frontend via Redis pub/sub
        self._emit_approval_request(context.session_id, approval)

        # Also emit via context callback if available
        if context.emit_event:
            context.emit_event({
                "event_type": "approval_required",
                "approval_id": approval_id,
                "tool": tool_name,
                "args": args,
                "required_roles": required_roles,
                "danger_level": danger_level,
            })

        # Return special PAUSED status
        return {
            "status": "paused",
            "reason": "approval_required",
            "approval_id": approval_id,
            "tool": tool_name,
            "required_roles": required_roles,
            "danger_level": danger_level,
        }

    def _emit_approval_request(self, session_id: str, approval) -> None:
        """Emit approval request via Redis pub/sub."""
        try:
            self.redis.publish(
                f"session:{session_id}",
                json.dumps({
                    "type": "approval_required",
                    "approval_id": approval.id,
                    "tool": approval.tool_name,
                    "args": approval.arguments,
                    "required_roles": approval.required_roles,
                    "danger_level": approval.danger_level,
                    "timestamp": datetime.utcnow().isoformat(),
                }),
            )
        except Exception as e:
            logger.warning("redis_publish_failed", error=str(e))

    async def execute_approved_tool(
        self,
        approval_id: str,
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute a tool that was approved.

        Called after approval is granted to actually run the tool.

        Args:
            approval_id: ID of the approved request
            context: Execution context

        Returns:
            Tool result
        """
        from druppie.db import crud

        approval = crud.get_approval(self.db, approval_id)
        if not approval:
            return {"success": False, "error": "Approval not found"}

        if approval.status != "approved":
            return {"success": False, "error": f"Approval status is {approval.status}"}

        # Parse tool name
        server, tool = approval.tool_name.split(":", 1)

        # Execute the tool
        return await self._execute_tool(server, tool, approval.arguments or {}, context)

    def get_tools_for_mcps(self, mcp_ids: list[str]) -> list[dict]:
        """Get tool definitions for specified MCPs.

        Args:
            mcp_ids: List of MCP IDs (coding, docker, hitl)

        Returns:
            List of tool definitions
        """
        tools = []
        for mcp_id in mcp_ids:
            mcp = self.config.get("mcps", {}).get(mcp_id, {})
            for tool in mcp.get("tools", []):
                tools.append({
                    "id": f"{mcp_id}:{tool['name']}",
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "category": mcp_id,
                    "requires_approval": tool.get("requires_approval", False),
                    "required_roles": tool.get("required_roles", []),
                    "danger_level": tool.get("danger_level", "low"),
                })
        return tools

    def to_openai_tools(self, mcp_ids: list[str] | None = None) -> list[dict]:
        """Convert tools to OpenAI function calling format.

        Args:
            mcp_ids: Optional list of MCP IDs. If None, include all.

        Returns:
            List of tool definitions in OpenAI format
        """
        if mcp_ids is None:
            mcp_ids = list(self.config.get("mcps", {}).keys())

        openai_tools = []
        for mcp_id in mcp_ids:
            mcp = self.config.get("mcps", {}).get(mcp_id, {})
            for tool in mcp.get("tools", []):
                # Generate a basic schema based on tool name
                # In production, you'd want more detailed schemas
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{mcp_id}_{tool['name']}",
                        "description": tool.get("description", f"Execute {tool['name']}"),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                })

        return openai_tools


# =============================================================================
# SINGLETON
# =============================================================================


_mcp_client: MCPClient | None = None


def get_mcp_client(db: "DBSession") -> MCPClient:
    """Get or create MCP client instance."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient(db)
    else:
        # Update db session
        _mcp_client.db = db
    return _mcp_client
