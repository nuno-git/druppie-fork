"""Agent runtime - clean abstraction for running agents.

Usage:
    result = await Agent("router").run("Create a todo app")
    result = await Agent("developer").run("Implement the API", context={...})
"""

import json
import os
import time
from typing import Any

import structlog
import yaml

from druppie.agents.models import AgentDefinition
from druppie.llm import get_llm_service
from druppie.core.execution_context import get_current_context

logger = structlog.get_logger()


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class AgentNotFoundError(AgentError):
    """Agent definition not found."""
    pass


class AgentMaxIterationsError(AgentError):
    """Agent exceeded maximum iterations."""
    pass


class Agent:
    """Clean agent abstraction.

    Handles:
    - Loading YAML definition
    - Building messages with system prompt
    - Running tool-calling loop
    - Parsing output
    - Tracking events and LLM calls via ExecutionContext

    The agent can call any MCP tool. If it calls hitl:ask,
    execution pauses automatically via LangGraph's interrupt().
    """

    _definitions_path: str = None
    _cache: dict[str, "AgentDefinition"] = {}

    def __init__(self, agent_id: str):
        """Initialize agent by ID.

        Args:
            agent_id: Agent identifier (e.g., "router", "developer")
        """
        self.id = agent_id
        self.definition = self._load_definition(agent_id)
        self._llm = None
        self._mcp_client = None

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions."""
        cls._definitions_path = path
        cls._cache.clear()

    @classmethod
    def _get_definitions_path(cls) -> str:
        """Get the path to agent definitions."""
        if cls._definitions_path:
            return cls._definitions_path
        # Default: druppie/agents/definitions/
        return os.path.join(os.path.dirname(__file__), "definitions")

    @classmethod
    def _load_definition(cls, agent_id: str) -> AgentDefinition:
        """Load agent definition from YAML."""
        if agent_id in cls._cache:
            return cls._cache[agent_id]

        path = os.path.join(cls._get_definitions_path(), f"{agent_id}.yaml")

        if not os.path.exists(path):
            raise AgentNotFoundError(f"Agent '{agent_id}' not found at {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        definition = AgentDefinition(**data)
        cls._cache[agent_id] = definition

        logger.debug("agent_definition_loaded", agent_id=agent_id)
        return definition

    @classmethod
    def list_agents(cls) -> list[str]:
        """List available agent IDs."""
        path = cls._get_definitions_path()
        if not os.path.exists(path):
            return []
        return [
            f.replace(".yaml", "").replace(".yml", "")
            for f in os.listdir(path)
            if f.endswith((".yaml", ".yml"))
        ]

    @property
    def llm(self):
        """Get LLM service (lazy loaded).

        Note: Currently uses global LLM config from environment.
        Agent-specific model/temperature settings in YAML are ignored.
        """
        if self._llm is None:
            self._llm = get_llm_service().get_llm()
        return self._llm

    @property
    def mcp_client(self):
        """Get MCP client (lazy loaded)."""
        if self._mcp_client is None:
            from druppie.api.deps import get_db
            from druppie.core.mcp_client import get_mcp_client
            db = next(get_db())
            self._mcp_client = get_mcp_client(db)
        return self._mcp_client

    async def run(self, prompt: str, context: dict = None) -> Any:
        """Run the agent with the given prompt.

        Args:
            prompt: User prompt or task description
            context: Optional context dict (previous results, etc.)

        Returns:
            Parsed result from agent's final response

        Note:
            If agent calls hitl:ask, execution pauses automatically
            via LangGraph's interrupt() inside the tool.
        """
        # Get execution context for event tracking
        exec_ctx = get_current_context()

        messages = [
            {"role": "system", "content": self.definition.system_prompt},
            {"role": "user", "content": self._build_prompt(prompt, context)},
        ]

        # Get tools for this agent's MCPs with full schemas from servers
        mcp_ids = self.definition.get_mcp_names() if hasattr(self.definition, 'get_mcp_names') else self.definition.mcps
        tools = await self.mcp_client.to_openai_tools_async(mcp_ids)

        # Build a mapping of tool_name -> required_fields for validation
        tool_schemas: dict[str, dict] = {}
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                tool_name = func.get("name", "")
                params = func.get("parameters", {})
                tool_schemas[tool_name] = {
                    "required": params.get("required", []),
                    "properties": params.get("properties", {}),
                }

        max_iterations = self.definition.max_iterations or 10

        logger.info(
            "agent_run_start",
            agent_id=self.id,
            prompt_length=len(prompt),
            tools_count=len(tools),
        )

        # Emit agent started event
        if exec_ctx:
            exec_ctx.agent_started(self.id, prompt)

        for iteration in range(max_iterations):
            start_time = time.time()
            response = await self.llm.achat(messages, tools)
            duration_ms = int((time.time() - start_time) * 1000)

            # Track LLM call
            if exec_ctx:
                exec_ctx.add_llm_call(
                    agent_id=self.id,
                    iteration=iteration,
                    messages=messages.copy(),
                    response=response,
                    tools=tools,
                    duration_ms=duration_ms,
                )

            # No tool calls = agent is done
            if not response.tool_calls:
                logger.info(
                    "agent_run_complete",
                    agent_id=self.id,
                    iterations=iteration + 1,
                )
                if exec_ctx:
                    exec_ctx.agent_completed(self.id, iteration + 1, success=True)
                return self._parse_output(response.content)

            # Execute tools
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})

                logger.debug(
                    "agent_tool_call",
                    agent_id=self.id,
                    tool=tool_name,
                    iteration=iteration,
                )

                # Emit tool call event
                if exec_ctx:
                    exec_ctx.tool_call(self.id, tool_name, tool_args)

                # Convert OpenAI format to MCP format (hitl_ask -> hitl:ask)
                mcp_tool_name = tool_name.replace("_", ":", 1)

                # Parse server:tool format
                if ":" in mcp_tool_name:
                    server, tool = mcp_tool_name.split(":", 1)
                else:
                    server = "coding"
                    tool = mcp_tool_name

                # Inject context into tool args
                # Only inject fields that are accepted by the MCP tool schemas
                if exec_ctx:
                    injected = {}
                    if server == "coding":
                        # Coding tools only accept: workspace_id, path, content
                        # Do NOT inject project_id, workspace_path, branch - not in MCP schemas
                        if "workspace_id" not in tool_args and exec_ctx.workspace_id:
                            tool_args["workspace_id"] = exec_ctx.workspace_id
                            injected["workspace_id"] = exec_ctx.workspace_id
                    if server == "hitl" and "session_id" not in tool_args:
                        tool_args["session_id"] = exec_ctx.session_id
                        injected["session_id"] = exec_ctx.session_id

                    if injected:
                        logger.debug(
                            "context_injected_into_tool",
                            agent_id=self.id,
                            tool=mcp_tool_name,
                            injected_fields=list(injected.keys()),
                            injected_values=injected,
                        )

                # Validate required arguments before MCP call
                schema = tool_schemas.get(tool_name, {})
                required_fields = schema.get("required", [])
                provided_args = set(tool_args.keys())
                missing_fields = [f for f in required_fields if f not in provided_args]

                if missing_fields:
                    missing_field = missing_fields[0]  # Report first missing field
                    logger.warning(
                        "agent_tool_validation_error",
                        agent_id=self.id,
                        tool=tool_name,
                        missing_field=missing_field,
                        missing_fields=missing_fields,
                        provided_args=list(provided_args),
                        required_args=required_fields,
                    )
                    result = {
                        "success": False,
                        "error": f"Missing required argument: {missing_field}",
                        "error_type": "validation",
                        "recoverable": True,
                        "tool": tool_name,
                        "provided_args": list(provided_args),
                        "required_args": list(required_fields),
                        "suggested_fix": f"Please call {tool_name} again with argument: {missing_field}",
                    }
                else:
                    # Execute tool via MCP client
                    result = await self.mcp_client.call_tool(server, tool, tool_args, exec_ctx, agent_id=self.id)

                # Check if paused for approval
                if result.get("status") == "paused":
                    # Return paused state - execution will resume after approval
                    logger.info("agent_paused_for_approval", agent_id=self.id, tool=mcp_tool_name)
                    return {
                        "paused": True,
                        "approval_id": result.get("approval_id"),
                        "tool": mcp_tool_name,
                        "iteration": iteration,
                    }

                # Check for MCP tool errors (success=False or error field)
                is_error = result.get("success") is False or "error" in result
                if is_error:
                    error_msg = result.get("error", "Unknown MCP tool error")
                    error_type = result.get("error_type", "mcp_error")
                    is_recoverable = result.get("recoverable", True)

                    logger.warning(
                        "agent_tool_error",
                        agent_id=self.id,
                        tool=mcp_tool_name,
                        error=error_msg,
                        error_type=error_type,
                        recoverable=is_recoverable,
                        iteration=iteration,
                    )

                    # Emit tool error event
                    if exec_ctx:
                        exec_ctx.tool_error(self.id, mcp_tool_name, error_msg)

                    # Format error result clearly for the agent
                    # This helps the agent understand what went wrong and decide how to proceed
                    result = {
                        "success": False,
                        "error": error_msg,
                        "error_type": error_type,
                        "recoverable": is_recoverable,
                        "tool": mcp_tool_name,
                        "original_args": tool_args,
                        "hint": "Check the error message and either retry with corrected arguments or try a different approach.",
                    }

                # Add tool result to messages
                # IMPORTANT: Use json.dumps for proper JSON format (not Python repr)
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": tool_call.get("id", f"call_{iteration}"),
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{iteration}"),
                    "content": json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                })

        logger.warning("agent_max_iterations", agent_id=self.id)
        if exec_ctx:
            exec_ctx.agent_error(self.id, f"Exceeded {max_iterations} iterations")
        raise AgentMaxIterationsError(
            f"Agent '{self.id}' exceeded {max_iterations} iterations"
        )

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        """Build the full prompt with context."""
        if not context:
            return prompt

        context_str = "\n".join(
            f"- {key}: {value}" for key, value in context.items()
        )
        return f"""CONTEXT:
{context_str}

TASK:
{prompt}"""

    def _parse_output(self, content: str) -> Any:
        """Parse agent's final output.

        Tries to parse as JSON using multiple extraction strategies,
        falls back to raw content.
        """
        import json
        import re

        if not content:
            return {}

        content = content.strip()

        # Strategy 1: Try direct JSON parse first (ideal case)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from markdown code blocks
        # Handles ```json ... ``` or ``` ... ```
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find JSON object in text (look for {...})
        # This handles cases where LLM adds text before/after JSON
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 4: Find JSON array in text (look for [...])
        array_match = re.search(r"\[[\s\S]*\]", content)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 5: Try to fix common JSON issues
        # Remove trailing commas before } or ]
        fixed_content = re.sub(r",\s*([}\]])", r"\1", content)
        try:
            return json.loads(fixed_content)
        except json.JSONDecodeError:
            pass

        # Fallback: Return as string content
        logger.debug(
            "json_parse_failed",
            agent_id=self.id,
            content_preview=content[:200] if len(content) > 200 else content,
        )
        return {"content": content}

    def __repr__(self) -> str:
        return f"Agent({self.id!r})"
