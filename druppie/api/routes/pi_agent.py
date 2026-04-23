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

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session as DBSession
import structlog

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
