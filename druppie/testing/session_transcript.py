"""Chronological transcript of a session for the HITL simulator.

Compiles agent runs, tool calls, HITL Q&A, and approvals into a single
text summary so the simulator can answer follow-up questions and make
approval decisions with full context of what the agent has done so far.
"""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Approval, Question, ToolCall


MAX_FIELD_CHARS = 4000


def _truncate(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    if value is None:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit] + f"... [truncated, {len(value) - limit} chars omitted]"


def _format_args(args) -> str:
    if not args:
        return "{}"
    try:
        return _truncate(json.dumps(args, ensure_ascii=False, indent=2))
    except Exception:
        return _truncate(str(args))


def build_transcript(db: DbSession, session_id: UUID, exclude_question_id: UUID | None = None,
                     exclude_approval_id: UUID | None = None) -> str:
    """Return a chronological transcript string for the session.

    Includes every tool call with its arguments and result, every HITL
    question with its answer, and every approval with its outcome. Events
    are ordered by `created_at`.

    `exclude_question_id` / `exclude_approval_id` let the caller omit the
    *current* pending question/approval from the transcript so the simulator
    sees prior context without the question it is about to answer.
    """
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session_id)
        .order_by(AgentRun.created_at.asc())
        .all()
    )
    tool_calls = (
        db.query(ToolCall)
        .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
        .filter(AgentRun.session_id == session_id)
        .order_by(ToolCall.created_at.asc())
        .all()
    )
    questions = (
        db.query(Question)
        .filter(Question.session_id == session_id)
        .order_by(Question.created_at.asc())
        .all()
    )
    approvals = (
        db.query(Approval)
        .filter(Approval.session_id == session_id)
        .order_by(Approval.created_at.asc())
        .all()
    )

    # Index for fast lookup
    questions_by_tc = {q.tool_call_id: q for q in questions if q.tool_call_id}
    approvals_by_tc = {a.tool_call_id: a for a in approvals if a.tool_call_id}
    run_agent_by_id = {r.id: r.agent_id for r in runs}

    lines: list[str] = []
    for tc in tool_calls:
        agent_id = run_agent_by_id.get(tc.agent_run_id, "?")
        header = f"[{agent_id}] {tc.mcp_server or 'builtin'}:{tc.tool_name}"

        # HITL question path
        q = questions_by_tc.get(tc.id)
        if q is not None:
            if exclude_question_id is not None and q.id == exclude_question_id:
                continue
            lines.append(f"{header} (HITL question)")
            if isinstance(tc.arguments, dict) and tc.arguments.get("context"):
                lines.append(f"  context: {_truncate(str(tc.arguments['context']))}")
            lines.append(f"  question: {_truncate(q.question)}")
            if q.choices:
                for i, c in enumerate(q.choices):
                    text = c.get("text", c) if isinstance(c, dict) else str(c)
                    lines.append(f"    {i + 1}. {text}")
            if q.status == "answered":
                lines.append(f"  answer: {_truncate(q.answer or '')}")
            else:
                lines.append("  answer: (still pending)")
            lines.append("")
            continue

        # Approval-gated tool call
        approval = approvals_by_tc.get(tc.id)
        if approval is not None and (exclude_approval_id is None or approval.id != exclude_approval_id):
            lines.append(f"{header} (approval-gated, role={approval.required_role})")
            lines.append(f"  arguments: {_format_args(tc.arguments)}")
            if approval.status == "pending":
                lines.append("  approval: (still pending)")
            elif approval.status == "rejected":
                reason = getattr(approval, "rejection_reason", None) or "(no reason given)"
                lines.append(f"  approval: REJECTED — reason: {_truncate(str(reason))}")
            else:
                lines.append(f"  approval: {approval.status.upper()}")
            lines.append("")
            continue

        # Plain tool call
        lines.append(header)
        if tc.arguments:
            lines.append(f"  arguments: {_format_args(tc.arguments)}")
        if tc.result:
            lines.append(f"  result: {_truncate(tc.result)}")
        if tc.status and tc.status not in ("completed", "pending"):
            lines.append(f"  status: {tc.status}")
        lines.append("")

    if not lines:
        return "(no prior agent activity in this session yet)"
    return "\n".join(lines).rstrip()
