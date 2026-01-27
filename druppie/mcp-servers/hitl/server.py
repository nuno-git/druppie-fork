"""HITL (Human-in-the-Loop) MCP Server.

Provides tools for agent-to-human interaction:
- ask_question: Free-form text input
- ask_choice: Multiple choice with optional "Other" text input

Uses Redis pub/sub for real-time communication with frontend.
Uses FastMCP framework for HTTP transport.
Persists questions to backend database via internal API.
"""

import logging
import os

from fastmcp import FastMCP

from module import HITLModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("hitl-mcp")

mcp = FastMCP("HITL MCP Server")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BACKEND_URL = os.getenv("BACKEND_URL", "http://druppie-backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-key")
REQUEST_TIMEOUT = int(os.getenv("HITL_TIMEOUT", "300"))

module = HITLModule(
    redis_url=REDIS_URL,
    backend_url=BACKEND_URL,
    internal_api_key=INTERNAL_API_KEY,
    request_timeout=REQUEST_TIMEOUT,
)


@mcp.tool()
async def ask_question(
    session_id: str,
    question: str,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a free-form text question."""
    return await module.ask_question(
        session_id=session_id,
        question=question,
        context=context,
        agent_id=agent_id,
    )


@mcp.tool()
async def ask_choice(
    session_id: str,
    question: str,
    choices: list[str],
    allow_other: bool = True,
    context: str | None = None,
    agent_id: str = "unknown",
) -> dict:
    """Ask user a multiple choice question with optional free-text "Other"."""
    return await module.ask_choice(
        session_id=session_id,
        question=question,
        choices=choices,
        allow_other=allow_other,
        context=context,
        agent_id=agent_id,
    )


@mcp.tool()
async def progress(
    session_id: str,
    message: str,
    percent: int | None = None,
    step: str | None = None,
) -> dict:
    """Send progress update to user (non-blocking)."""
    return module.progress(
        session_id=session_id,
        message=message,
        percent=percent,
        step=step,
    )


@mcp.tool()
async def submit_response(
    request_id: str,
    answer: str,
    selected: str | None = None,
) -> dict:
    """Submit user response (called by backend API when user answers)."""
    return module.submit_response(
        request_id=request_id,
        answer=answer,
        selected=selected,
    )


@mcp.tool()
async def notify(
    session_id: str,
    title: str,
    message: str,
    level: str = "info",
) -> dict:
    """Send notification to user (non-blocking)."""
    return module.notify(
        session_id=session_id,
        title=title,
        message=message,
        level=level,
    )


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        health_data = module.health_check()
        return JSONResponse(health_data)

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9003"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
