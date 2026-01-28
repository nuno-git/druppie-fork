"""Orchestrator - main entry point for processing messages.

The orchestrator coordinates:
1. Running router and planner agents
2. Executing pending agent runs (the plan)
3. Resuming after approvals or HITL questions

This replaces the complex MainLoop class with a simpler flow.

Architecture:
    Orchestrator uses repositories for all database access.
    No direct SQLAlchemy imports - only domain models.
"""

from uuid import UUID

import structlog

from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.domain.session import SessionSummary
from druppie.domain.agent_run import AgentRunSummary
from druppie.repositories import SessionRepository, ExecutionRepository

logger = structlog.get_logger()


class Orchestrator:
    """Main entry point for processing messages.

    Uses repositories for all database access. Returns session IDs,
    callers fetch SessionDetail to see the full chat timeline.
    """

    def __init__(
        self,
        session_repo: SessionRepository,
        execution_repo: ExecutionRepository,
    ):
        self.session_repo = session_repo
        self.execution_repo = execution_repo

    async def process_message(
        self,
        message: str,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> UUID:
        """Process a user message.

        Flow:
        1. Create or get session
        2. Run router agent (determines intent)
        3. Run planner agent (creates pending runs via make_plan tool)
        4. Execute pending runs in sequence

        Returns:
            session_id - Caller fetches SessionDetail to see result
        """
        from druppie.agents.runtime import Agent

        # 1. Get existing session or create new one
        if session_id:
            existing = self.session_repo.get_by_id(session_id)
            if not existing:
                raise ValueError(f"Session {session_id} not found")
            # Use the provided session_id
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
            "process_message",
            session_id=str(current_session_id),
            message_preview=message[:50] if message else "",
        )

        # 2. Run router agent
        router = Agent("router", db=self.session_repo.db, session_id=str(current_session_id))
        router_result = await router.run(message)

        if router_result.get("status") == "paused":
            logger.info("router_paused", session_id=str(current_session_id))
            return current_session_id

        # 3. Run planner agent (creates pending runs via make_plan tool)
        planner = Agent("planner", db=self.session_repo.db, session_id=str(current_session_id))
        planner_result = await planner.run(f"User request: {message}")

        if planner_result.get("status") == "paused":
            logger.info("planner_paused", session_id=str(current_session_id))
            return current_session_id

        # 4. Execute pending runs
        await self.execute_pending_runs(current_session_id)

        return current_session_id

    async def execute_pending_runs(self, session_id: UUID) -> None:
        """Execute all pending agent runs in sequence.

        Gets pending runs ordered by sequence_number and executes them.
        Stops if an agent pauses for approval or HITL.
        """
        from druppie.agents.runtime import Agent

        logger.info("execute_pending_runs", session_id=str(session_id))

        while True:
            # Get next pending run from repository
            next_run = self.execution_repo.get_next_pending(session_id)

            if not next_run:
                logger.info("no_more_pending_runs", session_id=str(session_id))
                # Update session status to completed
                self.session_repo.update_status(session_id, SessionStatus.COMPLETED)
                self.session_repo.commit()
                break

            logger.info(
                "executing_pending_run",
                session_id=str(session_id),
                agent_run_id=str(next_run.id),
                agent_id=next_run.agent_id,
                sequence_number=next_run.sequence_number,
            )

            # Update status to running
            self.execution_repo.update_status(next_run.id, AgentRunStatus.RUNNING)
            self.execution_repo.commit()

            # Execute using existing Agent class
            agent = Agent(
                next_run.agent_id,
                db=self.session_repo.db,
                session_id=str(session_id),
                agent_run_id=str(next_run.id),
            )
            result = await agent.run(next_run.planned_prompt)

            if result.get("status") == "paused":
                logger.info(
                    "agent_paused",
                    session_id=str(session_id),
                    agent_run_id=str(next_run.id),
                    reason=result.get("reason"),
                )
                # Session status already updated by agent
                return

            # Agent completed - mark run as completed
            self.execution_repo.update_status(next_run.id, AgentRunStatus.COMPLETED)
            self.execution_repo.commit()

            logger.info(
                "agent_run_completed",
                session_id=str(session_id),
                agent_run_id=str(next_run.id),
            )

            # Continue to next pending run

    async def resume_from_approval(self, session_id: UUID, approval_id: UUID) -> UUID:
        """Resume execution after an approval.

        Resumes the paused agent run and continues executing pending runs.
        """
        from druppie.agents.runtime import Agent

        logger.info(
            "resume_from_approval",
            session_id=str(session_id),
            approval_id=str(approval_id),
        )

        # Get the paused agent run from repository
        paused_run = self.execution_repo.get_paused_run(session_id)

        if paused_run:
            # Resume the agent
            agent = Agent(
                paused_run.agent_id,
                db=self.session_repo.db,
                session_id=str(session_id),
                agent_run_id=str(paused_run.id),
            )
            result = await agent.resume_from_approval(str(approval_id))

            if result.get("status") != "paused":
                # Agent completed - mark as completed and continue
                self.execution_repo.update_status(paused_run.id, AgentRunStatus.COMPLETED)
                self.execution_repo.commit()

                # Continue with remaining pending runs
                await self.execute_pending_runs(session_id)

        return session_id

    async def resume_from_question(self, session_id: UUID, question_id: UUID, answer: str) -> UUID:
        """Resume execution after a HITL question is answered.

        Resumes the paused agent run and continues executing pending runs.
        """
        from druppie.agents.runtime import Agent

        logger.info(
            "resume_from_question",
            session_id=str(session_id),
            question_id=str(question_id),
        )

        # Get the paused agent run from repository
        paused_run = self.execution_repo.get_paused_run(session_id)

        if paused_run:
            # Resume the agent with the answer
            agent = Agent(
                paused_run.agent_id,
                db=self.session_repo.db,
                session_id=str(session_id),
                agent_run_id=str(paused_run.id),
            )
            result = await agent.resume_from_question(str(question_id), answer)

            if result.get("status") != "paused":
                # Agent completed - mark as completed and continue
                self.execution_repo.update_status(paused_run.id, AgentRunStatus.COMPLETED)
                self.execution_repo.commit()

                # Continue with remaining pending runs
                await self.execute_pending_runs(session_id)

        return session_id
