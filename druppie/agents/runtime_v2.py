"""AgentV2 — new Agent facade using agent_runtime library.

Replicates the public API of the old Agent class (druppie/agents/runtime.py)
but delegates all execution to the new AgentLoop from agent_runtime/loop.py
via compat.py adapters.

Usage:
    agent = AgentV2("router", db=db_session)
    result = await agent.run("Create a todo app", session_id=uuid, agent_run_id=uuid)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from druppie.agent_runtime.compaction import CompactionConfig
from druppie.agent_runtime.compat import (
    DruppieToolProvider,
    SubagentsMCPConnection,
    adapt_llm,
    create_event_persister,
    old_definition_to_new,
)
from druppie.agent_runtime.loop import AgentLoop
from druppie.agent_runtime.types import AgentResult, LoopConfig
from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.agents.message_history import reconstruct_from_db
from druppie.agents.prompt_builder import DEFAULT_LANGUAGE, PromptBuilder
from druppie.agents.runtime import AgentError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

logger = structlog.get_logger()


class AgentMaxIterationsError(AgentError):
    """Agent exceeded maximum iterations."""
    pass


class AgentV2:
    """New Agent facade using agent_runtime library.

    Same public API as the old Agent class but internally uses AgentLoop
    from agent_runtime/loop.py via compat.py adapters.
    """

    def __init__(self, agent_id: str, db: DBSession | None = None, **kwargs):
        self.id = agent_id
        self.definition = self._load_definition(agent_id)
        self._db = db
        self._llm = None
        self._tool_executor = None
        self._mcp_config = None
        self._prompt_builder = None
        self._agent_loop = AgentLoop()
        self._tool_registry = None

    # ------------------------------------------------------------------
    # Class methods — delegate to AgentDefinitionLoader
    # ------------------------------------------------------------------

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        AgentDefinitionLoader.set_definitions_path(path)

    @classmethod
    def _load_definition(cls, agent_id: str):
        return AgentDefinitionLoader.load(agent_id)

    @classmethod
    def list_agents(cls) -> list[str]:
        return AgentDefinitionLoader.list_agents()

    # ------------------------------------------------------------------
    # Lazy properties
    # ------------------------------------------------------------------

    @property
    def db(self) -> DBSession:
        if self._db is None:
            from druppie.api.deps import get_db
            self._db = next(get_db())
        return self._db

    @property
    def llm(self):
        if self._llm is None:
            from druppie.llm import get_llm_service
            self._llm = get_llm_service().create_llm_for_agent(self.definition)
        return self._llm

    @property
    def mcp_config(self):
        if self._mcp_config is None:
            from druppie.core.mcp_config import MCPConfig
            self._mcp_config = MCPConfig()
        return self._mcp_config

    @property
    def tool_executor(self):
        if self._tool_executor is None:
            from druppie.execution.mcp_http import MCPHttp
            from druppie.execution.tool_executor import ToolExecutor
            mcp_http = MCPHttp(self.mcp_config)
            self._tool_executor = ToolExecutor(self.db, mcp_http, self.mcp_config)
        return self._tool_executor

    @property
    def tool_registry(self):
        if self._tool_registry is None:
            from druppie.core.tool_registry import get_tool_registry
            self._tool_registry = get_tool_registry()
        return self._tool_registry

    @property
    def prompt_builder(self) -> PromptBuilder:
        if self._prompt_builder is None:
            self._prompt_builder = PromptBuilder(self.id, self.definition)
        return self._prompt_builder

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        session_id: UUID | str,
        agent_run_id: UUID | str,
        context: dict = None,
    ) -> Any:
        """Run the agent with the given prompt using new AgentLoop."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        language = self._extract_language(context)
        language_info = context.get("language_info") if context else None

        messages = [
            {"role": "system", "content": self.prompt_builder.build_system_prompt(language, language_info)},
            {"role": "user", "content": self.prompt_builder.build_user_prompt(prompt, context)},
        ]

        return await self._run_with_new_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=0,
        )

    async def continue_run(
        self,
        session_id: UUID | str,
        agent_run_id: UUID | str,
        context: dict = None,
    ) -> Any:
        """Continue a paused agent run by reconstructing state from DB."""
        from druppie.repositories import ExecutionRepository

        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        execution_repo = ExecutionRepository(self.db)
        agent_run = execution_repo.get_by_id(agent_run_id)
        if not agent_run:
            raise ValueError(f"Agent run not found: {agent_run_id}")

        prompt = agent_run.planned_prompt or ""
        language = self._extract_language(context)
        language_info = context.get("language_info") if context else None

        llm_calls = execution_repo.get_llm_calls_for_run(agent_run_id)

        db_tool_calls = execution_repo.get_tool_calls_for_run(agent_run_id)
        tool_call_history: dict[str, int] = {}
        for tc in db_tool_calls:
            if tc.mcp_server and tc.mcp_server != "builtin":
                key = f"{tc.mcp_server}_{tc.tool_name}"
            else:
                key = tc.tool_name
            tool_call_history[key] = tool_call_history.get(key, 0) + 1

        if not llm_calls:
            logger.warning(
                "continue_run_no_llm_calls",
                agent_run_id=str(agent_run_id),
            )
            messages = [
                {"role": "system", "content": self.prompt_builder.build_system_prompt(language, language_info)},
                {"role": "user", "content": self.prompt_builder.build_user_prompt(prompt, context)},
            ]
            user_ctx = context.get("user_context") if context else None
            if user_ctx:
                messages.append({
                    "role": "user",
                    "content": f"[Additional context from user on resume]\n{user_ctx}",
                })
            return await self._run_with_new_loop(
                messages=messages,
                prompt=prompt,
                context=context,
                session_id=session_id,
                agent_run_id=agent_run_id,
                start_iteration=0,
                tool_call_history=tool_call_history,
            )

        messages = reconstruct_from_db(llm_calls, execution_repo)
        iteration = len(llm_calls)

        if not messages or messages[0].get("role") != "system":
            logger.info(
                "continue_run_prepending_prompts",
                agent_run_id=str(agent_run_id),
                reconstructed_count=len(messages),
            )
            messages = [
                {"role": "system", "content": self.prompt_builder.build_system_prompt(language, language_info)},
                {"role": "user", "content": self.prompt_builder.build_user_prompt(prompt, context)},
            ] + messages

        old_language = None
        if messages and messages[0].get("role") == "system":
            old_system = messages[0].get("content", "")
            import re
            match = re.search(r"→\s*(nl|en)\s*\(", old_system)
            if match:
                old_language = match.group(1).lower()
            else:
                match = re.search(r"Language:\s*(nl|en)", old_system)
                if match:
                    old_language = match.group(1).lower()

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = self.prompt_builder.build_system_prompt(language, language_info)

        if context and context.get("language_info") and old_language and old_language != language:
            from druppie.agents.prompt_builder import LANGUAGE_NAMES
            lang_name = LANGUAGE_NAMES.get(language, language.upper())
            messages.append({
                "role": "system",
                "content": f"LANGUAGE SWITCH: User now speaks {lang_name}. Respond in {lang_name}."
            })
            logger.info(
                "language_switch_detected",
                old_language=old_language,
                new_language=language,
            )

        user_ctx = context.get("user_context") if context else None
        if user_ctx:
            messages.append({
                "role": "user",
                "content": f"[Additional context from user on resume]\n{user_ctx}",
            })
            logger.info("user_context_injected", agent_run_id=str(agent_run_id))

        logger.info(
            "agent_continue_run_v2",
            agent_id=self.id,
            agent_run_id=str(agent_run_id),
            llm_calls_count=len(llm_calls),
            messages_count=len(messages),
            continuing_from_iteration=iteration,
            has_context=bool(context),
            conversational_language=language,
        )

        return await self._run_with_new_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=iteration,
            tool_call_history=tool_call_history,
        )

    async def resume(
        self,
        agent_state: dict,
        answer: str,
        session_id: UUID | str,
        agent_run_id: UUID | str,
    ) -> Any:
        """Resume after HITL answer."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        messages = list(agent_state.get("messages", []))
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        question = agent_state.get("question", "")
        tool_call_history = agent_state.get("tool_call_history")

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
            "agent_resume_v2",
            agent_id=self.id,
            iteration=start_iteration,
            answer_preview=answer[:50] if answer else "",
        )

        return await self._run_with_new_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
            tool_call_history=tool_call_history,
        )

    async def resume_from_approval(
        self,
        agent_state: dict,
        tool_result: dict,
        session_id: UUID | str,
        agent_run_id: UUID | str,
    ) -> Any:
        """Resume after MCP tool approval."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        messages = list(agent_state.get("messages", []))
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        tool_call_id = agent_state.get("tool_call_id", f"call_{start_iteration}")
        tool_call_history = agent_state.get("tool_call_history")

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(tool_result) if isinstance(tool_result, (dict, list)) else str(tool_result),
        })

        logger.info(
            "agent_resume_from_approval_v2",
            agent_id=self.id,
            iteration=start_iteration,
            tool=agent_state.get("tool_name"),
            has_tool_call_history=bool(tool_call_history),
        )

        return await self._run_with_new_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
            tool_call_history=tool_call_history,
        )

    # ------------------------------------------------------------------
    # New agent loop execution
    # ------------------------------------------------------------------

    async def _run_with_new_loop(
        self,
        messages: list[dict],
        prompt: str,
        context: dict | None,
        session_id: UUID,
        agent_run_id: UUID,
        start_iteration: int,
        tool_call_history: dict[str, int] | None = None,
    ) -> dict:
        """Execute the agent using new AgentLoop from agent_runtime.

        Returns old-format dict for backward compatibility with orchestrator:
        - On success: {"success": True, "result": summary_string}
        - On pause: {"status": "paused", "reason": "...", "tool_call_id": "...", "agent_state": {...}}
        """
        from druppie.repositories import ExecutionRepository

        repo = ExecutionRepository(self.db)

        loop_config = LoopConfig(
            max_turns=self.definition.max_iterations or 20,
        )

        compaction_config = self._build_compaction_config(loop_config)
        summary_llm = None

        from druppie.agent_runtime.types import SessionPauseToken

        # Create cancellation token that polls for session PAUSED status
        cancellation_token = SessionPauseToken(
            db_session_factory=None,  # uses SessionLocal internally
            session_id=session_id,
            poll_interval=2.0,
        )
        cancellation_token.start_polling()

        adapted_llm = await adapt_llm(self.llm)
        new_def = old_definition_to_new(self.definition)

        provider_name = getattr(self.llm, 'provider_name', 'unknown')

        tool_provider = DruppieToolProvider(
            execution_repo=repo,
            tool_executor=self.tool_executor,
            session_id=session_id,
            agent_run_id=agent_run_id,
            old_agent_definition=self.definition,
            tool_registry=self.tool_registry,
        )

        event_persister = create_event_persister(
            repo, session_id, agent_run_id, tool_provider,
            provider_name=provider_name,
        )

        subagents_conn = None
        if getattr(self.definition, "subagents", []):

            def _child_tp_factory(*, child_defn, child_sandbox_conn, parent_tool_provider, spawning_tool_call_id=None, current_depth=0, agent_chain=None, _parent_run_id=None):
                from druppie.domain.common import AgentRunStatus
                from druppie.repositories import ExecutionRepository
                child_repo = ExecutionRepository(self.db)
                child_agent_run = child_repo.create_agent_run(
                    session_id=session_id,
                    agent_id=child_defn.id,
                    status=AgentRunStatus.RUNNING,
                    planned_prompt="",
                    parent_run_id=_parent_run_id or agent_run_id,
                    spawning_tool_call_id=spawning_tool_call_id,
                )
                self.db.flush()
                child_tp = DruppieToolProvider(
                    execution_repo=child_repo,
                    tool_executor=self.tool_executor,
                    session_id=session_id,
                    agent_run_id=child_agent_run.id,
                    old_agent_definition=self._load_definition(child_defn.id),
                    tool_registry=self.tool_registry,
                )
                child_tp.event_callback = create_event_persister(
                    child_repo, session_id, child_agent_run.id, child_tp,
                    provider_name=provider_name,
                )
                # If the child agent itself has subagents (self-referencing
                # recursion or branching), register a nested SubagentsMCPConnection
                # so the child can also spawn subagents.
                child_subagents = getattr(child_defn, 'subagents', None) or getattr(self._load_definition(child_defn.id), 'subagents', [])
                if child_subagents:
                    child_subagents_conn = SubagentsMCPConnection(
                        agent_loader=lambda agent_id: old_definition_to_new(
                            self._load_definition(agent_id)
                        ),
                        sandbox_resolver=None,
                        loop_runner=self._agent_loop.run,
                        llm=adapted_llm,
                        config=loop_config,
                        event_callback=create_event_persister(
                            child_repo, session_id, child_agent_run.id, child_tp,
                            provider_name=provider_name,
                        ),
                        parent_tool_provider=child_tp,
                        parent_agent_def=old_definition_to_new(child_defn),
                        child_tool_provider_factory=lambda **kw: _child_tp_factory(**{**kw, '_parent_run_id': child_agent_run.id}),
                        current_depth=current_depth,
                        agent_chain=agent_chain,
                        cancellation_token=cancellation_token,
                    )
                    child_tp.set_subagents_connection(child_subagents_conn)
                return child_tp

            subagents_conn = SubagentsMCPConnection(
                agent_loader=lambda agent_id: old_definition_to_new(
                    self._load_definition(agent_id)
                ),
                sandbox_resolver=None,
                loop_runner=self._agent_loop.run,
                llm=adapted_llm,
                config=loop_config,
                event_callback=event_persister,
                parent_tool_provider=tool_provider,
                parent_agent_def=new_def,
                child_tool_provider_factory=_child_tp_factory,
                cancellation_token=cancellation_token,
            )
            tool_provider.set_subagents_connection(subagents_conn)

        try:
            agent_result: AgentResult = await self._agent_loop.run(
                agent=new_def,
                agent_loader=lambda _: new_def,
                tool_provider=tool_provider,
                prompt=prompt,
                initial_messages=messages,
                llm=adapted_llm,
                event_callbacks=[event_persister],
                config=loop_config,
                tool_call_history=tool_call_history,
                cancellation_token=cancellation_token,
                compaction_config=compaction_config,
                summary_llm=summary_llm,
            )
        finally:
            await cancellation_token.cleanup()

        return self._convert_result(
            agent_result, messages, prompt, context, start_iteration,
        )

    def _convert_result(
        self,
        agent_result: AgentResult,
        messages: list[dict],
        prompt: str,
        context: dict | None,
        start_iteration: int,
    ) -> dict:
        """Convert new AgentResult back to old dict format.

        The orchestrator and API handlers expect this format:
        - Success: {"success": True, "result": summary}
        - Pause: {"status": "paused", "reason": "...", "tool_call_id": "..."}
        """
        if agent_result.status == "completed":
            summary = ""
            if agent_result.done_result:
                summary = agent_result.done_result.get("summary", "")
            return {"success": True, "result": summary}

        if agent_result.status == "paused":
            pause_reason = self._infer_pause_reason(agent_result)
            # Capture tool_call_history so done() preconditions survive HITL resume
            tool_call_history = getattr(self._agent_loop, "_tool_call_history", {})
            return {
                "status": "paused",
                "reason": pause_reason,
                "tool_call_id": "",
                "agent_state": {
                    "agent_id": self.id,
                    "messages": messages,
                    "prompt": prompt,
                    "context": context or {},
                    "iteration": start_iteration,
                    "tool_call_id": "",
                    "tool_call_history": tool_call_history,
                },
            }

        if agent_result.status == "cancelled":
            return {"status": "paused", "reason": "user_paused"}

        if agent_result.status == "error":
            raise AgentError(agent_result.error or "Unknown agent error")

        raise AgentError(f"Unknown agent result status: {agent_result.status}")

    @staticmethod
    def _infer_pause_reason(result: AgentResult) -> str:
        """Infer the pause reason from AgentResult events."""
        if not result.events:
            return "waiting_answer"
        for event in reversed(result.events):
            if event.type == "tool_result":
                data = event.data
                pending = data.get("_pending", False)
                if pending:
                    reason = data.get("result", "")
                    if isinstance(reason, dict):
                        reason = reason.get("reason", "waiting_answer")
                    if "approval" in str(reason).lower():
                        return "waiting_approval"
                    if "sandbox" in str(reason).lower():
                        return "waiting_sandbox"
                    return "waiting_answer"
        return "waiting_answer"

    # ------------------------------------------------------------------
    # Compaction configuration
    # ------------------------------------------------------------------

    def _build_compaction_config(self, loop_config: LoopConfig) -> CompactionConfig:
        """Build CompactionConfig from agent definition and loop config."""
        cc = CompactionConfig(
            max_context_tokens=loop_config.max_context_tokens,
        )
        compression = getattr(self.definition, "compression", None)
        if compression and isinstance(compression, dict):
            if "summarization_threshold" in compression:
                cc.summarization_threshold = compression["summarization_threshold"]
            if "max_compactions" in compression:
                cc.max_compactions = compression["max_compactions"]
        return cc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_uuids(session_id, agent_run_id):
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)
        return session_id, agent_run_id

    @staticmethod
    def _extract_language(context: dict | None) -> str:
        if context and "conversational_language" in context:
            return context["conversational_language"]
        return DEFAULT_LANGUAGE

    def __repr__(self) -> str:
        return f"AgentV2({self.id!r})"
