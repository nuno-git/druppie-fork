"""Assertion matching for v2 tests.

Matches eval assertions against DB state with expected values from tests.
Three matching modes: exact, wildcard (*), any-of list.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, ToolCall
from druppie.testing.v2_schema import EvalAssertion


@dataclass
class AssertionResult:
    name: str
    passed: bool
    message: str


def match_assertions(
    db: DbSession,
    session_id: UUID,
    assertions: list[EvalAssertion],
    expected: dict[str, object],
) -> list[AssertionResult]:
    """Match eval assertions against DB state with expected values from test.

    Each assertion can check:
    - ``completed``: whether the agent completed (True) or failed (False)
    - ``tool_called``: whether a specific tool was called, with optional
      argument matching via *expected*

    Three argument matching modes:
    - Exact: ``expected_value == actual_value``
    - Wildcard: ``expected_value == "*"`` -- just check key exists
    - Any-of list: ``isinstance(expected_value, list) and actual_value in expected_value``
    """
    results = []
    for assertion in assertions:
        if assertion.completed is not None:
            result = _check_completed(db, session_id, assertion)
            results.append(result)
        if assertion.tool_called:
            result = _check_tool_called(db, session_id, assertion, expected)
            results.append(result)
    return results


def _check_completed(
    db: DbSession,
    session_id: UUID,
    assertion: EvalAssertion,
) -> AssertionResult:
    """Check whether an agent completed or failed."""
    agent_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.session_id == session_id,
            AgentRun.agent_id == assertion.agent,
        )
        .order_by(AgentRun.sequence_number.desc())
        .first()
    )
    if agent_run is None:
        return AssertionResult(
            f"{assertion.agent}.completed",
            False,
            f"No agent run found for '{assertion.agent}'",
        )
    expected_status = "completed" if assertion.completed else "failed"
    actual = agent_run.status
    passed = actual == expected_status
    return AssertionResult(
        f"{assertion.agent}.completed",
        passed,
        f"Expected {expected_status}, got {actual}",
    )


def _check_tool_called(
    db: DbSession,
    session_id: UUID,
    assertion: EvalAssertion,
    expected: dict[str, object],
) -> AssertionResult:
    """Check whether a specific tool was called, with optional argument matching."""
    # Find agent run
    agent_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.session_id == session_id,
            AgentRun.agent_id == assertion.agent,
        )
        .order_by(AgentRun.sequence_number.desc())
        .first()
    )
    if agent_run is None:
        return AssertionResult(
            f"{assertion.agent}.tool_called({assertion.tool_called})",
            False,
            f"No agent run found for '{assertion.agent}'",
        )

    # Parse tool name (format: "server:tool_name")
    parts = assertion.tool_called.split(":", 1)
    mcp_server = parts[0]
    tool_name = parts[1] if len(parts) > 1 else parts[0]

    # Find tool call
    tc = (
        db.query(ToolCall)
        .filter(
            ToolCall.agent_run_id == agent_run.id,
            ToolCall.mcp_server == mcp_server,
            ToolCall.tool_name == tool_name,
        )
        .first()
    )
    if tc is None:
        return AssertionResult(
            f"{assertion.agent}.tool_called({assertion.tool_called})",
            False,
            f"Tool {assertion.tool_called} not found in agent run",
        )

    # Match expected arguments
    if expected:
        actual_args = tc.arguments or {}
        for key, expected_val in expected.items():
            actual_val = actual_args.get(key)
            if not _match_value(expected_val, actual_val):
                return AssertionResult(
                    f"{assertion.agent}.tool_called({assertion.tool_called}).{key}",
                    False,
                    f"Argument '{key}': expected {expected_val}, got {actual_val}",
                )

    return AssertionResult(
        f"{assertion.agent}.tool_called({assertion.tool_called})",
        True,
        "Tool called with matching arguments",
    )


def _match_value(expected: object, actual: object) -> bool:
    """Match a value with three modes: exact, wildcard, any-of list."""
    if expected == "*":
        return actual is not None
    if isinstance(expected, list):
        return str(actual) in [str(v) for v in expected]
    return str(expected) == str(actual)
