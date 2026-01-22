"""Built-in Human-in-the-Loop (HITL) tools for agents.

These tools are built into the agent runtime and do not require a separate MCP server.
They save questions directly to the database and pause agent execution.

Tools:
- ask_question: Free-form text question
- ask_multiple_choice_question: Multiple choice with optional "Other" option

The workflow is:
1. Agent calls ask_question() or ask_multiple_choice_question()
2. Question is saved to database with status="pending"
3. WebSocket event is emitted to frontend
4. Agent returns paused state
5. User answers via frontend -> API updates question -> workflow resumes
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from druppie.core.execution_context import ExecutionContext

logger = structlog.get_logger()


# Tool definitions in OpenAI function format
HITL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "hitl_ask_question",
            "description": "Ask the user a free-form text question. Use this when you need clarification or input from the user. The workflow will pause until the user responds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hitl_ask_multiple_choice_question",
            "description": "Ask the user a multiple choice question. Use this when you want the user to select from predefined options. Can optionally allow a custom 'Other' answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of choices for the user to select from",
                    },
                    "allow_other": {
                        "type": "boolean",
                        "description": "Whether to allow a custom 'Other' answer (default: true)",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked",
                    },
                },
                "required": ["question", "choices"],
            },
        },
    },
]


async def ask_question(
    question: str,
    context: "ExecutionContext",
    agent_id: str,
    question_context: str | None = None,
) -> dict:
    """Ask the user a free-form text question.

    This saves the question to the database and returns a paused state.
    The workflow will resume when the user answers.

    Args:
        question: The question to ask
        context: Execution context with session info
        agent_id: ID of the agent asking the question
        question_context: Optional context about why the question is being asked

    Returns:
        Dict with paused status and question_id
    """
    from druppie.api.deps import get_db
    from druppie.db.crud import create_hitl_question

    question_id = str(uuid.uuid4())
    session_id = context.session_id

    logger.info(
        "hitl_ask_question",
        question_id=question_id,
        session_id=session_id,
        agent_id=agent_id,
        question=question[:100] + "..." if len(question) > 100 else question,
    )

    # Save question to database
    db = next(get_db())
    try:
        hitl_question = create_hitl_question(
            db=db,
            question_id=question_id,
            session_id=session_id,
            agent_id=agent_id,
            question=question,
            question_type="text",
            choices=None,
        )
        db.commit()

        logger.info(
            "hitl_question_created",
            question_id=question_id,
            session_id=session_id,
        )
    finally:
        db.close()

    # Emit event to frontend via WebSocket
    # Note: frontend expects 'request_id' and 'input_type' for backwards compatibility
    if context.emit_event:
        context.emit_event({
            "type": "question",
            "event_type": "question",
            "request_id": question_id,  # Frontend expects request_id
            "question_id": question_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "question": question,
            "input_type": "text",  # Frontend expects input_type
            "question_type": "text",
            "choices": None,
            "context": question_context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Also add to workflow events for persistence
    context.emit("question_asked", {
        "question_id": question_id,
        "agent_id": agent_id,
        "question": question,
        "question_type": "text",
    })

    # Return paused state
    return {
        "status": "paused",
        "reason": "waiting_for_answer",
        "question_id": question_id,
        "question": question,
        "question_type": "text",
    }


async def ask_multiple_choice_question(
    question: str,
    choices: list[str],
    context: "ExecutionContext",
    agent_id: str,
    allow_other: bool = True,
    question_context: str | None = None,
) -> dict:
    """Ask the user a multiple choice question.

    This saves the question to the database and returns a paused state.
    The workflow will resume when the user answers.

    Args:
        question: The question to ask
        choices: List of choices for the user to select from
        context: Execution context with session info
        agent_id: ID of the agent asking the question
        allow_other: Whether to allow a custom 'Other' answer
        question_context: Optional context about why the question is being asked

    Returns:
        Dict with paused status and question_id
    """
    from druppie.api.deps import get_db
    from druppie.db.crud import create_hitl_question

    question_id = str(uuid.uuid4())
    session_id = context.session_id

    logger.info(
        "hitl_ask_multiple_choice_question",
        question_id=question_id,
        session_id=session_id,
        agent_id=agent_id,
        question=question[:100] + "..." if len(question) > 100 else question,
        choices_count=len(choices),
        allow_other=allow_other,
    )

    # Include allow_other in choices metadata
    choices_data = {
        "options": choices,
        "allow_other": allow_other,
    }

    # Save question to database
    db = next(get_db())
    try:
        hitl_question = create_hitl_question(
            db=db,
            question_id=question_id,
            session_id=session_id,
            agent_id=agent_id,
            question=question,
            question_type="choice",
            choices=choices_data,
        )
        db.commit()

        logger.info(
            "hitl_choice_question_created",
            question_id=question_id,
            session_id=session_id,
        )
    finally:
        db.close()

    # Emit event to frontend via WebSocket
    # Note: frontend expects 'request_id' and 'input_type' for backwards compatibility
    if context.emit_event:
        context.emit_event({
            "type": "question",
            "event_type": "question",
            "request_id": question_id,  # Frontend expects request_id
            "question_id": question_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "question": question,
            "input_type": "choice",  # Frontend expects input_type
            "question_type": "choice",
            "choices": choices,
            "allow_other": allow_other,
            "context": question_context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Also add to workflow events for persistence
    context.emit("question_asked", {
        "question_id": question_id,
        "agent_id": agent_id,
        "question": question,
        "question_type": "choice",
        "choices": choices,
        "allow_other": allow_other,
    })

    # Return paused state
    return {
        "status": "paused",
        "reason": "waiting_for_answer",
        "question_id": question_id,
        "question": question,
        "question_type": "choice",
        "choices": choices,
        "allow_other": allow_other,
    }


async def execute_hitl_tool(
    tool_name: str,
    tool_args: dict,
    context: "ExecutionContext",
    agent_id: str,
) -> dict:
    """Execute a built-in HITL tool.

    Args:
        tool_name: Tool name (hitl_ask_question or hitl_ask_multiple_choice_question)
        tool_args: Tool arguments
        context: Execution context
        agent_id: ID of the calling agent

    Returns:
        Tool result (paused state with question_id)
    """
    if tool_name == "hitl_ask_question":
        return await ask_question(
            question=tool_args.get("question", ""),
            context=context,
            agent_id=agent_id,
            question_context=tool_args.get("context"),
        )
    elif tool_name == "hitl_ask_multiple_choice_question":
        return await ask_multiple_choice_question(
            question=tool_args.get("question", ""),
            choices=tool_args.get("choices", []),
            context=context,
            agent_id=agent_id,
            allow_other=tool_args.get("allow_other", True),
            question_context=tool_args.get("context"),
        )
    else:
        return {
            "success": False,
            "error": f"Unknown HITL tool: {tool_name}",
        }


def is_hitl_tool(tool_name: str) -> bool:
    """Check if a tool name is a built-in HITL tool."""
    return tool_name in ("hitl_ask_question", "hitl_ask_multiple_choice_question")
