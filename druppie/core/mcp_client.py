"""MCP Client - FastMCP client for MCP servers with approval checking.

This client:
1. Loads MCP configuration from mcp_config.yaml
2. Checks tool approval requirements before execution
3. Pauses execution and creates approval records when needed
4. Executes tools via FastMCP Client to MCP server containers
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import redis
import structlog
import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


# =============================================================================
# ERROR CLASSIFICATION
# =============================================================================


class MCPErrorType:
    """Error type constants for MCP tool execution."""
    TRANSIENT = "transient"  # Connection issues, timeouts - should retry
    PERMISSION = "permission"  # 403, approval needed - don't retry
    FATAL = "fatal"  # Invalid args, tool not found - don't retry


def classify_error(error: Exception) -> tuple[str, bool]:
    """Classify an error and determine if it's retryable.

    Args:
        error: The exception to classify

    Returns:
        Tuple of (error_type, retryable)
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Transient errors - connection/network issues that may resolve on retry
    transient_indicators = [
        "connection refused",
        "connection reset",
        "connection error",
        "timeout",
        "timed out",
        "temporary failure",
        "service unavailable",
        "503",
        "502",
        "504",
        "network unreachable",
        "name resolution",
        "dns",
        "econnrefused",
        "econnreset",
        "etimedout",
        "ehostunreach",
    ]

    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return MCPErrorType.TRANSIENT, True

    if isinstance(error, ConnectionError) or isinstance(error, OSError):
        return MCPErrorType.TRANSIENT, True

    for indicator in transient_indicators:
        if indicator in error_str:
            return MCPErrorType.TRANSIENT, True

    # Permission errors - authorization/approval issues
    permission_indicators = [
        "403",
        "forbidden",
        "permission denied",
        "access denied",
        "unauthorized",
        "401",
        "approval required",
        "not authorized",
        "insufficient permissions",
    ]

    for indicator in permission_indicators:
        if indicator in error_str:
            return MCPErrorType.PERMISSION, False

    # Fatal errors - invalid requests that won't succeed on retry
    fatal_indicators = [
        "invalid argument",
        "invalid parameter",
        "tool not found",
        "method not found",
        "not found",
        "404",
        "400",
        "bad request",
        "validation error",
        "schema",
        "missing required",
        "type error",
        "value error",
    ]

    for indicator in fatal_indicators:
        if indicator in error_str:
            return MCPErrorType.FATAL, False

    # Default to fatal for unknown errors (safer to not retry)
    return MCPErrorType.FATAL, False

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession
    from druppie.core.execution_context import ExecutionContext

logger = structlog.get_logger()


class MCPClient:
    """FastMCP client for MCP servers with approval checking."""

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
        self._clients: dict[str, Client] = {}

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

        # Handle ${VAR:-default} syntax (with default values)
        def replace_with_default(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.getenv(var_name, default)

        content = re.sub(r"\$\{(\w+):-([^}]+)\}", replace_with_default, content)

        # Handle ${VAR} syntax (without default)
        def replace_simple(match):
            var_name = match.group(1)
            return os.getenv(var_name, "")

        content = re.sub(r"\$\{(\w+)\}", replace_simple, content)

        return yaml.safe_load(content)

    def get_mcp_url(self, server: str) -> str:
        """Get URL for an MCP server."""
        mcp = self.config.get("mcps", {}).get(server, {})
        url = mcp.get("url", f"http://mcp-{server}:9001")
        # Ensure URL ends with /mcp for FastMCP HTTP transport
        if not url.endswith("/mcp"):
            url = url.rstrip("/") + "/mcp"
        return url

    def _get_client(self, server: str) -> Client:
        """Get or create FastMCP client for a server."""
        if server not in self._clients:
            url = self.get_mcp_url(server)
            transport = StreamableHttpTransport(url)
            self._clients[server] = Client(transport)
        return self._clients[server]

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

        # No approval needed for this tool - execute with retry for transient errors
        return await self._execute_tool_with_retry(server, tool, args, context)

    async def _execute_tool_with_retry(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> dict[str, Any]:
        """Execute tool with retry logic for transient errors.

        Uses exponential backoff: delay = base_delay * (2 ** attempt)
        So with base_delay=1.0: 1s, 2s, 4s delays between retries.

        Args:
            server: MCP server name
            tool: Tool name
            args: Tool arguments
            context: Execution context
            max_retries: Maximum number of retry attempts (default 3)
            base_delay: Base delay in seconds for exponential backoff (default 1.0)

        Returns:
            Tool result dict with success/error status
        """
        last_result = None

        for attempt in range(max_retries + 1):
            result = await self._execute_tool(server, tool, args, context)
            last_result = result

            # If successful or not retryable, return immediately
            if result.get("success", False):
                return result

            # Check if error is retryable
            if not result.get("retryable", False):
                return result

            # Don't retry after last attempt
            if attempt >= max_retries:
                logger.warning(
                    "mcp_tool_max_retries_exceeded",
                    server=server,
                    tool=tool,
                    attempts=attempt + 1,
                    error=result.get("error"),
                    error_type=result.get("error_type"),
                )
                # Add retry info to the result
                result["retry_attempts"] = attempt + 1
                result["max_retries_exceeded"] = True
                return result

            # Calculate delay with exponential backoff
            delay = base_delay * (2 ** attempt)
            logger.info(
                "mcp_tool_retry",
                server=server,
                tool=tool,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=result.get("error"),
                error_type=result.get("error_type"),
            )
            await asyncio.sleep(delay)

        # Should not reach here, but return last result as fallback
        return last_result or {"success": False, "error": "Unknown error", "error_type": MCPErrorType.FATAL, "retryable": False}

    async def _execute_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute tool via FastMCP client to MCP server."""
        url = self.get_mcp_url(server)

        # Extract workspace_id from args if present for better log context
        workspace_id = args.get("workspace_id")

        logger.info(
            "mcp_tool_executing",
            server=server,
            tool=tool,
            url=url,
            session_id=context.session_id,
            workspace_id=workspace_id,
            args=args,
        )

        try:
            client = self._get_client(server)

            # Use FastMCP client to call the tool
            async with client:
                result = await client.call_tool(tool, args)

                logger.debug(
                    "mcp_raw_result",
                    server=server,
                    tool=tool,
                    result_type=type(result).__name__,
                    result=str(result)[:500],
                )

                # FastMCP call_tool returns a list of content items
                # Each item typically has: type="text" and text=<json_string>
                result_dict = {"success": True}

                if isinstance(result, list) and len(result) > 0:
                    # Get first content item
                    first_item = result[0]
                    if hasattr(first_item, "text"):
                        # Parse JSON from text content
                        try:
                            result_dict = json.loads(first_item.text)
                        except json.JSONDecodeError:
                            result_dict = {"success": True, "content": first_item.text}
                    elif hasattr(first_item, "content"):
                        result_dict = {"success": True, "content": str(first_item.content)}
                    else:
                        result_dict = {"success": True, "data": str(first_item)}
                elif hasattr(result, "data"):
                    result_dict = result.data if isinstance(result.data, dict) else {"success": True, "data": result.data}
                elif hasattr(result, "content"):
                    # Handle text content response
                    if isinstance(result.content, list) and len(result.content) > 0:
                        first_content = result.content[0]
                        if hasattr(first_content, "text"):
                            try:
                                result_dict = json.loads(first_content.text)
                            except json.JSONDecodeError:
                                result_dict = {"success": True, "content": first_content.text}
                        else:
                            result_dict = {"success": True, "content": str(first_content)}
                    else:
                        result_dict = {"success": True, "content": str(result.content)}
                else:
                    result_dict = {"success": True, "result": str(result)}

                # Ensure we return a dict
                if not isinstance(result_dict, dict):
                    result_dict = {"success": True, "data": result_dict}

                # Check if the result indicates an error
                is_success = result_dict.get("success", True)
                if is_success:
                    logger.info(
                        "mcp_tool_completed",
                        server=server,
                        tool=tool,
                        workspace_id=workspace_id,
                        success=True,
                        result_preview=str(result_dict)[:200],
                    )
                else:
                    logger.warning(
                        "mcp_tool_returned_error",
                        server=server,
                        tool=tool,
                        workspace_id=workspace_id,
                        success=False,
                        error=result_dict.get("error", "Unknown error"),
                        result_preview=str(result_dict)[:200],
                    )
                return result_dict

        except Exception as e:
            # Classify the error
            error_type, retryable = classify_error(e)

            logger.error(
                "mcp_tool_error",
                server=server,
                tool=tool,
                workspace_id=workspace_id,
                error=str(e),
                error_type=error_type,
                retryable=retryable,
            )

            return {
                "success": False,
                "error": str(e),
                "error_type": error_type,
                "retryable": retryable,
            }

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

        # Extract workspace_id from args if present for better log context
        workspace_id = args.get("workspace_id")

        # Create approval record in DB
        approval_id = str(uuid.uuid4())

        # Get agent state for resumption
        agent_state = context.get_state() if hasattr(context, "get_state") else None

        logger.info(
            "approval_creating_record",
            tool=tool_name,
            session_id=context.session_id,
            workspace_id=workspace_id,
            danger_level=danger_level,
            has_agent_state=agent_state is not None,
        )

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
                "agent_state": agent_state,
            },
        )

        logger.info(
            "approval_requested",
            approval_id=approval_id,
            tool=tool_name,
            session_id=context.session_id,
            workspace_id=workspace_id,
            required_roles=required_roles,
            danger_level=danger_level,
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

    async def fetch_tools_from_server(self, server: str) -> list[dict]:
        """Fetch tool definitions from an MCP server.

        Uses FastMCP client to get actual tool schemas.

        Args:
            server: MCP server name

        Returns:
            List of tool definitions with proper schemas
        """
        try:
            client = self._get_client(server)
            async with client:
                tools = await client.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or f"Execute {tool.name}",
                        "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {
                            "type": "object",
                            "properties": {},
                        },
                    }
                    for tool in tools
                ]
        except Exception as e:
            logger.warning("fetch_tools_failed", server=server, error=str(e))
            return []

    def to_openai_tools(self, mcp_ids: list[str] | None = None) -> list[dict]:
        """Convert tools to OpenAI function calling format.

        Note: This is a synchronous fallback using config-defined tools.
        For full schemas, use to_openai_tools_async().

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
                # Get parameters from config if available, otherwise empty
                params = tool.get("parameters", {
                    "type": "object",
                    "properties": {},
                    "required": [],
                })
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{mcp_id}_{tool['name']}",
                        "description": tool.get("description", f"Execute {tool['name']}"),
                        "parameters": params,
                    },
                })

        return openai_tools

    async def to_openai_tools_async(self, mcp_ids: list[str] | None = None) -> list[dict]:
        """Convert tools to OpenAI function calling format with full schemas.

        Fetches actual tool schemas from MCP servers.

        Args:
            mcp_ids: Optional list of MCP IDs. If None, include all.

        Returns:
            List of tool definitions in OpenAI format
        """
        if mcp_ids is None:
            mcp_ids = list(self.config.get("mcps", {}).keys())

        openai_tools = []
        for mcp_id in mcp_ids:
            # Fetch actual tool schemas from MCP server
            server_tools = await self.fetch_tools_from_server(mcp_id)

            if server_tools:
                # Use actual schemas from server
                for tool in server_tools:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": f"{mcp_id}_{tool['name']}",
                            "description": tool.get("description", f"Execute {tool['name']}"),
                            "parameters": tool.get("parameters", {
                                "type": "object",
                                "properties": {},
                            }),
                        },
                    })
            else:
                # Fallback to config-defined tools
                mcp = self.config.get("mcps", {}).get(mcp_id, {})
                for tool in mcp.get("tools", []):
                    params = tool.get("parameters", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    })
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": f"{mcp_id}_{tool['name']}",
                            "description": tool.get("description", f"Execute {tool['name']}"),
                            "parameters": params,
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
