"""Session repository for database access."""

from uuid import UUID

from collections import defaultdict

from ..db.models import (
    AgentRun,
    Approval,
    CompactionEvent,
    LlmCall,
    MessageAttachment,
    Project,
    Question,
    ToolCall,
)
from ..db.models import (
    Message as MessageModel,
)
from ..db.models import (
    Session as SessionModel,
)
from ..db.models.user import User as UserModel
from ..domain import (
    AgentRunDetail,
    AgentRunStatus,
    AgentRunSummary,
    ApprovalStatus,
    ApprovalSummary,
    CompactionEventDetail,
    Attachment,
    LLMCallDetail,
    LLMMessage,
    LLMRetryDetail,
    Message,
    NormalizationDetail,
    ProjectSummary,
    ResumeContext,
    SessionDetail,
    SessionStatus,
    SessionSummary,
    TimelineEntry,
    TimelineEntryType,
    TokenUsage,
    ToolCallDetail,
    ToolCallStatus,
)
from .base import BaseRepository


class SessionRepository(BaseRepository):
    """Database access for sessions."""

    def get_by_id(self, session_id: UUID) -> SessionModel | None:
        """Get raw session model."""
        return self.db.query(SessionModel).filter_by(id=session_id).first()

    def get_by_id_for_update(self, session_id: UUID) -> SessionModel | None:
        """Get raw session model with a row-level lock (SELECT ... FOR UPDATE).

        Use this when you need to read-then-update the session atomically,
        e.g. to prevent race conditions on status transitions. The lock is
        held until the transaction commits or rolls back.
        """
        return (
            self.db.query(SessionModel)
            .filter_by(id=session_id)
            .with_for_update()
            .first()
        )

    def list_for_user(
        self,
        user_id: UUID | None,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        extra_session_ids: list[UUID] | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user with pagination.

        If user_id is None, returns all sessions (admin view).
        If extra_session_ids is given, those sessions are also included
        (used to surface sessions where the current user is an expert).
        """
        from sqlalchemy import or_

        query = self.db.query(SessionModel)

        # Filter by user if specified (None means admin viewing all)
        if user_id is not None:
            if extra_session_ids:
                query = query.filter(
                    or_(
                        SessionModel.user_id == user_id,
                        SessionModel.id.in_(list(extra_session_ids)),
                    )
                )
            else:
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

    def get_detail(self, session_id: UUID) -> SessionDetail | None:
        """Get session with full timeline."""
        session = self.get_by_id(session_id)
        if not session:
            return None

        timeline = self._build_timeline(session_id)
        project = self._get_project_summary(session.project_id) if session.project_id else None

        return SessionDetail(
            # Inherited from SessionSummary
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            error_message=session.error_message,
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
            language=session.language,
            timeline=timeline,
        )

    # Backward compat alias
    def get_with_chat(self, session_id: UUID) -> SessionDetail | None:
        """Alias for get_detail (backward compatibility)."""
        return self.get_detail(session_id)

    def create(
        self,
        user_id: UUID | None = None,
        title: str = "New Session",
        project_id: UUID | None = None,
        intent: str | None = None,
    ) -> SessionSummary:
        """Create a new session and return its summary."""
        session = SessionModel(
            user_id=user_id,
            title=title,
            project_id=project_id,
            status=SessionStatus.ACTIVE.value,
            intent=intent,
        )
        self.db.add(session)
        self.db.flush()
        return self._to_summary(session)

    def update_status(
        self,
        session_id: UUID,
        status: SessionStatus,
        error_message: str | None = None,
    ) -> None:
        """Update session status and optional error message."""
        updates = {"status": status.value}
        if error_message is not None:
            updates["error_message"] = error_message
        self.db.query(SessionModel).filter_by(id=session_id).update(updates)

    def clear_error_message(self, session_id: UUID) -> None:
        """Clear the error message on a session."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"error_message": None})

    def update_language(self, session_id: UUID, language: str) -> None:
        """Update session's detected conversational language."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"language": language})

    def update_intent(self, session_id: UUID, intent: str) -> None:
        """Update session intent."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"intent": intent})

    def update_project(self, session_id: UUID, project_id: UUID) -> None:
        """Update session's project."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"project_id": project_id})

    def recalculate_token_totals(self, session_id: UUID) -> None:
        """Recalculate session token totals from remaining non-pending agent runs."""
        from sqlalchemy import func

        result = (
            self.db.query(
                func.coalesce(func.sum(AgentRun.prompt_tokens), 0),
                func.coalesce(func.sum(AgentRun.completion_tokens), 0),
                func.coalesce(func.sum(AgentRun.total_tokens), 0),
            )
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status != AgentRunStatus.PENDING.value,
            )
            .first()
        )

        session = self.get_by_id(session_id)
        if session:
            session.prompt_tokens = result[0]
            session.completion_tokens = result[1]
            session.total_tokens = result[2]

    def delete(self, session_id: UUID) -> None:
        """Delete session (cascades to related data)."""
        self.db.query(SessionModel).filter_by(id=session_id).delete()

    def delete_many(self, session_ids: list[UUID]) -> int:
        """Delete sessions by IDs. Returns count deleted."""
        if not session_ids:
            return 0
        count = self.db.query(SessionModel).filter(SessionModel.id.in_(session_ids)).delete(synchronize_session="fetch")
        return count

    def delete_all_for_user(self, user_id: UUID | None) -> list[UUID]:
        """Delete all sessions for a user (None = all sessions). Returns deleted session IDs."""
        query = self.db.query(SessionModel.id)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        sessions = query.all()
        ids = [s.id for s in sessions]
        if ids:
            self.db.query(SessionModel).filter(SessionModel.id.in_(ids)).delete(synchronize_session="fetch")
        return ids

    def _to_summary(self, session: SessionModel) -> SessionSummary:
        """Convert session model to summary domain object."""
        # Look up username from users table
        username = None
        if session.user_id:
            user = self.db.query(UserModel).filter_by(id=session.user_id).first()
            if user:
                username = user.username
        project_name = None
        if session.project_id:
            project = self.db.query(Project).filter_by(id=session.project_id).first()
            if project:
                project_name = project.name
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            error_message=session.error_message,
            project_id=session.project_id,
            username=username,
            project_name=project_name,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _build_timeline(self, session_id: UUID) -> list[TimelineEntry]:
        """Build chronological timeline from messages and agent runs.

        Returns a unified list of TimelineEntry objects, each containing either:
        - A Message (user input, assistant response, system message)
        - An AgentRunSummary (pending, running, completed agent runs)

        Items are sorted by timestamp for chronological display.
        """
        entries = []

        # Get messages (user, system, assistant)
        messages = (
            self.db.query(MessageModel)
            .filter_by(session_id=session_id)
            .filter(MessageModel.role.in_(["user", "system", "assistant", "tool"]))
            .order_by(MessageModel.created_at)
            .all()
        )

        # Batch-load attachments for all messages
        message_ids = [msg.id for msg in messages]
        all_attachments = (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.message_id.in_(message_ids))
            .all()
        ) if message_ids else []
        attachments_by_msg = defaultdict(list)
        for att in all_attachments:
            attachments_by_msg[att.message_id].append(
                Attachment(
                    id=att.id,
                    original_filename=att.original_filename,
                    content_type=att.content_type,
                    file_size=att.file_size,
                    created_at=att.created_at,
                )
            )

        for msg in messages:
            entries.append(TimelineEntry(
                type=TimelineEntryType.MESSAGE,
                timestamp=msg.created_at,
                message=Message(
                    id=msg.id,
                    role=msg.role,
                    content=msg.content or "",
                    agent_id=msg.agent_id,
                    agent_run_id=msg.agent_run_id,
                    sequence_number=msg.sequence_number,
                    created_at=msg.created_at,
                    attachments=attachments_by_msg.get(msg.id, []),
                ),
            ))

        # Get agent runs (top-level only - parent_run_id is NULL)
        agent_runs = (
            self.db.query(AgentRun)
            .filter_by(session_id=session_id, parent_run_id=None)
            .order_by(AgentRun.sequence_number)
            .all()
        )

        for run in agent_runs:
            entries.append(TimelineEntry(
                type=TimelineEntryType.AGENT_RUN,
                timestamp=run.started_at or run.created_at,
                agent_run=self._build_agent_run_detail(run),
            ))

        # Sort by sequence_number (both messages and agent runs have one),
        # then by type (messages before agent runs at the same sequence),
        # then by timestamp as final tiebreaker.
        def _sort_key(entry):
            if entry.agent_run and entry.agent_run.sequence_number is not None:
                seq = entry.agent_run.sequence_number
            elif entry.message:
                seq = entry.message.sequence_number
            else:
                seq = -1
            # At the same sequence, messages sort before agent runs (0 < 1)
            type_order = 0 if entry.message else 1
            return (seq, type_order, entry.timestamp)

        entries.sort(key=_sort_key)
        return entries

    def _to_agent_run_summary(self, run: AgentRun) -> AgentRunSummary:
        """Convert AgentRun model to AgentRunSummary domain model."""
        return AgentRunSummary(
            id=run.id,
            session_id=run.session_id,
            agent_id=run.agent_id,
            status=AgentRunStatus(run.status),
            error_message=run.error_message,
            planned_prompt=run.planned_prompt,
            sequence_number=run.sequence_number,
            spawning_tool_call_id=run.spawning_tool_call_id,
            token_usage=TokenUsage(
                prompt_tokens=run.prompt_tokens or 0,
                completion_tokens=run.completion_tokens or 0,
                total_tokens=run.total_tokens or 0,
            ),
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def _build_agent_run_detail(self, run: AgentRun, _depth: int = 0) -> AgentRunDetail:
        """Build full agent run detail with LLM calls, tool executions, and nested subagent runs."""
        llm_calls = self._build_llm_calls(run.id)
        compaction_events = self._build_compaction_events(run.id)
        resume_contexts = self._build_resume_contexts(run.id)

        subagent_runs: list[AgentRunDetail] = []
        if _depth < 10:
            child_runs = (
                self.db.query(AgentRun)
                .filter_by(parent_run_id=run.id)
                .order_by(AgentRun.sequence_number, AgentRun.created_at)
                .all()
            )
            subagent_runs = [
                self._build_agent_run_detail(child, _depth=_depth + 1)
                for child in child_runs
            ]

        return AgentRunDetail(
            id=run.id,
            session_id=run.session_id,
            agent_id=run.agent_id,
            status=AgentRunStatus(run.status),
            error_message=run.error_message,
            planned_prompt=run.planned_prompt,
            sequence_number=run.sequence_number,
            spawning_tool_call_id=run.spawning_tool_call_id,
            token_usage=TokenUsage(
                prompt_tokens=run.prompt_tokens or 0,
                completion_tokens=run.completion_tokens or 0,
                total_tokens=run.total_tokens or 0,
            ),
            started_at=run.started_at,
            completed_at=run.completed_at,
            llm_calls=llm_calls,
            subagent_runs=subagent_runs,
            compaction_events=compaction_events,
            resume_contexts=resume_contexts,
        )

    def _build_compaction_events(self, agent_run_id: UUID) -> list[CompactionEventDetail]:
        """Build compaction event details for an agent run."""
        events_db = (
            self.db.query(CompactionEvent)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(CompactionEvent.created_at)
            .all()
        )
        return [
            CompactionEventDetail(
                id=ce.id,
                agent_run_id=ce.agent_run_id,
                llm_call_id=ce.llm_call_id,
                phase=ce.phase,
                tokens_before=ce.tokens_before or 0,
                tokens_after=ce.tokens_after or 0,
                turns_compressed=ce.turns_compressed or 0,
                summary_text=ce.summary_text,
                created_at=ce.created_at,
            )
            for ce in events_db
        ]

    def _build_resume_contexts(self, agent_run_id: UUID) -> list[ResumeContext]:
        """Build resume context entries for an agent run from the events table."""
        from ..db.models.resume_context_event import ResumeContextEvent

        events_db = (
            self.db.query(ResumeContextEvent)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(ResumeContextEvent.created_at)
            .all()
        )
        return [
            ResumeContext(
                content=e.content,
                created_at=e.created_at,
                llm_call_index=e.llm_call_index,
            )
            for e in events_db
        ]

    def _build_llm_calls(self, agent_run_id: UUID) -> list[LLMCallDetail]:
        """Build LLM calls with their tool executions for an agent run."""
        import json

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

            response_content = self._extract_response_content(llm.response_content)

            response_tool_calls = llm.response_tool_calls
            if not response_tool_calls and llm.response_content:
                try:
                    raw_data = json.loads(llm.response_content)
                    response_tool_calls = raw_data.get("tool_calls")
                except json.JSONDecodeError:
                    pass

            result.append(LLMCallDetail(
                id=llm.id,
                model=llm.model,
                provider=llm.provider,
                token_usage=TokenUsage(
                    prompt_tokens=llm.prompt_tokens or 0,
                    completion_tokens=llm.completion_tokens or 0,
                    total_tokens=llm.total_tokens or 0,
                ),
                duration_ms=llm.duration_ms,
                messages=messages,
                tools_provided=llm.tools_provided,
                response_content=response_content,
                thinking_content=llm.thinking_content,
                response_tool_calls=response_tool_calls,
                fallback_used=getattr(llm, 'fallback_used', False) or False,
                intended_provider=getattr(llm, 'intended_provider', None),
                intended_model=getattr(llm, 'intended_model', None),
                raw_request=llm.raw_request if llm.raw_request else None,
                raw_response=llm.raw_response if llm.raw_response else None,
                retries=[
                    LLMRetryDetail(
                        attempt=r.attempt,
                        error_type=r.error_type,
                        error_message=r.error_message,
                        delay_seconds=r.delay_seconds,
                    )
                    for r in llm.retries
                ],
                tool_calls=tool_calls,
            ))

        return result

    @staticmethod
    def _extract_response_content(raw: str | None) -> str | None:
        """Extract the LLM text content from the response_content column.

        The column may contain:
        - A JSON blob: {"content": "...", "tool_calls": [...], ...}
        - Plain text (legacy format)
        - An error JSON: {"error": "..."}
        - None

        Returns the actual LLM response text, or None.
        """
        if not raw:
            return None
        import json
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data.get("content") or None
            return raw
        except json.JSONDecodeError:
            return raw

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
        """Build tool call details for an LLM call.

        Uses llm_call_id foreign key for direct lookup instead of
        timestamp-based matching.
        """
        # Query tool calls directly by llm_call_id, ordered by tool_call_index
        tool_calls_db = (
            self.db.query(ToolCall)
            .filter_by(llm_call_id=llm.id)
            .order_by(ToolCall.tool_call_index)
            .all()
        )

        return [
            self._build_tool_call_detail(tc, tc.tool_call_index or idx)
            for idx, tc in enumerate(tool_calls_db)
        ]

    def _build_tool_call_detail(self, tc: ToolCall, index: int) -> ToolCallDetail:
        """Build a single tool call detail.

        Uses ToolRegistry to get tool description. Parameter schema is not
        included here - it's part of the ToolDefinition and can be looked
        up via the registry using full_name if needed.
        """
        from druppie.core.tool_registry import get_tool_registry
        from druppie.domain.tool import ToolType

        # Determine tool type
        tool_type = ToolType.MCP
        mcp_server = tc.mcp_server
        if tc.mcp_server in ["builtin", "hitl"]:
            tool_type = ToolType.BUILTIN
            mcp_server = None

        # Get tool definition from registry for description
        registry = get_tool_registry()
        tool_def = registry.get_by_server_and_name(tc.mcp_server, tc.tool_name)
        description = tool_def.description if tool_def else ""

        # Build full name (for registry lookup)
        if mcp_server:
            full_name = f"{mcp_server}_{tc.tool_name}"
        else:
            full_name = tc.tool_name

        # Get approval if any
        approval = (
            self.db.query(Approval)
            .filter_by(tool_call_id=tc.id)
            .first()
        )

        approval_summary = None
        if approval:
            approval_attachments = []
            if approval.status == "rejected":
                att_rows = (
                    self.db.query(MessageAttachment)
                    .filter_by(approval_id=approval.id)
                    .order_by(MessageAttachment.created_at)
                    .all()
                )
                approval_attachments = [
                    Attachment(
                        id=a.id,
                        original_filename=a.original_filename,
                        content_type=a.content_type,
                        file_size=a.file_size,
                        created_at=a.created_at,
                    )
                    for a in att_rows
                ]
            approval_summary = ApprovalSummary(
                id=approval.id,
                status=ApprovalStatus(approval.status),
                required_role=approval.required_role or "admin",
                resolved_by=approval.resolved_by,
                resolved_at=approval.resolved_at,
                rejection_reason=approval.rejection_reason,
                attachments=approval_attachments,
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

        question_id = None
        question_attachments = []
        if tc.tool_name in (
            "hitl_ask_question",
            "hitl_ask_multiple_choice_question",
            "ask_expert_question",
            "ask_expert_multiple_choice_question",
        ):
            question = (
                self.db.query(Question)
                .filter_by(tool_call_id=tc.id)
                .first()
            )
            if question:
                question_id = question.id
                att_rows = (
                    self.db.query(MessageAttachment)
                    .filter_by(question_id=question.id)
                    .order_by(MessageAttachment.created_at)
                    .all()
                )
                question_attachments = [
                    Attachment(
                        id=a.id,
                        original_filename=a.original_filename,
                        content_type=a.content_type,
                        file_size=a.file_size,
                        created_at=a.created_at,
                    )
                    for a in att_rows
                ]
                arguments = dict(arguments)
                if question.question:
                    arguments["question"] = question.question
                if question.choices:
                    arguments["choices"] = [
                        c["text"] if isinstance(c, dict) else c
                        for c in question.choices
                    ]
                if question.question_english:
                    arguments["question_english"] = question.question_english
                if question.choices_english:
                    arguments["choices_english"] = [
                        c["text"] if isinstance(c, dict) else c
                        for c in question.choices_english
                    ]

        return ToolCallDetail(
            id=tc.id,
            index=index,
            tool_type=tool_type,
            mcp_server=mcp_server,
            tool_name=tc.tool_name,
            full_name=full_name,
            description=description,
            arguments=arguments,
            status=ToolCallStatus(tc.status),
            result=tc.result,
            error=tc.error_message,
            normalizations=[
                NormalizationDetail(
                    field_name=n.field_name,
                    original_value=n.original_value,
                    normalized_value=n.normalized_value,
                )
                for n in tc.normalizations
            ],
            approval=approval_summary,
            question_id=question_id,
            attachments=question_attachments,
            child_run=child_run,
        )

    def _get_project_summary(self, project_id: UUID) -> ProjectSummary | None:
        """Get project summary for a session."""
        project = self.db.query(Project).filter_by(id=project_id).first()
        if not project:
            return None

        # Look up username from users table
        username = None
        if project.owner_id:
            user = self.db.query(UserModel).filter_by(id=project.owner_id).first()
            if user:
                username = user.username

        # Resolve repo_url dynamically from repo_name + repo_owner
        repo_url = None
        if project.repo_name:
            from druppie.core.gitea import get_gitea_client
            try:
                repo_url = get_gitea_client().get_public_url(project.repo_name, project.repo_owner)
            except Exception:
                repo_url = project.repo_url  # Fallback to stored value

        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_name=project.repo_name,
            repo_owner=project.repo_owner,
            repo_url=repo_url,
            username=username,
            created_at=project.created_at,
        )
