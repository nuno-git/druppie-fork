"""Sandbox events API routes.

Thin proxy to the sandbox control plane's events API.
Lets the frontend fetch detailed sandbox session events for observability.

Endpoints:
- POST /sandbox-sessions/internal/register - Register sandbox session ownership (MCP server only)
- GET /sandbox-sessions/{session_id}/events - Fetch events for a sandbox session
"""

import hashlib
import hmac
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
import structlog

from druppie.api.deps import (
    check_resource_ownership,
    get_current_user,
    verify_internal_api_key,
)
from druppie.db.database import get_db
from druppie.repositories import SandboxSessionRepository

logger = structlog.get_logger()

router = APIRouter()


def _generate_internal_token(secret: str) -> str:
    """Generate an HMAC-SHA256 token matching Open-Inspect's auth format.

    Token format: <unix-ms-timestamp>.<hmac-sha256-hex-signature>
    """
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        secret.encode(), timestamp.encode(), hashlib.sha256
    ).hexdigest()
    return f"{timestamp}.{signature}"


class RegisterSandboxSessionRequest(BaseModel):
    sandbox_session_id: str
    user_id: str
    session_id: str | None = None


@router.post("/sandbox-sessions/internal/register")
async def register_sandbox_session(
    body: RegisterSandboxSessionRequest,
    _auth: bool = Depends(verify_internal_api_key),
    db: Session = Depends(get_db),
):
    """Register sandbox session ownership. Called by MCP coding server."""
    repo = SandboxSessionRepository(db)
    session_uuid = UUID(body.session_id) if body.session_id else None
    mapping = repo.create(
        sandbox_session_id=body.sandbox_session_id,
        user_id=UUID(body.user_id),
        session_id=session_uuid,
    )
    db.commit()
    already_existed = mapping.created_at is not None  # always true after flush
    logger.info(
        "sandbox_session_registered",
        sandbox_session_id=body.sandbox_session_id,
        user_id=body.user_id,
    )
    return {"status": "registered", "sandbox_session_id": body.sandbox_session_id}


@router.get("/sandbox-sessions/{session_id}/events")
async def get_sandbox_events(
    session_id: str,
    message_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Proxy sandbox events from the control plane.

    Verifies the requesting user owns the sandbox session before proxying.
    """
    # Ownership check — deny access if no mapping exists
    repo = SandboxSessionRepository(db)
    mapping = repo.get_by_sandbox_id(session_id)
    if not mapping:
        logger.warning("sandbox_session_not_found", session_id=session_id)
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    check_resource_ownership(user, mapping.user_id)

    base_url = os.environ.get("SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787")
    api_secret = os.environ.get("SANDBOX_API_SECRET", "sandbox-dev-secret")

    url = f"{base_url}/sessions/{session_id}/events?limit={limit}"
    if message_id:
        url += f"&message_id={message_id}"

    token = _generate_internal_token(api_secret)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("sandbox_events_proxy_error", session_id=session_id, status=e.response.status_code)
        raise HTTPException(status_code=e.response.status_code, detail="Failed to fetch sandbox events")
    except httpx.RequestError as e:
        logger.warning("sandbox_events_connection_error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=502, detail="Sandbox control plane unavailable")
