"""HITL (Human-in-the-Loop) MCP Server.

Provides tools for agent-to-human interaction:
- ask_question: Free-form text input
- ask_choice: Multiple choice with optional "Other" text input

Uses FastMCP framework for HTTP transport.
Persists questions to the backend database via internal API.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("hitl-mcp")

# Initialize FastMCP server
mcp = FastMCP("HITL MCP Server")

# Backend API for persisting questions
BACKEND_URL = os.getenv("BACKEND_URL", "http://druppie-backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-key")

# Request timeout in seconds
REQUEST_TIMEOUT = int(os.getenv("HITL_TIMEOUT", "300"))


def safe_json_parse(data: bytes | str, context: str = "unknown") -> dict | None:
    """Safely parse JSON data with validation and logging.

    Args:
        data: JSON bytes or string to parse
        context: Description of where this data came from (for logging)

    Returns:
        Parsed dict or None if parsing failed
    """
    if data is None:
        logger.warning("Received None data in %s", context)
        return None

    try:
        # Handle bytes
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        parsed = json.loads(data)

        # Validate it's a dict (expected format for all our responses)
        if not isinstance(parsed, dict):
            logger.warning(
                "JSON parsed but not a dict in %s: got %s",
                context,
                type(parsed).__name__,
            )
            return None

        return parsed

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(
            "JSON parse error in %s: %s (data preview: %s)",
            context,
            str(e),
            str(data)[:100] if data else "empty",
        )
        return None
    except Exception as e:
        logger.error(
            "Unexpected error parsing JSON in %s: %s",
            context,
            str(e),
        )
        return None


async def persist_question(
    question_id: str,
    session_id: str,
    question: str,
    question_type: str = "text",
    choices: list[str] | None = None,
    agent_id: str = "unknown",
) -> bool:
    """Persist a HITL question to the backend database.

    This ensures questions survive service restarts and can be
    retrieved by the frontend even if the user refreshes the page.

    Returns True if successful, False otherwise.
    """
    try:
        logger.debug(
            "Persisting question %s for session %s (type: %s)",
            question_id,
            session_id,
            question_type,
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_URL}/api/questions/internal/create",
                json={
                    "question_id": question_id,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "question": question,
                    "question_type": question_type,
                    "choices": choices,
                },
                headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                timeout=10.0,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Successfully persisted question %s for session %s",
                    question_id,
                    session_id,
                )
                return True
            else:
                logger.error(
                    "Failed to persist question %s: HTTP %d - %s",
                    question_id,
                    response.status_code,
                    response.text[:200] if response.text else "no body",
                )
                return False
    except httpx.TimeoutException:
        logger.error(
            "Timeout persisting question %s for session %s",
            question_id,
            session_id,
        )
        return False
    except Exception as e:
        logger.error(
            "Error persisting question %s to backend: %s",
            question_id,
            str(e),
        )
        return False


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def ask_question(
    session_id: str,
    question: str,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a free-form text question.

    Example: "What framework would you like to use?"
    User types their answer in a text box.

    Args:
        session_id: Session ID for routing
        question: The question to ask
        context: Optional context about why this question is needed
        agent_id: ID of the agent asking the question

    Returns:
        Dict with success, answer
    """
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

    # Question is persisted to database; frontend polls for pending questions
    # and submits responses via the backend API
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


@mcp.tool()
async def ask_choice(
    session_id: str,
    question: str,
    choices: list[str],
    allow_other: bool = True,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a multiple choice question with optional free-text "Other".

    Example:
        question: "Which database should we use?"
        choices: ["PostgreSQL", "MySQL", "SQLite"]
        allow_other: True  # Shows "Other: [text input]" option

    User selects one choice OR types custom answer if allow_other=True.

    Args:
        session_id: Session ID for routing
        question: The question to ask
        choices: List of choice options
        allow_other: Whether to show "Other" option with text input
        context: Optional context
        agent_id: ID of the agent asking the question

    Returns:
        Dict with success, selected choice, answer (if "other")
    """
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

    # Question is persisted to database; frontend polls for pending questions
    # and submits responses via the backend API
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


@mcp.tool()
async def submit_response(
    request_id: str,
    answer: str,
    selected: str | None = None,
) -> dict:
    """Submit user response (called by backend API when user answers).

    This is called by the backend when the user submits their answer
    in the frontend. Responses are handled via the backend database.

    Args:
        request_id: The request ID from the question
        answer: User's answer text
        selected: For choice questions, the selected option

    Returns:
        Dict with success
    """
    logger.info(
        "submit_response: request_id=%s, selected=%s, answer_length=%d",
        request_id,
        selected,
        len(answer) if answer else 0,
    )

    return {"success": True}


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "hitl-mcp",
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9003"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
