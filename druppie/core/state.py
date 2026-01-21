"""State management for Druppie sessions.

Handles persistence and recovery of execution state.
"""

import json
from datetime import datetime
from typing import Any

import structlog

from .models import (
    ApprovalRequest,
    ExecutionState,
    ExecutionStatus,
    Plan,
    QuestionRequest,
)

logger = structlog.get_logger()


class StateManager:
    """Manages execution state for sessions.

    State can be persisted to database for recovery after restarts.
    """

    def __init__(self, db_session=None):
        """Initialize state manager.

        Args:
            db_session: Optional SQLAlchemy session for persistence
        """
        self._db = db_session
        self._states: dict[str, ExecutionState] = {}

    def get_state(self, session_id: str) -> ExecutionState | None:
        """Get execution state for a session."""
        # Try memory cache first
        if session_id in self._states:
            return self._states[session_id]

        # Try database if available
        if self._db:
            from druppie.db.crud import get_session_state

            state_dict = get_session_state(self._db, session_id)
            if state_dict:
                state = ExecutionState.model_validate(state_dict)
                self._states[session_id] = state
                return state

        return None

    def create_state(self, session_id: str, plan: Plan) -> ExecutionState:
        """Create new execution state for a session."""
        state = ExecutionState(
            plan=plan,
            current_index=0,
            status=ExecutionStatus.RUNNING,
            context={},
        )
        self._states[session_id] = state

        # Persist if database available
        if self._db:
            from druppie.db.crud import save_session_state

            save_session_state(self._db, session_id, state.model_dump())

        logger.info("state_created", session_id=session_id, plan_id=plan.id)
        return state

    def update_state(self, session_id: str, state: ExecutionState) -> None:
        """Update execution state."""
        self._states[session_id] = state

        # Persist if database available
        if self._db:
            from druppie.db.crud import save_session_state

            save_session_state(self._db, session_id, state.model_dump())

        logger.debug(
            "state_updated",
            session_id=session_id,
            status=state.status.value,
            current_index=state.current_index,
        )

    def pause_for_question(
        self,
        session_id: str,
        question: str,
        options: list[str] | None = None,
        agent_id: str | None = None,
    ) -> QuestionRequest:
        """Pause execution to ask user a question."""
        state = self.get_state(session_id)
        if not state:
            raise ValueError(f"No state found for session {session_id}")

        question_request = QuestionRequest(
            id=f"q_{session_id}_{datetime.utcnow().timestamp()}",
            session_id=session_id,
            question=question,
            options=options or [],
            agent_id=agent_id,
        )

        state.status = ExecutionStatus.PAUSED
        state.pending_question = question_request
        self.update_state(session_id, state)

        logger.info(
            "state_paused_for_question",
            session_id=session_id,
            question=question[:100],
        )
        return question_request

    def pause_for_approval(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        required_roles: list[str] | None = None,
        danger_level: str = "medium",
    ) -> ApprovalRequest:
        """Pause execution for approval."""
        state = self.get_state(session_id)
        if not state:
            raise ValueError(f"No state found for session {session_id}")

        approval_request = ApprovalRequest(
            id=f"a_{session_id}_{datetime.utcnow().timestamp()}",
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            required_roles=required_roles or [],
            danger_level=danger_level,
        )

        state.status = ExecutionStatus.PAUSED
        state.pending_approval = approval_request
        self.update_state(session_id, state)

        # Also persist approval to database
        if self._db:
            from druppie.db.crud import create_approval

            create_approval(self._db, approval_request.model_dump())

        logger.info(
            "state_paused_for_approval",
            session_id=session_id,
            tool=tool_name,
            danger_level=danger_level,
        )
        return approval_request

    def resume_with_answer(self, session_id: str, answer: str) -> ExecutionState:
        """Resume execution after user answered a question."""
        state = self.get_state(session_id)
        if not state:
            raise ValueError(f"No state found for session {session_id}")

        if not state.pending_question:
            raise ValueError("No pending question to answer")

        state.pending_question.response = answer
        state.pending_question.responded_at = datetime.utcnow()

        # Store answer in context for the agent
        state.context["user_answer"] = answer

        state.status = ExecutionStatus.RUNNING
        state.pending_question = None
        self.update_state(session_id, state)

        logger.info(
            "state_resumed_with_answer",
            session_id=session_id,
            answer=answer[:100] if answer else None,
        )
        return state

    def resume_with_approval(
        self,
        session_id: str,
        approved: bool,
        user_id: str,
        user_role: str,
    ) -> ExecutionState:
        """Resume execution after approval decision."""
        state = self.get_state(session_id)
        if not state:
            raise ValueError(f"No state found for session {session_id}")

        if not state.pending_approval:
            raise ValueError("No pending approval")

        if approved:
            state.pending_approval.approvals_received.append({
                "user_id": user_id,
                "role": user_role,
                "timestamp": datetime.utcnow().isoformat(),
            })
            state.pending_approval.status = "approved"
            state.status = ExecutionStatus.RUNNING
        else:
            state.pending_approval.status = "rejected"
            state.status = ExecutionStatus.FAILED
            state.error = f"Approval rejected by {user_id}"

        # Update database
        if self._db:
            from druppie.db.crud import update_approval

            update_approval(
                self._db,
                state.pending_approval.id,
                state.pending_approval.model_dump(),
            )

        state.pending_approval = None
        self.update_state(session_id, state)

        logger.info(
            "state_resumed_with_approval",
            session_id=session_id,
            approved=approved,
            user_id=user_id,
        )
        return state

    def complete(self, session_id: str, results: list[dict[str, Any]]) -> None:
        """Mark execution as completed."""
        state = self.get_state(session_id)
        if not state:
            return

        state.status = ExecutionStatus.COMPLETED
        state.results = results
        self.update_state(session_id, state)

        logger.info("state_completed", session_id=session_id)

    def fail(self, session_id: str, error: str) -> None:
        """Mark execution as failed."""
        state = self.get_state(session_id)
        if not state:
            return

        state.status = ExecutionStatus.FAILED
        state.error = error
        self.update_state(session_id, state)

        logger.error("state_failed", session_id=session_id, error=error)

    def delete_state(self, session_id: str) -> None:
        """Delete state for a session."""
        if session_id in self._states:
            del self._states[session_id]

        if self._db:
            from druppie.db.crud import delete_session_state

            delete_session_state(self._db, session_id)

        logger.info("state_deleted", session_id=session_id)
