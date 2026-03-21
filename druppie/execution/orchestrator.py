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

import os
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.agents.prompt_builder import DEFAULT_LANGUAGE
from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.core.language_detection import LanguageDetector
from druppie.execution.human_input import HumanInput

if TYPE_CHECKING:
    from druppie.repositories import SessionRepository, ExecutionRepository, ProjectRepository, QuestionRepository

logger = structlog.get_logger()


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
    ):
        """Initialize orchestrator with repositories.

        Args:
            session_repo: Repository for session operations
            execution_repo: Repository for agent runs, tool calls
            project_repo: Repository for project operations
            question_repo: Repository for question operations
        """
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.project_repo = project_repo
        self.question_repo = question_repo
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

        # Step 3b: Save user message to the timeline
        self.execution_repo.create_message(
            session_id=current_session_id,
            role="user",
            content=message,
            sequence_number=next_seq,
        )
        next_seq += 1
        self.execution_repo.commit()

        # Step 3.5: Detect and update language (only if detection succeeds)
        human_input = HumanInput(message, self.language_detector)
        self._last_language_info = human_input.language_info()
        if human_input.detected_language:  # None means text too short - preserve existing language
            self.session_repo.update_language(current_session_id, human_input.detected_language)
            logger.info(
                "language_detected",
                session_id=str(current_session_id),
                language=human_input.detected_language,
            )
            self.session_repo.commit()
        # If None, keep existing session language unchanged

        # Step 4: Get user's projects for router injection
        user_projects = self.project_repo.get_by_user(user_id)
        projects_context = self._format_projects_for_router(user_projects)

        # Step 5: Create router + planner (both PENDING)
        # Router will call set_intent() which updates planner's prompt
        if conversation_history:
            router_prompt = f"{projects_context}\n\n{conversation_history}\n\nNEW USER MESSAGE:\n{message}"
        else:
            router_prompt = f"{projects_context}\n\nUSER REQUEST:\n{message}"
        self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="router",
            status=AgentRunStatus.PENDING,
            planned_prompt=router_prompt,
            sequence_number=next_seq,
        )

        # Planner starts with basic prompt - set_intent will update it with context
        if conversation_history:
            planner_prompt = f"{conversation_history}\n\nNEW USER MESSAGE:\n{message}"
        else:
            planner_prompt = f"USER REQUEST:\n{message}"
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
            lines.append(f"{role_label}: {msg.content}")

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
                return

            # Rebuild context before each agent so it reflects changes
            # from previous agents (e.g., set_intent creates project/repo)
            context = self._build_project_context(session_id)

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

            # Run the agent with project context
            status = await self._run_agent(
                session_id=session_id,
                agent_run_id=next_run.id,
                agent_id=next_run.agent_id,
                prompt=next_run.planned_prompt or "",
                context=context,
            )

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

    def _build_project_context(self, session_id: UUID) -> dict | None:
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
        from druppie.db.models import Session as DBSession, Project

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

        logger.debug(
            "context_built",
            session_id=str(session_id),
            has_project=bool(session.project_id),
            conversational_language=context.get("conversational_language"),
        )

        return context

    async def _run_agent(
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
        from druppie.agents.runtime import Agent

        logger.info(
            "agent_run_start",
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
            agent_id=agent_id,
            has_context=bool(context),
        )

        # Create and run agent
        agent = Agent(agent_id, db=self.execution_repo.db)
        try:
            result = await agent.run(
                prompt=prompt,
                session_id=session_id,
                agent_run_id=agent_run_id,
                context=context,
            )
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

    def _on_agent_completed(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
    ) -> None:
        """Fire-and-forget live evaluation if configured."""
        try:
            from druppie.evaluation.config import get_evaluation_config

            config = get_evaluation_config()
            if not config.should_evaluate(agent_id):
                return

            from druppie.evaluation.live_evaluator import run_live_evaluation
            from druppie.core.background_tasks import create_tracked_task

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
        from druppie.execution.tool_executor import ToolExecutor, ToolCallStatus
        from druppie.execution.mcp_http import MCPHttp
        from druppie.core.mcp_config import MCPConfig
        from druppie.agents.runtime import Agent
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
        context = self._build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db)
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
            await self.execute_pending_runs(session_id)

        return session_id

    async def resume_after_answer(
        self,
        session_id: UUID,
        question_id: UUID,
        answer: str,
    ) -> UUID:
        """Resume execution after a HITL question is answered.

        This method:
        1. Saves the answer to the tool call result in DB
        2. Continues the paused agent run (it will reconstruct state from DB)
        3. After that agent completes, executes any remaining pending runs

        The agent's continue_run() method loads all LLM calls and tool results
        from the database, so the answer is automatically included.
        """
        from druppie.execution.tool_executor import ToolExecutor, ToolCallStatus
        from druppie.execution.mcp_http import MCPHttp
        from druppie.core.mcp_config import MCPConfig
        from druppie.agents.runtime import Agent

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

        # Step 2: Complete the HITL tool call (saves answer to DB)
        status = await tool_executor.complete_after_answer(question_id, answer)

        # Step 2.5: Detect and update language from HITL answer (only if detection succeeds)
        human_input = HumanInput(answer, self.language_detector)
        self._last_language_info = human_input.language_info()
        if human_input.detected_language:  # None means answer too short - preserve existing language
            self.session_repo.update_language(session_id, human_input.detected_language)
            logger.info(
                "language_detected_from_hitl_answer",
                session_id=str(session_id),
                question_id=str(question_id),
                language=human_input.detected_language,
            )
            self.session_repo.commit()
        # If None, keep existing session language unchanged

        if status != ToolCallStatus.COMPLETED:
            logger.error("complete_after_answer_failed", status=status)
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
        context = self._build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db)
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
            await self.execute_pending_runs(session_id)

        return session_id

    async def resume_paused_session(self, session_id: UUID) -> UUID:
        """Resume a paused or failed session.

        Priority order:
        1. PAUSED_USER agent run → continue via continue_run()
        2. PAUSED_TOOL/HITL agent run → restore waiting status
        3. Orphaned RUNNING agent run → continue via continue_run()
           (handles infrastructure crashes where the run stayed 'running')
        4. No paused/running run → execute pending runs directly
        """
        from druppie.agents.runtime import Agent

        logger.info("resume_paused_session", session_id=str(session_id))

        # Session is already set to ACTIVE by the endpoint's lock_for_resume()
        # Find the paused agent run
        paused_run = self.execution_repo.get_user_paused_run(session_id)

        if not paused_run:
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
                context = self._build_project_context(session_id)
                agent = Agent(orphan_run.agent_id, db=db)
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
            "resuming_user_paused_agent",
            agent_run_id=str(paused_run.id),
            agent_id=paused_run.agent_id,
        )

        # Mark agent run as running
        self.execution_repo.update_status(paused_run.id, AgentRunStatus.RUNNING)
        self.execution_repo.commit()

        # Build fresh context and continue the agent
        db = self.execution_repo.db
        context = self._build_project_context(session_id)
        agent = Agent(paused_run.agent_id, db=db)
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

        # Handle result (correctly handles user_paused, cancelled, etc.)
        status = self._handle_agent_resume_result(session_id, paused_run.id, result, agent_id=paused_run.agent_id)

        if status == "completed":
            logger.info(
                "agent_resumed_after_pause_completed",
                agent_run_id=str(paused_run.id),
                agent_id=paused_run.agent_id,
            )
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
        from druppie.agents.runtime import Agent

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
        context = self._build_project_context(session_id)
        agent = Agent(agent_run.agent_id, db=db)
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
            await self.execute_pending_runs(session_id)

        return session_id
