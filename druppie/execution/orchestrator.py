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

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.domain.common import AgentRunStatus, SessionStatus

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

        # Step 3: Save user message to the timeline
        self.execution_repo.create_message(
            session_id=current_session_id,
            role="user",
            content=message,
            sequence_number=0,
        )
        self.execution_repo.commit()

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
            sequence_number=0,
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
            sequence_number=1,
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
        Stops if an agent pauses (waiting for approval/answer).

        Context is rebuilt before each agent so it picks up changes
        from previous agents (e.g., router creates project + repo,
        deployer needs repo_name in context).
        """
        logger.info("execute_pending_runs_start", session_id=str(session_id))

        while True:
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

            # If paused, stop execution
            if status == "paused":
                logger.info(
                    "execute_pending_runs_paused",
                    session_id=str(session_id),
                    agent_run_id=str(next_run.id),
                )
                return

    def _build_project_context(self, session_id: UUID) -> dict | None:
        """Build project context for agents.

        Retrieves project info (repo_name, repo_owner, etc.) from the session
        and returns it as a context dict that will be injected into agent prompts.

        Called before each agent run to pick up changes from previous agents
        (e.g., router creates project + Gitea repo with repo_name).

        Args:
            session_id: Session UUID

        Returns:
            Context dict with project info, or None if no project associated
        """
        from druppie.db.models import Session as DBSession, Project

        # Expire cached objects to ensure we read fresh data from DB.
        # Previous agents (e.g., router's set_intent) may have modified
        # the project record (adding repo_name) since we last queried.
        self.session_repo.db.expire_all()

        session = self.session_repo.db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session or not session.project_id:
            return None

        project = self.session_repo.db.query(Project).filter(Project.id == session.project_id).first()
        if not project:
            return None

        context = {
            "project_id": str(project.id),
            "project_name": project.name,
            "session_id": str(session_id),
        }

        # Add intent so agents know what workflow to follow
        if session.intent:
            context["intent"] = session.intent

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
            # Store error on agent_run before re-raising
            error_msg = f"{type(e).__name__}: {e}"
            self.execution_repo.update_status(
                agent_run_id,
                AgentRunStatus.FAILED,
                error_message=error_msg[:2000],
            )
            self.execution_repo.commit()
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
        self.execution_repo.commit()

        # Step 5: Continue the agent - it will load state from DB including the tool result
        agent = Agent(agent_run.agent_id, db=db)
        result = await agent.continue_run(
            session_id=session_id,
            agent_run_id=agent_run.id,
        )

        # Step 6: Handle result
        if result.get("status") == "paused" or result.get("paused"):
            pause_reason = result.get("reason", "unknown")
            if pause_reason == "waiting_answer":
                self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_HITL)
            else:
                self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_TOOL)
            self.execution_repo.commit()
            return session_id

        # Completed - mark agent and continue with pending runs
        self.execution_repo.update_status(agent_run.id, AgentRunStatus.COMPLETED)
        self.execution_repo.commit()

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
        self.execution_repo.commit()

        # Step 5: Continue the agent - it will load state from DB including the answer
        agent = Agent(agent_run.agent_id, db=db)
        result = await agent.continue_run(
            session_id=session_id,
            agent_run_id=agent_run.id,
        )

        # Step 6: Handle result
        if result.get("status") == "paused" or result.get("paused"):
            pause_reason = result.get("reason", "unknown")
            if pause_reason == "waiting_answer":
                self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_HITL)
            else:
                self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_TOOL)
            self.execution_repo.commit()
            return session_id

        # Completed - mark agent and continue with pending runs
        self.execution_repo.update_status(agent_run.id, AgentRunStatus.COMPLETED)
        self.execution_repo.commit()

        logger.info(
            "agent_resumed_and_completed",
            agent_run_id=str(agent_run.id),
            agent_id=agent_run.agent_id,
        )

        await self.execute_pending_runs(session_id)
        return session_id
