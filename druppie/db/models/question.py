"""Question database model (HITL questions)."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class Question(Base):
    """A question from an agent to the user (human-in-the-loop).

    Questions allow agents to ask for user input during execution.
    There are three question types:
    - text: Free-form text answer (choices is NULL)
    - single_choice: One option must be selected
    - multiple_choice: Multiple options can be selected

    For choice questions, the `choices` column stores the available options as
    JSONB array: [{"text": "Option A"}, {"text": "Option B"}]

    When answered, `selected_indices` stores which choices were picked: [0, 2]
    The `answer` field contains the text of the answer (for text questions) or
    the selected choice texts joined (for display).
    """

    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id"))  # Links to ToolCall
    agent_id = Column(String(50))  # Direct reference to agent name (router, architect, etc.)

    question = Column(Text, nullable=False)
    question_type = Column(String(20), default="text")  # text, single_choice, multiple_choice

    # Choices for single_choice/multiple_choice questions as JSONB array.
    # Format: [{"text": "Option A"}, {"text": "Option B"}]
    choices = Column(JSON)

    # Which choices were selected (indices into the choices array).
    # Format: [0, 2] means first and third options selected.
    selected_indices = Column(JSON)

    status = Column(String(20), default="pending")  # pending, answered
    answer = Column(Text)  # Text answer or display string of selected choices
    answered_at = Column(DateTime(timezone=True))
    answered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Expert role for ask_expert tool calls.
    # When set, this question is for users with this Keycloak role
    # (instead of the session owner). NULL = regular HITL question.
    expert_role = Column(String(50))

    # Agent state for resumption (messages, iteration, context)
    agent_state = Column(JSON)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    agent_run = relationship("AgentRun", foreign_keys=[agent_run_id])

    def to_dict(self) -> dict[str, Any]:
        # Build choices list with selection state for API compatibility
        choices_with_selection = []
        if self.choices:
            selected = self.selected_indices or []
            for idx, choice in enumerate(self.choices):
                choices_with_selection.append({
                    "choice_index": idx,
                    "choice_text": choice.get("text", ""),
                    "is_selected": idx in selected,
                })

        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "agent_id": self.agent_id,
            "question": self.question,
            "question_type": self.question_type,
            "choices": choices_with_selection,
            "status": self.status,
            "answer": self.answer,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "answered_by": str(self.answered_by) if self.answered_by else None,
            "expert_role": self.expert_role,
            "agent_state": self.agent_state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
