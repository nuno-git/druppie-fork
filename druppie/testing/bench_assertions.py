"""Assertion checks against DB state for benchmark scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.testing.bench_schema import Assertion
from druppie.db.models import AgentRun, ToolCall


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    message: str


def check_assertions(
    db: DbSession,
    session_id: UUID,
    assertions: list[Assertion],
) -> list[AssertionResult]:
    return [_check_one(db, session_id, a) for a in assertions]


def _check_one(db: DbSession, session_id: UUID, assertion: Assertion) -> AssertionResult:
    agent_run = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session_id, AgentRun.agent_id == assertion.agent)
        .order_by(AgentRun.sequence_number.desc())
        .first()
    )

    if agent_run is None:
        return AssertionResult(assertion, False, f"No agent run found for '{assertion.agent}'")

    if assertion.assert_type == "completed":
        return AssertionResult(
            assertion,
            agent_run.status == "completed",
            f"Agent '{assertion.agent}' status: {agent_run.status}",
        )

    if assertion.assert_type == "failed":
        return AssertionResult(
            assertion,
            agent_run.status == "failed",
            f"Agent '{assertion.agent}' status: {agent_run.status}",
        )

    if assertion.assert_type == "tool_called":
        if not assertion.tool:
            return AssertionResult(assertion, False, "tool_called requires 'tool' field")
        server, name = assertion.tool.split(":", 1)
        tc = (
            db.query(ToolCall)
            .filter(
                ToolCall.agent_run_id == agent_run.id,
                ToolCall.mcp_server == server,
                ToolCall.tool_name == name,
            )
            .first()
        )
        if tc is None:
            return AssertionResult(assertion, False, f"Tool {assertion.tool} not found")
        if assertion.summary_contains:
            combined = json.dumps(tc.arguments or {}) + (tc.result or "")
            if assertion.summary_contains not in combined:
                return AssertionResult(
                    assertion,
                    False,
                    f"Tool found but '{assertion.summary_contains}' not in content",
                )
        return AssertionResult(assertion, True, f"Tool {assertion.tool} found")

    return AssertionResult(assertion, False, f"Unknown assertion type: {assertion.assert_type}")
