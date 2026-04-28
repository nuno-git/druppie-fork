"""Ingest endpoint for vendored pi_agent journal events.

The Node subprocess in pi_agent/src/journal.ts POSTs every journal event to
/api/pi-agent-runs/{run_id}/events with a per-run bearer token set by the
Python-side PiAgentRunner. We append into PiCodingRun.events (JSON array)
and on run_end also freeze PiCodingRun.summary + status.

This endpoint is server-to-server only — not exposed to end users. The token
is generated per run and never logged.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_user_roles
from druppie.db.database import get_db
from druppie.db.models.pi_coding_run import PiCodingRun

logger = structlog.get_logger()

router = APIRouter(prefix="/pi-agent-runs", tags=["pi_agent"])


_TOKENS: dict[str, str] = {}


def register_ingest_token(run_id: str, token: str) -> None:
    """Called by PiAgentRunner before spawning the child process."""
    _TOKENS[run_id] = token


def revoke_ingest_token(run_id: str) -> None:
    _TOKENS.pop(run_id, None)


def _authorize(run_id: str, authorization: str | None) -> None:
    expected = _TOKENS.get(run_id)
    if not expected or not authorization:
        raise HTTPException(status_code=401, detail="missing or unknown ingest token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != expected:
        raise HTTPException(status_code=401, detail="invalid ingest token")


@router.post("/{run_id}/events")
async def ingest_event(
    run_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    db: DBSession = Depends(get_db),
) -> dict:
    _authorize(run_id, authorization)
    payload = await request.json()

    row: PiCodingRun | None = (
        db.query(PiCodingRun).filter(PiCodingRun.run_id == run_id).one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"pi_coding_run {run_id} not found")

    events: list[dict[str, Any]] = json.loads(row.events) if row.events else []
    if isinstance(payload, list):
        events.extend(payload)
    else:
        events.append(payload)
    row.events = json.dumps(events)

    last = events[-1] if events else {}
    etype = last.get("type")
    if etype == "branch_renamed" and last.get("to"):
        row.branch_name = last["to"]
    elif etype == "pr_ensured":
        row.pr_url = last.get("url") or row.pr_url
        row.pr_number = last.get("number") or row.pr_number
    elif etype == "run_end":
        row.status = "succeeded" if last.get("success") else "failed"
        row.completed_at = datetime.now(timezone.utc)

    db.add(row)
    db.commit()
    return {"ok": True, "event_count": len(events)}


@router.post("/{run_id}/summary")
async def ingest_summary(
    run_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    db: DBSession = Depends(get_db),
) -> dict:
    """Final summary POST from pi_agent at the end of close()."""
    _authorize(run_id, authorization)
    summary = await request.json()

    row: PiCodingRun | None = (
        db.query(PiCodingRun).filter(PiCodingRun.run_id == run_id).one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"pi_coding_run {run_id} not found")

    row.summary = json.dumps(summary)
    if summary.get("pr", {}).get("url"):
        row.pr_url = summary["pr"]["url"]
        row.pr_number = summary["pr"].get("number")
    row.status = "succeeded" if summary.get("success") else "failed"
    row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return {"ok": True}


# ─── User-facing live-view endpoints ──────────────────────────────────────
# Used by the UI to render an execute_coding_task_pi call while it's in
# flight. Auth is JWT (session owner or admin) — distinct from the
# server-to-server ingest endpoints above which use a per-run bearer token.

def _view_payload(row: PiCodingRun, since: int = 0) -> dict:
    """Serialize a PiCodingRun for the live-view UI.

    Events are a JSON array in the column; ``since`` lets the client
    request only events it hasn't seen yet (cheap tail fetch).
    """
    events: list[dict[str, Any]] = json.loads(row.events) if row.events else []
    total = len(events)
    if since < 0:
        since = 0
    tail = events[since:] if since < total else []
    summary = json.loads(row.summary) if row.summary else None
    started = row.created_at
    ended = row.completed_at
    now = datetime.now(timezone.utc)
    elapsed_ms = int(((ended or now) - started).total_seconds() * 1000) if started else 0
    return {
        "run_id": row.run_id,
        "pi_coding_run_id": str(row.id),
        "tool_call_id": str(row.tool_call_id) if row.tool_call_id else None,
        "status": row.status,
        "agent_name": row.agent_name,
        "repo_target": row.repo_target,
        "repo_owner": row.repo_owner,
        "repo_name": row.repo_name,
        "branch_name": row.branch_name,
        "pr_url": row.pr_url,
        "pr_number": row.pr_number,
        "created_at": started.isoformat() if started else None,
        "completed_at": ended.isoformat() if ended else None,
        "elapsed_ms": elapsed_ms,
        "total_events": total,
        "since": since,
        "events": tail,
        "summary": summary,
    }


def _authorize_view(row: PiCodingRun, user: dict) -> None:
    """Session owner or admin may view."""
    user_id = UUID(user["sub"])
    roles = set(get_user_roles(user))
    if "admin" in roles:
        return
    if row.user_id == user_id:
        return
    raise HTTPException(status_code=403, detail="not authorized to view this pi_coding_run")


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    since: int = Query(0, ge=0, description="Return only events with index >= since"),
    db: DBSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    row: PiCodingRun | None = (
        db.query(PiCodingRun).filter(PiCodingRun.run_id == run_id).one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"pi_coding_run {run_id} not found")
    _authorize_view(row, user)
    return _view_payload(row, since=since)


@router.get("/by-tool-call/{tool_call_id}")
async def get_run_by_tool_call(
    tool_call_id: UUID,
    since: int = Query(0, ge=0, description="Return only events with index >= since"),
    db: DBSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Fetch a pi_coding_run by the tool_call that launched it.

    The frontend knows the tool_call id but not the opaque pi run_id when
    the tool call is still executing, so this is the entry point for the
    live view rendered inside the chat timeline.
    """
    row: PiCodingRun | None = (
        db.query(PiCodingRun)
        .filter(PiCodingRun.tool_call_id == tool_call_id)
        .order_by(PiCodingRun.created_at.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no pi_coding_run for tool_call {tool_call_id}")
    _authorize_view(row, user)
    return _view_payload(row, since=since)


@router.post("/{run_id}/stop")
async def stop_run(
    run_id: str,
    db: DBSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Stop a running pi_agent process.

    Only the session owner or admin can stop a run.
    """
    from druppie.agents.pi_agent_runner import stop_run as stop_pi_agent_run

    # Verify the run exists and user has permission
    row: PiCodingRun | None = (
        db.query(PiCodingRun).filter(PiCodingRun.run_id == run_id).one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"pi_coding_run {run_id} not found")

    _authorize_view(row, user)

    # Attempt to stop the process
    result = await stop_pi_agent_run(run_id)

    # Update the database if successful
    if result["success"]:
        row.status = "stopped"
        row.completed_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        logger.info("pi_agent_run_stopped", run_id=run_id, user_id=user["sub"])

    return result


@router.get("/running/list")
async def list_running_runs(
    db: DBSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """List all currently running pi_agent processes.

    Only admins can list all running runs; users can only see their own.
    """
    from druppie.agents.pi_agent_runner import list_running_runs as list_pi_agent_runs

    user_id = UUID(user["sub"])
    roles = set(get_user_roles(user))

    # Get all running processes from the registry
    all_running = list_pi_agent_runs()

    # Filter based on permissions
    if "admin" in roles:
        # Admins can see all
        visible_runs = all_running
    else:
        # Regular users can only see their own runs
        visible_runs = []
        for run_id in all_running:
            row: PiCodingRun | None = (
                db.query(PiCodingRun)
                .filter(PiCodingRun.run_id == run_id, PiCodingRun.user_id == user_id)
                .one_or_none()
            )
            if row:
                visible_runs.append(run_id)

    return {
        "running_runs": visible_runs,
        "total": len(visible_runs),
    }
