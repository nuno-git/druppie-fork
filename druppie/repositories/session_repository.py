"""Session repository for database access."""

from uuid import UUID
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from .base import BaseRepository
from ..domain import (
    SessionSummary,
    SessionDetail,
    ChatItem,
    TokenUsage,
    AgentRunDetail,
    AgentRunStep,
    LLMCallDetail,
    ToolExecutionDetail,
    ApprovalSummary,
    QuestionDetail,
    QuestionChoice,
    ProjectSummary,
)
from ..db.models import (
    Session as SessionModel,
    AgentRun,
    Message,
    ToolCall,
    LlmCall,
    Approval,
    HitlQuestion,
    HitlQuestionChoice,
    Project,
)


class SessionRepository(BaseRepository):
    """Database access for sessions."""

    def get_by_id(self, session_id: UUID) -> SessionModel | None:
        """Get raw session model."""
        return self.db.query(SessionModel).filter_by(id=session_id).first()

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user with pagination."""
        query = self.db.query(SessionModel).filter_by(user_id=user_id)

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

    def get_with_chat(self, session_id: UUID) -> SessionDetail | None:
        """Get session with full chat timeline."""
        session = self.get_by_id(session_id)
        if not session:
            return None

        chat = self._build_chat_timeline(session_id)
        tokens_by_agent = self._get_tokens_by_agent(session_id)
        project = self._get_project_summary(session.project_id) if session.project_id else None

        return SessionDetail(
            id=session.id,
            user_id=session.user_id,
            title=session.title or "Untitled",
            status=session.status,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            tokens_by_agent=tokens_by_agent,
            project=project,
            chat=chat,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def create(
        self,
        user_id: UUID,
        title: str,
        project_id: UUID | None = None,
    ) -> SessionModel:
        """Create a new session."""
        session = SessionModel(
            user_id=user_id,
            title=title,
            project_id=project_id,
            status="active",
        )
        self.db.add(session)
        self.db.flush()
        return session

    def update_status(self, session_id: UUID, status: str) -> None:
        """Update session status."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"status": status})

    def delete(self, session_id: UUID) -> None:
        """Delete session (cascades to related data)."""
        self.db.query(SessionModel).filter_by(id=session_id).delete()

    def _to_summary(self, session: SessionModel) -> SessionSummary:
        """Convert session model to summary domain object."""
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=session.status,
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
        """Build chronological chat timeline from messages and agent runs."""
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
                type=f"{msg.role}_message",
                content=msg.content,
                agent_id=msg.agent_id,
                timestamp=msg.created_at,
            ))

        # Get agent runs (top-level only - parent_run_id is NULL)
        agent_runs = (
            self.db.query(AgentRun)
            .filter_by(session_id=session_id, parent_run_id=None)
            .order_by(AgentRun.started_at)
            .all()
        )

        for run in agent_runs:
            items.append(ChatItem(
                type="agent_run",
                agent_id=run.agent_id,
                timestamp=run.started_at,
                agent_run=self._build_agent_run_detail(run),
            ))

        # Sort by timestamp
        items.sort(key=lambda x: x.timestamp)
        return items

    def _build_agent_run_detail(self, run: AgentRun) -> AgentRunDetail:
        """Build full agent run detail with steps."""
        steps = self._build_agent_run_steps(run.id)
        child_runs = self._get_child_runs(run.id)

        return AgentRunDetail(
            id=run.id,
            agent_id=run.agent_id,
            status=run.status,
            token_usage=TokenUsage(
                prompt_tokens=run.prompt_tokens or 0,
                completion_tokens=run.completion_tokens or 0,
                total_tokens=run.total_tokens or 0,
            ),
            started_at=run.started_at,
            completed_at=run.completed_at,
            steps=steps,
            child_runs=child_runs,
        )

    def _build_agent_run_steps(self, agent_run_id: UUID) -> list[AgentRunStep]:
        """Build steps for an agent run (LLM calls, tool executions, questions)."""
        steps = []

        # Get LLM calls
        llm_calls = (
            self.db.query(LlmCall)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(LlmCall.created_at)
            .all()
        )

        for llm in llm_calls:
            # Parse tools_decided from response_tool_calls
            tools_decided = []
            if llm.response_tool_calls:
                for tc in llm.response_tool_calls:
                    if isinstance(tc, dict) and "function" in tc:
                        tools_decided.append(tc["function"].get("name", ""))

            steps.append(AgentRunStep(
                type="llm_call",
                llm_call=LLMCallDetail(
                    id=llm.id,
                    model=llm.model,
                    provider=llm.provider,
                    token_usage=TokenUsage(
                        prompt_tokens=llm.prompt_tokens,
                        completion_tokens=llm.completion_tokens,
                        total_tokens=llm.total_tokens,
                    ),
                    duration_ms=llm.duration_ms,
                    tools_decided=tools_decided,
                ),
            ))

        # Get tool calls
        tool_calls = (
            self.db.query(ToolCall)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(ToolCall.created_at)
            .all()
        )

        for tc in tool_calls:
            # Get approval for this tool call if any
            approval = (
                self.db.query(Approval)
                .filter_by(tool_call_id=tc.id)
                .first()
            )

            approval_summary = None
            if approval:
                approval_summary = ApprovalSummary(
                    id=approval.id,
                    status=approval.status,
                    required_role=approval.required_role or "admin",
                    resolved_by=approval.resolved_by,
                    resolved_at=approval.resolved_at,
                )

            # Build arguments dict from relationship
            arguments = {}
            if tc.arguments:
                arguments = {a.arg_name: a.arg_value for a in tc.arguments}

            tool_type = "mcp"
            if tc.mcp_server in ["builtin", "hitl"]:
                tool_type = "builtin"

            steps.append(AgentRunStep(
                type="tool_execution",
                tool_execution=ToolExecutionDetail(
                    id=tc.id,
                    tool=f"{tc.mcp_server}:{tc.tool_name}",
                    tool_type=tool_type,
                    arguments=arguments,
                    status=tc.status,
                    result=tc.result,
                    error=tc.error_message,
                    approval=approval_summary,
                ),
            ))

        # Get HITL questions
        questions = (
            self.db.query(HitlQuestion)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(HitlQuestion.created_at)
            .all()
        )

        for q in questions:
            choices = (
                self.db.query(HitlQuestionChoice)
                .filter_by(question_id=q.id)
                .order_by(HitlQuestionChoice.choice_index)
                .all()
            )

            steps.append(AgentRunStep(
                type="hitl_question",
                question=QuestionDetail(
                    id=q.id,
                    session_id=q.session_id,
                    agent_run_id=q.agent_run_id,
                    agent_id=q.agent_id or "",
                    question=q.question,
                    question_type=q.question_type or "text",
                    choices=[
                        QuestionChoice(
                            index=c.choice_index,
                            text=c.choice_text,
                            is_selected=c.is_selected or False,
                        )
                        for c in choices
                    ],
                    status=q.status,
                    answer=q.answer,
                    answered_at=q.answered_at,
                    created_at=q.created_at,
                ),
            ))

        # Sort steps by their timestamp
        def get_step_timestamp(step: AgentRunStep):
            if step.llm_call:
                return step.llm_call.id  # Use ID as proxy for timestamp order
            if step.tool_execution:
                return step.tool_execution.id
            if step.question:
                return step.question.created_at
            return None

        # Note: Already ordered by DB queries, but could merge and sort if needed
        return steps

    def _get_child_runs(self, parent_run_id: UUID) -> list[AgentRunDetail]:
        """Get child agent runs (from execute_agent)."""
        children = (
            self.db.query(AgentRun)
            .filter_by(parent_run_id=parent_run_id)
            .order_by(AgentRun.started_at)
            .all()
        )
        return [self._build_agent_run_detail(child) for child in children]

    def _get_tokens_by_agent(self, session_id: UUID) -> dict[str, int]:
        """Get token usage grouped by agent."""
        results = (
            self.db.query(
                AgentRun.agent_id,
                func.sum(AgentRun.total_tokens).label("total"),
            )
            .filter_by(session_id=session_id)
            .group_by(AgentRun.agent_id)
            .all()
        )
        return {r.agent_id: r.total or 0 for r in results}

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
            status=project.status,
            created_at=project.created_at,
        )
