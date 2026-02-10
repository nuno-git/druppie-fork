"""Agent runtime - clean abstraction for running agents.

Usage:
    agent = Agent("router", db=db_session)
    result = await agent.run("Create a todo app", session_id=uuid, agent_run_id=uuid)

Tool Execution:
    All tools are executed via ToolExecutor:
    - Builtin tools (done, make_plan) - executed directly
    - HITL tools (hitl_ask_question) - creates Question record, pauses
    - MCP tools - checks approval, executes via MCPHttp

    Agent only completes when it calls the `done` tool.
"""

import json
import os
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
import yaml

from druppie.agents.builtin_tools import DEFAULT_BUILTIN_TOOLS, is_builtin_tool
from druppie.core.mcp_config import MCPConfig
from druppie.domain.agent_definition import AgentDefinition
from druppie.execution.mcp_http import MCPHttp
from druppie.execution.tool_executor import ToolCallStatus, ToolExecutor
from druppie.llm import get_llm_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

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
    - Running tool-calling loop via ToolExecutor
    - Agent only completes when calling `done` tool

    All tool execution goes through ToolExecutor.
    """

    _definitions_path: str = None
    _cache: dict[str, "AgentDefinition"] = {}
    _common_prompt: str | None = None

    def __init__(self, agent_id: str, db: "DBSession | None" = None):
        """Initialize agent by ID.

        Args:
            agent_id: Agent identifier (e.g., "router", "developer")
            db: Database session (required for tool execution)
        """
        self.id = agent_id
        self.definition = self._load_definition(agent_id)
        self._db = db
        self._llm = None
        self._tool_executor = None
        self._mcp_config = None

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions."""
        cls._definitions_path = path
        cls._cache.clear()
        cls._common_prompt = None

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
    def _load_common_prompt(cls) -> str:
        """Load shared prompt instructions from _common.md."""
        if cls._common_prompt is not None:
            return cls._common_prompt

        path = os.path.join(cls._get_definitions_path(), "_common.md")
        if os.path.exists(path):
            with open(path, "r") as f:
                cls._common_prompt = f.read().strip()
        else:
            cls._common_prompt = ""

        return cls._common_prompt

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
    def db(self) -> "DBSession":
        """Get database session (lazy loaded if not provided)."""
        if self._db is None:
            from druppie.api.deps import get_db
            self._db = next(get_db())
        return self._db

    @property
    def llm(self):
        """Get LLM service (lazy loaded)."""
        if self._llm is None:
            self._llm = get_llm_service().get_llm()
        return self._llm

    @property
    def mcp_config(self) -> MCPConfig:
        """Get MCP configuration (lazy loaded)."""
        if self._mcp_config is None:
            self._mcp_config = MCPConfig()
        return self._mcp_config

    @property
    def tool_executor(self) -> ToolExecutor:
        """Get tool executor (lazy loaded)."""
        if self._tool_executor is None:
            mcp_http = MCPHttp(self.mcp_config)
            self._tool_executor = ToolExecutor(self.db, mcp_http, self.mcp_config)
        return self._tool_executor

    async def run(
        self,
        prompt: str,
        session_id: UUID | str,
        agent_run_id: UUID | str,
        context: dict = None,
    ) -> Any:
        """Run the agent with the given prompt.

        Args:
            prompt: User prompt or task description
            session_id: Session UUID
            agent_run_id: Agent run UUID for tracking
            context: Optional context dict (previous results, etc.)

        Returns:
            Parsed result from agent's final response, or paused state

        Note:
            All tools are executed via ToolExecutor.
            Agent only completes when it calls the `done` tool.
        """
        # Convert string IDs to UUIDs
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_prompt(prompt, context)},
        ]

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=0,
        )

    async def resume(
        self,
        agent_state: dict,
        answer: str,
        session_id: UUID | str,
        agent_run_id: UUID | str,
    ) -> Any:
        """Resume the agent from a paused state with the user's answer.

        Args:
            agent_state: The saved agent state from when it paused
            answer: User's answer to the HITL question
            session_id: Session UUID
            agent_run_id: Agent run UUID for tracking

        Returns:
            Parsed result from agent's final response, or paused state
        """
        # Convert string IDs to UUIDs
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)

        # Restore state
        messages = agent_state.get("messages", [])
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        question = agent_state.get("question", "")

        # Add the HITL answer as a tool response
        messages.append({
            "role": "tool",
            "tool_call_id": agent_state.get("tool_call_id", f"hitl_{start_iteration}"),
            "content": json.dumps({
                "status": "answered",
                "answer": answer,
                "question": question,
            }),
        })

        logger.info(
            "agent_resume",
            agent_id=self.id,
            iteration=start_iteration,
            answer_preview=answer[:50] if answer else "",
        )

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
        )

    async def resume_from_approval(
        self,
        agent_state: dict,
        tool_result: dict,
        session_id: UUID | str,
        agent_run_id: UUID | str,
    ) -> Any:
        """Resume the agent from a paused state after MCP tool approval.

        Args:
            agent_state: The saved agent state from when it paused
            tool_result: Result from the approved tool execution
            session_id: Session UUID
            agent_run_id: Agent run UUID for tracking

        Returns:
            Parsed result from agent's final response, or paused state
        """
        # Convert string IDs to UUIDs
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)

        # Restore state
        messages = agent_state.get("messages", [])
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        tool_call_id = agent_state.get("tool_call_id", f"call_{start_iteration}")

        # Add the tool result as a tool response
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(tool_result) if isinstance(tool_result, (dict, list)) else str(tool_result),
        })

        logger.info(
            "agent_resume_from_approval",
            agent_id=self.id,
            iteration=start_iteration,
            tool=agent_state.get("tool_name"),
            tool_result_preview=str(tool_result)[:100] if tool_result else "",
        )

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
        )

    async def continue_run(
        self,
        session_id: UUID | str,
        agent_run_id: UUID | str,
    ) -> Any:
        """Continue a paused agent run by reconstructing state from the database.

        This method:
        1. Loads all LLM calls for this agent run from DB
        2. Reconstructs the message history including tool results
        3. Continues the agent loop from where it left off

        The HITL answer is already saved as a tool call result in the DB,
        so it will automatically be included in the reconstructed messages.

        Args:
            session_id: Session UUID
            agent_run_id: Agent run UUID to continue

        Returns:
            Parsed result from agent's final response, or paused state
        """
        from druppie.repositories import ExecutionRepository

        # Convert string IDs to UUIDs
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)

        execution_repo = ExecutionRepository(self.db)

        # Get the agent run to get the prompt
        agent_run = execution_repo.get_by_id(agent_run_id)
        if not agent_run:
            raise ValueError(f"Agent run not found: {agent_run_id}")

        prompt = agent_run.planned_prompt or ""

        # Get all LLM calls for this run
        llm_calls = execution_repo.get_llm_calls_for_run(agent_run_id)

        if not llm_calls:
            # No previous LLM calls - start fresh
            logger.warning(
                "continue_run_no_llm_calls",
                agent_run_id=str(agent_run_id),
            )
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": prompt},
            ]
            return await self._run_loop(
                messages=messages,
                prompt=prompt,
                context=None,
                session_id=session_id,
                agent_run_id=agent_run_id,
                start_iteration=0,
            )

        # Reconstruct message history from LLM calls
        messages = self._reconstruct_messages_from_db(llm_calls, execution_repo)
        iteration = len(llm_calls)

        logger.info(
            "agent_continue_run",
            agent_id=self.id,
            agent_run_id=str(agent_run_id),
            llm_calls_count=len(llm_calls),
            messages_count=len(messages),
            continuing_from_iteration=iteration,
        )

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=None,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=iteration,
        )

    def _reconstruct_messages_from_db(
        self,
        llm_calls: list,
        execution_repo,
    ) -> list[dict]:
        """Reconstruct message history from stored LLM calls.

        For each LLM call:
        1. Add the request_messages (first call has system + user)
        2. Add the assistant response (with tool_calls if any)
        3. Add tool results for each tool call

        Returns:
            Reconstructed messages list ready for next LLM call
        """
        messages = []

        for i, llm_call in enumerate(llm_calls):
            # For first LLM call, use the full request_messages (system + user)
            if i == 0 and llm_call.request_messages:
                messages.extend(llm_call.request_messages)
            elif llm_call.request_messages:
                # For subsequent calls, skip system/user (already added)
                # Just ensure we have continuity
                pass

            # Add assistant response with tool calls
            # Check for non-empty list (empty list [] is falsy in Python)
            if llm_call.response_tool_calls and len(llm_call.response_tool_calls) > 0:
                # Assistant made tool calls
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tc.get("id", f"call_{i}_{j}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": json.dumps(tc.get("args", {})),
                            },
                        }
                        for j, tc in enumerate(llm_call.response_tool_calls)
                    ],
                })

                # Add tool results from the database
                # Match tool_calls by index to get the correct ID
                for j, tool_call_db in enumerate(llm_call.tool_calls):
                    if tool_call_db.result or tool_call_db.error_message:
                        # Get the tool call ID from the stored response_tool_calls
                        tool_call_id = f"call_{i}_{j}"  # Default
                        if j < len(llm_call.response_tool_calls):
                            tool_call_id = llm_call.response_tool_calls[j].get("id", tool_call_id)

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": tool_call_db.result or f"Error: {tool_call_db.error_message}",
                        })

            elif llm_call.response_content:
                # Assistant gave text response (no tool calls)
                messages.append({
                    "role": "assistant",
                    "content": llm_call.response_content,
                })

        return messages

    async def _run_loop(
        self,
        messages: list[dict],
        prompt: str,
        context: dict | None,
        session_id: UUID,
        agent_run_id: UUID,
        start_iteration: int,
    ) -> Any:
        """Internal tool-calling loop.

        All tool execution goes through ToolExecutor:
        1. Create ToolCall record
        2. Call ToolExecutor.execute(tool_call_id)
        3. Handle status (completed, waiting_approval, waiting_answer, failed)

        Agent only completes when calling the `done` tool.
        """
        from druppie.core.tool_registry import get_tool_registry
        from druppie.repositories import ExecutionRepository

        execution_repo = ExecutionRepository(self.db)

        # Get all tools for this agent from the unified ToolRegistry
        registry = get_tool_registry()
        builtin_tool_names = DEFAULT_BUILTIN_TOOLS + self.definition.extra_builtin_tools
        tools = registry.get_tools_for_agent(
            agent_mcps=self.definition.mcps,
            builtin_tool_names=builtin_tool_names,
        )
        openai_tools = registry.to_openai_format(tools)

        max_iterations = self.definition.max_iterations or 10

        if start_iteration == 0:
            logger.info(
                "agent_run_start",
                agent_id=self.id,
                prompt_length=len(prompt),
                tools_count=len(openai_tools),
                session_id=str(session_id),
                agent_run_id=str(agent_run_id),
            )

        for iteration in range(start_iteration, max_iterations):
            # Create LLM call record BEFORE calling LLM
            llm_call_id = execution_repo.create_llm_call(
                session_id=session_id,
                agent_run_id=agent_run_id,
                provider=self.llm.provider_name if hasattr(self.llm, 'provider_name') else "unknown",
                model=self.llm.model if hasattr(self.llm, 'model') else self.definition.model or "unknown",
                messages=messages,
                tools=openai_tools,
            )
            self.db.commit()

            start_time = time.time()
            try:
                response = await self.llm.achat(messages, openai_tools, max_tokens=self.definition.max_tokens)
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                # Record the error on the LLM call so it's visible in the DB
                error_msg = f"{type(e).__name__}: {e}"
                execution_repo.update_llm_error(
                    llm_call_id=llm_call_id,
                    error_message=error_msg[:2000],
                    duration_ms=duration_ms,
                )
                self.db.commit()
                logger.error(
                    "llm_call_failed",
                    agent_id=self.id,
                    iteration=iteration,
                    duration_ms=duration_ms,
                    error=error_msg[:500],
                )
                raise
            duration_ms = int((time.time() - start_time) * 1000)

            # Warn if response was truncated (hit token limit)
            if response.finish_reason == "length":
                logger.warning(
                    "llm_response_truncated",
                    agent_id=self.id,
                    iteration=iteration,
                    completion_tokens=response.completion_tokens,
                )

            # Update LLM call with response
            # Store the full raw response as JSON for debugging
            raw_response_json = json.dumps({
                "content": response.raw_content if hasattr(response, 'raw_content') else response.content,
                "tool_calls": response.tool_calls or [],
                "finish_reason": response.finish_reason or "",
                "prompt_tokens": response.prompt_tokens or 0,
                "completion_tokens": response.completion_tokens or 0,
                "total_tokens": response.total_tokens or 0,
            })
            execution_repo.update_llm_response(
                llm_call_id=llm_call_id,
                response_content=raw_response_json[:10000],  # Full JSON response
                response_tool_calls=[
                    {
                        "id": tc.get("id", f"call_{iteration}_{idx}"),
                        "name": tc.get("name"),
                        "args": tc.get("args"),
                    }
                    for idx, tc in enumerate(response.tool_calls or [])
                ],
                prompt_tokens=response.prompt_tokens or 0,
                completion_tokens=response.completion_tokens or 0,
                duration_ms=duration_ms,
            )
            self.db.commit()

            logger.debug(
                "llm_call",
                agent_id=self.id,
                iteration=iteration,
                duration_ms=duration_ms,
                has_tool_calls=bool(response.tool_calls),
            )

            # No tool calls — all agents MUST use tool calls
            if not response.tool_calls:
                was_truncated = response.finish_reason == "length"
                if iteration < max_iterations - 1:
                    logger.warning(
                        "agent_no_tool_calls_retry",
                        agent_id=self.id,
                        iteration=iteration,
                        truncated=was_truncated,
                    )
                    messages.append({"role": "assistant", "content": response.content})
                    truncation_hint = (
                        " Your previous response was TRUNCATED (hit token limit). "
                        "Keep your response shorter — call a tool immediately."
                        if was_truncated else ""
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "ERROR: You did not call any tools. You MUST use tool calls — "
                            "either OpenAI function calling format or "
                            "<tool_call>{\"name\": \"tool_name\", \"arguments\": {...}}</tool_call> XML format. "
                            "Do NOT output raw JSON or plain text. "
                            f"Call `done` when finished.{truncation_hint}"
                        ),
                    })
                    continue

                # Final iteration exhausted — raise so error propagates properly
                truncation_note = " (response was truncated by token limit)" if was_truncated else ""
                logger.error(
                    "agent_max_iterations_no_tool_calls",
                    agent_id=self.id,
                    iteration=iteration,
                    truncated=was_truncated,
                )
                raise AgentMaxIterationsError(
                    f"Agent '{self.id}' exhausted {max_iterations} iterations "
                    f"without producing tool calls{truncation_note}"
                )

            # Execute each tool call via ToolExecutor
            for tool_index, llm_tool_call in enumerate(response.tool_calls):
                tool_name = llm_tool_call.get("name", "")
                tool_args = llm_tool_call.get("args", {})
                llm_tool_call_str_id = llm_tool_call.get("id", f"call_{iteration}_{tool_index}")

                # Parse server:tool from name
                if is_builtin_tool(tool_name):
                    server = "builtin"
                    tool = tool_name
                elif ":" in tool_name:
                    server, tool = tool_name.split(":", 1)
                else:
                    # Convert coding_read_file -> coding:read_file
                    parts = tool_name.split("_", 1)
                    server = parts[0] if len(parts) > 1 else "coding"
                    tool = parts[1] if len(parts) > 1 else tool_name

                logger.debug(
                    "agent_tool_call",
                    agent_id=self.id,
                    tool=f"{server}:{tool}",
                    iteration=iteration,
                )

                # Create ToolCall record (linked to the LLM call)
                tool_call_id = execution_repo.create_tool_call(
                    session_id=session_id,
                    agent_run_id=agent_run_id,
                    mcp_server=server,
                    tool_name=tool,
                    arguments=tool_args,
                    llm_call_id=llm_call_id,
                    tool_call_index=tool_index,
                )
                self.db.commit()

                # Execute via ToolExecutor
                status = await self.tool_executor.execute(tool_call_id)

                # Get updated tool call for result
                tool_call_record = execution_repo.get_tool_call(tool_call_id)
                result_str = tool_call_record.result if tool_call_record else "{}"

                # Handle status
                if status == ToolCallStatus.WAITING_ANSWER:
                    # HITL tool - paused for user answer
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": llm_tool_call_str_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }],
                    })

                    agent_state = {
                        "agent_id": self.id,
                        "messages": messages,
                        "prompt": prompt,
                        "context": context,
                        "iteration": iteration,
                        "tool_call_id": llm_tool_call_str_id,
                    }

                    return {
                        "status": "paused",
                        "paused": True,
                        "reason": "waiting_answer",
                        "tool_call_id": str(tool_call_id),
                        "agent_state": agent_state,
                    }

                if status == ToolCallStatus.WAITING_APPROVAL:
                    # MCP tool needs approval
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": llm_tool_call_str_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }],
                    })

                    agent_state = {
                        "agent_id": self.id,
                        "messages": messages,
                        "prompt": prompt,
                        "context": context,
                        "iteration": iteration,
                        "tool_call_id": llm_tool_call_str_id,
                    }

                    return {
                        "status": "paused",
                        "paused": True,
                        "reason": "waiting_approval",
                        "tool_call_id": str(tool_call_id),
                        "agent_state": agent_state,
                    }

                # Parse result
                try:
                    result = json.loads(result_str) if result_str else {}
                except json.JSONDecodeError:
                    result = {"content": result_str}

                # Check if agent called `done`
                if tool == "done" and result.get("status") == "completed":
                    logger.info(
                        "agent_task_complete",
                        agent_id=self.id,
                        summary=result.get("summary", "")[:100],
                    )
                    return {
                        "success": True,
                        "result": result.get("summary", "[NO_SUMMARY]"),
                    }

                # Add tool result to messages for next LLM call
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": llm_tool_call_str_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": llm_tool_call_str_id,
                    "content": json.dumps(result),
                })

        logger.warning("agent_max_iterations", agent_id=self.id)
        raise AgentMaxIterationsError(
            f"Agent '{self.id}' exceeded {max_iterations} iterations"
        )

    def _build_system_prompt(self) -> str:
        """Build the system prompt with shared tool usage instructions.

        This method:
        1. Injects common instructions from _common.md (if placeholder present)
        2. Adds shared tool usage instructions for non-router/planner agents
        3. Conditionally adds XML format instructions based on LLM capabilities

        Tool descriptions are now provided via the structured `tools` parameter
        to the LLM, not duplicated in the system prompt. Approval requirements
        are included in each tool's description field.

        Router and planner agents have special JSON output formats and don't
        need the built-in tools documentation.
        """
        base_prompt = self.definition.system_prompt

        # Inject common instructions (shared across agents)
        common_prompt = self._load_common_prompt()
        if common_prompt and "[COMMON_INSTRUCTIONS]" in base_prompt:
            base_prompt = base_prompt.replace("[COMMON_INSTRUCTIONS]", common_prompt)

        # Router and planner output JSON directly - no built-in tools needed
        if self.id in ("router", "planner"):
            # For LLMs that don't support native tools, add XML format instructions
            if not self.llm.supports_native_tools:
                base_prompt += self._get_xml_format_instructions()
            return base_prompt

        # For other agents, add full tool usage instructions
        shared_tool_instructions = self._get_shared_tool_instructions()
        return base_prompt + shared_tool_instructions

    def _get_xml_format_instructions(self) -> str:
        """Get XML format instructions for LLMs that don't support native tool calling."""
        return """

## TOOL CALL FORMAT

You MUST output tool calls using this XML format:
<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1"}}</tool_call>

Example:
<tool_call>{"name": "done", "arguments": {"summary": "Agent deployer: Deployed at http://localhost:9101 (container: app-preview, port 9101:80)."}}</tool_call>
"""

    def _get_shared_tool_instructions(self) -> str:
        """Get shared tool instructions, with XML format only for non-native LLMs."""
        # Check if LLM supports native tools
        uses_native_tools = self.llm.supports_native_tools

        if uses_native_tools:
            # Minimal instructions for native tool calling
            return """

###############################################################################
#                    CRITICAL: TOOL USAGE INSTRUCTIONS                        #
###############################################################################

You are an AI agent that can ONLY interact through TOOL CALLS.
You MUST NOT output plain text - always use a tool.

## BUILT-IN TOOLS (always available)

1. **hitl_ask_question** - Ask the user a free-form question
   Required: question (string)
   Optional: context (string)

2. **hitl_ask_multiple_choice_question** - Ask user to select from options
   Required: question (string), choices (array of strings)
   Optional: allow_other (boolean)

3. **done** - Signal that your task is complete
   Required: summary (string) - DETAILED summary of what you accomplished including URLs, branch names, container names, file paths. NEVER just "Task completed".

## CRITICAL RULES

1. NEVER output plain text to communicate - use hitl_ask_question instead
2. NEVER announce what you will do - just call the tool directly
3. ALWAYS call done() when you have finished your task
4. Tool names use UNDERSCORES not colons (e.g., hitl_ask_question not hitl:ask_question)
"""
        else:
            # Full instructions with XML format for non-native LLMs
            return """

###############################################################################
#                    CRITICAL: TOOL USAGE INSTRUCTIONS                        #
###############################################################################

You are an AI agent that can ONLY interact through TOOL CALLS.
You MUST NOT output plain text - always use a tool.

## TOOL CALL FORMAT

You MUST output tool calls using this XML format:
<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1", "arg2": "value2"}}</tool_call>

## EXAMPLES OF CORRECT TOOL CALLS

### Asking the user a question:
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What database would you like me to use?"}}</tool_call>

### Asking a yes/no question:
<tool_call>{"name": "hitl_ask_multiple_choice_question", "arguments": {"question": "Should I proceed with this plan?", "choices": ["Yes", "No"]}}</tool_call>

### Signaling task completion:
<tool_call>{"name": "done", "arguments": {"summary": "Agent developer: Implemented counter app on branch feature/add-counter, pushed index.html, styles.css, Dockerfile."}}</tool_call>

## BUILT-IN TOOLS (always available)

1. **hitl_ask_question** - Ask the user a free-form question
   Required: question (string)
   Optional: context (string)

2. **hitl_ask_multiple_choice_question** - Ask user to select from options
   Required: question (string), choices (array of strings)
   Optional: allow_other (boolean)

3. **done** - Signal that your task is complete
   Required: summary (string) - DETAILED summary of what you accomplished including URLs, branch names, container names, file paths. NEVER just "Task completed".

## CRITICAL RULES

1. NEVER output plain text to communicate - use hitl_ask_question instead
2. NEVER announce what you will do - just call the tool directly
3. ALWAYS call done() when you have finished your task
4. Tool names use UNDERSCORES not colons (e.g., hitl_ask_question not hitl:ask_question)

## WRONG vs RIGHT

WRONG (plain text output):
```
I'll now create a file for you. What name would you like?
```

RIGHT (tool call):
```
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What name would you like for the file?"}}</tool_call>
```

WRONG (announcing completion):
```
Done! I have completed the task.
```

RIGHT (tool call):
```
<tool_call>{"name": "done", "arguments": {"summary": "Agent developer: Created index.html and styles.css on branch main, pushed to remote."}}</tool_call>
```
"""

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        """Build the full prompt with context."""
        if not context:
            return prompt

        # Extract clarifications for natural inclusion
        clarifications = context.get("clarifications", [])

        # Build context string WITHOUT clarifications
        context_items = {k: v for k, v in context.items() if k != "clarifications"}
        context_str = "\n".join(
            f"- {key}: {value}" for key, value in context_items.items()
        )

        # Build user response section if present
        user_response_str = ""
        if clarifications:
            # Just show the most recent response naturally
            latest = clarifications[-1]
            question = latest.get("question", "")
            answer = latest.get("answer", "")
            user_response_str = f"""

USER RESPONSE:
You previously asked: {question[:200]}{'...' if len(question) > 200 else ''}
User's answer: {answer}
"""

        return f"""CONTEXT:
{context_str}

TASK:
{prompt}{user_response_str}"""

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

        # Strategy 3: Find the LAST valid JSON object in text (look for {...})
        # This handles cases where LLM adds thinking text before the actual JSON
        # We search backwards to find the last complete JSON object
        json_objects = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content))
        for match in reversed(json_objects):
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue

        # Strategy 3b: Try to find a JSON object with nested braces (more complex)
        # Look for JSON starting near the end of content
        last_brace = content.rfind("{")
        if last_brace >= 0:
            # Try to extract JSON from the last { to the matching }
            try:
                # Count braces to find the matching }
                brace_count = 0
                for i, char in enumerate(content[last_brace:]):
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_str = content[last_brace:last_brace + i + 1]
                            return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
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
