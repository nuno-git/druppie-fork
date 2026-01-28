"""Orchestrator - main entry point for processing messages.

The orchestrator coordinates:
1. Running router and planner agents
2. Executing pending agent runs (the plan)
3. Resuming after approvals or HITL questions

This replaces the complex MainLoop class with a simpler flow.
"""

from uuid import UUID

import structlog
from sqlalchemy.orm import Session as DBSession

from druppie.db.models import AgentRun, Session
from druppie.domain.common import AgentRunStatus, SessionStatus

logger = structlog.get_logger()


class Orchestrator:
    """Main entry point for processing messages."""

    def __init__(self, db: DBSession):
        self.db = db

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

        # 1. Create or get session
        if session_id:
            session = self.db.query(Session).filter(Session.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")
        else:
            session = Session(
                user_id=user_id,
                project_id=project_id,
                title=message[:100] if message else "New Session",
                status=SessionStatus.ACTIVE.value,
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        session_id = session.id

        logger.info(
            "process_message",
            session_id=str(session_id),
            message_preview=message[:50] if message else "",
        )

        # 2. Run router agent
        router = Agent("router", db=self.db, session_id=str(session_id))
        router_result = await router.run(message)

        if router_result.get("status") == "paused":
            logger.info("router_paused", session_id=str(session_id))
            return session_id

        # 3. Run planner agent (creates pending runs via make_plan tool)
        planner = Agent("planner", db=self.db, session_id=str(session_id))
        planner_result = await planner.run(f"User request: {message}")

        if planner_result.get("status") == "paused":
            logger.info("planner_paused", session_id=str(session_id))
            return session_id

        # 4. Execute pending runs
        await self.execute_pending_runs(session_id)

        return session_id

    async def execute_pending_runs(self, session_id: UUID) -> None:
        """Execute all pending agent runs in sequence.

        Gets pending runs ordered by sequence_number and executes them.
        Stops if an agent pauses for approval or HITL.
        """
        from druppie.agents.runtime import Agent

        logger.info("execute_pending_runs", session_id=str(session_id))

        while True:
            # Get next pending run
            next_run = (
                self.db.query(AgentRun)
                .filter(
                    AgentRun.session_id == session_id,
                    AgentRun.status == AgentRunStatus.PENDING.value,
                )
                .order_by(AgentRun.sequence_number)
                .first()
            )

            if not next_run:
                logger.info("no_more_pending_runs", session_id=str(session_id))
                # Update session status to completed
                session = self.db.query(Session).filter(Session.id == session_id).first()
                if session:
                    session.status = SessionStatus.COMPLETED.value
                    self.db.commit()
                break

            logger.info(
                "executing_pending_run",
                session_id=str(session_id),
                agent_run_id=str(next_run.id),
                agent_id=next_run.agent_id,
                sequence_number=next_run.sequence_number,
            )

            # Update status to running
            next_run.status = AgentRunStatus.RUNNING.value
            self.db.commit()

            # Execute using existing Agent class
            agent = Agent(
                next_run.agent_id,
                db=self.db,
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
            next_run.status = AgentRunStatus.COMPLETED.value
            self.db.commit()

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

        # Get the paused agent run
        paused_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PAUSED_TOOL.value,
            )
            .first()
        )

        if paused_run:
            # Resume the agent
            agent = Agent(
                paused_run.agent_id,
                db=self.db,
                session_id=str(session_id),
                agent_run_id=str(paused_run.id),
            )
            result = await agent.resume_from_approval(str(approval_id))

            if result.get("status") != "paused":
                # Agent completed - mark as completed and continue
                paused_run.status = AgentRunStatus.COMPLETED.value
                self.db.commit()

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

        # Get the paused agent run
        paused_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PAUSED_HITL.value,
            )
            .first()
        )

        if paused_run:
            # Resume the agent with the answer
            agent = Agent(
                paused_run.agent_id,
                db=self.db,
                session_id=str(session_id),
                agent_run_id=str(paused_run.id),
            )
            result = await agent.resume_from_question(str(question_id), answer)

            if result.get("status") != "paused":
                # Agent completed - mark as completed and continue
                paused_run.status = AgentRunStatus.COMPLETED.value
                self.db.commit()

                # Continue with remaining pending runs
                await self.execute_pending_runs(session_id)

        return session_id


def get_orchestrator(db: DBSession) -> Orchestrator:
    """Factory function to create an Orchestrator instance."""
    return Orchestrator(db)
