"""Orchestrator - coordinates agent runs and tool execution.

The orchestrator is the main entry point for processing user messages.

Flow:
1. Create session
2. Save user message to timeline
3. Run router with user's projects injected
4. Parse router's intent from done() result
5. Handle project creation/selection based on intent
6. Create planner with intent injected into prompt
7. Execute remaining pending runs (planner → architect → developer → deployer)

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
         ├─► Run Router (with projects injected)
         │         │
         │         └─► done(summary='{"intent": "...", ...}')
         │
         ├─► Parse intent, handle project
         │
         ├─► Create Planner (with intent injected)
         │
         └─► execute_pending_runs()
                 │
                 ▼
           Planner → Architect → Developer → Deployer
"""

import json
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

        Flow:
        1. Create or get session
        2. Save user message to timeline
        3. Get user's projects for router
        4. Run router to classify intent
        5. Handle project creation/selection
        6. Create planner with intent context
        7. Execute remaining pending runs

        Args:
            message: User's message
            user_id: User ID (required for project lookup)
            session_id: Existing session ID (optional)
            project_id: Project ID if already known (optional)

        Returns:
            session_id
        """
        # Step 1: Get or create session
        if session_id:
            existing = self.session_repo.get_by_id(session_id)
            if not existing:
                raise ValueError(f"Session {session_id} not found")
            current_session_id = session_id
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
        )

        # Step 2: Save user message to the timeline
        self.execution_repo.create_message(
            session_id=current_session_id,
            role="user",
            content=message,
            sequence_number=0,
        )
        self.execution_repo.commit()

        # Step 3: Get user's projects for router injection
        user_projects = self.project_repo.get_by_user(user_id)
        projects_context = self._format_projects_for_router(user_projects)

        # Step 4: Create and run router
        router_prompt = f"{projects_context}\n\nUSER REQUEST:\n{message}"
        router_run = self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="router",
            status=AgentRunStatus.PENDING,
            planned_prompt=router_prompt,
            sequence_number=0,
        )
        self.execution_repo.commit()

        # Run router and get result
        router_result = await self._run_agent(
            session_id=current_session_id,
            agent_run_id=router_run.id,
            agent_id="router",
            prompt=router_prompt,
        )

        # Step 5: Parse intent from router's done() result
        intent_data = self._parse_router_intent(router_run.id)
        intent = intent_data.get("intent", "general_chat")

        logger.info(
            "router_intent_parsed",
            session_id=str(current_session_id),
            intent=intent,
            intent_data=intent_data,
        )

        # Step 6: Handle project based on intent
        final_project_id = project_id
        if intent == "create_project":
            # Create new project
            project_name = intent_data.get("project_name", "new-project")
            new_project = self.project_repo.create(
                name=project_name,
                user_id=user_id,
            )
            self.project_repo.commit()
            final_project_id = new_project.id
            logger.info("project_created", project_id=str(final_project_id), name=project_name)

            # Create Gitea repository for the project under user's account
            repo_name, repo_url, repo_owner = await self._create_gitea_repo(
                project_name, final_project_id, user_id
            )
            if repo_name and repo_url:
                self.project_repo.update_repo(final_project_id, repo_name, repo_url, repo_owner)
                self.project_repo.commit()
                logger.info(
                    "gitea_repo_created",
                    project_id=str(final_project_id),
                    repo_owner=repo_owner,
                    repo_url=repo_url,
                )

        elif intent == "update_project":
            # Use existing project
            final_project_id = UUID(intent_data.get("project_id")) if intent_data.get("project_id") else project_id

        # Update session with project
        if final_project_id:
            self.session_repo.update_project(current_session_id, final_project_id)
            self.session_repo.commit()

        # Step 7: Create planner with intent context
        planner_prompt = self._build_planner_prompt(message, intent, final_project_id)
        self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="planner",
            status=AgentRunStatus.PENDING,
            planned_prompt=planner_prompt,
            sequence_number=1,
        )
        self.execution_repo.commit()

        # Step 8: Execute remaining pending runs (planner and beyond)
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

    def _parse_router_intent(self, router_run_id: UUID) -> dict:
        """Parse intent from router's done() tool call result.

        Router calls done(summary='{"intent": "...", ...}')
        We find the done tool call and parse the JSON from summary.
        """
        # Get all tool calls for this agent run
        tool_calls = self.execution_repo.get_tool_calls_for_run(router_run_id)

        # Find the done tool call
        for tc in tool_calls:
            if tc.tool_name == "done" and tc.result:
                # tc.result is stored as JSON string in Text column
                # Parse it to get: {"status": "completed", "summary": "..."}
                try:
                    result = json.loads(tc.result) if isinstance(tc.result, str) else tc.result
                except json.JSONDecodeError:
                    result = {}

                summary = result.get("summary", "") if isinstance(result, dict) else ""

                # Try to parse summary as JSON (router puts intent here)
                try:
                    return json.loads(summary)
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, try to extract intent from text
                    if "create_project" in summary.lower():
                        return {"intent": "create_project"}
                    elif "update_project" in summary.lower():
                        return {"intent": "update_project"}
                    return {"intent": "general_chat"}

        return {"intent": "general_chat"}

    def _build_planner_prompt(self, message: str, intent: str, project_id: UUID | None) -> str:
        """Build planner prompt with intent context injected."""
        return f"""INTENT: {intent}
PROJECT_ID: {str(project_id) if project_id else 'new'}

USER REQUEST:
{message}"""

    async def _create_gitea_repo(
        self,
        project_name: str,
        project_id: UUID,
        user_id: UUID,
    ) -> tuple[str | None, str | None, str | None]:
        """Create a Gitea repository for the project.

        First tries to create under user's Gitea account (if it exists).
        Falls back to creating in the shared organization.

        Args:
            project_name: Name of the project (used as repo name)
            project_id: Project UUID (appended to make repo name unique)
            user_id: User UUID (to look up Gitea username)

        Returns:
            Tuple of (repo_name, repo_url, repo_owner) or (None, None, None) if failed
        """
        from druppie.core.gitea import get_gitea_client, GITEA_ORG
        from druppie.db.models import User

        # Get username for Gitea account
        user = self.session_repo.db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error("user_not_found_for_gitea_repo", user_id=str(user_id))
            return None, None, None

        gitea_username = user.username

        # Make repo name unique by appending short project ID
        # This handles cases where user creates multiple "todo-app" projects
        short_id = str(project_id)[:8]
        repo_name = f"{project_name}-{short_id}"

        try:
            gitea = get_gitea_client()

            # First, try to create under user's account
            result = await gitea.create_repo(
                name=repo_name,
                description=f"Project: {project_name}",
                auto_init=True,
                owner=gitea_username,
            )

            # If user doesn't exist in Gitea, fall back to organization
            if not result.get("success") and result.get("status_code") == 404:
                logger.info(
                    "gitea_user_not_found_falling_back_to_org",
                    gitea_username=gitea_username,
                    org=GITEA_ORG,
                )
                result = await gitea.create_repo(
                    name=repo_name,
                    description=f"Project: {project_name} (owner: {gitea_username})",
                    auto_init=True,
                    owner=None,  # Uses organization
                )

            if result.get("success"):
                repo_owner = result.get("owner", GITEA_ORG)
                return repo_name, result.get("repo_url"), repo_owner
            else:
                logger.error(
                    "gitea_repo_creation_failed",
                    project_name=project_name,
                    gitea_username=gitea_username,
                    error=result.get("error"),
                    status_code=result.get("status_code"),
                )
                return None, None, None

        except Exception as e:
            logger.error(
                "gitea_repo_creation_error",
                project_name=project_name,
                error=str(e),
            )
            return None, None, None

    async def execute_pending_runs(self, session_id: UUID) -> None:
        """Execute all pending agent runs in sequence.

        Runs pending agents ordered by sequence_number.
        Stops if an agent pauses (waiting for approval/answer).
        """
        logger.info("execute_pending_runs_start", session_id=str(session_id))

        # Build project context for agents (repo_name, repo_owner, etc.)
        context = self._build_project_context(session_id)

        while True:
            # Get next pending run
            next_run = self.execution_repo.get_next_pending(session_id)

            if not next_run:
                logger.info("execute_pending_runs_complete", session_id=str(session_id))
                self.session_repo.update_status(session_id, SessionStatus.COMPLETED)
                self.session_repo.commit()
                return

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

        Args:
            session_id: Session UUID

        Returns:
            Context dict with project info, or None if no project associated
        """
        from druppie.db.models import Session as DBSession, Project

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
        result = await agent.run(
            prompt=prompt,
            session_id=session_id,
            agent_run_id=agent_run_id,
            context=context,
        )

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
