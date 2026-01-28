"""Execution repository - handles AgentRun, ToolCall, and LLMCall records."""

from datetime import datetime, timezone
from uuid import UUID

from druppie.db.models import AgentRun, ToolCall, LlmCall
from druppie.domain.common import AgentRunStatus, TokenUsage
from druppie.domain.agent_run import AgentRunSummary
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
        workflow_step_id: UUID | None = None,
    ) -> AgentRunSummary:
        """Create an agent run record."""
        agent_run = AgentRun(
            session_id=session_id,
            agent_id=agent_id,
            status=status.value,
            planned_prompt=planned_prompt,
            sequence_number=sequence_number,
            parent_run_id=parent_run_id,
            workflow_step_id=workflow_step_id,
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

    def update_status(self, agent_run_id: UUID, status: AgentRunStatus) -> None:
        """Update agent run status."""
        agent_run = self.db.query(AgentRun).filter(AgentRun.id == agent_run_id).first()
        if agent_run:
            agent_run.status = status.value
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

    def _to_summary(self, agent_run: AgentRun) -> AgentRunSummary:
        """Convert AgentRun model to AgentRunSummary domain model."""
        return AgentRunSummary(
            id=agent_run.id,
            agent_id=agent_run.agent_id,
            status=AgentRunStatus(agent_run.status),
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
    ) -> UUID:
        """Create a tool call record."""
        tool_call = ToolCall(
            session_id=session_id,
            agent_run_id=agent_run_id,
            mcp_server=mcp_server,
            tool_name=tool_name,
            arguments=arguments,
            status="pending",
        )
        self.db.add(tool_call)
        self.db.flush()
        return tool_call.id

    def update_tool_result(
        self,
        tool_call_id: UUID,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update tool call result."""
        tool_call = self.db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()
        if tool_call:
            tool_call.status = status
            tool_call.result = result
            tool_call.error_message = error
            tool_call.executed_at = datetime.now(timezone.utc)

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
    ) -> UUID:
        """Create an LLM call record."""
        llm_call = LlmCall(
            session_id=session_id,
            agent_run_id=agent_run_id,
            provider=provider,
            model=model,
            request_messages=messages,
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
