"""Orchestrator - coordinates agent runs and tool execution.

The orchestrator is the main entry point for processing user messages.
It is intentionally "dumb" - just creates agent runs and executes them.
All smart logic (intent handling, project creation, planner prompt updates)
is delegated to built-in tools.

Flow:
1. Create session
2. Save user message to timeline
3. Create router (seq 0) + planner (seq 1) as PENDING
4. Execute all pending runs:
   - Router runs → calls set_intent() which:
     - Sets session.intent
     - Creates project + Gitea repo if needed
     - Updates planner's prompt with intent context
   - Planner runs (now with updated prompt) → calls make_plan()
   - Remaining agents execute

Architecture:
    User Message
         │
         ▼
    Orchestrator.process_message()
         │
         ├─► Create Session
         │
         ├─► Save User Message (to timeline)
         │
         ├─► Create Router + Planner (both PENDING)
         │
         └─► execute_pending_runs()
                 │
                 ├─► Router → set_intent() updates planner prompt
                 │
                 ├─► Planner → make_plan() creates agent runs
                 │
                 └─► Architect → Developer → Deployer
"""

import asyncio
import os
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import structlog

from druppie.agents.prompt_builder import DEFAULT_LANGUAGE
from druppie.core.language_detection import LanguageDetector
from druppie.domain.common import AgentRunStatus, SessionStatus, ApprovalStatus
from druppie.execution.human_input import HumanInput

if TYPE_CHECKING:
    from druppie.repositories import SessionRepository, ExecutionRepository, ProjectRepository, QuestionRepository, JobRepository, AttachmentRepository

logger = structlog.get_logger()

_CODING_MCP_URL = os.getenv("MCP_CODING_URL", "http://module-coding:9001")


async def _cleanup_sandbox(session_id: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{_CODING_MCP_URL}/management/sandbox/cleanup/{session_id}",
                timeout=10,
            )
    except Exception as e:
        logger.warning("sandbox_cleanup_failed", session_id=session_id, error=str(e))


class Orchestrator:
    """Main entry point for processing messages.

    Uses repositories for all database operations.
    """

    def __init__(
        self,
        session_repo: "SessionRepository",
        execution_repo: "ExecutionRepository",
        project_repo: "ProjectRepository",
        question_repo: "QuestionRepository",
        job_repo: "JobRepository | None" = None,
        attachment_repo: "AttachmentRepository | None" = None,
    ):
        """Initialize orchestrator with repositories.

        Args:
            session_repo: Repository for session operations
            execution_repo: Repository for agent runs, tool calls
            project_repo: Repository for project operations
            question_repo: Repository for question operations
            job_repo: Repository for job runs (optional, required for approval-gated jobs)
            attachment_repo: Repository for message attachments (optional)
        """
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.project_repo = project_repo
        self.question_repo = question_repo
        self.job_repo = job_repo
        self.attachment_repo = attachment_repo
        self.language_detector = LanguageDetector()
        # Updated on each user input (process_message / resume_after_answer).
        # Safe as instance state because Orchestrator is created per-request.
        self._last_language_info = None

    async def process_message(
        self,
        message: str,
        user_id: UUID,
        session_id: UUID | None = None,
        project_id: UUID | None = None,
        attachment_ids: list[UUID] | None = None,
    ) -> UUID:
        """Process a user message.

        The orchestrator is intentionally simple - it just creates agent runs
        and executes them. All smart logic is in built-in tools:
        - set_intent: handles project creation, session updates, planner prompt
        - make_plan: creates the execution plan

        For continuation (session_id provided with completed session):
        - Resets session to ACTIVE
        - Queries conversation history from Messages table
        - Builds prompts that include the full conversation context

        Flow:
        1. Create or get session
        2. Save user message to timeline
        3. Build conversation history (if continuing)
        4. Create router + planner (both PENDING)
        5. Execute all pending runs

        Args:
            message: User's message
            user_id: User ID (required for project lookup)
            session_id: Existing session ID (optional)
            project_id: Project ID if already known (optional)

        Returns:
            session_id
        """
        # Step 1: Get or create session
        is_continuation = False
        if session_id:
            existing = self.session_repo.get_by_id(session_id)
            if not existing:
                raise ValueError(f"Session {session_id} not found")
            current_session_id = session_id
            is_continuation = True
            # Reset session status to ACTIVE for the new round
            self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
            self.session_repo.commit()
        else:
            session = self.session_repo.create(
                user_id=user_id,
                project_id=project_id,
                title=message[:100] if message else "New Session",
            )
            self.session_repo.commit()
            current_session_id = session.id

        logger.info(
            "process_message_start",
            session_id=str(current_session_id),
            message_preview=message[:50] if message else "",
            is_continuation=is_continuation,
        )

        # Step 2: Build conversation history BEFORE saving new message
        conversation_history = ""
        if is_continuation:
            conversation_history = self._build_conversation_history(current_session_id)

        # Step 3: Get next sequence number (session-level counter)
        # This ensures follow-up messages don't collide with existing runs
        next_seq = self.execution_repo.get_next_sequence_number(current_session_id)

        # Step 3.5: Detect and update language (only if detection succeeds)
        human_input = HumanInput(message, self.language_detector)
        self._last_language_info = human_input.language_info()
        if human_input.detected_language:  # None means text too short - preserve existing language
            # Only nl and en are conversational languages; others map to en for session
            session_language = (
                human_input.detected_language
                if human_input.detected_language in ("nl", "en")
                else "en"
            )
            self.session_repo.update_language(current_session_id, session_language)
            logger.info(
                "language_detected",
                session_id=str(current_session_id),
                detected_language=human_input.detected_language,
                session_language=session_language,
            )
            self.session_repo.commit()
        # If None, keep existing session language unchanged

        # Step 3.6: Translate to English if non-English (agents work in English)
        translated_message = message
        if human_input.detected_language and human_input.detected_language != "en":
            try:
                from druppie.core.translation import get_translation_service, TranslationNotAvailableError
                translator = get_translation_service()
                translated_message = await translator.translate_to_english(
                    message, human_input.detected_language
                )
                if translated_message != message:
                    logger.info(
                        "message_translated",
                        session_id=str(current_session_id),
                        source_language=human_input.detected_language,
                        original_preview=message[:80],
                        translated_preview=translated_message[:80],
                    )
            except TranslationNotAvailableError:
                logger.warning("translation_skipped_no_api_key", session_id=str(current_session_id))

        # Step 3b: Save user message to the timeline (after translation so we can store both versions)
        message_id = self.execution_repo.create_message(
            session_id=current_session_id,
            role="user",
            content=message,
            content_english=translated_message if translated_message != message else None,
            sequence_number=next_seq,
        )
        next_seq += 1

        # Step 3c: Link uploaded attachments to the user message
        attachment_context = ""
        if attachment_ids and self.attachment_repo:
            self.attachment_repo.link_to_message(
                attachment_ids, message_id, current_session_id,
            )
            attachments = self.attachment_repo.get_by_ids(attachment_ids)
            attachment_context = self._build_attachment_context(attachments)

        self.execution_repo.commit()

        # Step 4: Get user's projects for router injection
        user_projects = self.project_repo.get_by_user(user_id)
        projects_context = self._format_projects_for_router(user_projects)

        # Step 5: Create router + planner (both PENDING)
        # Router will call set_intent() which updates planner's prompt
        if conversation_history:
            router_prompt = f"{projects_context}\n\n{conversation_history}\n\nNEW USER MESSAGE:\n{translated_message}{attachment_context}"
        else:
            router_prompt = f"{projects_context}\n\nUSER REQUEST:\n{translated_message}{attachment_context}"
        self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="router",
            status=AgentRunStatus.PENDING,
            planned_prompt=router_prompt,
            sequence_number=next_seq,
        )

        # Planner starts with basic prompt - set_intent will update it with context
        if conversation_history:
            planner_prompt = f"{conversation_history}\n\nNEW USER MESSAGE:\n{translated_message}{attachment_context}"
        else:
            planner_prompt = f"USER REQUEST:\n{translated_message}{attachment_context}"
        self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="planner",
            status=AgentRunStatus.PENDING,
            planned_prompt=planner_prompt,
            sequence_number=next_seq + 1,
        )
        self.execution_repo.commit()

        # Step 6: Execute all pending runs
        # Router runs first, calls set_intent() which updates planner prompt
        # Then planner runs with updated prompt
        await self.execute_pending_runs(current_session_id)

        return current_session_id

    @staticmethod
    def _build_attachment_context(attachments) -> str:
        """Build a file listing for LLM prompts (agents use read_attachment tool for content)."""
        if not attachments:
            return ""
        lines = ["\n\nUPLOADED FILES (use the read_attachment tool to read file contents):"]
        for att in attachments:
            size_kb = att.file_size / 1024
            lines.append(
                f"- {att.original_filename} (id: {att.id}, type: {att.content_type}, "
                f"size: {size_kb:.1f} KB)"
            )
        return "\n".join(lines)

    def _format_projects_for_router(self, projects: list) -> str:
        """Format user's projects for injection into router prompt."""
        if not projects:
            return "YOUR PROJECTS:\n(No projects yet)"

        lines = ["YOUR PROJECTS:"]
        for p in projects:
            # Handle both domain objects and raw models
            project_id = str(p.id) if hasattr(p, 'id') else str(p.get('id', ''))
            project_name = p.name if hasattr(p, 'name') else p.get('name', 'unnamed')
            lines.append(f"- {project_name} (id: {project_id})")

        return "\n".join(lines)

    def _build_conversation_history(self, session_id: UUID) -> str:
        """Build conversation history from previous rounds.

        Queries all user and assistant (summarizer) messages from the session,
        ordered by created_at. These form the natural conversation:
        user → assistant → user → assistant → ...

        Args:
            session_id: Session UUID

        Returns:
            Formatted conversation history string, or empty string if no history.
        """
        from druppie.db.models import Message

        messages = (
            self.execution_repo.db.query(Message)
            .filter(
                Message.session_id == session_id,
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at)
            .all()
        )

        if not messages:
            return ""

        lines = ["CONVERSATION HISTORY:"]
        for msg in messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            text = msg.content_english or msg.content
            lines.append(f"{role_label}: {text}")

        logger.info(
            "conversation_history_built",
            session_id=str(session_id),
            message_count=len(messages),
        )

        return "\n".join(lines)

    async def execute_pending_runs(self, session_id: UUID) -> None:
        """Execute all pending agent runs in sequence.

        Runs pending agents ordered by sequence_number.
        Stops if an agent pauses (waiting for approval/answer/user stop).

        Context is rebuilt before each agent so it picks up changes
        from previous agents (e.g., router creates project + repo,
        deployer needs repo_name in context).
        """
        logger.info("execute_pending_runs_start", session_id=str(session_id))

        while True:
            # Check for user-initiated pause (cooperative — Stop button sets PAUSED)
            self.session_repo.db.expire_all()
            session = self.session_repo.get_by_id(session_id)
            if session and session.status == SessionStatus.PAUSED.value:
                # Pending runs stay PENDING — they'll resume later
                logger.info("execution_paused_by_user", session_id=str(session_id))
                return

            # Get next pending run
            next_run = self.execution_repo.get_next_pending(session_id)

            if not next_run:
                logger.info("execute_pending_runs_complete", session_id=str(session_id))
                self.session_repo.update_status(session_id, SessionStatus.COMPLETED)
                self.session_repo.commit()
                await _cleanup_sandbox(str(session_id))
                return

            # Rebuild context before each agent so it reflects changes
            # from previous agents (e.g., set_intent creates project/repo)
            context = self.build_project_context(session_id)

            # Planner needs the accumulated summary from all completed agents
            # so it knows what has been done. Build it fresh from the DB.
            prompt = next_run.planned_prompt or ""
            if next_run.agent_id == "planner":
                prompt = self._prepend_agent_summary(session_id, prompt)

            logger.info(
                "executing_agent_run",
                session_id=str(session_id),
                agent_run_id=str(next_run.id),
                agent_id=next_run.agent_id,
                sequence_number=next_run.sequence_number,
            )

            # Mark as running
            self.execution_repo.update_status(next_run.id, AgentRunStatus.RUNNING)
            self.execution_repo.commit()

            try:
                status = await self.run_agent(
                    session_id=session_id,
                    agent_run_id=next_run.id,
                    agent_id=next_run.agent_id,
                    prompt=prompt,
                    context=context,
                )
            except asyncio.CancelledError:
                self.execution_repo.db.rollback()
                self.execution_repo.update_status(next_run.id, AgentRunStatus.PAUSED_USER)
                self.execution_repo.commit()
                self.session_repo.update_status(session_id, SessionStatus.PAUSED)
                self.session_repo.commit()
                logger.info("execute_pending_runs_cancelled", session_id=str(session_id), agent_run_id=str(next_run.id))
                raise

            # If paused, update session status and stop execution
            if status == "paused":
                # Determine pause type from agent_run status
                refreshed_run = self.execution_repo.get_by_id(next_run.id)
                if refreshed_run and refreshed_run.status == AgentRunStatus.PAUSED_HITL:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                elif refreshed_run and refreshed_run.status == AgentRunStatus.PAUSED_SANDBOX:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                elif refreshed_run and refreshed_run.status == AgentRunStatus.PAUSED_USER:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED)
                else:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                self.session_repo.commit()
                logger.info(
                    "execute_pending_runs_paused",
                    session_id=str(session_id),
                    agent_run_id=str(next_run.id),
                )
                return

            # Otherwise "completed" — loop continues to next pending run

    def _prepend_agent_summary(self, session_id: UUID, prompt: str) -> str:
        """Build accumulated summary from completed runs and prepend to prompt.

        Reads all done() summaries from completed agent runs, deduplicates
        lines, and prepends the result as PREVIOUS AGENT SUMMARY.
        """
        completed_runs = self.execution_repo.get_completed_runs(session_id)
        seen = []
        seen_set = set()
        for run in completed_runs:
            run_summary = self.execution_repo.get_done_summary_for_run(run.id)
            if not run_summary:
                continue
            for line in run_summary.strip().split("\n"):
                stripped = line.strip()
                if stripped and stripped not in seen_set:
                    seen_set.add(stripped)
                    seen.append(stripped)

        if not seen:
            return prompt

        accumulated = "\n".join(seen)
        logger.info(
            "planner_summary_prepended",
            session_id=str(session_id),
            summary_lines=len(seen),
            preview=accumulated[:200],
        )
        return f"PREVIOUS AGENT SUMMARY:\n{accumulated}\n\n---\n\n{prompt}"

    def build_project_context(self, session_id: UUID) -> dict | None:
        """Build project context for agents.

        Retrieves project info (repo_name, repo_owner, etc.) from the session
        and returns it as a context dict that will be injected into agent prompts.

        Called before each agent run to pick up changes from previous agents
        (e.g., router creates project + Gitea repo with repo_name).

        Args:
            session_id: Session UUID

        Returns:
            Context dict with project info and always conversational_language,
            or None if session not found
        """
        from druppie.db.models import Project
        from druppie.db.models import Session as DBSession

        # Expire cached objects to ensure we read fresh data from DB.
        # Previous agents (e.g., router's set_intent) may have modified
        # the project record (adding repo_name) since we last queried.
        self.session_repo.db.expire_all()

        session = self.session_repo.db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session:
            return None

        # Always include conversational_language, even without a project
        context = {
            "session_id": str(session_id),
            "conversational_language": session.language or DEFAULT_LANGUAGE,
            "language_info": self._last_language_info,
        }

        # Add intent so agents know what workflow to follow
        if session.intent:
            context["intent"] = session.intent

        # If there's a project, add project-specific context
        if session.project_id:
            project = self.session_repo.db.query(Project).filter(Project.id == session.project_id).first()
            if project:
                context["project_id"] = str(project.id)
                context["project_name"] = project.name
                # Add git repo info if available
                if project.repo_name:
                    context["repo_name"] = project.repo_name
                if project.repo_url:
                    context["repo_url"] = project.repo_url
                if hasattr(project, 'repo_owner') and project.repo_owner:
                    context["repo_owner"] = project.repo_owner

                logger.debug(
                    "project_context_built",
                    session_id=str(session_id),
                    project_id=str(project.id),
                    has_repo=bool(project.repo_name),
                )

        # Include session-level attachment context so ALL agents see uploaded files
        if self.attachment_repo:
            attachments = self.attachment_repo.get_for_session(session_id)
            att_ctx = self._build_attachment_context(attachments)
            if att_ctx:
                context["attachment_context"] = att_ctx

        logger.debug(
            "context_built",
            session_id=str(session_id),
            has_project=bool(session.project_id),
            conversational_language=context.get("conversational_language"),
        )

        return context

    async def run_agent(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
        prompt: str,
        context: dict = None,
    ) -> str:
        """Run a single agent.

        Args:
            session_id: Session UUID
            agent_run_id: Agent run UUID
            agent_id: Agent identifier
            prompt: Task prompt
            context: Optional context dict (e.g., with clarifications from HITL)

        Returns:
            "completed" or "paused"

        Raises:
            Exception: Re-raises after storing error on agent_run record
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent

        logger.info(
            "agent_run_start",
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
            agent_id=agent_id,
            has_context=bool(context),
        )

        self.execution_repo.update_status(agent_run_id, AgentRunStatus.RUNNING)
        self.execution_repo.commit()

        # Create and run agent
        agent = Agent(agent_id, db=self.execution_repo.db, session_id=str(session_id))
        try:
            result = await agent.run(
                prompt=prompt,
                session_id=session_id,
                agent_run_id=agent_run_id,
                context=context,
            )
        except asyncio.CancelledError:
            self.execution_repo.db.rollback()
            self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_USER)
            self.execution_repo.commit()
            logger.info("agent_run_cancelled", session_id=str(session_id), agent_run_id=str(agent_run_id), agent_id=agent_id)
            raise
        except Exception as e:
            # Store error on agent_run before re-raising.
            # Rollback first — if the failure was a DB error, the transaction
            # is in an ABORTED state and no further SQL will work until ROLLBACK.
            error_msg = f"{type(e).__name__}: {e}"
            try:
                self.execution_repo.db.rollback()
                self.execution_repo.update_status(
                    agent_run_id,
                    AgentRunStatus.FAILED,
                    error_message=error_msg[:2000],
                )
                self.execution_repo.commit()
            except Exception as status_err:
                logger.error(
                    "failed_to_record_agent_run_error",
                    session_id=str(session_id),
                    agent_run_id=str(agent_run_id),
                    status_error=str(status_err),
                )
            logger.error(
                "agent_run_failed",
                session_id=str(session_id),
                agent_run_id=str(agent_run_id),
                agent_id=agent_id,
                error=error_msg[:500],
            )
            await _cleanup_sandbox(str(session_id))
            raise

        # Check if paused
        if result.get("status") == "paused" or result.get("paused"):
            pause_reason = result.get("reason", "unknown")
            if pause_reason == "waiting_answer":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_HITL)
            elif pause_reason == "waiting_sandbox":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_SANDBOX)
            elif pause_reason == "user_paused":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_USER)
            else:
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_TOOL)
            self.execution_repo.commit()
            return "paused"

        # Completed
        self.execution_repo.update_status(agent_run_id, AgentRunStatus.COMPLETED)
        self.execution_repo.commit()

        logger.info(
            "agent_run_completed",
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
            agent_id=agent_id,
        )

        self._on_agent_completed(session_id, agent_run_id, agent_id)

        return "completed"

    def _all_siblings_completed(self, parent_run_id: UUID, spawning_tool_call_id: UUID) -> bool:
        """Check if ALL sibling subagents from the same tool call have finished.

        Returns True only if every sibling has a terminal status
        (completed, failed, or cancelled). Returns False if any sibling
        is still in a non-terminal state (running, paused_hitl, etc.).
        """
        from druppie.db.models.agent_run import AgentRun

        db = self.execution_repo.db
        terminal_statuses = {
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }

        siblings = (
            db.query(AgentRun)
            .filter(
                AgentRun.parent_run_id == parent_run_id,
                AgentRun.spawning_tool_call_id == spawning_tool_call_id,
            )
            .all()
        )

        for sibling in siblings:
            if sibling.status not in terminal_statuses:
                logger.info(
                    "sibling_not_yet_completed",
                    sibling_id=str(sibling.id),
                    sibling_agent_id=sibling.agent_id,
                    sibling_status=sibling.status,
                    parent_run_id=str(parent_run_id),
                    spawning_tool_call_id=str(spawning_tool_call_id),
                )
                return False

        logger.info(
            "all_siblings_completed",
            parent_run_id=str(parent_run_id),
            spawning_tool_call_id=str(spawning_tool_call_id),
            sibling_count=len(siblings),
        )
        return True

    def _patch_paused_subagents_tool_call(self, parent_run_id: UUID, session_id: UUID) -> None:
        import json as _json

        from druppie.db.models.agent_run import AgentRun
        from druppie.db.models.tool_call import ToolCall as ToolCallModel

        db = self.execution_repo.db
        paused_tc = (
            db.query(ToolCallModel)
            .filter(
                ToolCallModel.agent_run_id == parent_run_id,
                ToolCallModel.tool_name == "subagents",
                ToolCallModel.status.in_(["pending", "paused", "completed", "executing"]),
            )
            .order_by(ToolCallModel.created_at.desc())
            .first()
        )
        if not paused_tc:
            return

        children = (
            db.query(AgentRun)
            .filter(
                AgentRun.parent_run_id == parent_run_id,
                AgentRun.spawning_tool_call_id == paused_tc.id,
            )
            .all()
        )

        subagent_results = []
        for child in children:
            entry = {"agent": child.agent_id, "status": "success" if child.status == AgentRunStatus.COMPLETED.value else "error"}
            if child.error_message:
                entry["error"] = child.error_message
            subagent_results.append(entry)

        new_result = {"success": True, "data": subagent_results}
        paused_tc.result = _json.dumps(new_result)
        paused_tc.status = "completed"
        db.commit()

    def _on_agent_completed(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
    ) -> None:
        """Fire-and-forget live evaluation if configured."""
        try:
            from druppie.testing.eval_config import get_evaluation_config

            config = get_evaluation_config()
            if not config.should_evaluate(agent_id):
                return

            from druppie.core.background_tasks import create_tracked_task
            from druppie.testing.eval_live import run_live_evaluation

            create_tracked_task(
                run_live_evaluation(session_id, agent_run_id, agent_id),
                name=f"live-eval-{agent_id}-{agent_run_id}",
            )
        except Exception:
            # Live evaluation must never crash agent execution
            pass

    def _handle_agent_resume_result(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        result: dict,
        agent_id: str | None = None,
    ) -> str:
        """Handle the result from a resumed agent (continue_run).

        Updates agent run and session status based on the result.
        This is the single source of truth for mapping agent loop results
        to status transitions — used by all resume methods.

        Returns:
            "completed" or "paused"
        """
        # Paused
        if result.get("status") == "paused" or result.get("paused"):
            pause_reason = result.get("reason", "unknown")
            if pause_reason == "waiting_answer":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_HITL)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
            elif pause_reason == "waiting_sandbox":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_SANDBOX)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
            elif pause_reason == "user_paused":
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_USER)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED)
            else:
                self.execution_repo.update_status(agent_run_id, AgentRunStatus.PAUSED_TOOL)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
            self.execution_repo.commit()
            return "paused"

        # Completed
        self.execution_repo.update_status(agent_run_id, AgentRunStatus.COMPLETED)
        self.execution_repo.commit()

        if agent_id:
            self._on_agent_completed(session_id, agent_run_id, agent_id)

        return "completed"

    async def resume_after_approval(self, session_id: UUID, approval_id: UUID) -> UUID:
        """Resume execution after an approval is granted.

        This method:
        1. Executes the approved tool
        2. Continues the paused agent run (it will reconstruct state from DB)
        3. After that agent completes, executes any remaining pending runs

        The agent's continue_run() method loads all LLM calls and tool results
        from the database, so the tool result is automatically included.
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent
        from druppie.core.mcp_config import MCPConfig
        from druppie.execution.mcp_http import MCPHttp
        from druppie.execution.tool_executor import ToolCallStatus, ToolExecutor
        from druppie.repositories import ApprovalRepository

        logger.info(
            "resume_after_approval",
            session_id=str(session_id),
            approval_id=str(approval_id),
        )

        db = self.execution_repo.db
        mcp_config = MCPConfig()
        mcp_http = MCPHttp(mcp_config)
        tool_executor = ToolExecutor(db, mcp_http, mcp_config)
        approval_repo = ApprovalRepository(db)

        # Step 1: Get the approval to find the agent run
        approval = approval_repo.get_by_id(approval_id)
        if not approval or not approval.agent_run_id:
            logger.error("approval_missing_agent_run", approval_id=str(approval_id))
            await self.execute_pending_runs(session_id)
            return session_id

        # Step 2: Execute the approved tool
        # Note: Even if the tool fails, we continue to resume the agent
        # so it can see the error and decide what to do (retry, different approach, etc.)
        tool_status = await tool_executor.execute_after_approval(approval_id)

        logger.info(
            "tool_executed_after_approval",
            approval_id=str(approval_id),
            tool_status=tool_status,
        )

        # Step 3: Get the paused agent run
        agent_run = self.execution_repo.get_by_id(approval.agent_run_id)
        if not agent_run:
            logger.error("agent_run_not_found", agent_run_id=str(approval.agent_run_id))
            await self.execute_pending_runs(session_id)
            return session_id

        logger.info(
            "resuming_paused_agent_after_approval",
            agent_run_id=str(agent_run.id),
            agent_id=agent_run.agent_id,
            previous_status=agent_run.status.value if hasattr(agent_run.status, 'value') else agent_run.status,
        )

        # Step 4: Set status back to running
        self.execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
        self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
        self.execution_repo.commit()

        # Step 5: Build fresh context and continue the agent
        context = self.build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db, session_id=str(session_id))
        result = await agent.continue_run(
            session_id=session_id,
            agent_run_id=agent_run.id,
            context=context,
        )

        # Step 6: Handle result (correctly handles user_paused, sandbox, etc.)
        status = self._handle_agent_resume_result(session_id, agent_run.id, result, agent_id=agent_run.agent_id)

        if status == "completed":
            logger.info(
                "agent_resumed_after_approval_completed",
                agent_run_id=str(agent_run.id),
                agent_id=agent_run.agent_id,
            )
            parent_chain_completed = await self._walk_parent_chain(
                session_id, agent_run, db,
            )
            if parent_chain_completed:
                await self.execute_pending_runs(session_id)

        return session_id

    async def resume_after_answer(
        self,
        session_id: UUID,
        question_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
    ) -> UUID:
        """Resume execution after a HITL question is answered.

        This method:
        1. Saves the answer to the tool call result in DB
        2. Continues the paused agent run (it will reconstruct state from DB)
        3. After that agent completes, executes any remaining pending runs

        The agent's continue_run() method loads all LLM calls and tool results
        from the database, so the answer is automatically included.
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent
        from druppie.core.mcp_config import MCPConfig
        from druppie.execution.mcp_http import MCPHttp
        from druppie.execution.tool_executor import ToolCallStatus, ToolExecutor

        logger.info(
            "resume_after_answer",
            session_id=str(session_id),
            question_id=str(question_id),
        )

        db = self.execution_repo.db
        mcp_config = MCPConfig()
        mcp_http = MCPHttp(mcp_config)
        tool_executor = ToolExecutor(db, mcp_http, mcp_config)

        # Step 1: Get the question to find the agent run
        question = self.question_repo.get_by_id(question_id)
        if not question or not question.agent_run_id:
            logger.error("question_missing_agent_run", question_id=str(question_id))
            await self.execute_pending_runs(session_id)
            return session_id

        # Step 2: Detect language for translation but do NOT update session language.
        # Session language is locked by the initial user message to prevent
        # HITL answers from flipping it (e.g. a Dutch user giving one
        # English-sounding answer would switch the entire session to English).
        human_input = HumanInput(answer, self.language_detector)
        self._last_language_info = human_input.language_info()

        translated_answer = answer
        if human_input.detected_language and human_input.detected_language != "en":
            try:
                from druppie.core.translation import get_translation_service, TranslationNotAvailableError
                translator = get_translation_service()
                translated_answer = await translator.translate_to_english(
                    answer, human_input.detected_language
                )
                if translated_answer != answer:
                    logger.info(
                        "hitl_answer_translated",
                        session_id=str(session_id),
                        question_id=str(question_id),
                        source_language=human_input.detected_language,
                    )
            except TranslationNotAvailableError:
                logger.warning("translation_skipped_no_api_key", session_id=str(session_id))

        # Step 2.5: Complete the HITL tool call with translated answer (English for agent)
        # but preserve the original answer for display in the UI
        status = await tool_executor.complete_after_answer(
            question_id, answer_english=translated_answer, user_answer=answer,
            selected_choices=selected_choices,
        )

        if status != ToolCallStatus.COMPLETED:
            logger.error("complete_after_answer_failed", status=status)
            return session_id

        # Check if ALL questions for this agent run have been answered.
        # If some are still pending, don't resume the agent yet.
        from druppie.db.models.question import Question as QuestionModel
        from druppie.domain.common import QuestionStatus

        pending_siblings = (
            db.query(QuestionModel)
            .filter(
                QuestionModel.agent_run_id == question.agent_run_id,
                QuestionModel.status == QuestionStatus.PENDING.value,
                QuestionModel.id != question_id,
            )
            .count()
        )
        if pending_siblings > 0:
            logger.info(
                "waiting_for_sibling_answers",
                agent_run_id=str(question.agent_run_id),
                answered_question_id=str(question_id),
                pending_count=pending_siblings,
                session_id=str(session_id),
            )
            return session_id

        # Step 3: Get the paused agent run
        agent_run = self.execution_repo.get_by_id(question.agent_run_id)
        if not agent_run:
            logger.error("agent_run_not_found", agent_run_id=str(question.agent_run_id))
            await self.execute_pending_runs(session_id)
            return session_id

        logger.info(
            "resuming_paused_agent",
            agent_run_id=str(agent_run.id),
            agent_id=agent_run.agent_id,
            previous_status=agent_run.status,
        )

        # Step 4: Set status back to running
        self.execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
        self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
        self.execution_repo.commit()

        # Step 5: Build fresh context and continue the agent
        context = self.build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db, session_id=str(session_id))
        result = await agent.continue_run(
            session_id=session_id,
            agent_run_id=agent_run.id,
            context=context,
        )

        # Step 6: Handle result (correctly handles user_paused, sandbox, etc.)
        status = self._handle_agent_resume_result(session_id, agent_run.id, result, agent_id=agent_run.agent_id)

        if status == "completed":
            logger.info(
                "agent_resumed_and_completed",
                agent_run_id=str(agent_run.id),
                agent_id=agent_run.agent_id,
            )
            parent_chain_completed = await self._walk_parent_chain(
                session_id, agent_run, db,
            )
            if parent_chain_completed:
                logger.info(
                    "parent_chain_completed_running_pending",
                    session_id=str(session_id),
                )
                await self.execute_pending_runs(session_id)
            else:
                logger.info(
                    "parent_chain_incomplete_waiting_for_siblings",
                    session_id=str(session_id),
                )

        return session_id

    async def _walk_parent_chain(
        self,
        session_id: UUID,
        completed_run,
        db,
    ) -> bool:
        """Walk up the parent chain from a completed agent run.

        For each paused parent, checks if ALL sibling subagents have completed.
        If so, patches the subagents tool call with results and resumes the parent.
        Returns True if the entire chain completed (caller should run pending runs),
        False if the chain stopped early (siblings not done or parent re-paused).
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent

        paused_statuses = {
            AgentRunStatus.PAUSED_HITL,
            AgentRunStatus.PAUSED_TOOL,
            AgentRunStatus.PAUSED_SANDBOX,
            AgentRunStatus.PAUSED_USER,
        }
        current_run = completed_run
        while current_run.parent_run_id:
            self.execution_repo.db.expire_all()
            parent_run = self.execution_repo.get_by_id(current_run.parent_run_id)
            if not parent_run or AgentRunStatus(parent_run.status) not in paused_statuses:
                logger.info(
                    "parent_chain_break_not_paused",
                    parent_run_id=str(parent_run.id) if parent_run else None,
                    parent_status=parent_run.status if parent_run else "not_found",
                    current_run_id=str(current_run.id),
                )
                break

            logger.info(
                "resuming_paused_parent",
                parent_run_id=str(parent_run.id),
                parent_agent_id=parent_run.agent_id,
                previous_status=parent_run.status,
            )

            if not self._all_siblings_completed(current_run.parent_run_id, current_run.spawning_tool_call_id):
                logger.info(
                    "skipping_parent_resume_siblings_not_done",
                    parent_run_id=str(parent_run.id),
                    child_run_id=str(current_run.id),
                    spawning_tool_call_id=str(current_run.spawning_tool_call_id),
                )
                # Parent chain is NOT completed — siblings still running.
                # Do NOT call execute_pending_runs() or the session will be
                # prematurely marked COMPLETED.
                return False

            self._patch_paused_subagents_tool_call(parent_run.id, session_id)

            self.execution_repo.update_status(parent_run.id, AgentRunStatus.RUNNING)
            self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
            self.execution_repo.commit()

            parent_context = self.build_project_context(session_id)
            parent_agent = Agent(parent_run.agent_id, db=db)
            parent_result = await parent_agent.continue_run(
                session_id=session_id,
                agent_run_id=parent_run.id,
                context=parent_context,
            )
            parent_status = self._handle_agent_resume_result(
                session_id, parent_run.id, parent_result, agent_id=parent_run.agent_id,
            )
            if parent_status != "completed":
                return False
            current_run = parent_run

        return True

    async def resume_paused_session(
        self,
        session_id: UUID,
        contexts: dict[str, str] | None = None,
    ) -> UUID:
        """Resume a paused or failed session.

        Priority order:
        1. PAUSED_USER agent run → continue via continue_run()
        2. PAUSED_TOOL/HITL agent run → restore waiting status
        3. Orphaned RUNNING agent run → continue via continue_run()
           (handles infrastructure crashes where the run stayed 'running')
        4. No paused/running run → execute pending runs directly

        Args:
            session_id: Session to resume
            contexts: Optional dict of agent_run_id -> context string for each leaf
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent

        logger.info(
            "resume_paused_session",
            session_id=str(session_id),
            has_context=bool(contexts),
        )

        # Session is already set to ACTIVE by the endpoint's lock_for_resume()

        paused_leaves = self.execution_repo.get_user_paused_leaves(session_id)

        if not paused_leaves:
            # Check if there's a run waiting for approval/answer — if so,
            # restore the session to its waiting status and let the
            # approval/answer flow handle it naturally
            waiting_run = self.execution_repo.get_paused_run(session_id)
            if waiting_run:
                if waiting_run.status == AgentRunStatus.PAUSED_HITL:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                elif waiting_run.status == AgentRunStatus.PAUSED_SANDBOX:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                else:
                    self.session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                self.session_repo.commit()
                logger.info(
                    "resume_restored_waiting_status",
                    session_id=str(session_id),
                    agent_run_id=str(waiting_run.id),
                    restored_status=waiting_run.status,
                )
                return session_id

            # Check for orphaned running runs (e.g., infrastructure crash).
            # The background task died but the agent run stayed 'running'
            # because run_session_task's db.rollback() reverted the status update.
            orphan_run = self.execution_repo.get_running_run(session_id)
            if orphan_run:
                logger.info(
                    "resuming_orphaned_running_agent",
                    agent_run_id=str(orphan_run.id),
                    agent_id=orphan_run.agent_id,
                )

                # Already RUNNING — just continue it
                db = self.execution_repo.db
                context = self.build_project_context(session_id)
                agent = Agent(orphan_run.agent_id, db=db, session_id=str(session_id))
                try:
                    result = await agent.continue_run(
                        session_id=session_id,
                        agent_run_id=orphan_run.id,
                        context=context,
                    )
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {e}"
                    self.execution_repo.update_status(
                        orphan_run.id,
                        AgentRunStatus.FAILED,
                        error_message=error_msg[:2000],
                    )
                    self.execution_repo.commit()
                    raise

                status = self._handle_agent_resume_result(session_id, orphan_run.id, result, agent_id=orphan_run.agent_id)

                if status == "completed":
                    logger.info(
                        "orphaned_agent_resumed_and_completed",
                        agent_run_id=str(orphan_run.id),
                        agent_id=orphan_run.agent_id,
                    )
                    parent_chain_completed = await self._walk_parent_chain(
                        session_id, orphan_run, db,
                    )
                    if parent_chain_completed:
                        await self.execute_pending_runs(session_id)

                return session_id

            # Pause happened between runs — just continue with pending
            logger.info(
                "resume_no_paused_run_found",
                session_id=str(session_id),
            )
            await self.execute_pending_runs(session_id)
            return session_id

        logger.info(
            "resuming_user_paused_leaves",
            count=len(paused_leaves),
            agents=[l.agent_id for l in paused_leaves],
        )

        if len(paused_leaves) == 1:
            leaf = paused_leaves[0]
            ctx = contexts.get(str(leaf.id)) if contexts else None
            await self._resume_single_paused_leaf(session_id, leaf, user_context=ctx)
        else:
            import asyncio as _asyncio
            await _asyncio.gather(*[
                self._resume_leaf_with_own_db(
                    session_id, leaf,
                    user_context=contexts.get(str(leaf.id)) if contexts else None,
                )
                for leaf in paused_leaves
            ])

        return session_id

    async def _resume_leaf_with_own_db(self, session_id: UUID, leaf, user_context: str | None = None) -> None:
        from druppie.db.database import SessionLocal
        from druppie.repositories import ExecutionRepository, SessionRepository

        db = SessionLocal()
        try:
            leaf_orchestrator = Orchestrator(
                session_repo=SessionRepository(db),
                execution_repo=ExecutionRepository(db),
                project_repo=self.project_repo,
                question_repo=self.question_repo,
            )
            await leaf_orchestrator._resume_single_paused_leaf(session_id, leaf, user_context=user_context)
        finally:
            db.close()

    async def _resume_single_paused_leaf(
        self, session_id: UUID, paused_run, user_context: str | None = None,
    ) -> None:
        from druppie.agents.runtime_v2 import AgentV2 as Agent

        logger.info(
            "resuming_user_paused_agent",
            agent_run_id=str(paused_run.id),
            agent_id=paused_run.agent_id,
            has_user_context=bool(user_context),
        )

        self.execution_repo.update_status(paused_run.id, AgentRunStatus.RUNNING)
        self.execution_repo.commit()

        db = self.execution_repo.db
        context = self.build_project_context(session_id)
        if user_context and context is not None:
            context["user_context"] = user_context
            from druppie.db.models.llm_call import LlmCall
            from druppie.db.models.resume_context_event import ResumeContextEvent
            llm_call_count = db.query(LlmCall).filter_by(agent_run_id=paused_run.id).count()
            next_seq = self.execution_repo.get_next_sequence_number(session_id)
            self.execution_repo.create_message(
                session_id=session_id,
                role="user",
                content=user_context,
                agent_run_id=paused_run.id,
                sequence_number=next_seq,
            )
            db.add(ResumeContextEvent(
                session_id=session_id,
                agent_run_id=paused_run.id,
                content=user_context,
                llm_call_index=llm_call_count,
            ))
            self.execution_repo.commit()
        agent = Agent(paused_run.agent_id, db=db, session_id=str(session_id))
        try:
            result = await agent.continue_run(
                session_id=session_id,
                agent_run_id=paused_run.id,
                context=context,
            )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            self.execution_repo.update_status(
                paused_run.id,
                AgentRunStatus.FAILED,
                error_message=error_msg[:2000],
            )
            self.execution_repo.commit()
            raise

        status = self._handle_agent_resume_result(session_id, paused_run.id, result, agent_id=paused_run.agent_id)

        if status == "completed":
            logger.info(
                "agent_resumed_after_pause_completed",
                agent_run_id=str(paused_run.id),
                agent_id=paused_run.agent_id,
            )
            parent_chain_completed = await self._walk_parent_chain(
                session_id, paused_run, db,
            )
            if parent_chain_completed:
                await self.execute_pending_runs(session_id)

        return session_id

    def _sync_workspace(self, session_id: UUID) -> None:
        """Git pull in the workspace so it picks up sandbox commits.

        The sandbox pushed to Gitea, but the MCP coding server's workspace
        (shared Docker volume) still has the old HEAD. Without this pull,
        the next tool call (read_file, write_file) would see stale code.

        Best-effort: logs warnings on failure but never blocks the resume.
        """
        import subprocess
        from pathlib import Path

        from druppie.db.models import Session as DBSession

        db = self.execution_repo.db
        session = db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session or not session.project_id:
            return

        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))
        user_part = str(session.user_id) if session.user_id else "default"
        workspace_path = workspace_root / user_part / str(session.project_id) / str(session.id)

        if not (workspace_path / ".git").exists():
            logger.debug("sync_workspace_no_git_dir", workspace=str(workspace_path))
            return

        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("sync_workspace_pulled", workspace=str(workspace_path), output=result.stdout.strip())
            else:
                logger.warning("sync_workspace_pull_failed", workspace=str(workspace_path), stderr=result.stderr.strip())
        except Exception as e:
            logger.warning("sync_workspace_error", workspace=str(workspace_path), error=str(e))

    async def resume_after_sandbox(self, tool_call_id: UUID) -> UUID | None:
        """Resume execution after a sandbox task completes.

        Called by the webhook handler after the control plane notifies
        that a sandbox session finished. The tool call result is already
        populated by the webhook handler.

        This method:
        1. Finds the paused agent run from the tool call
        2. Sets statuses back to RUNNING/ACTIVE
        3. Continues the agent (it reconstructs state from DB)
        4. Executes any remaining pending runs
        """
        from druppie.agents.runtime_v2 import AgentV2 as Agent

        # Find the tool call and its agent run
        tool_call = self.execution_repo.get_tool_call(tool_call_id)
        if not tool_call or not tool_call.agent_run_id:
            logger.error("sandbox_resume_tool_call_not_found", tool_call_id=str(tool_call_id))
            return None

        agent_run = self.execution_repo.get_by_id(tool_call.agent_run_id)
        if not agent_run:
            logger.error("sandbox_resume_agent_run_not_found", agent_run_id=str(tool_call.agent_run_id))
            return None

        session_id = agent_run.session_id

        logger.info(
            "resume_after_sandbox",
            tool_call_id=str(tool_call_id),
            agent_run_id=str(agent_run.id),
            session_id=str(session_id),
        )

        # Pull sandbox commits into the workspace before resuming.
        # The sandbox pushed to Gitea but the shared workspace volume
        # still has the old HEAD.
        self._sync_workspace(session_id)

        # Set statuses back to running
        self.execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
        self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
        self.execution_repo.commit()

        # Build fresh context and continue the agent
        db = self.execution_repo.db
        context = self.build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db, session_id=str(session_id))
        try:
            result = await agent.continue_run(
                session_id=session_id,
                agent_run_id=agent_run.id,
                context=context,
            )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            self.execution_repo.update_status(
                agent_run.id,
                AgentRunStatus.FAILED,
                error_message=error_msg[:2000],
            )
            self.execution_repo.commit()
            raise

        # Handle result — agent may pause again
        status = self._handle_agent_resume_result(session_id, agent_run.id, result, agent_id=agent_run.agent_id)

        if status == "completed":
            logger.info(
                "agent_resumed_after_sandbox_completed",
                agent_run_id=str(agent_run.id),
                agent_id=agent_run.agent_id,
            )
            parent_chain_completed = await self._walk_parent_chain(
                session_id, agent_run, db,
            )
            if parent_chain_completed:
                await self.execute_pending_runs(session_id)
            else:
                logger.info(
                    "parent_chain_incomplete_waiting_for_siblings",
                    session_id=str(session_id),
                )

        return session_id
