"""MCP Client - FastMCP client for MCP servers with approval checking.

This client:
1. Loads MCP configuration from mcp_config.yaml
2. Checks tool approval requirements before execution
3. Pauses execution and creates approval records when needed
4. Executes tools via FastMCP Client to MCP server containers
5. Records tool calls in the database for debugging/tracing
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import UUID

import structlog
import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from druppie.db.crud import create_tool_call, update_tool_call


# =============================================================================
# ERROR CLASSIFICATION
# =============================================================================


class MCPErrorType:
    """Error type constants for MCP tool execution."""
    TRANSIENT = "transient"  # Connection issues, timeouts - should retry
    PERMISSION = "permission"  # 403, approval needed - don't retry
    FATAL = "fatal"  # Invalid args, tool not found - don't retry
    VALIDATION = "validation"  # Argument validation errors - recoverable by LLM


def classify_error(error: Exception) -> tuple[str, bool, bool]:
    """Classify an error and determine if it's retryable or recoverable.

    Args:
        error: The exception to classify

    Returns:
        Tuple of (error_type, retryable, recoverable)
        - retryable: System should auto-retry (for transient errors)
        - recoverable: LLM can fix and retry (for validation errors)
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
        return MCPErrorType.TRANSIENT, True, False

    if isinstance(error, ConnectionError) or isinstance(error, OSError):
        return MCPErrorType.TRANSIENT, True, False

    for indicator in transient_indicators:
        if indicator in error_str:
            return MCPErrorType.TRANSIENT, True, False

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
            return MCPErrorType.PERMISSION, False, False

    # Validation errors - argument/parameter issues that LLM can fix
    validation_indicators = [
        "missing required",
        "validation error",
        "required argument",
        "invalid argument format",
        "required field",
        "missing field",
        "invalid value for",
        "expected type",
        "argument must be",
        "parameter must be",
    ]

    for indicator in validation_indicators:
        if indicator in error_str:
            return MCPErrorType.VALIDATION, False, True

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
        "schema",
        "type error",
        "value error",
    ]

    for indicator in fatal_indicators:
        if indicator in error_str:
            return MCPErrorType.FATAL, False, False

    # Default to fatal for unknown errors (safer to not retry)
    return MCPErrorType.FATAL, False, False

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession
    from druppie.core.execution_context import ExecutionContext
    from druppie.core.models import AgentDefinition

logger = structlog.get_logger()


class MCPClient:
    """FastMCP client for MCP servers with approval checking."""

    def __init__(self, db: "DBSession"):
        """Initialize MCP client.

        Args:
            db: Database session
        """
        self.db = db
        self._config: dict | None = None
        self._clients: dict[str, Client] = {}

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

    def is_builtin_server(self, server: str) -> bool:
        """Check if a server is marked as built-in (no external MCP server)."""
        mcp = self.config.get("mcps", {}).get(server, {})
        return mcp.get("builtin", False)

    def requires_approval(
        self,
        server: str,
        tool: str,
        agent_definition: "AgentDefinition | None" = None,
    ) -> tuple[bool, str | None]:
        """Check if tool requires approval and what role can approve.

        LAYERED APPROVAL SYSTEM (per goal.md):
        1. First check agent's approval_overrides (if agent_definition provided)
        2. Fall back to global defaults from mcp_config.yaml

        Args:
            server: MCP server name
            tool: Tool name
            agent_definition: Optional agent definition to check for overrides

        Returns:
            Tuple of (requires_approval, required_role)
            - required_role is singular string (not array) per goal.md
        """
        from druppie.core.models import AgentDefinition

        # Step 1: Check agent-specific override (if agent_definition provided)
        if agent_definition is not None:
            override = agent_definition.get_approval_override(server, tool)
            if override is not None:
                logger.debug(
                    "using_agent_approval_override",
                    agent_id=agent_definition.id,
                    tool=f"{server}:{tool}",
                    requires_approval=override.requires_approval,
                    required_role=override.required_role,
                )
                return (override.requires_approval, override.required_role)

        # Step 2: Fall back to global config from mcp_config.yaml
        config = self.get_tool_config(server, tool)
        requires = config.get("requires_approval", False)

        # Support both old "required_roles" (array) and new "required_role" (string)
        # Prefer new "required_role" if present
        required_role = config.get("required_role")
        if required_role is None:
            # Fall back to old format - take first role from array
            old_roles = config.get("required_roles", [])
            required_role = old_roles[0] if old_roles else None

        return (requires, required_role)

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
        agent_id: str | None = None,
        agent_definition: "AgentDefinition | None" = None,
    ) -> dict[str, Any]:
        """Call MCP tool, checking for approval requirements.

        LAYERED APPROVAL SYSTEM (per goal.md):
        1. Check agent's approval_overrides first (if agent_definition provided)
        2. Fall back to global defaults from mcp_config.yaml

        IMPORTANT: AI executes tools, so user ALWAYS confirms for
        approval-required tools (even if user has the role).

        Args:
            server: MCP server name (coding, docker, hitl)
            tool: Tool name
            args: Tool arguments
            context: Execution context with session/user info
            agent_id: ID of the agent making this call (for approval tracking)
            agent_definition: Optional agent definition for layered approval

        Returns:
            Tool result or paused status if approval required
        """
        tool_name = f"{server}:{tool}"

        # Create tool_call record in database for tracing
        tool_call_record = None
        try:
            agent_run_id = UUID(context.current_agent_run_id) if context.current_agent_run_id else None
            tool_call_record = create_tool_call(
                self.db,
                session_id=UUID(context.session_id),
                agent_run_id=agent_run_id,
                mcp_server=server,
                tool_name=tool,
                arguments=args,
            )
        except Exception as e:
            # Don't fail the tool call if we can't record it
            logger.warning("tool_call_record_failed", error=str(e), tool=tool_name)

        # Use layered approval system: agent overrides > global config
        needs_approval, required_role = self.requires_approval(
            server, tool, agent_definition
        )

        if needs_approval:
            # Check if we have a cached result from a recently approved execution
            # This happens when resuming after MCP tool approval - the agent re-runs
            # and tries to call the same tool again
            if hasattr(context, "completed_tool_results") and context.completed_tool_results:
                cached_result = context.completed_tool_results.get(tool_name)
                if cached_result is not None:
                    logger.info(
                        "returning_cached_tool_result",
                        tool=tool_name,
                        session_id=context.session_id,
                    )
                    # Clear the cached result so it's not reused again
                    del context.completed_tool_results[tool_name]
                    # Update tool_call record as completed
                    if tool_call_record:
                        try:
                            update_tool_call(
                                self.db,
                                tool_call_record.id,
                                status="completed",
                                result=json.dumps(cached_result)[:4000] if cached_result else None,
                            )
                        except Exception as e:
                            logger.warning("tool_call_update_failed", error=str(e))

                    # Emit app_running event for docker:run cached results
                    # This ensures the deployment URL is persisted even when returning cached result
                    if server == "docker" and tool == "run" and isinstance(cached_result, dict):
                        app_url = cached_result.get("url") or cached_result.get("app_url")
                        if app_url and cached_result.get("success", True):
                            context.app_running(
                                container_name=cached_result.get("container_name") or "",
                                url=app_url,
                                port=cached_result.get("port") or 0,
                                image_name=cached_result.get("image_name"),
                            )
                            # Also broadcast via WebSocket
                            try:
                                from druppie.api.websocket import emit_deployment_complete
                                loop = asyncio.get_running_loop()
                                loop.create_task(emit_deployment_complete(
                                    session_id=context.session_id,
                                    url=app_url,
                                    container_name=cached_result.get("container_name"),
                                    port=cached_result.get("port"),
                                    project_id=context.project_id,
                                ))
                            except Exception as e:
                                logger.debug("deployment_broadcast_from_cache_failed", error=str(e))

                    return cached_result

            # ALWAYS request approval - AI is executing, user must confirm
            # Convert required_role to list for backwards compatibility
            required_roles = [required_role] if required_role else []
            # Update tool_call record as pending approval
            if tool_call_record:
                try:
                    update_tool_call(self.db, tool_call_record.id, status="pending_approval")
                except Exception as e:
                    logger.warning("tool_call_update_failed", error=str(e))
            return await self._request_approval(
                server, tool, args, required_roles, "low", context, agent_id
            )

        # No approval needed for this tool - execute with retry for transient errors
        # Update tool_call record as executing
        if tool_call_record:
            try:
                update_tool_call(self.db, tool_call_record.id, status="executing")
            except Exception as e:
                logger.warning("tool_call_update_failed", error=str(e))

        result = await self._execute_tool_with_retry(server, tool, args, context)

        # Update tool_call record with result
        if tool_call_record:
            try:
                is_success = result.get("success", False)
                update_tool_call(
                    self.db,
                    tool_call_record.id,
                    status="completed" if is_success else "failed",
                    result=json.dumps(result)[:4000] if is_success else None,
                    error_message=result.get("error")[:4000] if result.get("error") else None,
                )
            except Exception as e:
                logger.warning("tool_call_update_failed", error=str(e))

        return result

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
        return last_result or {"success": False, "error": "Unknown error", "error_type": MCPErrorType.FATAL, "retryable": False, "recoverable": False}

    async def _execute_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute tool via FastMCP client to MCP server, or builtin handler."""
        # Check if this is a builtin server (like hitl)
        if self.is_builtin_server(server):
            return await self._execute_builtin_tool(server, tool, args, context)

        url = self.get_mcp_url(server)

        # Extract workspace_id from args if present for better log context
        workspace_id = args.get("workspace_id")

        logger.info(
            "mcp_tool_executing",
            server=server,
            tool=tool,
            url=url,
            session_id=context.session_id if context else None,
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

                    # Emit deployment_complete event when docker:run succeeds
                    # This notifies the user in real-time about the deployed app URL
                    if server == "docker" and tool == "run":
                        app_url = result_dict.get("url") or result_dict.get("app_url")
                        if app_url:
                            container_name = result_dict.get("container_name")
                            port = result_dict.get("port")

                            # Persist app_running event to database for history
                            # This ensures the deployment URL is shown on page refresh
                            context.app_running(
                                container_name=container_name or "",
                                url=app_url,
                                port=port or 0,
                                image_name=result_dict.get("image_name"),
                            )

                            # Use direct WebSocket broadcast for reliability
                            # (context.emit_event may not always be configured)
                            try:
                                from druppie.api.websocket import emit_deployment_complete
                                loop = asyncio.get_running_loop()
                                loop.create_task(emit_deployment_complete(
                                    session_id=context.session_id,
                                    url=app_url,
                                    container_name=container_name,
                                    port=port,
                                    project_id=context.project_id,
                                ))
                            except RuntimeError:
                                # No running event loop - can't broadcast
                                logger.debug("no_event_loop_for_deployment_broadcast")
                            except Exception as e:
                                logger.warning("deployment_complete_broadcast_failed", error=str(e))
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
            error_type, retryable, recoverable = classify_error(e)

            # Use appropriate log level based on error type
            if error_type == MCPErrorType.VALIDATION:
                logger.warning(
                    "mcp_tool_validation_error",
                    server=server,
                    tool=tool,
                    workspace_id=workspace_id,
                    error=str(e),
                    recoverable=True,
                )
            else:
                logger.error(
                    "mcp_tool_error",
                    server=server,
                    tool=tool,
                    workspace_id=workspace_id,
                    error=str(e),
                    error_type=error_type,
                    retryable=retryable,
                    recoverable=recoverable,
                )

            return {
                "success": False,
                "error": str(e),
                "error_type": error_type,
                "retryable": retryable,
                "recoverable": recoverable,
            }

    async def _execute_builtin_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute a built-in tool (not via HTTP to external MCP server).

        Currently supports:
        - hitl server: ask_question, ask_choice, progress, notify
        """
        logger.info(
            "builtin_tool_executing",
            server=server,
            tool=tool,
            session_id=context.session_id if context else None,
        )

        try:
            if server == "hitl":
                return await self._execute_hitl_tool(tool, args, context)
            else:
                return {
                    "success": False,
                    "error": f"Unknown builtin server: {server}",
                    "error_type": MCPErrorType.FATAL,
                    "retryable": False,
                    "recoverable": False,
                }
        except Exception as e:
            logger.error(
                "builtin_tool_error",
                server=server,
                tool=tool,
                error=str(e),
                exc_info=True,
            )
            return {
                "success": False,
                "error": str(e),
                "error_type": MCPErrorType.FATAL,
                "retryable": False,
                "recoverable": False,
            }

    async def _execute_hitl_tool(
        self,
        tool: str,
        args: dict[str, Any],
        context: "ExecutionContext",
    ) -> dict[str, Any]:
        """Execute a built-in HITL tool.

        Supported tools:
        - ask_question: Ask user a free-form question (pauses workflow)
        - ask_choice: Ask user a multiple choice question (pauses workflow)
        - progress: Send progress update to user (non-blocking)
        - notify: Send notification to user (non-blocking)
        """
        from druppie.agents.hitl import ask_question, ask_multiple_choice_question

        agent_id = context.current_agent_id if hasattr(context, 'current_agent_id') else "unknown"

        if tool == "ask_question":
            # Ask user a free-form question
            result = await ask_question(
                question=args.get("question", ""),
                context=context,
                agent_id=agent_id,
                question_context=args.get("context"),
            )
            # HITL tools return paused status, which is success for the agent
            return result

        elif tool == "ask_choice":
            # Ask user a multiple choice question
            result = await ask_multiple_choice_question(
                question=args.get("question", ""),
                choices=args.get("choices", []),
                context=context,
                agent_id=agent_id,
                allow_other=args.get("allow_other", True),
                question_context=args.get("context"),
            )
            return result

        else:
            return {
                "success": False,
                "error": f"Unknown HITL tool: {tool}",
                "error_type": MCPErrorType.FATAL,
                "retryable": False,
                "recoverable": False,
            }

    async def _request_approval(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        required_roles: list[str],
        danger_level: str,
        context: "ExecutionContext",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Request approval and pause execution."""
        from druppie.db import crud

        tool_name = f"{server}:{tool}"

        # Include workspace context from ExecutionContext in the arguments
        # This ensures workspace_id is available when resuming after approval
        # IMPORTANT: Only inject for tools that actually accept these parameters!
        args_with_context = dict(args)

        # Coding tools use workspace_id
        # Docker:build and docker:register_workspace use workspace_id
        # Docker:run, docker:stop, docker:logs, docker:list_containers do NOT use workspace_id
        tools_with_workspace = {
            "coding": True,  # All coding tools use workspace_id
            "docker:build": True,
            "docker:register_workspace": True,
        }
        should_inject_workspace = (
            server == "coding" or
            tool_name in tools_with_workspace
        )

        if should_inject_workspace:
            if context.workspace_id and "workspace_id" not in args_with_context:
                args_with_context["workspace_id"] = context.workspace_id
            if context.project_id and "project_id" not in args_with_context:
                args_with_context["project_id"] = context.project_id
            if context.workspace_path and "workspace_path" not in args_with_context:
                args_with_context["workspace_path"] = context.workspace_path
            if context.branch and "branch" not in args_with_context:
                args_with_context["branch"] = context.branch
        else:
            # Remove workspace_id if LLM incorrectly added it to a tool that doesn't use it
            for field in ["workspace_id", "project_id", "workspace_path", "branch"]:
                if field in args_with_context:
                    del args_with_context[field]
                    logger.debug(
                        "removed_invalid_context_field",
                        tool=tool_name,
                        field=field,
                    )

        # Extract workspace_id from args for logging
        workspace_id = args_with_context.get("workspace_id")

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
                "arguments": args_with_context,
                "required_roles": required_roles or ["developer", "admin"],
                "danger_level": danger_level,
                "description": f"Execute {tool_name} with args: {json.dumps(args_with_context)[:200]}",
                "status": "pending",
                "agent_id": agent_id,
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
                "type": "approval_required",
                "approval_id": approval_id,
                "tool": tool_name,
                "agent_id": agent_id,
                "args": args_with_context,
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
        """Emit approval request via WebSocket broadcast."""
        try:
            # Broadcast to WebSocket role rooms for cross-user notifications
            # This runs in a separate task to not block the current execution
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._broadcast_approval_to_roles(approval))
            except RuntimeError:
                # No running event loop - we're in sync context
                # The context.emit_event callback should handle this
                pass

        except Exception as e:
            logger.warning("approval_request_emit_failed", error=str(e))

    async def _broadcast_approval_to_roles(self, approval) -> None:
        """Broadcast approval request to WebSocket role rooms."""
        try:
            from druppie.api.websocket import emit_approval_request
            await emit_approval_request(
                approval_id=str(approval.id),  # Convert UUID to string for JSON serialization
                session_id=str(approval.session_id),  # Convert UUID to string for JSON serialization
                tool_name=approval.tool_name,
                required_roles=approval.required_roles or [],
                details={
                    "args": approval.arguments,
                    "danger_level": approval.danger_level,
                    "description": approval.description,
                },
                agent_id=approval.agent_id,  # Pass agent_id for frontend attribution
            )
            logger.debug(
                "approval_broadcast_to_roles",
                approval_id=approval.id,
                roles=approval.required_roles,
                agent_id=approval.agent_id,
            )
        except Exception as e:
            logger.warning("approval_broadcast_to_roles_failed", error=str(e))

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
        full_tool_name = f"{server}:{tool}"

        # Determine which context params this tool needs
        # docker:build needs workspace_path, coding tools need workspace_id
        tools_needing_workspace_path = {"docker:build"}
        tools_needing_workspace_id = {"coding"}  # All coding tools

        # Start with all arguments from approval
        tool_args = dict(approval.arguments or {})

        # Filter out context params that aren't needed by this specific tool
        # project_id is never passed to tools (for audit only)
        if "project_id" in tool_args:
            del tool_args["project_id"]

        # Keep workspace_path only for tools that need it
        if full_tool_name not in tools_needing_workspace_path:
            if "workspace_path" in tool_args:
                del tool_args["workspace_path"]

        # branch is only for context, not passed to tools
        if "branch" in tool_args:
            del tool_args["branch"]

        # Inject workspace context from execution context if not already present
        if full_tool_name in tools_needing_workspace_path:
            if "workspace_path" not in tool_args and context and context.workspace_path:
                tool_args["workspace_path"] = context.workspace_path
            if "workspace_id" not in tool_args and context and context.workspace_id:
                tool_args["workspace_id"] = context.workspace_id

        if server in tools_needing_workspace_id:
            if "workspace_id" not in tool_args and context and context.workspace_id:
                tool_args["workspace_id"] = context.workspace_id

        # Execute the tool
        return await self._execute_tool(server, tool, tool_args, context)

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


# =============================================================================
# TOOL DESCRIPTION GENERATION
# =============================================================================


def generate_tool_descriptions(agent_mcps: list[str] | dict[str, list[str]]) -> str:
    """Generate tool descriptions for agent system prompt from MCP config.

    This function dynamically generates tool descriptions based on the agent's
    mcps configuration. It reads from mcp_config.yaml and formats the tool
    information for inclusion in the agent's system prompt.

    Args:
        agent_mcps: Either a list of MCP names (all tools allowed) or a dict
                    mapping MCP names to lists of specific tool names.
                    Examples:
                    - ["coding", "hitl"] - all tools from these MCPs
                    - {"coding": ["read_file"], "hitl": ["ask_question"]} - specific tools

    Returns:
        Formatted string with tool descriptions for system prompt
    """
    # Load MCP config
    config_path = Path(__file__).parent / "mcp_config.yaml"
    with open(config_path) as f:
        content = f.read()

    # Handle ${VAR:-default} syntax
    def replace_with_default(match):
        var_name = match.group(1)
        default = match.group(2)
        return os.getenv(var_name, default)

    content = re.sub(r"\$\{(\w+):-([^}]+)\}", replace_with_default, content)

    # Handle ${VAR} syntax
    def replace_simple(match):
        var_name = match.group(1)
        return os.getenv(var_name, "")

    content = re.sub(r"\$\{(\w+)\}", replace_simple, content)

    config = yaml.safe_load(content)

    # Generate tool descriptions
    sections = []

    # Add MCP tools based on agent's mcps configuration
    # Handle both list format (all tools) and dict format (specific tools)
    if isinstance(agent_mcps, list):
        # Simple list format - include all tools from each MCP
        for server_name in agent_mcps:
            mcp = config.get("mcps", {}).get(server_name, {})
            if not mcp:
                continue

            server_tools = mcp.get("tools", [])
            if not server_tools:
                continue

            sections.append(f"  {server_name.upper()} TOOLS ({server_name}:):")
            for tool in server_tools:
                _add_tool_to_sections(tool, server_name, sections)
            sections.append("")
    else:
        # Dict format - include only specified tools
        for server_name, tool_names in agent_mcps.items():
            mcp = config.get("mcps", {}).get(server_name, {})
            if not mcp:
                continue

            server_tools = mcp.get("tools", [])
            if not server_tools:
                continue

            sections.append(f"  {server_name.upper()} TOOLS ({server_name}:):")
            for tool in server_tools:
                # Only include tools that the agent has access to
                if tool_names and tool["name"] not in tool_names:
                    continue
                _add_tool_to_sections(tool, server_name, sections)
            sections.append("")

    return "\n".join(sections)


def _add_tool_to_sections(tool: dict, server_name: str, sections: list[str]) -> None:
    """Add a single tool's description to the sections list.

    Helper function for generate_tool_descriptions.

    Args:
        tool: Tool configuration from mcp_config.yaml
        server_name: Name of the MCP server
        sections: List to append formatted tool description to
    """
    tool_name = f"{server_name}:{tool['name']}"
    sections.append(f"  - {tool_name}: {tool.get('description', '')}")

    # Add approval requirement
    if tool.get("requires_approval"):
        required_role = tool.get("required_role", "developer")
        sections.append(f"    (REQUIRES APPROVAL by {required_role})")

    # Add parameter info if available
    params = tool.get("parameters", {})
    if params.get("properties"):
        required = params.get("required", [])
        if required:
            sections.append(f"    REQUIRED: {', '.join(required)}")
        optional = [k for k in params["properties"].keys() if k not in required]
        if optional:
            sections.append(f"    OPTIONAL: {', '.join(optional)}")
