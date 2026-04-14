"""Bounded orchestrator that wraps the real Orchestrator to stop after specified agents."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Question
from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.testing.hitl_simulator import HITLSimulator, MAX_HITL_INTERACTIONS

logger = logging.getLogger(__name__)


class BoundedOrchestrator:
    """Wraps the real Orchestrator to stop after the last real_agent completes."""

    def __init__(self, db: DbSession, user_id: UUID, real_agents: list[str],
                 hitl_simulator: HITLSimulator | None):
        self._db = db
        self._user_id = user_id
        self._real_agents = real_agents
        self._hitl_simulator = hitl_simulator

    def _all_real_agents_done(self, session_id: UUID, execution_repo) -> bool:
        if not self._real_agents:
            return False
        self._db.expire_all()
        completed_runs = execution_repo.get_completed_runs(session_id)
        completed_ids = {r.agent_id for r in completed_runs}
        done = all(a in completed_ids for a in self._real_agents)
        if done:
            logger.info("All real_agents completed: real=%s completed=%s",
                        self._real_agents, sorted(completed_ids))
        return done

    def _cancel_remaining_runs(self, session_id: UUID, execution_repo, session_repo) -> None:
        cancelled_count = execution_repo.cancel_pending_runs(session_id)
        execution_repo.commit()
        running = execution_repo.get_running_run(session_id)
        if running:
            execution_repo.update_status(running.id, AgentRunStatus.CANCELLED)
            execution_repo.commit()
            cancelled_count += 1
        session_repo.update_status(session_id, SessionStatus.COMPLETED)
        session_repo.commit()
        logger.info("Bounded cleanup: cancelled %d remaining runs, session=%s marked COMPLETED",
                     cancelled_count, session_id)

    async def run(self, message: str, session_id: UUID | None = None) -> UUID:
        from druppie.execution.orchestrator import Orchestrator
        from druppie.repositories import (
            ExecutionRepository, ProjectRepository, QuestionRepository, SessionRepository,
        )

        session_repo = SessionRepository(self._db)
        execution_repo = ExecutionRepository(self._db)
        project_repo = ProjectRepository(self._db)
        question_repo = QuestionRepository(self._db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
        )

        if not self._real_agents:
            session_id = await orchestrator.process_message(
                message=message, user_id=self._user_id, session_id=session_id,
            )
            session_id = await self._handle_pause_loop(
                orchestrator, session_id, question_repo, execution_repo, session_repo
            )
            return session_id

        async def _bounded_execute(session_id):
            while True:
                session_repo.db.expire_all()
                session = session_repo.get_by_id(session_id)
                if session and session.status == SessionStatus.PAUSED.value:
                    return

                next_run = execution_repo.get_next_pending(session_id)
                if not next_run:
                    session_repo.update_status(session_id, SessionStatus.COMPLETED)
                    session_repo.commit()
                    return

                if next_run.agent_id not in self._real_agents:
                    if self._all_real_agents_done(session_id, execution_repo):
                        self._cancel_remaining_runs(session_id, execution_repo, session_repo)
                        return

                context = orchestrator._build_project_context(session_id)
                execution_repo.update_status(next_run.id, AgentRunStatus.RUNNING)
                execution_repo.commit()

                status = await orchestrator._run_agent(
                    session_id=session_id,
                    agent_run_id=next_run.id,
                    agent_id=next_run.agent_id,
                    prompt=next_run.planned_prompt or "",
                    context=context,
                )

                if status == "paused":
                    refreshed = execution_repo.get_by_id(next_run.id)
                    if refreshed and refreshed.status == AgentRunStatus.PAUSED_HITL:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                    elif refreshed and refreshed.status == AgentRunStatus.PAUSED_SANDBOX:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                    else:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                    session_repo.commit()
                    return

        orchestrator.execute_pending_runs = _bounded_execute

        if session_id:
            # Continue existing session: create agent runs directly
            # instead of going through process_message (which creates router+planner)
            result_session_id = session_id

            # Reset session to active
            session_repo.update_status(session_id, SessionStatus.ACTIVE)
            session_repo.commit()

            # Add user message
            from druppie.db.models import Message
            from druppie.db.models.base import utcnow
            next_seq = execution_repo.get_next_sequence_number(session_id)
            self._db.add(Message(
                session_id=session_id,
                role="user",
                content=message,
                sequence_number=next_seq,
                created_at=utcnow(),
            ))
            self._db.flush()

            # Build context from the session's project
            context = orchestrator._build_project_context(session_id)

            # Get the last done summary for prompt context
            completed_runs = execution_repo.get_completed_runs(session_id)
            previous_summary = ""
            for run in completed_runs:
                s = execution_repo.get_done_summary_for_run(run.id)
                if s:
                    previous_summary += s + "\n"

            # Create and run each specified agent directly
            all_agents_completed = True
            for i, agent_id in enumerate(self._real_agents):
                prompt = f"PREVIOUS AGENT SUMMARY:\n{previous_summary}\n---\n\nUSER REQUEST:\n{message}"

                agent_run = execution_repo.create_agent_run(
                    session_id=session_id,
                    agent_id=agent_id,
                    status=AgentRunStatus.PENDING,
                    planned_prompt=prompt,
                    sequence_number=next_seq + 1 + i,
                )
                execution_repo.commit()

                execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
                execution_repo.commit()

                status = await orchestrator._run_agent(
                    session_id=session_id,
                    agent_run_id=agent_run.id,
                    agent_id=agent_id,
                    prompt=prompt,
                    context=context,
                )

                if status == "paused":
                    refreshed = execution_repo.get_by_id(agent_run.id)
                    if refreshed and refreshed.status == AgentRunStatus.PAUSED_HITL:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                    elif refreshed and refreshed.status == AgentRunStatus.PAUSED_SANDBOX:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                    else:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                    session_repo.commit()

                    # Handle pauses (HITL + approvals)
                    result_session_id = await self._handle_pause_loop(
                        orchestrator, session_id, question_repo, execution_repo, session_repo
                    )

                    # Check if pause loop broke early (no simulator, non-real agent question)
                    self._db.expire_all()
                    session = session_repo.get_by_id(session_id)
                    if session and session.status in (
                        SessionStatus.PAUSED_HITL.value,
                        SessionStatus.PAUSED_APPROVAL.value,
                        SessionStatus.PAUSED_SANDBOX.value,
                    ):
                        all_agents_completed = False
                        logger.warning(
                            "Session still paused after pause loop, skipping remaining agents: session=%s status=%s",
                            session_id, session.status,
                        )
                        break

                # Update summary for next agent
                run_summary = execution_repo.get_done_summary_for_run(agent_run.id)
                if run_summary:
                    previous_summary += run_summary + "\n"

            # Only mark COMPLETED if all agents actually ran to completion
            if all_agents_completed:
                session_repo.update_status(session_id, SessionStatus.COMPLETED)
                session_repo.commit()
        else:
            # New session: use normal process_message flow
            result_session_id = await orchestrator.process_message(
                message=message, user_id=self._user_id,
            )
            result_session_id = await self._handle_pause_loop(
                orchestrator, result_session_id, question_repo, execution_repo, session_repo
            )

            if self._all_real_agents_done(result_session_id, execution_repo):
                self._cancel_remaining_runs(result_session_id, execution_repo, session_repo)

        return result_session_id

    async def _handle_pause_loop(self, orchestrator, session_id, question_repo,
                                 execution_repo, session_repo) -> UUID:
        """Handle HITL questions and approval gates during agent execution.

        Loops until the session is no longer paused (completed, failed, or
        all real agents done).
        """
        from druppie.db.models import Session as DBSession
        from druppie.db.models import Approval
        from druppie.db.models.base import utcnow

        for iteration in range(MAX_HITL_INTERACTIONS * 2):
            self._db.expire_all()
            session = self._db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session:
                break

            status = session.status
            logger.info("Pause loop iteration %d: session status=%s", iteration, status)

            if self._real_agents and self._all_real_agents_done(session_id, execution_repo):
                break

            # Handle HITL pause
            if status == SessionStatus.PAUSED_HITL.value:
                if not self._hitl_simulator:
                    logger.warning("No HITL simulator — cannot answer questions")
                    break

                pending_question = (
                    self._db.query(Question)
                    .filter(Question.session_id == session_id, Question.status == "pending")
                    .order_by(Question.created_at.desc())
                    .first()
                )
                if not pending_question:
                    break

                if self._real_agents and pending_question.agent_run_id:
                    agent_run = self._db.query(AgentRun).filter(
                        AgentRun.id == pending_question.agent_run_id
                    ).first()
                    if agent_run and agent_run.agent_id not in self._real_agents:
                        break

                raw_answer = self._hitl_simulator.answer(
                    question_text=pending_question.question,
                    choices=pending_question.choices,
                )

                answer = raw_answer
                if pending_question.choices and pending_question.question_type in (
                    "single_choice", "multiple_choice",
                ):
                    answer, _ = self._resolve_choice_answer(raw_answer, pending_question.choices)

                logger.info("HITL auto-answer (iteration %d): answer=%s", iteration, answer[:80])
                await orchestrator.resume_after_answer(
                    session_id=session_id,
                    question_id=pending_question.id,
                    answer=answer,
                )
                continue

            # Handle approval pause
            if status == SessionStatus.PAUSED_APPROVAL.value:
                pending_approval = (
                    self._db.query(Approval)
                    .filter(Approval.session_id == session_id, Approval.status == "pending")
                    .order_by(Approval.created_at.desc())
                    .first()
                )
                if not pending_approval:
                    break

                # Auto-approve with the test user
                pending_approval.status = "approved"
                pending_approval.resolved_by = session.user_id
                pending_approval.resolved_at = utcnow()
                self._db.commit()

                logger.info("Approval auto-approved (iteration %d): tool=%s:%s",
                            iteration, pending_approval.mcp_server, pending_approval.tool_name)
                await orchestrator.resume_after_approval(
                    session_id=session_id,
                    approval_id=pending_approval.id,
                )
                continue

            # Not paused — done
            break

        return session_id

    @staticmethod
    def _resolve_choice_answer(raw_answer: str, choices: list[dict]) -> tuple[str, list[int] | None]:
        text = raw_answer.strip().rstrip(".")
        choice_texts = []
        for c in choices:
            ct = c.get("text", str(c)) if isinstance(c, dict) else str(c)
            choice_texts.append(ct)

        text_lower = text.lower()

        # 1. Exact match (case-insensitive)
        for idx, ct in enumerate(choice_texts):
            if ct.lower() == text_lower:
                return ct, [idx]

        # 2. Partial match — only if exactly one choice matches
        partial_matches = []
        for idx, ct in enumerate(choice_texts):
            if ct.lower() in text_lower or text_lower in ct.lower():
                partial_matches.append((idx, ct))
        if len(partial_matches) == 1:
            idx, ct = partial_matches[0]
            return ct, [idx]
        elif len(partial_matches) > 1:
            logger.warning(
                "Ambiguous choice match: answer=%r matched %d choices: %s",
                text, len(partial_matches), [ct for _, ct in partial_matches],
            )

        # 3. Numeric index
        try:
            choice_num = int(text)
        except ValueError:
            return raw_answer, None

        idx = choice_num - 1
        if 0 <= idx < len(choices):
            return choice_texts[idx], [idx]
        return raw_answer, None
