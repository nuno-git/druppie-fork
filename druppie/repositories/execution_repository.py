"""Execution repository - handles AgentRun, ToolCall, LLMCall, and Message records."""

from datetime import datetime, timezone
from uuid import UUID

from druppie.db.models import AgentRun, LlmCall, LlmRetry, Message, ToolCall, ToolCallNormalization
from druppie.domain.agent_run import AgentRunSummary
from druppie.domain.common import AgentRunStatus, TokenUsage
from druppie.repositories.base import BaseRepository


class ExecutionRepository(BaseRepository):
    """Combined repository for execution records (agent_runs, tool_calls, llm_calls)."""

    # =========================================================================
    # AGENT RUN METHODS
    # =========================================================================

    def create_agent_run(
        self,
        session_id: UUID,
        agent_id: str,
        status: AgentRunStatus = AgentRunStatus.RUNNING,
        planned_prompt: str | None = None,
        sequence_number: int | None = None,
        parent_run_id: UUID | None = None,
    ) -> AgentRunSummary:
        """Create an agent run record."""
        agent_run = AgentRun(
            session_id=session_id,
            agent_id=agent_id,
            status=status.value,
            planned_prompt=planned_prompt,
            sequence_number=sequence_number,
            parent_run_id=parent_run_id,
        )
        self.db.add(agent_run)
        self.db.flush()
        return self._to_summary(agent_run)

    def get_by_id(self, agent_run_id: UUID) -> AgentRunSummary | None:
        """Get agent run by ID."""
        agent_run = self.db.query(AgentRun).filter(AgentRun.id == agent_run_id).first()
        return self._to_summary(agent_run) if agent_run else None

    def get_next_pending(self, session_id: UUID) -> AgentRunSummary | None:
        """Get next pending agent run for a session (ordered by sequence_number)."""
        agent_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PENDING.value,
            )
            .order_by(AgentRun.sequence_number)
            .first()
        )
        return self._to_summary(agent_run) if agent_run else None

    def cancel_pending_runs(self, session_id: UUID) -> int:
        """Cancel all pending agent runs for a session.

        Used by make_plan() to clear stale pending runs from a previous plan
        before creating new ones.
        """
        pending_runs = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PENDING.value,
            )
            .all()
        )
        for run in pending_runs:
            run.status = AgentRunStatus.CANCELLED.value
            run.completed_at = datetime.now(timezone.utc)
        return len(pending_runs)

    def get_pending_runs(self, session_id: UUID) -> list[AgentRunSummary]:
        """Get all pending runs (the 'plan') for a session."""
        runs = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PENDING.value,
            )
            .order_by(AgentRun.sequence_number)
            .all()
        )
        return [self._to_summary(r) for r in runs]

    def get_paused_run(self, session_id: UUID) -> AgentRunSummary | None:
        """Get the paused agent run for a session."""
        agent_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status.in_([
                    AgentRunStatus.PAUSED_TOOL.value,
                    AgentRunStatus.PAUSED_HITL.value,
                ]),
            )
            .first()
        )
        return self._to_summary(agent_run) if agent_run else None

    def update_status(
        self,
        agent_run_id: UUID,
        status: AgentRunStatus,
        error_message: str | None = None,
    ) -> None:
        """Update agent run status and optional error message."""
        agent_run = self.db.query(AgentRun).filter(AgentRun.id == agent_run_id).first()
        if agent_run:
            agent_run.status = status.value
            if error_message is not None:
                agent_run.error_message = error_message
            if status == AgentRunStatus.RUNNING and not agent_run.started_at:
                agent_run.started_at = datetime.now(timezone.utc)
            elif status in (AgentRunStatus.COMPLETED, AgentRunStatus.FAILED):
                agent_run.completed_at = datetime.now(timezone.utc)

    def update_tokens(
        self,
        agent_run_id: UUID,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Update agent run token counts."""
        agent_run = self.db.query(AgentRun).filter(AgentRun.id == agent_run_id).first()
        if agent_run:
            agent_run.prompt_tokens = (agent_run.prompt_tokens or 0) + prompt_tokens
            agent_run.completion_tokens = (agent_run.completion_tokens or 0) + completion_tokens
            agent_run.total_tokens = agent_run.prompt_tokens + agent_run.completion_tokens

    def update_planned_prompt(self, agent_run_id: UUID, planned_prompt: str) -> None:
        """Update the planned_prompt for an agent run."""
        agent_run = self.db.query(AgentRun).filter(AgentRun.id == agent_run_id).first()
        if agent_run:
            agent_run.planned_prompt = planned_prompt

    def get_pending_by_agent_id(self, session_id: UUID, agent_id: str) -> AgentRunSummary | None:
        """Get a pending agent run by session and agent ID."""
        agent_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.agent_id == agent_id,
                AgentRun.status == AgentRunStatus.PENDING.value,
            )
            .first()
        )
        return self._to_summary(agent_run) if agent_run else None

    def get_completed_runs(self, session_id: UUID) -> list[AgentRunSummary]:
        """Get all completed agent runs for a session, ordered by completion time."""
        runs = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.COMPLETED.value,
            )
            .order_by(AgentRun.completed_at)
            .all()
        )
        return [self._to_summary(r) for r in runs]

    def get_done_summary_for_run(self, agent_run_id: UUID) -> str | None:
        """Extract the summary from the done() tool call result for a completed agent run.

        Looks for a tool_call with tool_name='done' and status='completed',
        then extracts the summary from its result JSON.

        Returns:
            The summary string, or None if not found.
        """
        import json

        tool_call = (
            self.db.query(ToolCall)
            .filter(
                ToolCall.agent_run_id == agent_run_id,
                ToolCall.tool_name == "done",
                ToolCall.status == "completed",
            )
            .first()
        )
        if tool_call and tool_call.result:
            try:
                result = json.loads(tool_call.result)
                return result.get("summary")
            except (json.JSONDecodeError, AttributeError):
                pass
        return None

    def _to_summary(self, agent_run: AgentRun) -> AgentRunSummary:
        """Convert AgentRun model to AgentRunSummary domain model."""
        return AgentRunSummary(
            id=agent_run.id,
            agent_id=agent_run.agent_id,
            status=AgentRunStatus(agent_run.status),
            error_message=agent_run.error_message,
            planned_prompt=agent_run.planned_prompt,
            sequence_number=agent_run.sequence_number,
            token_usage=TokenUsage(
                prompt_tokens=agent_run.prompt_tokens or 0,
                completion_tokens=agent_run.completion_tokens or 0,
                total_tokens=agent_run.total_tokens or 0,
            ),
            started_at=agent_run.started_at,
            completed_at=agent_run.completed_at,
        )

    # =========================================================================
    # TOOL CALL METHODS
    # =========================================================================

    def create_tool_call(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        mcp_server: str,
        tool_name: str,
        arguments: dict,
        llm_call_id: UUID | None = None,
        tool_call_index: int = 0,
    ) -> UUID:
        """Create a tool call record."""
        tool_call = ToolCall(
            session_id=session_id,
            agent_run_id=agent_run_id,
            llm_call_id=llm_call_id,
            mcp_server=mcp_server,
            tool_name=tool_name,
            arguments=arguments,
            tool_call_index=tool_call_index,
            status="pending",
        )
        self.db.add(tool_call)
        self.db.flush()
        return tool_call.id

    def get_tool_call(self, tool_call_id: UUID) -> ToolCall | None:
        """Get tool call by ID (returns raw model for ToolExecutor)."""
        return self.db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()

    def get_tool_calls_for_run(self, agent_run_id: UUID) -> list[ToolCall]:
        """Get all tool calls for an agent run."""
        return (
            self.db.query(ToolCall)
            .filter(ToolCall.agent_run_id == agent_run_id)
            .order_by(ToolCall.created_at)
            .all()
        )

    def get_invoked_skills(self, agent_run_id: UUID) -> list[str]:
        """Get skill names from invoke_skill tool calls in this agent run.

        Used to check if a tool is allowed via a previously invoked skill.

        Args:
            agent_run_id: Agent run ID to check

        Returns:
            List of skill names that were invoked
        """
        import json

        tool_calls = (
            self.db.query(ToolCall)
            .filter(
                ToolCall.agent_run_id == agent_run_id,
                ToolCall.tool_name == "invoke_skill",
                ToolCall.status == "completed",
            )
            .all()
        )

        skill_names = []
        for tc in tool_calls:
            # Extract skill_name from arguments
            if tc.arguments:
                try:
                    args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    if isinstance(args, dict) and "skill_name" in args:
                        skill_names.append(args["skill_name"])
                except (json.JSONDecodeError, TypeError):
                    pass
        return skill_names

    def get_llm_calls_for_run(self, agent_run_id: UUID) -> list[LlmCall]:
        """Get all LLM calls for an agent run, ordered by creation time."""
        return (
            self.db.query(LlmCall)
            .filter(LlmCall.agent_run_id == agent_run_id)
            .order_by(LlmCall.created_at)
            .all()
        )

    def update_tool_call(
        self,
        tool_call_id: UUID,
        status: str | None = None,
        result: dict | str | None = None,
        error: str | None = None,
    ) -> None:
        """Update tool call with result.

        Args:
            tool_call_id: ID of tool call to update
            status: New status (pending, executing, waiting_approval, waiting_answer, completed, failed)
            result: Tool result (will be serialized to JSON if dict)
            error: Error message if failed
        """
        import json

        tool_call = self.db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()
        if tool_call:
            if status is not None:
                tool_call.status = status
            if result is not None:
                # Serialize dict to JSON string
                if isinstance(result, dict):
                    tool_call.result = json.dumps(result)
                else:
                    tool_call.result = result
            if error is not None:
                tool_call.error_message = error
            if status in ("completed", "failed"):
                tool_call.executed_at = datetime.now(timezone.utc)

    def update_tool_result(
        self,
        tool_call_id: UUID,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update tool call result (legacy method, use update_tool_call instead)."""
        tool_call = self.db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()
        if tool_call:
            tool_call.status = status
            tool_call.result = result
            tool_call.error_message = error
            tool_call.executed_at = datetime.now(timezone.utc)

    # =========================================================================
    # TOOL CALL NORMALIZATION METHODS
    # =========================================================================

    def create_tool_call_normalizations(
        self,
        tool_call_id: UUID,
        normalizations: list[dict],
    ) -> None:
        """Persist normalization events for a tool call.

        Args:
            tool_call_id: ID of the tool call that was normalized
            normalizations: List of dicts with field_name, original_value, normalized_value
        """
        for norm in normalizations:
            self.db.add(ToolCallNormalization(
                tool_call_id=tool_call_id,
                field_name=norm["field_name"],
                original_value=norm.get("original_value"),
                normalized_value=norm.get("normalized_value"),
            ))
        self.db.flush()

    # =========================================================================
    # LLM CALL METHODS
    # =========================================================================

    def create_llm_call(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        provider: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> UUID:
        """Create an LLM call record."""
        llm_call = LlmCall(
            session_id=session_id,
            agent_run_id=agent_run_id,
            provider=provider,
            model=model,
            request_messages=messages,
            tools_provided=tools,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        self.db.add(llm_call)
        self.db.flush()
        return llm_call.id

    def update_llm_response(
        self,
        llm_call_id: UUID,
        response_content: str | None,
        response_tool_calls: list[dict] | None,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: int,
        actual_provider: str | None = None,
        actual_model: str | None = None,
    ) -> None:
        """Update LLM call response."""
        llm_call = self.db.query(LlmCall).filter(LlmCall.id == llm_call_id).first()
        if llm_call:
            llm_call.response_content = response_content
            llm_call.response_tool_calls = response_tool_calls
            llm_call.prompt_tokens = prompt_tokens
            llm_call.completion_tokens = completion_tokens
            llm_call.total_tokens = prompt_tokens + completion_tokens
            llm_call.duration_ms = duration_ms
            if actual_provider:
                llm_call.provider = actual_provider
            if actual_model:
                llm_call.model = actual_model

    def update_llm_error(
        self,
        llm_call_id: UUID,
        error_message: str,
        duration_ms: int,
    ) -> None:
        """Update LLM call with error info when the API call fails."""
        import json

        llm_call = self.db.query(LlmCall).filter(LlmCall.id == llm_call_id).first()
        if llm_call:
            llm_call.response_content = json.dumps({"error": error_message})
            llm_call.duration_ms = duration_ms

    # =========================================================================
    # LLM RETRY METHODS
    # =========================================================================

    def create_llm_retries(
        self,
        llm_call_id: UUID,
        retries: list[dict],
    ) -> None:
        """Persist retry events for an LLM call.

        Args:
            llm_call_id: ID of the LLM call that was retried
            retries: List of dicts with attempt, error_type, error_message, delay_seconds
        """
        for retry in retries:
            self.db.add(LlmRetry(
                llm_call_id=llm_call_id,
                attempt=retry["attempt"],
                error_type=retry["error_type"],
                error_message=retry.get("error_message"),
                delay_seconds=retry.get("delay_seconds"),
            ))
        self.db.flush()

    # =========================================================================
    # MESSAGE METHODS
    # =========================================================================

    def create_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        agent_run_id: UUID | None = None,
        agent_id: str | None = None,
        sequence_number: int = 0,
    ) -> UUID:
        """Create a message record.

        Args:
            session_id: Session ID
            role: Message role (user, assistant, system)
            content: Message content
            agent_run_id: Optional agent run ID (for agent messages)
            agent_id: Optional agent ID (for assistant messages)
            sequence_number: Sequence number within session

        Returns:
            Message ID
        """
        message = Message(
            session_id=session_id,
            agent_run_id=agent_run_id,
            role=role,
            content=content,
            agent_id=agent_id,
            sequence_number=sequence_number,
        )
        self.db.add(message)
        self.db.flush()
        return message.id

    def get_message_count(self, session_id: UUID) -> int:
        """Get total message count for a session (for sequence numbering)."""
        return self.db.query(Message).filter(Message.session_id == session_id).count()
