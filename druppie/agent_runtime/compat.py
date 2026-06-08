"""Compatibility layer bridging old Druppie backend to new agent_runtime.

Provides 4 key components:
1. adapt_llm(old_llm) — wraps old BaseLLM to new async callable
2. DruppieToolProvider — implements ToolProvider protocol
3. create_event_persister(repo, session_id, agent_run_id) — event callback → DB writes
4. old_definition_to_new(old_def) — converts old Pydantic AgentDefinition to new dataclass
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Callable
from uuid import UUID

from druppie.agent_runtime.definition import AgentDefinition as NewAgentDefinition
from druppie.agent_runtime.definition import parse_definition
from druppie.agent_runtime.types import AgentEvent

logger = logging.getLogger(__name__)


async def adapt_llm(old_llm) -> Callable:
    """Wrap old BaseLLM.achat() to new agent_runtime LLM callable.

    The new runtime expects an async callable with signature:
        llm(**kwargs) -> {"choices": [...], "usage": {...}, "model": "..."}

    Args:
        old_llm: An instance of druppie.llm.base.BaseLLM (or any subclass)

    Returns:
        Async callable compatible with the new runtime's LLM interface
    """
    async def new_llm(**kwargs) -> dict[str, Any]:
        messages = kwargs["messages"]
        tools = kwargs.get("tools")
        max_tokens = kwargs.get("max_tokens", 4096)

        response = await old_llm.achat(messages, tools, max_tokens=max_tokens)

        message: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.thinking_content:
            message["reasoning_content"] = response.thinking_content
        if response.tool_calls:
            # Convert internal tool_calls format to OpenAI wire format.
            # Internal: {"id": ..., "name": ..., "args": dict}
            # OpenAI:   {"id": ..., "type": "function", "function": {"name": ..., "arguments": str}}
            # Without this conversion, ZAI sees tool_calls without "type" and
            # rejects with "Tool type cannot be empty".
            message["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"]) if isinstance(tc.get("args"), dict) else str(tc.get("args", "{}")),
                    },
                }
                for tc in response.tool_calls
            ]

        result = {
            "choices": [{"message": message, "finish_reason": response.finish_reason or "stop"}],
            "usage": {
                "prompt_tokens": response.prompt_tokens or 0,
                "completion_tokens": response.completion_tokens or 0,
                "total_tokens": response.total_tokens or 0,
            },
            "model": response.model or "",
        }
        if response.raw_request:
            result["raw_request"] = response.raw_request
        if response.raw_response:
            result["raw_response"] = response.raw_response
        return result

    return new_llm


class DruppieToolProvider:
    """ToolProvider that bridges old Druppie tool execution to new runtime.

    Routes tool calls through the old ToolExecutor (for MCP tools) and
    execute_builtin (for builtin tools). Persists all calls to the DB
    via ExecutionRepository. Implements the new ToolProvider protocol.

    Tool naming convention:
    - Builtin tools: just the tool name (e.g. "done", "hitl_ask_question")
    - MCP tools: "{server}_{tool}" (e.g. "coding_read_file")
    """

    def __init__(
        self,
        execution_repo,
        tool_executor,
        session_id: UUID,
        agent_run_id: UUID,
        old_agent_definition,
        tool_registry,
        builtin_tool_defs: dict | None = None,
        subagents_connection: SubagentsMCPConnection | None = None,
    ) -> None:
        self._execution_repo = execution_repo
        self._tool_executor = tool_executor
        self._session_id = session_id
        self._agent_run_id = agent_run_id
        self._old_def = old_agent_definition
        self._tool_registry = tool_registry
        self._builtin_tool_defs = builtin_tool_defs or {}
        self._llm_call_id: UUID | None = None
        self._tools_cache: list[dict] | None = None
        self._subagents_connection = subagents_connection

    def set_llm_call_id(self, llm_call_id: UUID) -> None:
        self._llm_call_id = llm_call_id

    def set_subagents_connection(self, conn: SubagentsMCPConnection) -> None:
        self._subagents_connection = conn
        self._tools_cache = None

    async def list_tools(self) -> list[dict]:
        """Return all tools available to this agent in OpenAI format.

        Combines builtin tools (minus excluded, plus extra) with MCP tools
        from the agent's allowed MCP servers.
        """
        if self._tools_cache is not None:
            return self._tools_cache

        from druppie.agents.builtin_tools import DEFAULT_BUILTIN_TOOLS

        excluded = set(self._old_def.excluded_builtin_tools or [])
        extra = list(self._old_def.extra_builtin_tools or [])
        builtin_names = [t for t in DEFAULT_BUILTIN_TOOLS if t not in excluded] + extra

        # Auto-enable ask_expert tools when experts is declared
        if getattr(self._old_def, 'experts', None):
            for name in ("ask_expert_question", "ask_expert_multiple_choice_question"):
                if name not in builtin_names:
                    builtin_names.append(name)

        tools = self._tool_registry.get_tools_for_agent(
            agent_mcps=self._old_def.mcps,
            builtin_tool_names=builtin_names,
        )

        if self._subagents_connection is not None and getattr(self._old_def, "subagents", []):
            tools.extend(
                self._subagents_connection.get_tools(
                    getattr(self._old_def, "subagents", [])
                )
            )

        self._tools_cache = self._tool_registry.to_openai_format(tools)

        # Inject allowed expert roles as enum on ask_expert tool schemas
        experts = getattr(self._old_def, 'experts', None)
        if experts:
            for tool in self._tools_cache:
                fn = tool.get("function", {})
                name = fn.get("name", "")
                if name in ("ask_expert_question", "ask_expert_multiple_choice_question"):
                    props = fn.get("parameters", {}).get("properties", {})
                    if "expert_role" in props:
                        props["expert_role"]["enum"] = list(experts)
                        props["expert_role"]["description"] = (
                            f"Expert role to ask. Allowed values: {', '.join(experts)}."
                        )

        return self._tools_cache

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool call, routing to builtin, HITL, or MCP execution.

        Args:
            tool_name: Tool name (builtin name or "{server}_{tool}")
            arguments: Tool arguments

        Returns:
            Success: {"success": True, "result": ...} or {"success": True, "data": ...}
            Error: {"success": False, "error": "..."}
            Pending: {"success": True, "_pending": True, "reason": "..."}
        """
        from druppie.agents.builtin_tools import execute_builtin, is_builtin_tool, is_hitl_tool

        if tool_name == "subagents":
            return await self._execute_subagents(arguments)
        elif is_hitl_tool(tool_name):
            return await self._execute_hitl(tool_name, arguments)
        elif is_builtin_tool(tool_name):
            return await self._execute_builtin(tool_name, arguments, execute_builtin)
        else:
            return await self._execute_mcp(tool_name, arguments)

    async def _execute_builtin(
        self,
        tool_name: str,
        arguments: dict,
        execute_builtin_fn: Callable,
    ) -> dict:
        """Execute a builtin tool via old execute_builtin."""
        tool_call_id = self._execution_repo.create_tool_call(
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            mcp_server="builtin",
            tool_name=tool_name,
            arguments=arguments,
            llm_call_id=self._llm_call_id,
            tool_call_index=0,
        )
        self._execution_repo.db.commit()

        try:
            result = await execute_builtin_fn(
                tool_name=tool_name,
                args=arguments,
                session_id=self._session_id,
                agent_run_id=self._agent_run_id,
                execution_repo=self._execution_repo,
            )
            if isinstance(result, dict):
                success = result.get("success", True)
                status = "completed" if success else "failed"
                error_msg = None if success else result.get("error", "Builtin tool failed")
                self._execution_repo.update_tool_call(
                    tool_call_id=tool_call_id,
                    status=status,
                    result=result if isinstance(result, dict) else {"result": result},
                    error=error_msg,
                )
                self._execution_repo.db.commit()
                if success:
                    return {"success": True, "result": result}
                return {"success": False, "error": error_msg}
            self._execution_repo.update_tool_call(
                tool_call_id=tool_call_id,
                status="completed",
                result={"result": result},
            )
            self._execution_repo.db.commit()
            return {"success": True, "result": result}
        except Exception as e:
            logger.exception("Builtin tool %s failed", tool_name)
            self._execution_repo.update_tool_call(
                tool_call_id=tool_call_id,
                status="failed",
                error=str(e),
            )
            self._execution_repo.db.commit()
            return {"success": False, "error": str(e)}

    async def _execute_hitl(self, tool_name: str, arguments: dict) -> dict:
        """Execute a HITL tool via old ToolExecutor (creates Question, pauses)."""
        tool_call_id = self._execution_repo.create_tool_call(
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            mcp_server="builtin",
            tool_name=tool_name,
            arguments=arguments,
            llm_call_id=self._llm_call_id,
            tool_call_index=0,
        )
        self._execution_repo.db.commit()

        status = await self._tool_executor.execute(tool_call_id)

        if status == "waiting_answer":
            return {"success": True, "_pending": True, "reason": "waiting_answer"}
        elif status == "completed":
            updated = self._execution_repo.get_tool_call(tool_call_id)
            return {"success": True, "result": updated.result}
        else:
            updated = self._execution_repo.get_tool_call(tool_call_id)
            error_msg = updated.error_message if updated else None
            return {"success": False, "error": error_msg or "HITL tool execution failed"}

    async def _execute_mcp(self, tool_name: str, arguments: dict) -> dict:
        """Execute an MCP tool via old ToolExecutor."""
        parts = tool_name.split("_", 1)
        if len(parts) != 2:
            return {"success": False, "error": f"Invalid MCP tool name: {tool_name}"}
        server, tool = parts

        tool_call_id = self._execution_repo.create_tool_call(
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            mcp_server=server,
            tool_name=tool,
            arguments=arguments,
            llm_call_id=self._llm_call_id,
            tool_call_index=0,
        )

        status = await self._tool_executor.execute(tool_call_id)

        if status == "completed":
            updated = self._execution_repo.get_tool_call(tool_call_id)
            return {"success": True, "result": updated.result}
        elif status in ("waiting_approval", "waiting_answer", "waiting_sandbox"):
            return {"success": True, "_pending": True, "reason": status.lower()}
        else:
            updated = self._execution_repo.get_tool_call(tool_call_id)
            error_msg = updated.error_message if updated else None
            return {"success": False, "error": error_msg or "Tool execution failed"}

    async def _execute_subagents(self, arguments: dict) -> dict:
        if self._subagents_connection is None:
            return {"success": False, "error": "subagents not configured for this provider"}

        agents = arguments.get("agents", [])
        if not agents:
            return {"success": False, "error": "subagents requires 'agents' list"}

        # Create tool_call record (same pattern as _execute_builtin)
        tool_call_id = self._execution_repo.create_tool_call(
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            mcp_server="builtin",
            tool_name="subagents",
            arguments=arguments,
            llm_call_id=self._llm_call_id,
            tool_call_index=0,
        )
        self._execution_repo.db.commit()

        try:
            result = await self._subagents_connection.call_tool("subagents", arguments, spawning_tool_call_id=tool_call_id)

            if isinstance(result, dict):
                success = result.get("success", True)
                is_paused = result.get("_pending", False)
                status = "completed" if success and not is_paused else ("paused" if is_paused else "failed")
                error_msg = None if success else result.get("error", "Subagent execution failed")
                self._execution_repo.update_tool_call(
                    tool_call_id=tool_call_id,
                    status=status,
                    result=result,
                    error=error_msg,
                )
                self._execution_repo.db.commit()
                return result
            self._execution_repo.update_tool_call(
                tool_call_id=tool_call_id,
                status="completed",
                result={"result": result},
            )
            self._execution_repo.db.commit()
            return result
        except Exception as e:
            logger.exception("Subagents execution failed")
            self._execution_repo.update_tool_call(
                tool_call_id=tool_call_id,
                status="failed",
                error=str(e),
            )
            self._execution_repo.db.commit()
            return {"success": False, "error": str(e)}

    async def close(self) -> None:
        """Clean up — no-op for DruppieToolProvider."""
        pass


def create_event_persister(
    execution_repo,
    session_id: UUID,
    agent_run_id: UUID,
    tool_provider: DruppieToolProvider | None = None,
    provider_name: str = "unknown",
) -> Callable[[AgentEvent], None]:
    """Create an event callback that persists agent runtime events to the DB.

    Maps new runtime AgentEvent types to old Druppie DB operations:
    - agent_start → update agent run status to RUNNING
    - agent_end → update agent run status to COMPLETED
    - error → update agent run status to FAILED
    - llm_response → create LlmCall record, thread llm_call_id to tool_provider
    - turn_end → update token aggregation (fallback)
    - context_overflow → log warning (no DB action)

    Args:
        execution_repo: ExecutionRepository instance
        session_id: Session UUID
        agent_run_id: Agent run UUID
        tool_provider: Optional DruppieToolProvider to receive llm_call_id
        provider_name: LLM provider name (e.g. "zai", "deepinfra")

    Returns:
        Callable that accepts AgentEvent instances
    """
    def persist_event(event: AgentEvent) -> None:
        try:
            if event.type == "agent_start":
                execution_repo.update_status(agent_run_id, "RUNNING")
            elif event.type == "agent_end":
                execution_repo.update_status(agent_run_id, "COMPLETED")
            elif event.type == "error":
                error_msg = str(event.data.get("error", ""))
                execution_repo.update_status(agent_run_id, "FAILED", error_message=error_msg)
            elif event.type == "llm_response":
                data = event.data
                resp = data.get("response", {})
                usage = resp.get("usage", {})
                choices = resp.get("choices", [{}])
                choice = choices[0] if choices else {}
                msg = choice.get("message", {})

                provider = provider_name
                model = resp.get("model", "unknown")

                messages = data.get("messages_snapshot", [])
                tools = data.get("tools_snapshot")
                duration_ms = data.get("duration_ms", 0)

                logger.warning(
                    "LLM_RESPONSE debug [agent_run=%s]: data_keys=%s, "
                    "resp_keys=%s, usage=%s, choices_count=%s, msg_keys=%s, "
                    "messages_snapshot_len=%s, duration_ms=%s",
                    agent_run_id,
                    list(data.keys()),
                    list(resp.keys()) if resp else "NONE",
                    usage,
                    len(choices),
                    list(msg.keys()) if msg else "NONE",
                    len(messages),
                    duration_ms,
                )

                llm_call_id = execution_repo.create_llm_call(
                    session_id=session_id,
                    agent_run_id=agent_run_id,
                    provider=provider,
                    model=model,
                    messages=messages,
                    tools=tools,
                )
                execution_repo.db.commit()
                logger.warning(
                    "LLM_RESPONSE create_llm_call OK [agent_run=%s]: llm_call_id=%s, messages_stored=%s",
                    agent_run_id, llm_call_id, len(messages),
                )

                if tool_provider:
                    tool_provider.set_llm_call_id(llm_call_id)

                response_tool_calls = []
                for tc in (msg.get("tool_calls") or []):
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    response_tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "args": args,
                    })

                prompt_tokens = usage.get("prompt_tokens") or 0
                completion_tokens = usage.get("completion_tokens") or 0
                total_tokens = usage.get("total_tokens") or 0

                response_content = msg.get("content") or ""
                finish_reason = choice.get("finish_reason", "")

                thinking_content = msg.get("reasoning_content") or msg.get("thinking") or None

                raw_response_json = json.dumps({
                    "content": response_content,
                    "tool_calls": [
                        {
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "args": tc.get("function", {}).get("arguments", ""),
                        }
                        for tc in (msg.get("tool_calls") or [])
                    ],
                    "finish_reason": finish_reason,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                })

                logger.warning(
                    "LLM_RESPONSE pre-update [llm_call=%s]: prompt_tokens=%s, completion_tokens=%s, "
                    "response_content=%r, tool_calls_count=%s, duration_ms=%s, actual_model=%s",
                    llm_call_id,
                    prompt_tokens,
                    completion_tokens,
                    (response_content[:100] + "...") if len(response_content) > 100 else response_content,
                    len(response_tool_calls),
                    duration_ms,
                    model,
                )

                execution_repo.update_llm_response(
                    llm_call_id=llm_call_id,
                    response_content=raw_response_json[:10000],
                    response_tool_calls=response_tool_calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                    actual_model=model,
                    thinking_content=thinking_content,
                    raw_request=data.get("raw_request"),
                    raw_response=data.get("raw_response"),
                )
                execution_repo.db.commit()
                logger.warning("LLM_RESPONSE update_llm_response OK [llm_call=%s]", llm_call_id)

                if prompt_tokens or completion_tokens:
                    execution_repo.update_tokens(agent_run_id, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
                    execution_repo.db.commit()

            elif event.type == "tool_call":
                tool_name = event.data.get("tool_name", "unknown")
                if tool_name == "done":
                    arguments = event.data.get("arguments", {})
                    current_llm_call_id = getattr(tool_provider, "_llm_call_id", None)
                    tc_id = execution_repo.create_tool_call(
                        session_id=session_id,
                        agent_run_id=agent_run_id,
                        mcp_server="builtin",
                        tool_name=tool_name,
                        arguments=arguments,
                        llm_call_id=current_llm_call_id,
                        tool_call_index=0,
                    )
                    execution_repo.db.commit()
                    tool_provider._last_tool_call_id = tc_id
                    tool_provider._last_tool_call_name = tool_name
                    if current_llm_call_id:
                        from druppie.db.models import LlmCall as _LlmCall
                        llm_call = execution_repo.db.query(_LlmCall).filter(_LlmCall.id == current_llm_call_id).first()
                        if llm_call:
                            existing = llm_call.response_tool_calls or []
                            existing.append({
                                "id": str(tc_id),
                                "name": tool_name,
                                "args": arguments,
                            })
                            llm_call.response_tool_calls = existing
                            execution_repo.db.commit()

            elif event.type == "tool_result":
                result_data = event.data.get("result", {})
                tool_name = event.data.get("tool_name", "unknown")
                if tool_name == "done":
                    tc_id = getattr(tool_provider, "_last_tool_call_id", None)
                    tc_name = getattr(tool_provider, "_last_tool_call_name", None)
                    if tc_id and tc_name == tool_name:
                        import json as _json
                        try:
                            parsed = _json.loads(result_data) if isinstance(result_data, str) else result_data
                        except (json.JSONDecodeError, TypeError):
                            parsed = {"result": result_data}
                        success = parsed.get("success", True) if isinstance(parsed, dict) else True
                        status = "completed" if success else "failed"
                        error_msg = None if success else (parsed.get("error", "") if isinstance(parsed, dict) else "")
                        execution_repo.update_tool_call(
                            tool_call_id=tc_id,
                            status=status,
                            result=parsed if isinstance(parsed, dict) else {"result": parsed},
                            error=error_msg,
                        )
                        execution_repo.db.commit()
                        tool_provider._last_tool_call_id = None
                        tool_provider._last_tool_call_name = None

            elif event.type == "turn_end":
                tokens_used = event.data.get("tokens_used", {})
                pt = tokens_used.get("prompt_tokens", 0) or 0
                ct = tokens_used.get("completion_tokens", 0) or 0
                if pt or ct:
                    execution_repo.update_tokens(agent_run_id, prompt_tokens=pt, completion_tokens=ct)
                    execution_repo.db.commit()

            elif event.type == "context_overflow":
                logger.warning("Context overflow for agent_run %s", agent_run_id)
        except Exception as e:
            logger.warning(
                "PERSIST_EVENT FAILED [event=%s, agent_run=%s]: %s\n%s",
                event.type,
                agent_run_id,
                e,
                traceback.format_exc(),
            )

    return persist_event


class SubagentsMCPConnection:
    """Wraps SubagentsMCP as an in-process MCPConnection for DruppieToolProvider.

    Captures all parent context at construction so that execute() calls from
    the tool provider don't need per-call context.
    """

    def __init__(
        self,
        agent_loader,
        sandbox_resolver,
        loop_runner,
        llm,
        config,
        event_callback,
        parent_tool_provider,
        parent_agent_def=None,
        parent_git_scope=None,
        cancellation_token=None,
        child_tool_provider_factory=None,
        current_depth: int = 0,
        agent_chain: list[str] | None = None,
    ) -> None:
        from druppie.agent_runtime.subagents import SubagentsMCP

        self._mcp = SubagentsMCP(
            agent_loader,
            sandbox_resolver,
            loop_runner,
            child_tool_provider_factory=child_tool_provider_factory,
        )
        self._llm = llm
        self._config = config
        self._event_callback = event_callback
        self._parent_tool_provider = parent_tool_provider
        self._parent_agent_def = parent_agent_def
        self._parent_git_scope = parent_git_scope
        self._cancellation_token = cancellation_token
        self._current_depth = current_depth
        self._agent_chain: list[str] = agent_chain or []

    def get_tools(self, allowed_agents: list[str]) -> list[dict]:
        return [self._mcp.build_schema(allowed_agents)]

    async def call_tool(self, tool_name: str, arguments: dict, spawning_tool_call_id=None) -> dict:
        if tool_name != "subagents":
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        agents = arguments.get("agents", [])
        if not agents:
            return {"success": False, "error": "subagents requires 'agents' list"}

        try:
            results = await self._mcp.execute(
                agents=agents,
                parent_agent=self._parent_agent_def,
                parent_tool_provider=self._parent_tool_provider,
                parent_git_scope=self._parent_git_scope,
                parent_sandbox_conn=None,
                llm=self._llm,
                config=self._config,
                event_callback=self._event_callback,
                current_depth=self._current_depth,
                agent_chain=self._agent_chain,
                cancellation_token=self._cancellation_token,
                spawning_tool_call_id=spawning_tool_call_id,
            )

            has_pending = isinstance(results, dict) and results.get("_pending")
            results_list = results.get("results", results) if isinstance(results, dict) else results

            serialized = []
            for r in results_list:
                entry = {"agent": r.get("agent"), "status": r.get("status")}
                result = r.get("result")
                if result is not None:
                    if hasattr(result, "done_result"):
                        entry["result"] = {
                            "status": result.status,
                            "summary": (result.done_result or {}).get("summary", ""),
                            "variables": (result.done_result or {}).get("variables", {}),
                        }
                    else:
                        entry["result"] = str(result)
                error = r.get("error")
                if error:
                    entry["error"] = error
                serialized.append(entry)
            response = {"success": True, "data": serialized}
            if has_pending:
                response["_pending"] = True
                response["reason"] = "subagent_paused"
            return response
        except Exception as e:
            logger.exception("subagents execution failed")
            return {"success": False, "error": f"subagents failed: {e}"}


def old_definition_to_new(old_def) -> NewAgentDefinition:
    """Convert old Pydantic AgentDefinition to new dataclass AgentDefinition.

    Args:
        old_def: Instance of druppie.domain.agent_definition.AgentDefinition

    Returns:
        New runtime AgentDefinition dataclass instance
    """
    yaml_dict: dict[str, Any] = {
        "id": old_def.id,
        "name": old_def.name,
        "description": old_def.description or "",
        "role": getattr(old_def, "role", "primary"),
        "subagents": getattr(old_def, "subagents", []),
        "system_prompt": old_def.system_prompt or "",
        "system_prompts": old_def.system_prompts or [],
        "mcps": _convert_mcps(old_def.mcps),
        "skills": old_def.skills or [],
        "llm_profile": old_def.llm_profile or "standard",
        "temperature": old_def.temperature if old_def.temperature is not None else 0.1,
        "max_tokens": old_def.max_tokens if old_def.max_tokens is not None else 4096,
        "max_iterations": old_def.max_iterations if old_def.max_iterations is not None else 20,
        "extra_builtin_tools": old_def.extra_builtin_tools or [],
        "excluded_builtin_tools": old_def.excluded_builtin_tools or [],
        "allowed_next_agents": old_def.allowed_next_agents or [],
        "approval_overrides": _to_dict(old_def.approval_overrides),
        "completion_preconditions": _to_dicts(old_def.completion_preconditions),
        "required_summary_status": _to_dict(old_def.required_summary_status),
    }
    if hasattr(old_def, "sandbox_constraints") and old_def.sandbox_constraints:
        yaml_dict["sandbox_constraints"] = _to_dict(old_def.sandbox_constraints)

    sandbox_data = {}
    old_sandbox = getattr(old_def, "sandbox", None)
    if old_sandbox:
        old_networks = getattr(old_sandbox, "networks", [])
        if old_networks:
            sandbox_data["networks"] = old_networks
    yaml_dict["sandbox"] = sandbox_data

    return parse_definition(yaml_dict)


def _convert_mcps(mcps: list[str] | dict[str, list[str]]) -> dict[str, Any]:
    """Convert old mcps format to new format expected by parse_definition.

    Old format: list[str] (e.g. ["coding", "docker"])
             or dict[str, list[str]] (e.g. {"coding": ["read_file"]})

    New format: dict[str, Any]
             e.g. {"coding": {"tools": ["read_file"]}, "docker": {"tools": []}}
    """
    if isinstance(mcps, dict):
        return {k: {"tools": v} if isinstance(v, list) else v for k, v in mcps.items()}
    if isinstance(mcps, list):
        return {name: {"tools": []} for name in mcps}
    return {}


def _to_dict(obj) -> dict | None:
    """Convert a Pydantic model or dict to a plain dict."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return None


def _to_dicts(objs) -> list[dict]:
    """Convert a list of Pydantic models to a list of plain dicts."""
    if not objs:
        return []
    return [_to_dict(o) for o in objs if o is not None]
