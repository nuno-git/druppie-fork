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
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.agents.loop import AgentLoop
from druppie.agents.message_history import reconstruct_from_db
from druppie.agents.prompt_builder import DEFAULT_LANGUAGE, PromptBuilder
from druppie.core.mcp_config import MCPConfig
from druppie.execution.mcp_http import MCPHttp
from druppie.execution.tool_executor import ToolExecutor
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
    Context (language, project info) is always provided by the caller (orchestrator).
    """

    def __init__(self, agent_id: str, db: "DBSession | None" = None):
        self.id = agent_id
        self.definition = self._load_definition(agent_id)
        self._db = db
        self._llm = None
        self._tool_executor = None
        self._mcp_config = None
        self._loop = None
        self._prompt_builder = None

    # ------------------------------------------------------------------
    # Class methods — delegate to AgentDefinitionLoader
    # ------------------------------------------------------------------

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions."""
        AgentDefinitionLoader.set_definitions_path(path)

    @classmethod
    def _load_definition(cls, agent_id: str):
        """Load agent definition from YAML."""
        return AgentDefinitionLoader.load(agent_id)

    @classmethod
    def list_agents(cls) -> list[str]:
        """List available agent IDs."""
        return AgentDefinitionLoader.list_agents()

    # ------------------------------------------------------------------
    # Lazy properties
    # ------------------------------------------------------------------

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

    @property
    def loop(self) -> AgentLoop:
        """Get agent loop (lazy loaded)."""
        if self._loop is None:
            self._loop = AgentLoop(
                agent_id=self.id,
                definition=self.definition,
                llm=self.llm,
                tool_executor=self.tool_executor,
                db=self.db,
            )
        return self._loop

    @property
    def prompt_builder(self) -> PromptBuilder:
        """Get prompt builder (lazy loaded)."""
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
        """Run the agent with the given prompt."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        language = self._extract_language(context)
        language_info = context.get("language_info") if context else None

        messages = [
            {"role": "system", "content": self.prompt_builder.build_system_prompt(language, language_info)},
            {"role": "user", "content": self.prompt_builder.build_user_prompt(prompt, context)},
        ]

        return await self.loop.run(
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
        """Resume the agent from a paused state with the user's answer."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

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

        return await self.loop.run(
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
        """Resume the agent from a paused state after MCP tool approval."""
        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

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

        return await self.loop.run(
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
        context: dict = None,
    ) -> Any:
        """Continue a paused agent run by reconstructing state from the database.

        Context is provided by the orchestrator (which owns context building).
        """
        from druppie.repositories import ExecutionRepository

        session_id, agent_run_id = self._to_uuids(session_id, agent_run_id)

        execution_repo = ExecutionRepository(self.db)

        # Get the agent run to get the prompt
        agent_run = execution_repo.get_by_id(agent_run_id)
        if not agent_run:
            raise ValueError(f"Agent run not found: {agent_run_id}")

        prompt = agent_run.planned_prompt or ""
        language = self._extract_language(context)
        language_info = context.get("language_info") if context else None

        # Get all LLM calls for this run
        llm_calls = execution_repo.get_llm_calls_for_run(agent_run_id)

        if not llm_calls:
            # No previous LLM calls — start fresh
            logger.warning(
                "continue_run_no_llm_calls",
                agent_run_id=str(agent_run_id),
            )
            messages = [
                {"role": "system", "content": self.prompt_builder.build_system_prompt(language, language_info)},
                {"role": "user", "content": self.prompt_builder.build_user_prompt(prompt, context)},
            ]
            return await self.loop.run(
                messages=messages,
                prompt=prompt,
                context=context,
                session_id=session_id,
                agent_run_id=agent_run_id,
                start_iteration=0,
            )

        # Reconstruct message history from LLM calls
        messages = reconstruct_from_db(llm_calls, execution_repo)
        iteration = len(llm_calls)

        # Detect language switch by checking old system prompt
        old_language = None
        if messages and messages[0].get("role") == "system":
            old_system = messages[0].get("content", "")
            # Extract language from old system prompt
            # Format can be: "Language: nl (DUTCH)" or "Auto-detected ... → nl (DUTCH)"
            import re
            # Try arrow format first (e.g., "→ nl")
            match = re.search(r"→\s*(nl|en)\s*\(", old_system)
            if match:
                old_language = match.group(1).lower()
            else:
                # Fallback to "Language: nl" format
                match = re.search(r"Language:\s*(nl|en)", old_system)
                if match:
                    old_language = match.group(1).lower()

        # Update the system prompt with the current language
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = self.prompt_builder.build_system_prompt(language, language_info)

        # Inject synthetic system message if language switched (Option 2 + 3 combination)
        # Use language_info as indicator of HITL answer (set in _build_project_context)
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

        logger.info(
            "agent_continue_run",
            agent_id=self.id,
            agent_run_id=str(agent_run_id),
            llm_calls_count=len(llm_calls),
            messages_count=len(messages),
            continuing_from_iteration=iteration,
            has_context=bool(context),
            conversational_language=language,
        )

        return await self.loop.run(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=iteration,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_uuids(session_id, agent_run_id):
        """Convert string IDs to UUIDs if needed."""
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(agent_run_id, str):
            agent_run_id = UUID(agent_run_id)
        return session_id, agent_run_id

    @staticmethod
    def _extract_language(context: dict | None) -> str:
        """Extract conversational language from context."""
        if context and "conversational_language" in context:
            return context["conversational_language"]
        return DEFAULT_LANGUAGE

    def __repr__(self) -> str:
        return f"Agent({self.id!r})"
