"""AgentLoop — core execution loop for the agent runtime.

Orchestrates the LLM ↔ tool-call turn cycle, enforcing done() completion,
context limits, cancellation, retries, and event emission.
"""

from __future__ import annotations

import asyncio
import logging
import random
import traceback
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.tools.done import DoneTool
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.tools.provider import ToolProvider
from druppie.agent_runtime.types import (
    AgentEvent,
    AgentResult,
    CancellationToken,
    LoopConfig,
)

_SUBAGENT_TOOL_SCHEMA = {
    "name": "subagents",
    "description": (
        "Spawn a subagent to handle a sub-task. "
        "Provide the subagent_id and a prompt describing what it should do."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "subagent_id": {
                "type": "string",
                "description": "ID of the subagent to invoke",
            },
            "prompt": {
                "type": "string",
                "description": "Task description for the subagent",
            },
        },
        "required": ["subagent_id", "prompt"],
    },
}

_ENFORCEMENT_ERROR_MSG = (
    "You must call done() to signal completion. "
    "Do not respond with only text — invoke the done tool."
)

_CONTEXT_LIMIT_MSG = (
    "You have reached the context limit. Call done() NOW with a summary."
)

_TRUNCATION_NUDGE_MSG = (
    "Your previous response was truncated because it hit the maximum output token limit. "
    "Be more concise and call your tools instead of writing long text responses. "
    "Continue with your task."
)


class AgentLoop:
    """Core execution loop that drives an LLM agent through tool-call turns."""

    async def run(
        self,
        agent: AgentDefinition,
        agent_loader: Callable[[str], AgentDefinition],
        tool_provider: ToolProvider,
        prompt: str | None = None,
        initial_messages: list[dict] | None = None,
        llm: Callable = None,
        sandbox_resolver: Callable[[str], Awaitable[MCPConnection]] | None = None,
        event_callbacks: list[Callable[[AgentEvent], None]] = [],
        config: LoopConfig = LoopConfig(),
        cancellation_token: CancellationToken | None = None,
        tool_call_history: dict[str, int] | None = None,
    ) -> AgentResult:
        emitter = EventEmitter()
        for cb in event_callbacks:
            emitter.on(cb)

        if not prompt and not initial_messages:
            raise ValueError("Either prompt or initial_messages must be provided")

        messages = list(initial_messages) if initial_messages else []

        if prompt and not any(m.get("role") == "user" for m in messages):
            messages.append({"role": "user", "content": prompt})

        done_tool = DoneTool()
        tool_call_history = dict(tool_call_history) if tool_call_history else {}
        self._tool_call_history = tool_call_history
        expanded_tools: set[str] = set()
        enforcement_retries = 0
        max_enforcement_retries = 3
        truncation_retries = 0
        max_truncation_retries = 5

        for turn in range(1, config.max_turns + 1):
            if cancellation_token and cancellation_token.is_cancelled:
                return AgentResult(
                    status="cancelled",
                    events=emitter.get_events(),
                )

            emitter.emit(AgentEvent.now("turn_start", {"turn_number": turn}))

            all_tools = await self._build_tool_list(
                agent, tool_provider, done_tool, expanded_tools,
            )

            context_overflow = self._estimate_tokens(messages) > config.max_context_tokens
            tools_for_call = all_tools

            if context_overflow:
                messages.append({"role": "system", "content": _CONTEXT_LIMIT_MSG})
                done_schema = self._to_openai_tool(done_tool.build_schema(agent))
                tools_for_call = [done_schema]
                emitter.emit(AgentEvent.now("enforcement_retry", {
                    "reason": "context_overflow",
                }))

            import time as _time
            _llm_start = _time.monotonic()

            try:
                response = await self._call_llm_with_retries(
                    llm, agent, messages, tools_for_call, emitter, config,
                )
            except Exception as exc:
                emitter.emit(AgentEvent.now("error", {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }))
                return AgentResult(
                    status="error",
                    error=str(exc),
                    events=emitter.get_events(),
                )

            _llm_duration_ms = int((_time.monotonic() - _llm_start) * 1000)

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = response.get("usage", {})

            emitter.emit(AgentEvent.now("llm_response", {
                "response": response,
                "messages_count": len(messages),
                "messages_snapshot": list(messages),
                "tools_snapshot": list(tools_for_call or []),
                "duration_ms": _llm_duration_ms,
                "raw_request": response.get("raw_request"),
                "raw_response": response.get("raw_response"),
            }))

            messages.append(message)

            if cancellation_token and cancellation_token.is_cancelled:
                return AgentResult(
                    status="cancelled",
                    events=emitter.get_events(),
                )

            tool_calls = message.get("tool_calls")

            if not tool_calls:
                finish_reason = choice.get("finish_reason")

                if finish_reason == "length":
                    truncation_retries += 1
                    logger.warning(
                        "llm_response_truncated",
                        extra={
                            "agent_id": agent.id,
                            "finish_reason": "length",
                            "completion_tokens": usage.get("completion_tokens"),
                        },
                    )
                    emitter.emit(AgentEvent.now("enforcement_retry", {
                        "reason": "max_tokens_truncated",
                        "truncation_retries": truncation_retries,
                    }))

                    if truncation_retries >= max_truncation_retries:
                        summary = message.get("content", "") or "Response truncated (max retries)"
                        done_result = {
                            "summary": summary,
                            "variables": {},
                            "completion_meta": {
                                "reason": "max_tokens_truncated",
                                "turn": turn,
                                "enforcement_retries": enforcement_retries,
                                "truncation_retries": truncation_retries,
                            },
                        }
                        emitter.emit(AgentEvent.now("done", done_result))
                        return AgentResult(
                            status="completed",
                            done_result=done_result,
                            events=emitter.get_events(),
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": "truncation-nudge",
                        "content": _TRUNCATION_NUDGE_MSG,
                    })

                    emitter.emit(AgentEvent.now("turn_end", {
                        "turn_number": turn,
                        "tokens_used": usage,
                    }))
                    continue

                if context_overflow:
                    summary = message.get("content", "") or "Context limit reached"
                    done_result = {
                        "summary": summary,
                        "variables": {},
                        "completion_meta": {
                            "reason": "context_overflow",
                            "turn": turn,
                            "enforcement_retries": enforcement_retries,
                            "truncation_retries": truncation_retries,
                        },
                    }
                    emitter.emit(AgentEvent.now("done", done_result))
                    return AgentResult(
                        status="completed",
                        done_result=done_result,
                        events=emitter.get_events(),
                    )

                enforcement_retries += 1
                emitter.emit(AgentEvent.now("enforcement_retry", {
                    "reason": _ENFORCEMENT_ERROR_MSG,
                }))

                if enforcement_retries >= max_enforcement_retries:
                    summary = message.get("content", "") or "Agent did not call done()"
                    done_result = {
                        "summary": summary,
                        "variables": {},
                        "completion_meta": {
                            "reason": "enforcement_retries_exhausted",
                            "turn": turn,
                            "enforcement_retries": enforcement_retries,
                            "truncation_retries": truncation_retries,
                        },
                    }
                    emitter.emit(AgentEvent.now("done", done_result))
                    return AgentResult(
                        status="completed",
                        done_result=done_result,
                        events=emitter.get_events(),
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": "enforcement",
                    "content": _ENFORCEMENT_ERROR_MSG,
                })

                emitter.emit(AgentEvent.now("turn_end", {
                    "turn_number": turn,
                    "tokens_used": usage,
                }))
                continue

            enforcement_retries = 0
            truncation_retries = 0

            pending_found = False

            if len(tool_calls) > 1:
                tasks = []
                for tc in tool_calls:
                    tasks.append(self._execute_tool_call(
                        tc, agent, tool_provider, done_tool,
                        tool_call_history, emitter, messages, expanded_tools,
                    ))
                results = await asyncio.gather(*tasks)
                for tc, result, is_pending in results:
                    if is_pending:
                        pending_found = True
                    messages.append(result)
            else:
                tc = tool_calls[0]
                _, result, is_pending = await self._execute_tool_call(
                    tc, agent, tool_provider, done_tool,
                    tool_call_history, emitter, messages, expanded_tools,
                )
                if is_pending:
                    pending_found = True
                messages.append(result)

            emitter.emit(AgentEvent.now("turn_end", {
                "turn_number": turn,
                "tokens_used": usage,
            }))

            if pending_found:
                return AgentResult(
                    status="paused",
                    events=emitter.get_events(),
                )

            done_info = self._check_done_called(tool_calls, messages, done_tool, agent, tool_call_history, emitter)
            if done_info is not None:
                return done_info

        auto_summary = self._last_assistant_content(messages) or "Max turns reached"
        done_result = {
            "summary": auto_summary,
            "variables": {},
            "completion_meta": {
                "reason": "max_turns_reached",
                "turn": turn,
                "enforcement_retries": enforcement_retries,
                "truncation_retries": truncation_retries,
            },
        }
        emitter.emit(AgentEvent.now("done", done_result))
        return AgentResult(
            status="completed",
            done_result=done_result,
            events=emitter.get_events(),
        )

    @staticmethod
    def _tool_name(tool: dict) -> str:
        fn = tool.get("function")
        if isinstance(fn, dict):
            return fn.get("name", "")
        return tool.get("name", "")

    async def _build_tool_list(
        self,
        agent: AgentDefinition,
        tool_provider: ToolProvider,
        done_tool: DoneTool,
        expanded_tools: set[str],
    ) -> list[dict]:
        raw_tools = await tool_provider.list_tools()

        filtered = []
        seen_names: set[str] = set()
        for t in raw_tools:
            name = self._tool_name(t)
            if name and name not in seen_names and name != "done":
                filtered.append(self._to_openai_tool(t))
                seen_names.add(name)

        for name in expanded_tools:
            if name not in seen_names:
                for t in raw_tools:
                    if self._tool_name(t) == name:
                        filtered.append(self._to_openai_tool(t))
                        seen_names.add(name)
                        break

        done_schema = self._to_openai_tool(done_tool.build_schema(agent))
        filtered.append(done_schema)
        seen_names.add("done")

        if agent.has_subagents:
            if "subagents" not in seen_names:
                filtered.append(self._to_openai_tool(_SUBAGENT_TOOL_SCHEMA))
                seen_names.add("subagents")

        return filtered

    @staticmethod
    def _to_openai_tool(tool: dict) -> dict:
        if "function" in tool:
            return tool
        schema = tool.get("inputSchema") or tool.get("parameters", {})
        return {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": schema,
            },
        }

    async def _call_llm_with_retries(
        self,
        llm: Callable,
        agent: AgentDefinition,
        messages: list[dict],
        tools: list[dict],
        emitter: EventEmitter,
        config: LoopConfig,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(config.max_retries + 1):
            try:
                safe_tools = []
                for t in tools:
                    if t.get("type") == "function" and "function" in t:
                        safe_tools.append(t)
                    elif "function" in t:
                        safe_tools.append({"type": "function", "function": t["function"]})
                    else:
                        safe_tools.append({"type": "function", "function": {
                            "name": t.get("name", ""),
                            "description": t.get("description", ""),
                            "parameters": t.get("inputSchema") or t.get("parameters", {}),
                        }})

                kwargs: dict[str, Any] = {
                    "model": agent.llm_profile,
                    "messages": messages,
                    "tools": safe_tools,
                    "temperature": agent.temperature,
                    "max_tokens": agent.max_tokens,
                }
                return await llm(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < config.max_retries:
                    delay = config.retry_base_delay * (2 ** attempt)
                    jitter = random.uniform(0, 0.1 * delay)
                    actual_delay = delay + jitter
                    emitter.emit(AgentEvent.now("llm_retry", {
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "delay": actual_delay,
                    }))
                    await asyncio.sleep(actual_delay)

        raise last_error

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            total += len(str(msg)) // 4
        return total

    async def _execute_tool_call(
        self,
        tool_call: dict,
        agent: AgentDefinition,
        tool_provider: ToolProvider,
        done_tool: DoneTool,
        tool_call_history: dict[str, int],
        emitter: EventEmitter,
        messages: list[dict],
        expanded_tools: set[str],
    ) -> tuple[dict, dict, bool]:
        function = tool_call.get("function", {})
        tool_name = function.get("name", "")
        call_id = tool_call.get("id", "")
        arguments_str = function.get("arguments", "{}")

        import json
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except (json.JSONDecodeError, TypeError):
            arguments = {}

        emitter.emit(AgentEvent.now("tool_call", {
            "tool_name": tool_name,
            "arguments": arguments,
            "call_id": call_id,
        }))

        is_pending = False

        if tool_name == "done":
            is_valid, error_msg = done_tool.validate(arguments, agent, tool_call_history)
            if is_valid:
                done_vars = self._extract_done_variables(arguments, agent)
                result_content = json.dumps(done_tool.build_result(
                    arguments.get("summary", ""),
                    done_vars,
                ))
                emitter.emit(AgentEvent.now("done", {
                    "summary": arguments.get("summary", ""),
                    "variables": done_vars,
                }))
            else:
                result_content = json.dumps({"success": False, "error": error_msg})
                emitter.emit(AgentEvent.now("tool_result", {
                    "tool_name": tool_name,
                    "result": {"success": False, "error": error_msg},
                    "call_id": call_id,
                    "_pending": False,
                }))
                tool_call_history[tool_name] = tool_call_history.get(tool_name, 0) + 1
                result_msg = {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_content,
                }
                return tool_call, result_msg, False
        else:
            result_data = await tool_provider.execute(tool_name, arguments)
            if result_data.get("_pending"):
                is_pending = True
            if "allowed_tools" in result_data:
                for t in result_data["allowed_tools"]:
                    expanded_tools.add(t)
            result_content = json.dumps(result_data)

        tool_call_history[tool_name] = tool_call_history.get(tool_name, 0) + 1

        emitter.emit(AgentEvent.now("tool_result", {
            "tool_name": tool_name,
            "result": result_content,
            "call_id": call_id,
            "_pending": is_pending,
        }))

        result_msg = {
            "role": "tool",
            "tool_call_id": call_id,
            "content": result_content,
        }
        return tool_call, result_msg, is_pending

    def _check_done_called(
        self,
        tool_calls: list[dict],
        messages: list[dict],
        done_tool: DoneTool,
        agent: AgentDefinition,
        tool_call_history: dict[str, int],
        emitter: EventEmitter,
    ) -> AgentResult | None:
        for tc in tool_calls:
            func = tc.get("function", {})
            if func.get("name") != "done":
                continue

            import json
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except (json.JSONDecodeError, TypeError):
                args = {}

            is_valid, _ = done_tool.validate(args, agent, tool_call_history)
            if is_valid:
                done_vars = self._extract_done_variables(args, agent)
                done_result = done_tool.build_result(
                    args.get("summary", ""),
                    done_vars,
                )
                return AgentResult(
                    status="completed",
                    done_result=done_result,
                    events=emitter.get_events(),
                )

        return None

    @staticmethod
    def _extract_done_variables(args: dict, agent: AgentDefinition) -> dict:
        if agent.done_variables:
            variables = {}
            for var_name in agent.done_variables:
                if var_name in args:
                    variables[var_name] = args[var_name]
            if variables:
                return variables
        return args.get("variables", {})

    @staticmethod
    def _last_assistant_content(messages: list[dict]) -> str | None:
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        return None
