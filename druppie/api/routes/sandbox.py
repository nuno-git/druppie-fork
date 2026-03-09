"""Sandbox API routes.

Proxy to the sandbox control plane, ownership registration, and webhook receiver.

Endpoints:
- POST /sandbox-sessions/internal/register - Register sandbox session ownership (internal)
- GET /sandbox-sessions/{session_id}/events - Fetch events for a sandbox session (frontend)
- POST /sandbox-sessions/{sandbox_session_id}/complete - Webhook from control plane on completion

Also provides a sandbox watchdog that detects stuck sandbox tool calls.
"""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
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
from druppie.core.sandbox_auth import generate_control_plane_token, SANDBOX_API_SECRET
from druppie.db.database import get_db
from druppie.db.models.sandbox_session import SandboxSession as SandboxSessionModel
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

    url = f"{base_url}/sessions/{session_id}/events?limit={limit}"
    if message_id:
        url += f"&message_id={message_id}"

    token = generate_control_plane_token(SANDBOX_API_SECRET)

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
    """Webhook payload from control plane on sandbox completion.
    
    Note: 'success' is required (no default) to ensure malformed payloads
    fail validation rather than silently succeeding.
    """
    sessionId: str
    messageId: str = ""
    success: bool  # Required - no default to prevent silent success on malformed payloads
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


async def _retry_sandbox_with_next_model(
    sandbox_mapping: SandboxSessionModel,
    tool_call_id: UUID,
    db: Session,
) -> bool:
    """Attempt to retry the sandbox with the next model in the chain.

    Creates a new sandbox session on the control plane with the next model,
    registers ownership, and sends the prompt. Returns True if retry was
    initiated, False if no more models to try.
    """
    from druppie.sandbox.model_resolver import PROVIDER_API_KEYS, get_raw_model_chains

    if not sandbox_mapping.model_chain or not sandbox_mapping.task_prompt:
        return False

    chain = json.loads(sandbox_mapping.model_chain)
    next_index = (sandbox_mapping.model_chain_index or 0) + 1

    if next_index >= len(chain):
        logger.info(
            "sandbox_retry_chain_exhausted",
            sandbox_session_id=sandbox_mapping.sandbox_session_id,
            tried_models=next_index,
            chain_length=len(chain),
        )
        return False

    next_entry = chain[next_index]
    next_model = next_entry["model"]
    next_provider = next_entry["provider"]

    # Check if the next provider's API key is available
    env_var = PROVIDER_API_KEYS.get(next_provider)
    if not env_var or not os.getenv(env_var):
        logger.warning(
            "sandbox_retry_provider_unavailable",
            provider=next_provider,
            model=next_model,
        )
        # Skip to the next entry in chain
        sandbox_mapping.model_chain_index = next_index
        db.flush()
        return await _retry_sandbox_with_next_model(sandbox_mapping, tool_call_id, db)

    logger.info(
        "sandbox_retry_with_next_model",
        sandbox_session_id=sandbox_mapping.sandbox_session_id,
        next_model=next_model,
        next_provider=next_provider,
        chain_index=next_index,
    )

    # Create a new sandbox session with the next model
    control_plane_url = os.environ.get(
        "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
    ).rstrip("/")

    from druppie.core.sandbox_auth import generate_control_plane_token as _gen_token

    webhook_secret = secrets.token_urlsafe(32)

    _provider_base_urls = {
        "zai": os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas"),
        "deepseek": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        # NOTE: /v1 not /v1/openai — the sandbox LLM proxy appends its own path segments
        "deepinfra": os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1"),
        "openai": "https://api.openai.com",
        "anthropic": "https://api.anthropic.com",
    }

    llm_credentials = []
    for prov_name, api_key_env_var in PROVIDER_API_KEYS.items():
        api_key = os.getenv(api_key_env_var, "")
        if api_key:
            llm_credentials.append({
                "provider": prov_name,
                "apiKey": api_key,
                "baseUrl": _provider_base_urls.get(prov_name, ""),
            })

    from druppie.agents.builtin_tools import _load_agent_files
    from druppie.sandbox.model_resolver import resolve_sandbox_models

    agent = sandbox_mapping.agent_name or "druppie-builder"
    model_config = resolve_sandbox_models(agent)

    create_body = {
        "repoOwner": os.getenv("GITEA_ORG", "druppie"),
        "repoName": "unknown",
        "model": next_model,
        "agentModels": model_config.agents,
        "agentFiles": _load_agent_files(),
        "modelChains": get_raw_model_chains(),
        "title": f"Druppie sandbox (retry {next_index}): {sandbox_mapping.task_prompt[:80]}",
        "credentials": {
            "git": {
                "provider": "gitea",
                "url": os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000"),
                "username": os.getenv("GITEA_ADMIN_USER", "gitea_admin"),
                "password": os.getenv("GITEA_ADMIN_PASSWORD", ""),
            },
            "llm": llm_credentials,
        },
    }

    # Get repo info from the original session
    if sandbox_mapping.session_id:
        from druppie.repositories import SessionRepository, ProjectRepository
        session_repo = SessionRepository(db)
        session = session_repo.get_by_id(sandbox_mapping.session_id)
        if session and session.project_id:
            project_repo = ProjectRepository(db)
            project = project_repo.get_by_id(session.project_id)
            if project:
                create_body["repoOwner"] = project.repo_owner or os.getenv("GITEA_ORG", "druppie")
                create_body["repoName"] = project.repo_name or ""

    try:
        auth_token = _gen_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_headers = {
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            }

            resp = await client.post(
                f"{control_plane_url}/sessions",
                json=create_body,
                headers=auth_headers,
            )

            if resp.status_code not in (200, 201):
                logger.error(
                    "sandbox_retry_create_failed",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return False

            new_session_id = resp.json().get("sessionId")
            if not new_session_id:
                return False

            # Register new ownership record
            sandbox_repo = SandboxSessionRepository(db)
            sandbox_repo.create(
                sandbox_session_id=new_session_id,
                user_id=sandbox_mapping.user_id,
                session_id=sandbox_mapping.session_id,
                webhook_secret=webhook_secret,
                model_chain=sandbox_mapping.model_chain,
                model_chain_index=next_index,
                task_prompt=sandbox_mapping.task_prompt,
                agent_name=agent,
            )

            # Link to the same tool call
            sandbox_repo.update_tool_call_id(new_session_id, tool_call_id)
            db.flush()

            # Send the prompt to the new sandbox
            prompt_resp = await client.post(
                f"{control_plane_url}/sessions/{new_session_id}/prompt",
                json={
                    "content": sandbox_mapping.task_prompt,
                    "authorId": str(sandbox_mapping.user_id),
                    "source": "retry",
                    "callbackContext": {
                        "callbackUrl": f"{os.environ.get('BACKEND_URL', 'http://druppie-backend:8000')}/api/sandbox-sessions/{new_session_id}/complete",
                        "callbackSecret": webhook_secret,
                    },
                },
                headers=auth_headers,
            )

            if prompt_resp.status_code not in (200, 201):
                logger.error(
                    "sandbox_retry_prompt_failed",
                    status=prompt_resp.status_code,
                )
                return False

            logger.info(
                "sandbox_retry_initiated",
                old_sandbox=sandbox_mapping.sandbox_session_id,
                new_sandbox=new_session_id,
                model=next_model,
                chain_index=next_index,
            )
            return True

    except Exception as e:
        logger.error("sandbox_retry_error", error=str(e))
        return False


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
    signature = request.headers.get("X-Signature")
    # Explicit check for missing signature header - don't default to empty string
    if not signature:
        logger.warning("sandbox_webhook_missing_signature", sandbox_session_id=sandbox_session_id)
        raise HTTPException(status_code=403, detail="Missing signature header")
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

    try:
        token = generate_control_plane_token(SANDBOX_API_SECRET)
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

    # Guard against duplicate webhooks for same sandbox session
    if sandbox_mapping.completed_at is not None:
        logger.info("sandbox_webhook_already_completed", sandbox_session_id=sandbox_session_id)
        return {"status": "already_processed", "sandbox_session_id": sandbox_session_id}

    # Mark the sandbox session as completed (proxy key lifecycle managed by control plane)
    sandbox_repo.mark_completed(sandbox_session_id)

    # On failure, attempt retry with next model in chain
    if not body.success:
        retry_initiated = await _retry_sandbox_with_next_model(
            sandbox_mapping, sandbox_mapping.tool_call_id, db
        )
        if retry_initiated:
            logger.info(
                "sandbox_webhook_retry_initiated",
                sandbox_session_id=sandbox_session_id,
                tool_call_id=str(sandbox_mapping.tool_call_id),
            )
            # Don't complete the tool call — keep it in WAITING_SANDBOX state
            # The new sandbox will fire its own webhook when done
            db.commit()
            return {"status": "retrying", "sandbox_session_id": sandbox_session_id}

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
    
    Idempotency: Checks that the agent run is still in PAUSED_SANDBOX state
    before resuming, to prevent duplicate resume attempts.
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
        # Idempotency guard: check if the agent run is still paused for sandbox
        execution_repo = ExecutionRepository(resume_db)
        tool_call = execution_repo.get_tool_call(tool_call_id)
        if not tool_call or not tool_call.agent_run_id:
            logger.warning("sandbox_resume_no_tool_call_or_agent", tool_call_id=str(tool_call_id))
            return
            
        agent_run = execution_repo.get_by_id(tool_call.agent_run_id)
        if not agent_run:
            logger.warning("sandbox_resume_no_agent_run", tool_call_id=str(tool_call_id))
            return
            
        # Only resume if still in PAUSED_SANDBOX - prevents duplicate resume attempts
        if agent_run.status != AgentRunStatus.PAUSED_SANDBOX:
            logger.info(
                "sandbox_resume_skipped_not_paused",
                tool_call_id=str(tool_call_id),
                agent_run_id=str(agent_run.id),
                current_status=agent_run.status,
            )
            return
        
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
                # Fix: Also handle PAUSED_SANDBOX state in case error occurred before status change
                if agent_run and agent_run.status in (AgentRunStatus.RUNNING, AgentRunStatus.PAUSED_SANDBOX):
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
                    # Try retry with next model before failing
                    sandbox_mapping = sandbox_repo.get_by_tool_call_id(tc.id)
                    if sandbox_mapping:
                        retry_initiated = await _retry_sandbox_with_next_model(
                            sandbox_mapping, tc.id, db
                        )
                        if retry_initiated:
                            # Mark old sandbox as completed but keep tool call waiting
                            sandbox_repo.mark_completed(sandbox_mapping.sandbox_session_id)
                            # Reset sandbox_waiting_at so watchdog doesn't re-trigger immediately
                            execution_repo.update_tool_call(
                                tc.id,
                                sandbox_waiting_at=datetime.now(timezone.utc),
                            )
                            db.commit()
                            logger.info(
                                "sandbox_watchdog_retry_initiated",
                                tool_call_id=str(tc.id),
                                old_sandbox=sandbox_mapping.sandbox_session_id,
                            )
                            # Best-effort cancel old sandbox
                            try:
                                control_plane_url = os.environ.get(
                                    "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
                                ).rstrip("/")
                                token = generate_control_plane_token(SANDBOX_API_SECRET)
                                async with httpx.AsyncClient(timeout=10.0) as client:
                                    await client.delete(
                                        f"{control_plane_url}/sessions/{sandbox_mapping.sandbox_session_id}",
                                        headers={"Authorization": f"Bearer {token}"},
                                    )
                            except Exception:
                                pass
                            continue  # Don't fail the tool call

                    # No retry possible — fail as before
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

                    # Mark completed and cancel the sandbox container
                    if sandbox_mapping:
                        sandbox_repo.mark_completed(sandbox_mapping.sandbox_session_id)
                        try:
                            control_plane_url = os.environ.get(
                                "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
                            ).rstrip("/")
                            token = generate_control_plane_token(SANDBOX_API_SECRET)
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
