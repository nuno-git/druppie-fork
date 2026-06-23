"""Live tool output API routes.

Provides on-demand reading of partial bash output from sandbox containers.
The frontend polls this endpoint while a bash tool call is executing.
"""

import asyncio
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user
from druppie.db.database import get_db
from druppie.db.models.tool_call import ToolCall

logger = structlog.get_logger()

router = APIRouter()


@router.get("/tool-calls/{tool_call_id}/live-output")
async def get_tool_call_live_output(
    tool_call_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    tc = db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Tool call not found")

    if tc.status != "executing":
        return {"output": None, "status": tc.status}

    if tc.mcp_server != "coding" or tc.tool_name != "bash":
        return {"output": None, "status": tc.status}

    args = tc.arguments or {}
    git_scope = args.get("git_scope") or "current_project"
    session_id_short = str(tc.session_id)[:12] if tc.session_id else "unknown"
    container_name = f"druppie-{session_id_short}-{git_scope}"

    output_file = f"/tmp/bash_{tool_call_id}.out"
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container_name, "cat", output_file,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except asyncio.TimeoutError:
        return {"output": None, "status": "executing", "error": "timeout"}

    return {
        "output": stdout.decode() if proc.returncode == 0 else None,
        "status": "executing",
        "exists": proc.returncode == 0,
    }
