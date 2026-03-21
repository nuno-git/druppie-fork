"""Context extraction for evaluation rubrics.

Extracts data from the DB (tool calls, messages, agent definitions)
and formats it as strings for use in rubric prompt templates.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Message, ToolCall
from druppie.testing.eval_schema import ContextSource


def extract_context(
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    sources: list[ContextSource],
) -> dict[str, str]:
    """Extract context values from DB based on source directives.

    Returns a dict mapping template variable names to string values.
    """
    result = {}
    for source in sources:
        extractor = _EXTRACTORS.get(source.source)
        if extractor is None:
            raise ValueError(f"Unknown context source: {source.source}")
        result[source.as_name] = extractor(
            db=db,
            agent_run_id=agent_run_id,
            session_id=session_id,
            agent_id=agent_id,
            source=source,
        )
    return result


# ---------------------------------------------------------------------------
# Private extractors
# ---------------------------------------------------------------------------


def _extract_all_tool_calls(
    *,
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    source: ContextSource,
) -> str:
    """Query ToolCall by agent_run_id, format as indexed list."""
    tool_calls = (
        db.query(ToolCall)
        .filter(ToolCall.agent_run_id == agent_run_id)
        .order_by(ToolCall.tool_call_index)
        .all()
    )
    lines = []
    for tc in tool_calls:
        idx = tc.tool_call_index
        server = tc.mcp_server
        name = tc.tool_name
        args_str = json.dumps(tc.arguments) if tc.arguments else "{}"
        status = tc.status or "pending"
        result_part = ""
        if tc.result:
            result_part = f': "{tc.result}"'
        lines.append(f"[{idx}] {server}:{name}({args_str}) -> {status}{result_part}")
    return "\n".join(lines)


def _extract_session_messages(
    *,
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    source: ContextSource,
) -> str:
    """Query Message by session_id, optionally filter by role."""
    query = db.query(Message).filter(Message.session_id == session_id)
    if source.role:
        query = query.filter(Message.role == source.role)
    messages = query.order_by(Message.sequence_number).all()
    lines = []
    for msg in messages:
        lines.append(f"[{msg.role}] {msg.content}")
    return "\n".join(lines)


def _extract_agent_definition(
    *,
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    source: ContextSource,
) -> str:
    """Load agent YAML definition from disk.

    If source.field is specified, extract just that section.
    Otherwise return the full system_prompt.
    """
    definitions_dir = Path(__file__).resolve().parents[1] / "agents" / "definitions"
    yaml_path = definitions_dir / f"{agent_id}.yaml"

    if not yaml_path.exists():
        return f"<agent definition not found: {agent_id}>"

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    if source.field:
        value = data.get(source.field)
        if value is None:
            return f"<field '{source.field}' not found in {agent_id}.yaml>"
        if isinstance(value, (dict, list)):
            return yaml.dump(value, default_flow_style=False).strip()
        return str(value)

    return data.get("system_prompt", "")


def _extract_tool_call_result(
    *,
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    source: ContextSource,
) -> str:
    """Query ToolCall by agent_run_id matching source.tool, return result."""
    mcp_server, tool_name = _parse_tool_ref(source.tool)
    tc = (
        db.query(ToolCall)
        .filter(
            ToolCall.agent_run_id == agent_run_id,
            ToolCall.mcp_server == mcp_server,
            ToolCall.tool_name == tool_name,
        )
        .first()
    )
    if tc is None:
        return ""
    return tc.result or ""


def _extract_tool_call_arguments(
    *,
    db: DbSession,
    agent_run_id: UUID,
    session_id: UUID,
    agent_id: str,
    source: ContextSource,
) -> str:
    """Query ToolCall by agent_run_id matching source.tool, return formatted arguments."""
    mcp_server, tool_name = _parse_tool_ref(source.tool)
    tc = (
        db.query(ToolCall)
        .filter(
            ToolCall.agent_run_id == agent_run_id,
            ToolCall.mcp_server == mcp_server,
            ToolCall.tool_name == tool_name,
        )
        .first()
    )
    if tc is None:
        return ""
    if tc.arguments:
        return json.dumps(tc.arguments, indent=2)
    return "{}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tool_ref(tool_ref: str | None) -> tuple[str, str]:
    """Split 'mcp_server:tool_name' into (server, name)."""
    if not tool_ref:
        raise ValueError("source.tool is required for tool_call_result/tool_call_arguments")
    parts = tool_ref.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid tool reference '{tool_ref}', expected 'server:name'")
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    "all_tool_calls": _extract_all_tool_calls,
    "session_messages": _extract_session_messages,
    "agent_definition": _extract_agent_definition,
    "tool_call_result": _extract_tool_call_result,
    "tool_call_arguments": _extract_tool_call_arguments,
}
