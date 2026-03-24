"""HITL v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import uuid

from fastmcp import FastMCP

from .hitl_helpers import persist_question

MODULE_ID = "hitl"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "HITL v1",
    version=MODULE_VERSION,
    instructions="""Human-in-the-loop interaction. Ask users questions and wait for responses.

Use when:
- You need user input before proceeding
- A decision requires human judgement
- Presenting multiple options for the user to choose from

Don't use when:
- The answer can be inferred from context
- The question is purely technical and has a clear default
""",
)


@mcp.tool(
    name="ask_question",
    description="Ask user a free-form text question. Example: 'What framework would you like to use?' User types their answer in a text box.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def ask_question(
    session_id: str,
    question: str,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a free-form text question.

    Args:
        session_id: Session ID for routing
        question: The question to ask
        context: Optional context about why this question is needed
        agent_id: ID of the agent asking the question

    Returns:
        Dict with success, request_id, status
    """
    import logging

    logger = logging.getLogger("hitl-mcp")
    request_id = str(uuid.uuid4())

    logger.info(
        "ask_question: session=%s, request_id=%s, agent=%s, question=%s",
        session_id,
        request_id,
        agent_id,
        question[:100] + "..." if len(question) > 100 else question,
    )

    # Persist question to database for durability
    await persist_question(
        question_id=request_id,
        session_id=session_id,
        question=question,
        question_type="text",
        agent_id=agent_id,
    )

    logger.info(
        "Question %s persisted for session %s, awaiting response via backend API",
        request_id,
        session_id,
    )

    return {
        "success": True,
        "request_id": request_id,
        "status": "pending",
    }


@mcp.tool(
    name="ask_choice",
    description="Ask user a multiple choice question with optional free-text 'Other'. User selects one choice or types a custom answer.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def ask_choice(
    session_id: str,
    question: str,
    choices: list[str],
    allow_other: bool = True,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a multiple choice question with optional free-text "Other".

    Args:
        session_id: Session ID for routing
        question: The question to ask
        choices: List of choice options
        allow_other: Whether to show "Other" option with text input
        context: Optional context
        agent_id: ID of the agent asking the question

    Returns:
        Dict with success, request_id, status
    """
    import logging

    logger = logging.getLogger("hitl-mcp")
    request_id = str(uuid.uuid4())

    logger.info(
        "ask_choice: session=%s, request_id=%s, agent=%s, question=%s, choices=%d",
        session_id,
        request_id,
        agent_id,
        question[:100] + "..." if len(question) > 100 else question,
        len(choices),
    )

    # Persist question to database for durability
    await persist_question(
        question_id=request_id,
        session_id=session_id,
        question=question,
        question_type="choice",
        choices=choices,
        agent_id=agent_id,
    )

    logger.info(
        "Choice question %s persisted for session %s, awaiting response via backend API",
        request_id,
        session_id,
    )

    return {
        "success": True,
        "request_id": request_id,
        "status": "pending",
    }


@mcp.tool(
    name="submit_response",
    description="Submit user response (called by backend API when user answers a pending HITL question).",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def submit_response(
    request_id: str,
    answer: str,
    selected: str | None = None,
) -> dict:
    """Submit user response (called by backend API when user answers).

    Args:
        request_id: The request ID from the question
        answer: User's answer text
        selected: For choice questions, the selected option

    Returns:
        Dict with success
    """
    import logging

    logger = logging.getLogger("hitl-mcp")

    logger.info(
        "submit_response: request_id=%s, selected=%s, answer_length=%d",
        request_id,
        selected,
        len(answer) if answer else 0,
    )

    return {"success": True}
