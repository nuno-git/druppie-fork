"""Workflow service for execution and resumption.

This service wraps the MainLoop and provides a clean interface for:
- Resuming workflows after HITL questions are answered
- Resuming workflows after approvals/rejections
- Resuming from step approval checkpoints

The MainLoop is the actual execution engine (LangGraph-based). This service
provides a simpler, typed interface that routes can use without knowing
the details of how the MainLoop works.

Architecture:
    Route ──▶ WorkflowService ──▶ MainLoop
                                     │
                                     ▼
                              (LangGraph execution)
"""

from uuid import UUID
from typing import Any, Callable, Awaitable
import structlog

from ..core.loop import MainLoop

logger = structlog.get_logger()


# Type alias for the emit_event callback used for WebSocket updates
EmitEventCallback = Callable[[str, dict], Awaitable[None]]


def create_emit_event(session_id: str) -> EmitEventCallback:
    """Create an emit_event callback for WebSocket updates.

    This is imported from chat routes but we define a simple version here
    to avoid circular imports. The actual implementation sends events
    via WebSocket to connected clients.
    """
    from ..api.routes.chat import create_emit_event as _create_emit_event
    return _create_emit_event(session_id)


class WorkflowService:
    """Handles workflow execution and resumption.

    This service is the interface between API routes and the MainLoop
    execution engine. It handles:

    1. HITL Question Resumption
       When a user answers a question, the workflow needs to continue
       from where it paused.

    2. Approval Resumption
       When an approval is granted/rejected, the workflow either
       executes the tool and continues, or handles the rejection.

    3. Step Approval Resumption
       For workflow step checkpoints that require human approval
       before proceeding to the next step.

    All resumption methods:
    - Create WebSocket emit callbacks for real-time updates
    - Call the appropriate MainLoop method
    - Return the execution result
    """

    def __init__(self, main_loop: MainLoop):
        """Initialize with MainLoop instance.

        Args:
            main_loop: The execution engine that runs agent workflows
        """
        self.main_loop = main_loop

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
            Execution result from the MainLoop, typically containing:
            - status: "completed", "paused_approval", "paused_hitl", etc.
            - Any output from the continued execution
        """
        session_id_str = str(session_id)
        question_id_str = str(question_id)

        logger.info(
            "workflow_resuming_from_question",
            session_id=session_id_str,
            question_id=question_id_str,
            answer_preview=answer[:50] if answer else "",
        )

        # Create callback for WebSocket updates during execution
        emit_event = create_emit_event(session_id_str)

        # Resume the workflow via MainLoop
        result = await self.main_loop.resume_from_question_answer(
            session_id=session_id_str,
            question_id=question_id_str,
            answer=answer,
            emit_event=emit_event,
        )

        logger.info(
            "workflow_resumed_from_question",
            session_id=session_id_str,
            question_id=question_id_str,
            result_status=result.get("status") if result else None,
        )

        return result or {}

    async def resume_from_approval(
        self,
        session_id: UUID,
        approval_id: UUID,
    ) -> dict[str, Any]:
        """Resume workflow after an approval (tool already executed).

        This is called after a tool approval is granted and the tool
        has been executed. The workflow continues with the tool result.

        Args:
            session_id: The session containing the paused workflow
            approval_id: The approval that was granted

        Returns:
            Execution result from the MainLoop
        """
        session_id_str = str(session_id)
        approval_id_str = str(approval_id)

        logger.info(
            "workflow_resuming_from_approval",
            session_id=session_id_str,
            approval_id=approval_id_str,
        )

        emit_event = create_emit_event(session_id_str)

        result = await self.main_loop.resume_from_approval(
            session_id=session_id_str,
            approval_id=approval_id_str,
            emit_event=emit_event,
        )

        logger.info(
            "workflow_resumed_from_approval",
            session_id=session_id_str,
            approval_id=approval_id_str,
            result_status=result.get("status") if result else None,
        )

        return result or {}

    async def resume_from_step_approval(
        self,
        session_id: UUID,
        agent_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume workflow from a step approval checkpoint.

        Step approvals are checkpoints in a workflow where human approval
        is required before proceeding. The agent_state contains the saved
        context needed to continue execution.

        Args:
            session_id: The session containing the paused workflow
            agent_state: Saved agent state for resumption (includes
                        current_step, agent_id, messages, etc.)

        Returns:
            Execution result from the MainLoop
        """
        session_id_str = str(session_id)

        logger.info(
            "workflow_resuming_from_step_approval",
            session_id=session_id_str,
            current_step=agent_state.get("current_step"),
            agent_id=agent_state.get("agent_id"),
        )

        emit_event = create_emit_event(session_id_str)

        result = await self.main_loop.resume_from_step_approval(
            session_id=session_id_str,
            agent_state=agent_state,
            emit_event=emit_event,
        )

        logger.info(
            "workflow_resumed_from_step_approval",
            session_id=session_id_str,
            result_status=result.get("status") if result else None,
        )

        return result or {}

    async def resume_session(
        self,
        session_id: UUID,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume a session with a tool response.

        This is a lower-level resumption used when we have a direct
        tool result to feed back into the workflow.

        Args:
            session_id: The session to resume
            response: Tool response to continue with

        Returns:
            Execution result from the MainLoop
        """
        session_id_str = str(session_id)

        logger.info(
            "workflow_resuming_session",
            session_id=session_id_str,
            response_keys=list(response.keys()) if response else [],
        )

        emit_event = create_emit_event(session_id_str)

        result = await self.main_loop.resume_session(
            session_id=session_id_str,
            response=response,
            emit_event=emit_event,
        )

        logger.info(
            "workflow_session_resumed",
            session_id=session_id_str,
            result_status=result.get("status") if result else None,
        )

        return result or {}
