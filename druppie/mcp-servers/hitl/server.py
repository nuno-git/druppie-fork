"""HITL (Human-in-the-Loop) MCP Server.

Provides tools for agent-to-human interaction:
- ask_question: Free-form text input
- ask_choice: Multiple choice with optional "Other" text input

Uses Redis pub/sub for real-time communication with frontend.
Uses FastMCP framework for HTTP transport.
"""

import json
import os
import uuid
from datetime import datetime

import redis
from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("HITL MCP Server")

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL)

# Request timeout in seconds
REQUEST_TIMEOUT = int(os.getenv("HITL_TIMEOUT", "300"))


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def ask_question(
    session_id: str,
    question: str,
    context: str | None = None,
) -> dict:
    """Ask user a free-form text question.

    Example: "What framework would you like to use?"
    User types their answer in a text box.

    Args:
        session_id: Session ID for routing
        question: The question to ask
        context: Optional context about why this question is needed

    Returns:
        Dict with success, answer
    """
    request_id = str(uuid.uuid4())

    # Publish question to frontend via Redis
    redis_client.publish(
        f"hitl:{session_id}",
        json.dumps({
            "type": "question",
            "request_id": request_id,
            "question": question,
            "input_type": "text",
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        }),
    )

    # Wait for response (blocking)
    response = redis_client.blpop(
        f"hitl:response:{request_id}",
        timeout=REQUEST_TIMEOUT,
    )

    if response:
        data = json.loads(response[1])
        return {
            "success": True,
            "answer": data.get("answer"),
            "request_id": request_id,
        }

    return {
        "success": False,
        "error": "Timeout waiting for response",
        "request_id": request_id,
    }


@mcp.tool()
async def ask_choice(
    session_id: str,
    question: str,
    choices: list[str],
    allow_other: bool = True,
    context: str | None = None,
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

    Returns:
        Dict with success, selected choice, answer (if "other")
    """
    request_id = str(uuid.uuid4())

    # Publish to frontend
    redis_client.publish(
        f"hitl:{session_id}",
        json.dumps({
            "type": "question",
            "request_id": request_id,
            "question": question,
            "input_type": "choice",
            "choices": choices,
            "allow_other": allow_other,
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        }),
    )

    # Wait for response
    response = redis_client.blpop(
        f"hitl:response:{request_id}",
        timeout=REQUEST_TIMEOUT,
    )

    if response:
        data = json.loads(response[1])
        return {
            "success": True,
            "selected": data.get("selected"),  # The choice or "other"
            "answer": data.get("answer"),  # Custom text if "other"
            "request_id": request_id,
        }

    return {
        "success": False,
        "error": "Timeout waiting for response",
        "request_id": request_id,
    }


@mcp.tool()
async def progress(
    session_id: str,
    message: str,
    percent: int | None = None,
    step: str | None = None,
) -> dict:
    """Send progress update to user (non-blocking).

    Args:
        session_id: Session ID
        message: Progress message
        percent: Optional percentage (0-100)
        step: Optional step name

    Returns:
        Dict with success
    """
    # Publish progress event
    redis_client.publish(
        f"hitl:{session_id}",
        json.dumps({
            "type": "progress",
            "message": message,
            "percent": percent,
            "step": step,
            "timestamp": datetime.utcnow().isoformat(),
        }),
    )

    return {"success": True, "acknowledged": True}


@mcp.tool()
async def submit_response(
    request_id: str,
    answer: str,
    selected: str | None = None,
) -> dict:
    """Submit user response (called by backend API when user answers).

    This is called by the backend when the user submits their answer
    in the frontend. It pushes the response to Redis so the blocking
    ask_question/ask_choice call can complete.

    Args:
        request_id: The request ID from the question
        answer: User's answer text
        selected: For choice questions, the selected option

    Returns:
        Dict with success
    """
    redis_client.lpush(
        f"hitl:response:{request_id}",
        json.dumps({
            "answer": answer,
            "selected": selected,
            "timestamp": datetime.utcnow().isoformat(),
        }),
    )

    return {"success": True}


@mcp.tool()
async def notify(
    session_id: str,
    title: str,
    message: str,
    level: str = "info",
) -> dict:
    """Send notification to user (non-blocking).

    Args:
        session_id: Session ID
        title: Notification title
        message: Notification message
        level: Notification level (info, success, warning, error)

    Returns:
        Dict with success
    """
    redis_client.publish(
        f"hitl:{session_id}",
        json.dumps({
            "type": "notification",
            "title": title,
            "message": message,
            "level": level,
            "timestamp": datetime.utcnow().isoformat(),
        }),
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
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

        return JSONResponse({
            "status": "healthy" if redis_ok else "degraded",
            "service": "hitl-mcp",
            "redis": "connected" if redis_ok else "disconnected",
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9003"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
