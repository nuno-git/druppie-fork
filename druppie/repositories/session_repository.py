"""Session repository for database access."""

from uuid import UUID
from sqlalchemy.orm import Session as DbSession

from .base import BaseRepository
from ..domain import (
    SessionSummary,
    SessionDetail,
    SessionStatus,
    ChatItem,
    ChatItemType,
    MessageSummary,
    TokenUsage,
    LLMMessage,
    AgentRunSummary,
    AgentRunDetail,
    AgentRunStatus,
    LLMCallDetail,
    ToolCallDetail,
    ToolCallStatus,
    ApprovalSummary,
    ApprovalStatus,
    ProjectSummary,
)
from ..db.models import (
    Session as SessionModel,
    AgentRun,
    Message,
    ToolCall,
    LlmCall,
    Approval,
    Project,
)


class SessionRepository(BaseRepository):
    """Database access for sessions."""

    def get_by_id(self, session_id: UUID) -> SessionModel | None:
        """Get raw session model."""
        return self.db.query(SessionModel).filter_by(id=session_id).first()

    def list_for_user(
        self,
        user_id: UUID | None,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user with pagination.

        If user_id is None, returns all sessions (admin view).
        """
        query = self.db.query(SessionModel)

        # Filter by user if specified (None means admin viewing all)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)

        if status:
            query = query.filter_by(status=status)

        total = query.count()
        sessions = (
            query.order_by(SessionModel.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return [self._to_summary(s) for s in sessions], total

    def list_for_project(
        self,
        project_id: UUID,
        limit: int = 10,
    ) -> list[SessionSummary]:
        """List recent sessions for a project."""
        sessions = (
            self.db.query(SessionModel)
            .filter_by(project_id=project_id)
            .order_by(SessionModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_summary(s) for s in sessions]

    def get_with_chat(self, session_id: UUID) -> SessionDetail | None:
        """Get session with full chat timeline."""
        session = self.get_by_id(session_id)
        if not session:
            return None

        chat = self._build_chat_timeline(session_id)
        project = self._get_project_summary(session.project_id) if session.project_id else None

        return SessionDetail(
            # Inherited from SessionSummary
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            project_id=session.project_id,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
            # SessionDetail specific
            user_id=session.user_id,
            project=project,
            chat=chat,
        )

    def create(
        self,
        user_id: UUID | None = None,
        title: str = "New Session",
        project_id: UUID | None = None,
    ) -> SessionSummary:
        """Create a new session and return its summary."""
        session = SessionModel(
            user_id=user_id,
            title=title,
            project_id=project_id,
            status=SessionStatus.ACTIVE.value,
        )
        self.db.add(session)
        self.db.flush()
        return self._to_summary(session)

    def update_status(self, session_id: UUID, status: SessionStatus) -> None:
        """Update session status."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"status": status.value})

    def delete(self, session_id: UUID) -> None:
        """Delete session (cascades to related data)."""
        self.db.query(SessionModel).filter_by(id=session_id).delete()

    def _to_summary(self, session: SessionModel) -> SessionSummary:
        """Convert session model to summary domain object."""
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            project_id=session.project_id,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _build_chat_timeline(self, session_id: UUID) -> list[ChatItem]:
        """Build chronological chat timeline from messages and agent runs.

        Returns a unified list of ChatItem objects, each containing either:
        - A MessageSummary (user input, assistant response, system message)
        - An AgentRunSummary (pending, running, completed agent runs)

        Items are sorted by created_at for chronological display.
        """
        items = []

        # Get messages (user, system, assistant)
        messages = (
            self.db.query(Message)
            .filter_by(session_id=session_id)
            .filter(Message.role.in_(["user", "system", "assistant"]))
            .order_by(Message.created_at)
            .all()
        )

        for msg in messages:
            items.append(ChatItem(
                type=ChatItemType.MESSAGE,
                message=MessageSummary(
                    id=msg.id,
                    role=msg.role,
                    content=msg.content or "",
                    agent_id=msg.agent_id,
                    created_at=msg.created_at,
                ),
                created_at=msg.created_at,
            ))

        # Get agent runs (top-level only - parent_run_id is NULL)
        agent_runs = (
            self.db.query(AgentRun)
            .filter_by(session_id=session_id, parent_run_id=None)
            .order_by(AgentRun.started_at)
            .all()
        )

        for run in agent_runs:
            # Use started_at for running/completed runs, created_at for pending
            timestamp = run.started_at or run.created_at
            items.append(ChatItem(
                type=ChatItemType.AGENT_RUN,
                agent_run=self._to_agent_run_summary(run),
                created_at=timestamp,
            ))

        # Sort by created_at for chronological order
        items.sort(key=lambda x: x.created_at)
        return items

    def _to_agent_run_summary(self, run: AgentRun) -> AgentRunSummary:
        """Convert AgentRun model to AgentRunSummary domain model."""
        return AgentRunSummary(
            id=run.id,
            agent_id=run.agent_id,
            status=AgentRunStatus(run.status),
            planned_prompt=run.planned_prompt,
            sequence_number=run.sequence_number,
            token_usage=TokenUsage(
                prompt_tokens=run.prompt_tokens or 0,
                completion_tokens=run.completion_tokens or 0,
                total_tokens=run.total_tokens or 0,
            ),
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def _build_agent_run_detail(self, run: AgentRun) -> AgentRunDetail:
        """Build full agent run detail with LLM calls and their tool executions."""
        llm_calls = self._build_llm_calls(run.id)

        return AgentRunDetail(
            id=run.id,
            agent_id=run.agent_id,
            status=AgentRunStatus(run.status),
            planned_prompt=run.planned_prompt,
            sequence_number=run.sequence_number,
            token_usage=TokenUsage(
                prompt_tokens=run.prompt_tokens or 0,
                completion_tokens=run.completion_tokens or 0,
                total_tokens=run.total_tokens or 0,
            ),
            started_at=run.started_at,
            completed_at=run.completed_at,
            llm_calls=llm_calls,
        )

    def _build_llm_calls(self, agent_run_id: UUID) -> list[LLMCallDetail]:
        """Build LLM calls with their tool executions for an agent run."""
        llm_calls_db = (
            self.db.query(LlmCall)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(LlmCall.created_at)
            .all()
        )

        result = []
        for llm in llm_calls_db:
            # Convert raw messages to LLMMessage objects
            messages = self._parse_messages(llm.request_messages)

            # Get tool calls that were executed after this LLM call
            tool_calls = self._build_tool_calls_for_llm(llm)

            result.append(LLMCallDetail(
                id=llm.id,
                model=llm.model,
                provider=llm.provider,
                token_usage=TokenUsage(
                    prompt_tokens=llm.prompt_tokens,
                    completion_tokens=llm.completion_tokens,
                    total_tokens=llm.total_tokens,
                ),
                duration_ms=llm.duration_ms,
                messages=messages,
                response_content=llm.response_content,
                tool_calls=tool_calls,
            ))

        return result

    def _parse_messages(self, raw_messages: list | None) -> list[LLMMessage]:
        """Parse raw message dicts into LLMMessage objects."""
        if not raw_messages:
            return []

        messages = []
        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue
            messages.append(LLMMessage(
                role=msg.get("role", "unknown"),
                content=msg.get("content"),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
                name=msg.get("name"),
            ))
        return messages

    def _build_tool_calls_for_llm(self, llm: LlmCall) -> list[ToolCallDetail]:
        """Build tool call details from LLM response_tool_calls."""
        tool_calls = []

        # The LLM's response_tool_calls contains what the LLM decided
        llm_tool_calls = llm.response_tool_calls or []

        for index, tc_response in enumerate(llm_tool_calls):
            if not isinstance(tc_response, dict):
                continue

            function_info = tc_response.get("function", {})
            tool_name = function_info.get("name", "")

            # Find the matching ToolCall record in DB
            tool_call_db = (
                self.db.query(ToolCall)
                .filter_by(agent_run_id=llm.agent_run_id, tool_name=tool_name)
                .filter(ToolCall.created_at >= llm.created_at)
                .order_by(ToolCall.created_at)
                .first()
            )

            if tool_call_db:
                tool_calls.append(self._build_tool_call_detail(tool_call_db, index))

        return tool_calls

    def _build_tool_call_detail(self, tc: ToolCall, index: int) -> ToolCallDetail:
        """Build a single tool call detail."""
        # Determine tool type
        tool_type = "mcp"
        mcp_server = tc.mcp_server
        if tc.mcp_server in ["builtin", "hitl"]:
            tool_type = "builtin"
            mcp_server = None

        # Get approval if any
        approval = (
            self.db.query(Approval)
            .filter_by(tool_call_id=tc.id)
            .first()
        )

        approval_summary = None
        if approval:
            approval_summary = ApprovalSummary(
                id=approval.id,
                status=ApprovalStatus(approval.status),
                required_role=approval.required_role or "admin",
                resolved_by=approval.resolved_by,
                resolved_at=approval.resolved_at,
            )

        # Arguments are stored as JSONB directly in tool_calls.arguments
        # No separate table or relationship needed
        arguments = tc.arguments or {}

        # Check for child run (execute_agent)
        child_run = None
        if tc.tool_name == "execute_agent":
            child_run_db = (
                self.db.query(AgentRun)
                .filter_by(parent_run_id=tc.agent_run_id)
                .order_by(AgentRun.started_at)
                .first()
            )
            if child_run_db:
                child_run = self._build_agent_run_detail(child_run_db)

        return ToolCallDetail(
            id=tc.id,
            index=index,
            tool_type=tool_type,
            mcp_server=mcp_server,
            tool_name=tc.tool_name,
            arguments=arguments,
            status=ToolCallStatus(tc.status),
            result=tc.result,
            error=tc.error_message,
            approval=approval_summary,
            child_run=child_run,
        )

    def _get_project_summary(self, project_id: UUID) -> ProjectSummary | None:
        """Get project summary for a session."""
        project = self.db.query(Project).filter_by(id=project_id).first()
        if not project:
            return None
        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url,
            created_at=project.created_at,
        )
