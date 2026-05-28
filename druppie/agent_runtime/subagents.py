"""SubagentsMCP — in-process MCP server for spawning subagent runtime instances.

Provides the subagents() tool that allows agents to spawn child runtime instances.
The subagents MCP server runs in-process inside the backend (or any caller).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.tools.provider import MCPToolProvider
from druppie.agent_runtime.types import AgentEvent, AgentResult, CancellationToken, LoopConfig
from druppie.domain.common import AgentRunStatus


def _resolve_pause_status(result: AgentResult) -> AgentRunStatus:
    """Determine the AgentRunStatus for a paused child from its events.

    Scans events in reverse to find the last tool_result with _pending=True,
    then maps the reason to the appropriate AgentRunStatus (matching the
    orchestrator's mapping at execution/orchestrator.py lines 492-502).
    """
    for event in reversed(result.events):
        if event.type == "tool_result" and event.data.get("_pending"):
            raw = event.data.get("result", "{}")
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                data = {}
            reason = data.get("reason", "")
            if reason == "waiting_answer":
                return AgentRunStatus.PAUSED_HITL
            elif reason == "waiting_sandbox":
                return AgentRunStatus.PAUSED_SANDBOX
            elif reason == "user_paused":
                return AgentRunStatus.PAUSED_USER
            break
    return AgentRunStatus.PAUSED_TOOL


class SubagentsMCP:
    """In-process MCP server providing the subagents() tool.

    Responsibilities:
    - Dynamic schema generation based on allowed agents
    - Agent name validation (two-layer: schema enum + server-side)
    - Role enforcement (reject subagent-only agents at top level)
    - Sandbox resolution (share or new based on git scope)
    - Parallel subagent spawning via asyncio.gather
    - Recursion depth tracking
    - Circular reference detection
    """

    def __init__(
        self,
        agent_loader: Callable[[str], AgentDefinition],
        sandbox_resolver: Callable[[str], Awaitable[MCPConnection]] | None = None,
        loop_runner: Callable | None = None,
        child_tool_provider_factory: Callable | None = None,
    ) -> None:
        self._agent_loader = agent_loader
        self._sandbox_resolver = sandbox_resolver
        self._loop_runner = loop_runner
        self._child_tool_provider_factory = child_tool_provider_factory

    def build_schema(self, allowed_agents: list[str]) -> dict:
        """Generate the subagents() tool schema with enum restriction.

        The agent parameter enum is restricted to only allowed agents,
        preventing 99% of invalid calls at the LLM framework level.
        """
        agent_descriptions: list[str] = []
        for agent_id in allowed_agents:
            try:
                defn = self._agent_loader(agent_id)
                agent_descriptions.append(f"- {agent_id}: {defn.description}")
            except Exception:
                agent_descriptions.append(f"- {agent_id}")

        description = (
            "Spawn subagents to accomplish tasks. Available agents:\n"
            + "\n".join(agent_descriptions)
            + "\n\nEach subagent runs independently and returns results."
        )

        return {
            "name": "subagents",
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {"type": "string", "enum": list(allowed_agents)},
                                "prompt": {"type": "string"},
                            },
                            "required": ["agent", "prompt"],
                        },
                    }
                },
                "required": ["agents"],
            },
        }

    async def execute(
        self,
        agents: list[dict[str, Any]],
        parent_agent: AgentDefinition,
        parent_tool_provider: Any,
        parent_git_scope: str | None,
        parent_sandbox_conn: MCPConnection | None,
        llm: Callable,
        config: LoopConfig,
        event_callback: Callable[[AgentEvent], None] | None = None,
        current_depth: int = 0,
        agent_chain: list[str] | None = None,
        cancellation_token: CancellationToken | None = None,
        spawning_tool_call_id: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Spawn subagents and collect results.

        Args:
            agents: [{"agent": "builder", "prompt": "..."}, ...]
            parent_agent: The parent agent's definition
            parent_tool_provider: The parent's ToolProvider
            parent_git_scope: The parent's sandbox git scope
            parent_sandbox_conn: The parent's sandbox MCPConnection
            llm: LLM callable for subagents
            config: Loop configuration
            event_callback: Callback for events
            current_depth: Current recursion depth
            agent_chain: List of agent IDs in the chain (informational, depth-limited)
            cancellation_token: Cancellation token

        Returns:
            List of results when all children complete, or dict with
            {"results": [...], "_pending": True} when any child paused.
        """
        chain = agent_chain or []

        async def spawn_one(agent_spec: dict[str, Any]) -> dict[str, Any]:
            agent_id = agent_spec["agent"]
            prompt = agent_spec["prompt"]

            if agent_id not in parent_agent.subagents:
                return {
                    "agent": agent_id,
                    "status": "error",
                    "result": None,
                    "error": f"Agent '{agent_id}' not in allowed subagents list: {parent_agent.subagents}",
                }

            new_depth = current_depth + 1
            if new_depth > config.max_subagent_depth:
                return {
                    "agent": agent_id,
                    "status": "error",
                    "result": None,
                    "error": f"Maximum subagent depth ({config.max_subagent_depth}) exceeded",
                }

            try:
                child_defn = self._agent_loader(agent_id)
            except Exception as e:
                return {
                    "agent": agent_id,
                    "status": "error",
                    "result": None,
                    "error": f"Failed to load agent '{agent_id}': {e}",
                }



            child_sandbox_conn = await self._resolve_sandbox(
                child_defn.sandbox_git_scope, parent_git_scope, parent_sandbox_conn
            )

            if self._child_tool_provider_factory is not None:
                child_tool_provider = self._child_tool_provider_factory(
                    child_defn=child_defn,
                    child_sandbox_conn=child_sandbox_conn,
                    parent_tool_provider=parent_tool_provider,
                    spawning_tool_call_id=spawning_tool_call_id,
                    current_depth=new_depth,
                    agent_chain=chain + [parent_agent.id],
                )
            elif child_sandbox_conn is not None:
                child_tool_provider = MCPToolProvider(
                    {"sandbox": child_sandbox_conn}
                )
            else:
                child_tool_provider = MCPToolProvider({})

            if event_callback:
                event_callback(AgentEvent.now("subagent_start", {
                    "agent": agent_id,
                    "task": prompt,
                    "depth": new_depth,
                    "parent_agent_id": parent_agent.id,
                }))

            try:
                if self._loop_runner is None:
                    return {
                        "agent": agent_id,
                        "status": "error",
                        "result": None,
                        "error": "No loop runner configured",
                    }

                child_event_cb = getattr(child_tool_provider, 'event_callback', None) or event_callback

                # Build child-specific config using the child's max_iterations
                # instead of inheriting the parent's max_turns.
                child_config = LoopConfig(
                    max_turns=getattr(child_defn, 'max_iterations', None) or config.max_turns,
                    max_retries=config.max_retries,
                    retry_base_delay=config.retry_base_delay,
                    respect_retry_after=config.respect_retry_after,
                    max_context_tokens=config.max_context_tokens,
                    max_subagent_depth=config.max_subagent_depth,
                )

                child_result = await self._loop_runner(
                    agent=child_defn,
                    agent_loader=self._agent_loader,
                    tool_provider=child_tool_provider,
                    prompt=prompt,
                    llm=llm,
                    sandbox_resolver=self._sandbox_resolver,
                    event_callbacks=[child_event_cb] if child_event_cb else [],
                    config=child_config,
                    cancellation_token=cancellation_token,
                )

                child_repo = getattr(child_tool_provider, '_execution_repo', None)
                child_run_id = getattr(child_tool_provider, '_agent_run_id', None)

                if child_result.status == "paused":
                    if child_repo is not None and child_run_id is not None:
                        pause_status = _resolve_pause_status(child_result)
                        child_repo.update_status(child_run_id, pause_status)

                    if event_callback:
                        event_callback(AgentEvent.now("subagent_end", {
                            "agent": agent_id,
                            "result": child_result.done_result if child_result else None,
                            "depth": new_depth,
                            "parent_agent_id": parent_agent.id,
                            "paused": True,
                        }))

                    return {
                        "agent": agent_id,
                        "status": "paused",
                        "result": child_result,
                        "error": None,
                    }

                if child_repo is not None and child_run_id is not None:
                    child_repo.update_status(child_run_id, AgentRunStatus.COMPLETED)

                if event_callback:
                    event_callback(AgentEvent.now("subagent_end", {
                        "agent": agent_id,
                        "result": child_result.done_result if child_result else None,
                        "depth": new_depth,
                        "parent_agent_id": parent_agent.id,
                    }))

                return {
                    "agent": agent_id,
                    "status": "success",
                    "result": child_result,
                    "error": None,
                }
            except Exception as e:
                # Mark child agent_run as failed
                child_repo = getattr(child_tool_provider, '_execution_repo', None)
                child_run_id = getattr(child_tool_provider, '_agent_run_id', None)
                if child_repo is not None and child_run_id is not None:
                    child_repo.update_status(
                        child_run_id, AgentRunStatus.FAILED, error_message=str(e)
                    )

                if event_callback:
                    event_callback(AgentEvent.now("subagent_end", {
                        "agent": agent_id,
                        "result": None,
                        "depth": new_depth,
                        "parent_agent_id": parent_agent.id,
                    }))
                return {
                    "agent": agent_id,
                    "status": "error",
                    "result": None,
                    "error": str(e),
                }

        tasks = [spawn_one(spec) for spec in agents]
        results = await asyncio.gather(*tasks)
        results_list = list(results)
        any_paused = any(r.get("status") == "paused" for r in results_list)
        if any_paused:
            return {"results": results_list, "_pending": True}
        return results_list

    async def _resolve_sandbox(
        self,
        child_git_scope: str | None,
        parent_git_scope: str | None,
        parent_sandbox_conn: MCPConnection | None,
    ) -> MCPConnection | None:
        """Resolve sandbox connection for a child agent.

        Rules:
        - No sandbox needed if child has no mcps.sandbox
        - Share parent's connection if same git scope
        - Create new connection via sandbox_resolver if different git scope
        """
        if child_git_scope is None:
            return None

        if child_git_scope == parent_git_scope and parent_sandbox_conn is not None:
            return parent_sandbox_conn

        if self._sandbox_resolver is not None:
            return await self._sandbox_resolver(child_git_scope)

        return None
