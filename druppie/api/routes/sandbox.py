"""Sandbox API routes.

Proxy to the sandbox control plane, ownership registration, and webhook receiver.

Endpoints:
- POST /sandbox-sessions/internal/register - Register sandbox session ownership (internal)
- GET /sandbox-sessions/{session_id}/events - Fetch events for a sandbox session (frontend)
- POST /sandbox-sessions/{sandbox_session_id}/complete - Webhook from control plane on completion

Also provides a sandbox watchdog that detects stuck sandbox tool calls.
"""

import asyncio
import hmac
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
import structlog

from druppie.api.deps import (
    check_resource_ownership,
    get_current_user,
    verify_internal_api_key,
)
from druppie.core.sandbox_auth import generate_control_plane_token
from druppie.db.database import get_db
from druppie.repositories import SandboxSessionRepository

# Watchdog configuration
SANDBOX_TIMEOUT_MINUTES = int(os.getenv("SANDBOX_TIMEOUT_MINUTES", "30"))
SANDBOX_WATCHDOG_INTERVAL_SECONDS = int(os.getenv("SANDBOX_WATCHDOG_INTERVAL_SECONDS", "300"))  # 5 min

logger = structlog.get_logger()

router = APIRouter()


class RegisterSandboxSessionRequest(BaseModel):
    sandbox_session_id: str
    user_id: str
    session_id: str | None = None
    git_proxy_key: str | None = None
    git_provider: str | None = None
    git_repo_owner: str | None = None
    git_repo_name: str | None = None


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
        git_proxy_key=body.git_proxy_key,
        git_provider=body.git_provider,
        git_repo_owner=body.git_repo_owner,
        git_repo_name=body.git_repo_name,
    )
    db.commit()
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

    token = generate_control_plane_token(api_secret)

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


# =============================================================================
# WEBHOOK: Sandbox completion callback from control plane
# =============================================================================


class SandboxCompletePayload(BaseModel):
    """Webhook payload from control plane on sandbox completion."""
    sessionId: str
    messageId: str = ""
    success: bool = True
    timestamp: int = 0


def _verify_webhook_signature(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from control plane webhook."""
    expected = hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _extract_changed_files(events: list[dict]) -> list[dict]:
    """Extract changed files from sandbox events (tool_call events with write operations)."""
    files = []
    seen_paths = set()
    for event in events:
        if event.get("type") != "tool_call":
            continue
        data = event.get("data", {})
        tool = data.get("tool", "")
        args = data.get("args", {})
        path = args.get("filePath") or args.get("path") or ""
        if tool in ("write", "write_file", "batch_write_files") and path and path not in seen_paths:
            seen_paths.add(path)
            files.append({"path": path, "action": tool})
    return files


def _extract_agent_output(events: list[dict]) -> str:
    """Extract agent text output from token events, sorted chronologically."""
    parts = []
    for event in events:
        if event.get("type") == "token":
            content = (event.get("data") or {}).get("content", "")
            if content:
                ts = event.get("createdAt") or event.get("created_at") or ""
                parts.append((ts, content))
        elif event.get("type") == "agent_message":
            content = event.get("content", "")
            if content:
                ts = event.get("createdAt") or event.get("created_at") or ""
                parts.append((ts, content))
    parts.sort(key=lambda x: x[0])
    return "\n".join(c for _, c in parts).strip()


@router.post("/sandbox-sessions/{sandbox_session_id}/complete")
async def sandbox_complete_webhook(
    sandbox_session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Webhook called by the control plane when a sandbox session completes.

    Verifies HMAC signature, fetches final events, extracts results,
    completes the tool call, and resumes the paused agent.

    Idempotent: returns 200 OK if the tool call was already processed.
    """
    # Look up the sandbox session first to get the per-session webhook secret
    sandbox_repo = SandboxSessionRepository(db)
    sandbox_mapping = sandbox_repo.get_by_sandbox_id(sandbox_session_id)
    if not sandbox_mapping or not sandbox_mapping.webhook_secret:
        logger.warning(
            "sandbox_webhook_no_session_or_secret",
            sandbox_session_id=sandbox_session_id,
            has_mapping=sandbox_mapping is not None,
        )
        raise HTTPException(status_code=404, detail="Sandbox session not found or no webhook secret")

    # Verify HMAC signature using the per-session secret
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")
    if not _verify_webhook_signature(raw_body, signature, sandbox_mapping.webhook_secret):
        logger.warning("sandbox_webhook_invalid_signature", sandbox_session_id=sandbox_session_id)
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = SandboxCompletePayload.model_validate_json(raw_body)

    logger.info(
        "sandbox_webhook_received",
        sandbox_session_id=sandbox_session_id,
        success=body.success,
        message_id=body.messageId,
    )

    # Find the tool call for this sandbox session via SandboxSession ownership record
    from druppie.repositories import ExecutionRepository
    from druppie.execution.tool_executor import ToolCallStatus
    if not sandbox_mapping.tool_call_id:
        logger.warning(
            "sandbox_webhook_no_tool_call",
            sandbox_session_id=sandbox_session_id,
        )
        raise HTTPException(status_code=404, detail="No waiting tool call found")

    execution_repo = ExecutionRepository(db)
    # SELECT ... FOR UPDATE: prevents concurrent webhook retries from both
    # reading WAITING_SANDBOX and spawning duplicate resume tasks.
    tool_call = execution_repo.get_tool_call_for_update(sandbox_mapping.tool_call_id)
    if not tool_call:
        logger.warning(
            "sandbox_webhook_tool_call_missing",
            sandbox_session_id=sandbox_session_id,
            tool_call_id=str(sandbox_mapping.tool_call_id),
        )
        raise HTTPException(status_code=404, detail="Tool call not found")

    # Idempotency guard: if tool call is no longer waiting, the webhook was already processed
    if tool_call.status != ToolCallStatus.WAITING_SANDBOX:
        logger.info(
            "sandbox_webhook_already_processed",
            sandbox_session_id=sandbox_session_id,
            tool_call_id=str(tool_call.id),
            current_status=tool_call.status,
        )
        return {"status": "already_processed", "sandbox_session_id": sandbox_session_id}

    # Fetch final events from control plane
    control_plane_url = os.environ.get(
        "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
    ).rstrip("/")
    changed_files = []
    agent_output = ""
    event_count = 0

    api_secret = os.environ.get("SANDBOX_API_SECRET", "sandbox-dev-secret")
    try:
        token = generate_control_plane_token(api_secret)
        async with httpx.AsyncClient(timeout=30.0) as client:
            events_resp = await client.get(
                f"{control_plane_url}/sessions/{sandbox_session_id}/events?limit=500",
                headers={"Authorization": f"Bearer {token}"},
            )
            if events_resp.status_code == 200:
                events_data = events_resp.json()
                events = events_data.get("events", [])
                event_count = len(events)
                changed_files = _extract_changed_files(events)
                agent_output = _extract_agent_output(events)
    except Exception as e:
        logger.warning("sandbox_webhook_event_fetch_failed", error=str(e))

    # Invalidate the git proxy key so the proxy URL stops working
    sandbox_repo.invalidate_proxy_key(sandbox_session_id)

    # Build the final tool result
    result = {
        "success": body.success,
        "sandbox_session_id": sandbox_session_id,
        "status": "completed" if body.success else "failed",
        "event_count": event_count,
        "changed_files": changed_files,
        "agent_output": agent_output[-5000:] if agent_output else "",
    }

    # Complete the tool call
    execution_repo.update_tool_call(
        tool_call.id,
        status=ToolCallStatus.COMPLETED if body.success else ToolCallStatus.FAILED,
        result=result,
    )
    db.commit()

    logger.info(
        "sandbox_webhook_tool_call_completed",
        sandbox_session_id=sandbox_session_id,
        tool_call_id=str(tool_call.id),
        success=body.success,
        event_count=event_count,
        changed_files=len(changed_files),
    )

    # Resume the agent in the background via Starlette BackgroundTasks
    # (properly managed lifecycle — awaited before server shutdown)
    tool_call_id = tool_call.id
    background_tasks.add_task(_resume_agent_after_sandbox, tool_call_id)

    return {"status": "ok", "sandbox_session_id": sandbox_session_id}


async def _resume_agent_after_sandbox(tool_call_id: UUID) -> None:
    """Resume the paused agent after sandbox completion.

    Runs as a Starlette BackgroundTask (proper lifecycle management).
    Creates its own DB session. On failure, reverts statuses so the
    session doesn't get permanently stuck.
    """
    from druppie.execution.orchestrator import Orchestrator
    from druppie.repositories import ExecutionRepository, SessionRepository, ProjectRepository, QuestionRepository
    from druppie.db.database import SessionLocal
    from druppie.domain.common import AgentRunStatus, SessionStatus

    # Fresh DB session: this runs as a background task after the webhook request
    # has completed and its DB session has been closed. The rollback in the
    # except block only affects this session, not the webhook's committed data.
    resume_db = SessionLocal()
    try:
        orchestrator = Orchestrator(
            session_repo=SessionRepository(resume_db),
            execution_repo=ExecutionRepository(resume_db),
            project_repo=ProjectRepository(resume_db),
            question_repo=QuestionRepository(resume_db),
        )
        await orchestrator.resume_after_sandbox(tool_call_id)
    except Exception as e:
        logger.error("sandbox_resume_failed", tool_call_id=str(tool_call_id), error=str(e))
        # Revert statuses so the session doesn't get permanently stuck
        try:
            resume_db.rollback()
            execution_repo = ExecutionRepository(resume_db)
            tool_call = execution_repo.get_tool_call(tool_call_id)
            if tool_call and tool_call.agent_run_id:
                agent_run = execution_repo.get_by_id(tool_call.agent_run_id)
                if agent_run and agent_run.status == AgentRunStatus.RUNNING:
                    execution_repo.update_status(agent_run.id, AgentRunStatus.FAILED, error_message=f"Resume failed: {e}")
                    session_repo = SessionRepository(resume_db)
                    session_repo.update_status(agent_run.session_id, SessionStatus.FAILED)
                    resume_db.commit()
                    logger.info(
                        "sandbox_resume_statuses_reverted",
                        tool_call_id=str(tool_call_id),
                        agent_run_id=str(agent_run.id),
                    )
        except Exception as revert_error:
            logger.error("sandbox_resume_status_revert_failed", error=str(revert_error))
    finally:
        resume_db.close()


# =============================================================================
# WATCHDOG: Detect and fail stuck sandbox sessions
# =============================================================================


async def sandbox_watchdog_loop() -> None:
    """Periodic background task that detects stuck WAITING_SANDBOX tool calls.

    If a sandbox tool call has been waiting longer than SANDBOX_TIMEOUT_MINUTES,
    the watchdog marks it as FAILED and updates the agent run / session statuses
    so the session doesn't stay stuck forever.

    Runs every SANDBOX_WATCHDOG_INTERVAL_SECONDS (default 5 min).
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories import ExecutionRepository, SessionRepository
    from druppie.domain.common import AgentRunStatus, SessionStatus
    from druppie.execution.tool_executor import ToolCallStatus

    logger.info(
        "sandbox_watchdog_started",
        timeout_minutes=SANDBOX_TIMEOUT_MINUTES,
        interval_seconds=SANDBOX_WATCHDOG_INTERVAL_SECONDS,
    )

    while True:
        await asyncio.sleep(SANDBOX_WATCHDOG_INTERVAL_SECONDS)

        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - (SANDBOX_TIMEOUT_MINUTES * 60)
            cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)

            execution_repo = ExecutionRepository(db)
            session_repo = SessionRepository(db)
            sandbox_repo = SandboxSessionRepository(db)

            stuck_tool_calls = execution_repo.get_stuck_sandbox_tool_calls(cutoff_dt)

            if not stuck_tool_calls:
                continue

            logger.warning(
                "sandbox_watchdog_found_stuck",
                count=len(stuck_tool_calls),
                tool_call_ids=[str(tc.id) for tc in stuck_tool_calls],
            )

            for tc in stuck_tool_calls:
                try:
                    execution_repo.update_tool_call(
                        tc.id,
                        status=ToolCallStatus.FAILED,
                        error=f"Sandbox timed out after {SANDBOX_TIMEOUT_MINUTES} minutes (no webhook received)",
                    )

                    if tc.agent_run_id:
                        agent_run = execution_repo.get_by_id(tc.agent_run_id)
                        if agent_run and agent_run.status in (
                            AgentRunStatus.PAUSED_SANDBOX,
                            AgentRunStatus.RUNNING,
                        ):
                            execution_repo.update_status(
                                agent_run.id,
                                AgentRunStatus.FAILED,
                                error_message=f"Sandbox timed out after {SANDBOX_TIMEOUT_MINUTES} min",
                            )
                            session_repo.update_status(
                                agent_run.session_id,
                                SessionStatus.FAILED,
                                error_message=f"Sandbox timed out after {SANDBOX_TIMEOUT_MINUTES} min",
                            )

                    # Invalidate the git proxy key and cancel the sandbox container
                    sandbox_mapping = sandbox_repo.get_by_tool_call_id(tc.id)
                    if sandbox_mapping:
                        sandbox_repo.invalidate_proxy_key(sandbox_mapping.sandbox_session_id)
                        # Best-effort: cancel the sandbox on the control plane to free resources
                        try:
                            control_plane_url = os.environ.get(
                                "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
                            ).rstrip("/")
                            api_secret = os.environ.get("SANDBOX_API_SECRET", "sandbox-dev-secret")
                            token = generate_control_plane_token(api_secret)
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                await client.delete(
                                    f"{control_plane_url}/sessions/{sandbox_mapping.sandbox_session_id}",
                                    headers={"Authorization": f"Bearer {token}"},
                                )
                            logger.info(
                                "sandbox_watchdog_cancelled_sandbox",
                                sandbox_session_id=sandbox_mapping.sandbox_session_id,
                            )
                        except Exception as cancel_err:
                            logger.warning(
                                "sandbox_watchdog_cancel_failed",
                                sandbox_session_id=sandbox_mapping.sandbox_session_id,
                                error=str(cancel_err),
                            )

                    db.commit()
                    logger.warning(
                        "sandbox_watchdog_timed_out_session",
                        tool_call_id=str(tc.id),
                        agent_run_id=str(tc.agent_run_id) if tc.agent_run_id else None,
                        age_minutes=round((datetime.now(timezone.utc) - tc.created_at).total_seconds() / 60, 1),
                    )
                except Exception as e:
                    db.rollback()
                    logger.error(
                        "sandbox_watchdog_failed_to_timeout",
                        tool_call_id=str(tc.id),
                        error=str(e),
                    )

        except Exception as e:
            logger.error("sandbox_watchdog_error", error=str(e))
        finally:
            db.close()
