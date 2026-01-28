"""Workflow service for execution and resumption.

This service wraps the Orchestrator and provides a clean interface for:
- Resuming workflows after HITL questions are answered
- Resuming workflows after approvals/rejections

Architecture:
    Route ──▶ WorkflowService ──▶ Orchestrator
                                     │
                                     ▼
                              (Agent execution)
"""

from uuid import UUID
from typing import Any
import structlog

from ..execution import Orchestrator

logger = structlog.get_logger()


class WorkflowService:
    """Handles workflow execution and resumption.

    This service is the interface between API routes and the Orchestrator.
    It handles:

    1. HITL Question Resumption
       When a user answers a question, the workflow needs to continue
       from where it paused.

    2. Approval Resumption
       When an approval is granted/rejected, the workflow either
       executes the tool and continues, or handles the rejection.

    All resumption methods:
    - Call the appropriate Orchestrator method
    - Return the session ID for the caller to fetch updated state
    """

    def __init__(self, orchestrator: Orchestrator):
        """Initialize with Orchestrator instance.

        Args:
            orchestrator: The execution engine that runs agent workflows
        """
        self.orchestrator = orchestrator

    async def resume_from_question(
        self,
        session_id: UUID,
        question_id: UUID,
        answer: str,
    ) -> dict[str, Any]:
        """Resume workflow after user answers a HITL question.

        When an agent asks a question (via hitl_ask_question tool),
        the workflow pauses. This method resumes it with the user's answer.

        Args:
            session_id: The session containing the paused workflow
            question_id: The question that was answered
            answer: The user's answer text

        Returns:
            Dict with session_id and status
        """
        logger.info(
            "workflow_resuming_from_question",
            session_id=str(session_id),
            question_id=str(question_id),
            answer_preview=answer[:50] if answer else "",
        )

        result_session_id = await self.orchestrator.resume_after_answer(
            session_id=session_id,
            question_id=question_id,
            answer=answer,
        )

        logger.info(
            "workflow_resumed_from_question",
            session_id=str(session_id),
            question_id=str(question_id),
        )

        return {"session_id": str(result_session_id), "status": "resumed"}

    async def resume_from_approval(
        self,
        session_id: UUID,
        approval_id: UUID,
    ) -> dict[str, Any]:
        """Resume workflow after an approval is granted.

        This is called after a tool approval is granted and the tool
        has been executed. The workflow continues with the tool result.

        Args:
            session_id: The session containing the paused workflow
            approval_id: The approval that was granted

        Returns:
            Dict with session_id and status
        """
        logger.info(
            "workflow_resuming_from_approval",
            session_id=str(session_id),
            approval_id=str(approval_id),
        )

        result_session_id = await self.orchestrator.resume_after_approval(
            session_id=session_id,
            approval_id=approval_id,
        )

        logger.info(
            "workflow_resumed_from_approval",
            session_id=str(session_id),
            approval_id=str(approval_id),
        )

        return {"session_id": str(result_session_id), "status": "resumed"}
