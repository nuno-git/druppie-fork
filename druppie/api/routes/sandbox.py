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
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, Request
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


async def _cleanup_gitea_users(sandbox_mapping: SandboxSessionModel, context: str = "") -> None:
    """Clean up per-sandbox Gitea service accounts (primary + context).

    GitHub tokens expire automatically — git_user_id is None for GitHub sandboxes.
    """
    for uid_attr in ("git_user_id", "context_git_user_id"):
        uid = getattr(sandbox_mapping, uid_attr)
        if uid:
            try:
                from druppie.opencode.gitea_credentials import delete_sandbox_git_user
                await delete_sandbox_git_user(uid)
            except Exception as e:
                logger.warning(f"sandbox_{context}gitea_cleanup_failed", attr=uid_attr, error=str(e))

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
    limit: int = Query(500, ge=1, le=2000),
    cursor: str | None = Query(None),
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
    if cursor:
        url += f"&cursor={cursor}"

    token = generate_control_plane_token(SANDBOX_API_SECRET)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # If control plane returned events, use them
            if data.get("events"):
                return data
            # If control plane returned empty but we have a persisted snapshot, use that
            if mapping.events_snapshot:
                return {"events": json.loads(mapping.events_snapshot), "hasMore": False, "source": "snapshot"}
            return data
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        # Control plane unavailable — fall back to persisted snapshot
        logger.warning("sandbox_events_proxy_error", session_id=session_id, error=str(e))
        if mapping.events_snapshot:
            return {"events": json.loads(mapping.events_snapshot), "hasMore": False, "source": "snapshot"}
        raise HTTPException(status_code=502, detail="Sandbox events unavailable")


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
        tool_lower = tool.lower()
        if tool_lower in ("write", "write_file", "batch_write_files", "edit") and path and path not in seen_paths:
            seen_paths.add(path)
            files.append({"path": path, "action": tool_lower})
    return files


def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> reasoning blocks from model output.

    Some models (Qwen3, DeepSeek R1) emit chain-of-thought reasoning
    inside <think> tags. This is useful for the model but should not
    leak into agent results or user-facing output.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_agent_output(events: list[dict]) -> str:
    """Extract agent text output from token events, sorted chronologically.

    Falls back to conversation_history assistant messages if token events
    are empty after stripping think tags (common with Qwen3/DeepSeek R1
    models that wrap everything in <think> blocks).
    """
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
    raw = "\n".join(c for _, c in parts).strip()
    result = _strip_think_tags(raw)

    # If stripping think tags left nothing, extract from conversation_history.
    # This covers models that emit only <think> blocks (Qwen3, DeepSeek R1)
    # where the useful output is in tool results within the conversation.
    if not result:
        result = _extract_output_from_conversation_history(events)

    return result


def _extract_output_from_conversation_history(events: list[dict]) -> str:
    """Extract assistant text and tool results from conversation_history event.

    Used as fallback when token events contain only think-tagged content.
    """
    for event in events:
        if event.get("type") != "conversation_history":
            continue
        data = event.get("data") or {}
        messages = data.get("messages", [])
        output_parts = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for part in msg.get("parts", []):
                if part.get("type") == "text":
                    text = _strip_think_tags(part.get("text", ""))
                    if text:
                        output_parts.append(text)
                elif part.get("type") == "tool":
                    state = part.get("state", {})
                    tool_name = part.get("tool", "unknown")
                    status = state.get("status", "")
                    # Include tool output/error for context
                    if status == "error":
                        error = state.get("error", "")
                        if error:
                            output_parts.append(f"[{tool_name} error]: {error}")
                    elif status == "completed":
                        output = state.get("output", "")
                        if output:
                            # Cap individual tool output at 5000 chars
                            truncated = output[:5000] if len(output) > 5000 else output
                            output_parts.append(f"[{tool_name} output]: {truncated}")
        if output_parts:
            return "\n\n".join(output_parts)
    return ""


def _extract_git_operations(events: list[dict]) -> dict:
    """Extract git-related info from sandbox events: commits, PRs, branches."""
    commits = []
    pr_urls = []
    branches = []
    for event in events:
        if event.get("type") != "tool_call":
            continue
        data = event.get("data", {})
        tool = (data.get("tool") or "").lower()
        result = data.get("result", {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = {}

        # Extract commit info
        if tool in ("run_git", "git") and isinstance(result, dict):
            output = result.get("output", "") or result.get("stdout", "") or ""
            args = data.get("args", {})
            command = args.get("command", "") or args.get("args", "")
            if "commit" in str(command) and output:
                commits.append(output.strip()[:200])
            if "branch" in str(command) and output:
                for line in output.strip().split("\n"):
                    line = line.strip().lstrip("* ")
                    if line and line not in branches:
                        branches.append(line)

        # Extract PR info
        if tool in ("create_pull_request", "create_pr"):
            if isinstance(result, dict):
                pr_url = result.get("url") or result.get("pr_url") or result.get("html_url") or ""
                if pr_url:
                    pr_urls.append(pr_url)
                pr_number = result.get("number") or result.get("pr_number")
                if pr_number and not pr_url:
                    pr_urls.append(f"PR #{pr_number}")

    return {
        "commits": commits[-5:],  # Last 5 commits
        "pr_urls": pr_urls,
        "branches": branches[-3:],  # Last 3 branches
    }


def _extract_tool_results_summary(events: list[dict]) -> list[str]:
    """Extract a summary of key tool calls and their results."""
    summaries = []
    for event in events:
        if event.get("type") != "tool_call":
            continue
        data = event.get("data", {})
        tool = data.get("tool") or ""
        args = data.get("args", {})
        result = data.get("result", {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                pass

        # Summarize important operations
        tool_lower = tool.lower()
        if tool_lower in ("write", "write_file"):
            path = args.get("filePath") or args.get("path") or "?"
            summaries.append(f"Wrote file: {path}")
        elif tool_lower == "edit":
            path = args.get("filePath") or args.get("path") or "?"
            summaries.append(f"Edited file: {path}")
        elif tool_lower in ("run_git", "git"):
            command = args.get("command") or args.get("args") or ""
            if isinstance(command, list):
                command = " ".join(command)
            summaries.append(f"Git: {command[:100]}")
        elif tool_lower in ("create_pull_request", "create_pr"):
            if isinstance(result, dict):
                pr_url = result.get("url") or result.get("pr_url") or result.get("html_url") or ""
                title = result.get("title") or args.get("title") or ""
                summaries.append(f"Created PR: {title} ({pr_url})")
        elif tool_lower == "bash":
            command = args.get("command") or ""
            summaries.append(f"Ran: {command[:100]}")

    return summaries


def _extract_cache_packages(events: list[dict]) -> list[dict]:
    """Extract package list from cache_summary event in sandbox events."""
    for event in events:
        if event.get("type") == "cache_summary":
            packages = event.get("packages") or event.get("data", {}).get("packages")
            if packages and isinstance(packages, list):
                return packages
    return []


def _diagnose_sandbox_failure(
    events: list[dict],
    sandbox_agent: str | None,
) -> str:
    """Inspect sandbox events to produce a clear failure diagnosis.

    The control plane emits richer signals than the bare `success: false` on
    the webhook payload. This walks the event list looking for the most
    actionable failure cause and turns it into a one-block message the
    calling Druppie agent can act on (retry / pick a different sandbox
    agent / surface to the user).
    """
    error_messages: list[str] = []
    llm_provider_errors: dict[str, int] = {}  # provider -> count

    for event in events or []:
        etype = event.get("type")
        # Explicit sandbox_error events carry the most useful context
        if etype == "sandbox_error":
            err = event.get("error") or (event.get("data") or {}).get("error") or ""
            if err and err not in error_messages:
                error_messages.append(str(err))
        elif etype == "error":
            data = event.get("data") or {}
            msg = data.get("message") or data.get("error") or event.get("message") or ""
            if msg and msg not in error_messages:
                error_messages.append(str(msg))
        elif etype in ("llm_error", "provider_error"):
            data = event.get("data") or {}
            provider = data.get("provider") or "unknown"
            llm_provider_errors[provider] = llm_provider_errors.get(provider, 0) + 1

    parts: list[str] = []
    agent_label = sandbox_agent or "(unknown sandbox agent)"
    parts.append(f"Sandbox subagent: {agent_label}")

    if error_messages:
        parts.append("Failure cause(s):")
        for m in error_messages[:5]:
            parts.append(f"  - {m}")

    if llm_provider_errors:
        details = ", ".join(f"{p}: {n} error(s)" for p, n in llm_provider_errors.items())
        parts.append(f"LLM provider failures observed during the run: {details}")
        parts.append(
            "  → Often a transient rate-limit or upstream outage. Consider "
            "waiting and retrying, or routing to a different model."
        )

    if not error_messages and not llm_provider_errors:
        parts.append(
            "No explicit error event was emitted by the control plane. The "
            "sandbox container likely crashed, ran out of resources, or its "
            "primary agent terminated without producing output. Check the "
            "sandbox session events for raw logs."
        )

    return "\n".join(parts)


def _build_agent_result_text(
    success: bool,
    changed_files: list[dict],
    agent_output: str,
    git_info: dict,
    tool_summaries: list[str],
    events: list[dict] | None = None,
    sandbox_agent: str | None = None,
) -> str:
    """Build a structured, human-readable result for the Druppie agent.

    This replaces the raw JSON blob with clear text the LLM can understand.
    On failure, leads with a diagnosis of WHY the sandbox failed (which
    sandbox subagent ran, what the control plane reported, what the LLM
    proxy saw) so the calling agent doesn't just see "SANDBOX TASK FAILED".
    """
    lines = []

    if success:
        lines.append("SANDBOX TASK COMPLETED SUCCESSFULLY")
    else:
        lines.append("SANDBOX TASK FAILED")
        # Lead with diagnosis — the calling agent needs to know which
        # subagent ran and why it died before it can decide what to do next.
        lines.append("")
        lines.append(_diagnose_sandbox_failure(events or [], sandbox_agent))

    # PR info (most important for the agent)
    if git_info.get("pr_urls"):
        lines.append("")
        lines.append("Pull Requests created:")
        for url in git_info["pr_urls"]:
            lines.append(f"  - {url}")

    # Changed files
    if changed_files:
        lines.append("")
        lines.append(f"Files changed ({len(changed_files)}):")
        for f in changed_files[:20]:  # Cap at 20
            lines.append(f"  - {f['action']}: {f['path']}")
        if len(changed_files) > 20:
            lines.append(f"  ... and {len(changed_files) - 20} more files")

    # Git commits
    if git_info.get("commits"):
        lines.append("")
        lines.append("Git commits:")
        for c in git_info["commits"]:
            lines.append(f"  - {c}")

    # Tool operations summary
    if tool_summaries:
        lines.append("")
        lines.append(f"Operations performed ({len(tool_summaries)}):")
        # Show last 30 operations (most relevant)
        for s in tool_summaries[-30:]:
            lines.append(f"  - {s}")
        if len(tool_summaries) > 30:
            lines.append(f"  ... and {len(tool_summaries) - 30} earlier operations")

    # Agent reasoning/output (last 10000 chars instead of 5000)
    if agent_output:
        lines.append("")
        lines.append("Agent output (summary):")
        truncated = agent_output[-10000:] if len(agent_output) > 10000 else agent_output
        if len(agent_output) > 10000:
            lines.append(f"  [... truncated {len(agent_output) - 10000} chars ...]")
        lines.append(truncated)

    return "\n".join(lines)



@router.post("/sandbox-sessions/{sandbox_session_id}/complete")
async def sandbox_complete_webhook(
    sandbox_session_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook called by the control plane when a sandbox session completes.

    Verifies HMAC signature, fetches final events, extracts results,
    completes the tool call, and resumes the paused agent.

    Idempotent: returns 200 OK if the tool call was already processed.
    """
    # Read body and check signature header BEFORE any DB access to minimize
    # unauthenticated attack surface. All auth failures return 403 with a
    # generic message to prevent timing oracle on session existence.
    raw_body = await request.body()
    signature = request.headers.get("X-Signature")
    if not signature:
        logger.warning("sandbox_webhook_missing_signature", sandbox_session_id=sandbox_session_id)
        raise HTTPException(status_code=403, detail="Forbidden")

    # Look up sandbox session to get the per-session webhook secret
    sandbox_repo = SandboxSessionRepository(db)
    sandbox_mapping = sandbox_repo.get_by_sandbox_id(sandbox_session_id)
    if not sandbox_mapping or not sandbox_mapping.webhook_secret:
        logger.warning(
            "sandbox_webhook_no_session_or_secret",
            sandbox_session_id=sandbox_session_id,
            has_mapping=sandbox_mapping is not None,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    # Verify HMAC signature using the per-session secret
    if not _verify_webhook_signature(raw_body, signature, sandbox_mapping.webhook_secret):
        logger.warning("sandbox_webhook_invalid_signature", sandbox_session_id=sandbox_session_id)
        raise HTTPException(status_code=403, detail="Forbidden")

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

    # Refresh sandbox_mapping inside the FOR UPDATE critical section to get
    # the latest completed_at value (prevents stale read from initial load).
    db.refresh(sandbox_mapping)

    # Fetch final events from control plane
    control_plane_url = os.environ.get(
        "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
    ).rstrip("/")
    changed_files = []
    agent_output = ""
    git_info: dict = {}
    tool_summaries: list[str] = []
    event_count = 0
    events: list[dict] = []

    try:
        token = generate_control_plane_token(SANDBOX_API_SECRET)
        async with httpx.AsyncClient(timeout=30.0) as client:
            events_resp = await client.get(
                f"{control_plane_url}/sessions/{sandbox_session_id}/events?limit=2000",
                headers={"Authorization": f"Bearer {token}"},
            )
            if events_resp.status_code == 200:
                events_data = events_resp.json()
                events = events_data.get("events", [])
                event_count = len(events)
                changed_files = _extract_changed_files(events)
                agent_output = _extract_agent_output(events)
                git_info = _extract_git_operations(events)
                tool_summaries = _extract_tool_results_summary(events)
    except Exception as e:
        logger.warning("sandbox_webhook_event_fetch_failed", error=str(e))

    # Guard against duplicate webhooks for same sandbox session
    if sandbox_mapping.completed_at is not None:
        logger.info("sandbox_webhook_already_completed", sandbox_session_id=sandbox_session_id)
        return {"status": "already_processed", "sandbox_session_id": sandbox_session_id}

    # Mark the sandbox session as completed (proxy key lifecycle managed by control plane)
    sandbox_repo.mark_completed(sandbox_session_id)

    # Clean up the per-sandbox Gitea service accounts
    await _cleanup_gitea_users(sandbox_mapping)

    # Build structured result text for the agent (readable by LLM).
    # On failure we also pass `events` and `sandbox_agent` so the diagnosis
    # block can tell the calling agent which subagent ran and why it died.
    agent_result_text = _build_agent_result_text(
        success=body.success,
        changed_files=changed_files,
        agent_output=agent_output,
        git_info=git_info,
        tool_summaries=tool_summaries,
        events=events,
        sandbox_agent=sandbox_mapping.agent_name if sandbox_mapping else None,
    )

    # Also store structured data for the frontend/API
    result = {
        "success": body.success,
        "sandbox_session_id": sandbox_session_id,
        "status": "completed" if body.success else "failed",
        "event_count": event_count,
        "changed_files": changed_files,
        "git_info": git_info,
        "tool_summaries": tool_summaries[-50:],
        "agent_result_text": agent_result_text,
    }

    # Complete the tool call — use the readable text as the result so the
    # agent sees a clear summary, not a raw JSON blob
    execution_repo.update_tool_call(
        tool_call.id,
        status=ToolCallStatus.COMPLETED if body.success else ToolCallStatus.FAILED,
        result=agent_result_text,
    )

    # Persist events snapshot to sandbox_session so they survive control plane
    # restarts and remain visible in the frontend details view
    try:
        sandbox_mapping.events_snapshot = json.dumps(events[-500:])  # Last 500 events
        sandbox_mapping.result_summary = json.dumps(result)
        db.add(sandbox_mapping)
    except Exception as e:
        logger.warning("sandbox_events_persist_failed", error=str(e))

    # Store discovered package dependencies linked to the project
    try:
        cache_packages = _extract_cache_packages(events)
        if cache_packages and sandbox_mapping.session_id:
            from druppie.db.models.session import Session as SessionModel
            session = db.query(SessionModel).filter_by(id=sandbox_mapping.session_id).first()
            if session and session.project_id:
                from druppie.repositories import ProjectDependencyRepository
                dep_repo = ProjectDependencyRepository(db)
                count = dep_repo.upsert_packages(session.project_id, cache_packages)
                if count:
                    logger.info(
                        "project_dependencies_stored",
                        project_id=str(session.project_id),
                        package_count=count,
                    )
    except Exception as e:
        logger.warning("project_dependencies_store_failed", error=str(e))

    db.commit()

    logger.info(
        "sandbox_webhook_tool_call_completed",
        sandbox_session_id=sandbox_session_id,
        tool_call_id=str(tool_call.id),
        success=body.success,
        event_count=event_count,
        changed_files=len(changed_files),
        pr_urls=git_info.get("pr_urls", []),
    )

    # Resume the agent via create_session_task for proper lifecycle management:
    # - Tracked by shutdown_background_tasks (survives hot-reload gracefully)
    # - Session-level concurrency guard prevents duplicate resume tasks
    from druppie.core.background_tasks import create_session_task, run_session_task, SessionTaskConflict

    druppie_session_id = tool_call.session_id
    tc_id = tool_call.id
    try:
        create_session_task(
            druppie_session_id,
            run_session_task(druppie_session_id, _make_sandbox_resume(tc_id), "sandbox-resume"),
            name=f"sandbox-resume-{druppie_session_id}",
        )
    except SessionTaskConflict:
        logger.warning(
            "sandbox_resume_task_conflict",
            sandbox_session_id=sandbox_session_id,
            session_id=str(druppie_session_id),
        )

    return {"status": "ok", "sandbox_session_id": sandbox_session_id}


def _make_sandbox_resume(tool_call_id: UUID):
    """Build the resume coroutine function for run_session_task.

    Includes an idempotency guard: only resumes if the agent run is still
    in PAUSED_SANDBOX state, preventing duplicate resume attempts from
    concurrent webhook deliveries.
    """
    from druppie.domain.common import AgentRunStatus

    async def _resume(ctx) -> None:
        # Idempotency guard: check if the agent run is still paused for sandbox
        tool_call = ctx.execution_repo.get_tool_call(tool_call_id)
        if not tool_call or not tool_call.agent_run_id:
            logger.warning("sandbox_resume_no_tool_call_or_agent", tool_call_id=str(tool_call_id))
            return

        agent_run = ctx.execution_repo.get_by_id(tool_call.agent_run_id)
        if not agent_run:
            logger.warning("sandbox_resume_no_agent_run", tool_call_id=str(tool_call_id))
            return

        if agent_run.status != AgentRunStatus.PAUSED_SANDBOX:
            logger.info(
                "sandbox_resume_skipped_not_paused",
                tool_call_id=str(tool_call_id),
                agent_run_id=str(agent_run.id),
                current_status=agent_run.status,
            )
            return

        await ctx.orchestrator.resume_after_sandbox(tool_call_id)

    return _resume


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
                    sandbox_mapping = sandbox_repo.get_by_tool_call_id(tc.id)

                    # Fail the stuck tool call with a diagnostic message
                    # that names the subagent, so the calling agent can decide
                    # whether to retry or switch approaches.
                    subagent = sandbox_mapping.agent_name if sandbox_mapping else "(unknown)"
                    execution_repo.update_tool_call(
                        tc.id,
                        status=ToolCallStatus.FAILED,
                        error=(
                            f"SANDBOX TASK FAILED\n\n"
                            f"Sandbox subagent: {subagent}\n"
                            f"Failure cause(s):\n"
                            f"  - No webhook received from the sandbox control plane "
                            f"within {SANDBOX_TIMEOUT_MINUTES} minutes.\n"
                            f"  → The sandbox container is likely stuck on upstream "
                            f"calls (LLM provider unresponsive, network partition) or "
                            f"crashed without emitting a completion event. Consider "
                            f"retrying later, or routing the task through a different "
                            f"approach that doesn't need a sandbox."
                        ),
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
                        await _cleanup_gitea_users(sandbox_mapping, context="watchdog_")
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
