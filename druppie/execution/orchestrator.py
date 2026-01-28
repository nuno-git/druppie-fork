"""Orchestrator - coordinates agent runs and tool execution.

The orchestrator is the main entry point for processing user messages.

Flow:
1. Create session
2. Run router with user's projects injected
3. Parse router's intent from done() result
4. Handle project creation/selection based on intent
5. Create planner with intent injected into prompt
6. Execute remaining pending runs (planner → architect → developer → deployer)

Architecture:
    User Message
         │
         ▼
    Orchestrator.process_message()
         │
         ├─► Create Session
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
    from druppie.repositories import SessionRepository, ExecutionRepository, ProjectRepository

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
    ):
        """Initialize orchestrator with repositories.

        Args:
            session_repo: Repository for session operations
            execution_repo: Repository for agent runs, tool calls
            project_repo: Repository for project operations
        """
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.project_repo = project_repo

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
        2. Get user's projects for router
        3. Run router to classify intent
        4. Handle project creation/selection
        5. Create planner with intent context
        6. Execute remaining pending runs

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

        # Step 2: Get user's projects for router injection
        user_projects = self.project_repo.get_by_user(user_id)
        projects_context = self._format_projects_for_router(user_projects)

        # Step 3: Create and run router
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

        # Step 4: Parse intent from router's done() result
        intent_data = self._parse_router_intent(router_run.id)
        intent = intent_data.get("intent", "general_chat")

        logger.info(
            "router_intent_parsed",
            session_id=str(current_session_id),
            intent=intent,
            intent_data=intent_data,
        )

        # Step 5: Handle project based on intent
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

        elif intent == "update_project":
            # Use existing project
            final_project_id = UUID(intent_data.get("project_id")) if intent_data.get("project_id") else project_id

        # Update session with project
        if final_project_id:
            self.session_repo.update_project(current_session_id, final_project_id)
            self.session_repo.commit()

        # Step 6: Create planner with intent context
        planner_prompt = self._build_planner_prompt(message, intent, final_project_id)
        self.execution_repo.create_agent_run(
            session_id=current_session_id,
            agent_id="planner",
            status=AgentRunStatus.PENDING,
            planned_prompt=planner_prompt,
            sequence_number=1,
        )
        self.execution_repo.commit()

        # Step 7: Execute remaining pending runs (planner and beyond)
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

    async def execute_pending_runs(self, session_id: UUID) -> None:
        """Execute all pending agent runs in sequence.

        Runs pending agents ordered by sequence_number.
        Stops if an agent pauses (waiting for approval/answer).
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

            # Run the agent
            status = await self._run_agent(
                session_id=session_id,
                agent_run_id=next_run.id,
                agent_id=next_run.agent_id,
                prompt=next_run.planned_prompt or "",
            )

            # If paused, stop execution
            if status == "paused":
                logger.info(
                    "execute_pending_runs_paused",
                    session_id=str(session_id),
                    agent_run_id=str(next_run.id),
                )
                return

    async def _run_agent(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
        prompt: str,
    ) -> str:
        """Run a single agent.

        Returns:
            "completed" or "paused"
        """
        from druppie.agents.runtime import Agent

        logger.info(
            "agent_run_start",
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
            agent_id=agent_id,
        )

        # Create and run agent
        agent = Agent(agent_id, db=self.execution_repo.db)
        result = await agent.run(
            prompt=prompt,
            session_id=session_id,
            agent_run_id=agent_run_id,
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
        """Resume execution after an approval is granted."""
        from druppie.execution.tool_executor import ToolExecutor, ToolCallStatus
        from druppie.execution.mcp_http import MCPHttp
        from druppie.core.mcp_config import MCPConfig

        logger.info(
            "resume_after_approval",
            session_id=str(session_id),
            approval_id=str(approval_id),
        )

        db = self.execution_repo.db
        mcp_config = MCPConfig()
        mcp_http = MCPHttp(mcp_config)
        tool_executor = ToolExecutor(db, mcp_http, mcp_config)

        status = await tool_executor.execute_after_approval(approval_id)

        if status == ToolCallStatus.COMPLETED:
            await self.execute_pending_runs(session_id)

        return session_id

    async def resume_after_answer(
        self,
        session_id: UUID,
        question_id: UUID,
        answer: str,
    ) -> UUID:
        """Resume execution after a HITL question is answered."""
        from druppie.execution.tool_executor import ToolExecutor, ToolCallStatus
        from druppie.execution.mcp_http import MCPHttp
        from druppie.core.mcp_config import MCPConfig

        logger.info(
            "resume_after_answer",
            session_id=str(session_id),
            question_id=str(question_id),
        )

        db = self.execution_repo.db
        mcp_config = MCPConfig()
        mcp_http = MCPHttp(mcp_config)
        tool_executor = ToolExecutor(db, mcp_http, mcp_config)

        status = await tool_executor.complete_after_answer(question_id, answer)

        if status == ToolCallStatus.COMPLETED:
            await self.execute_pending_runs(session_id)

        return session_id
