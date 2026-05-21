"""Assertion matching for tests.

Matches eval assertions against DB state with expected values from tests.
Three matching modes: exact, wildcard (*), any-of list.

Dynamic references:
  ``@project:<name>`` in expected values resolves to the actual project UUID
  by looking up projects owned by the session's user.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, ToolCall
from druppie.testing.schema import CheckAssertion

logger = logging.getLogger(__name__)


@dataclass
class AssertionResult:
    name: str
    passed: bool
    message: str


def match_assertions(
    db: DbSession,
    session_id: UUID,
    assertions: list[CheckAssertion],
    expected: dict[str, object],
) -> list[AssertionResult]:
    """Match eval assertions against DB state with expected values from test.

    Each assertion can check:
    - ``completed``: whether the agent completed (True) or failed (False)
    - ``tool``: whether a specific tool was called, with optional
      argument matching via *expected*

    Three argument matching modes:
    - Exact: ``expected_value == actual_value``
    - Wildcard: ``expected_value == "*"`` -- just check key exists
    - Any-of list: ``isinstance(expected_value, list) and actual_value in expected_value``

    Dynamic references in expected values (e.g. ``@project:weather-dashboard``)
    are resolved to actual UUIDs before matching.
    """
    resolved_expected = _resolve_references(db, session_id, expected)
    results = []
    for assertion in assertions:
        if assertion.completed is not None:
            result = _check_completed(db, session_id, assertion)
            results.append(result)
        if assertion.tool:
            result = _check_tool(db, session_id, assertion, resolved_expected)
            results.append(result)
    return results


def _resolve_references(
    db: DbSession, session_id: UUID, expected: dict[str, object]
) -> dict[str, object]:
    """Resolve dynamic references in expected values.

    Supported references:
      ``@project:<name>`` -- resolves to the project's UUID by looking up
      projects owned by the session's user.
    """
    if not expected:
        return expected

    # Only do the DB lookup if there are references to resolve
    has_refs = any(
        isinstance(v, str) and v.startswith("@project:")
        for v in expected.values()
    )
    if not has_refs:
        return expected

    from druppie.db.models import Project
    from druppie.db.models import Session as SessionModel

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session or not session.user_id:
        logger.warning(
            "Cannot resolve references: session %s not found or has no user_id",
            session_id,
        )
        return expected

    resolved: dict[str, object] = {}
    for key, value in expected.items():
        if isinstance(value, str) and value.startswith("@project:"):
            project_name = value[len("@project:"):]
            project = (
                db.query(Project)
                .filter(
                    Project.name == project_name,
                    Project.owner_id == session.user_id,
                )
                .first()
            )
            if project:
                resolved[key] = str(project.id)
                logger.info(
                    "Resolved %s -> %s (project %s)",
                    value,
                    project.id,
                    project_name,
                )
            else:
                # Leave as-is; will fail assertion with a clear message
                resolved[key] = value
                logger.warning(
                    "Could not resolve %s: no project named '%s' for user %s",
                    value,
                    project_name,
                    session.user_id,
                )
        else:
            resolved[key] = value
    return resolved


def _check_completed(
    db: DbSession,
    session_id: UUID,
    assertion: CheckAssertion,
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
    actual = agent_run.status
    if assertion.completed:
        passed = actual == "completed"
        expected_label = "completed"
    else:
        # completed: false → agent should NOT be completed (any other status is fine)
        passed = actual != "completed"
        expected_label = "not completed"
    return AssertionResult(
        f"{assertion.agent}.completed",
        passed,
        f"Expected {expected_label}, got {actual}",
    )


def _check_tool(
    db: DbSession,
    session_id: UUID,
    assertion: CheckAssertion,
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
            f"{assertion.agent}.tool({assertion.tool})",
            False,
            f"No agent run found for '{assertion.agent}'",
        )

    # Parse tool name (format: "server:tool_name")
    parts = assertion.tool.split(":", 1)
    mcp_server = parts[0]
    tool_name = parts[1] if len(parts) > 1 else parts[0]

    # Merge external expected with inline assertion.arguments (inline wins
    # on key collision — assertions that hard-code a path should not be
    # overridden by a generic expected dict from the test).
    merged_expected: dict[str, object] = {**expected, **(assertion.arguments or {})}

    # Find all tool calls of this type; pick one matching merged_expected.
    # With only expected={} and multiple calls, we fall back to .first()
    # behaviour by using the first call. With expected, we filter.
    tool_calls = (
        db.query(ToolCall)
        .filter(
            ToolCall.agent_run_id == agent_run.id,
            ToolCall.mcp_server == mcp_server,
            ToolCall.tool_name == tool_name,
        )
        .all()
    )
    if not tool_calls:
        return AssertionResult(
            f"{assertion.agent}.tool({assertion.tool})",
            False,
            f"Tool {assertion.tool} not found in agent run",
        )

    if merged_expected:
        matching = [
            t for t in tool_calls
            if all(
                _match_value(v, (t.arguments or {}).get(k))
                for k, v in merged_expected.items()
            )
        ]
        if not matching:
            # Report against the first call for diagnostics
            first = tool_calls[0]
            actual_first = first.arguments or {}
            mismatches = [
                f"'{k}': expected {v}, got {actual_first.get(k)}"
                for k, v in merged_expected.items()
                if not _match_value(v, actual_first.get(k))
            ]
            return AssertionResult(
                f"{assertion.agent}.tool({assertion.tool}).args",
                False,
                (
                    f"No {assertion.tool} call matched expected arguments "
                    f"across {len(tool_calls)} call(s). First call mismatches: "
                    f"{'; '.join(mismatches)}"
                ),
            )
        tc = matching[0]
    else:
        tc = tool_calls[0]

    # Check tool call status if assertion specifies one
    if assertion.status:
        if tc.status != assertion.status:
            return AssertionResult(
                f"{assertion.agent}.tool({assertion.tool}).status",
                False,
                f"Tool status: expected {assertion.status}, got {tc.status}",
            )

    # Check error message if assertion specifies one
    if assertion.error_contains:
        error_msg = tc.error_message or tc.result or ""
        if assertion.error_contains.lower() not in error_msg.lower():
            return AssertionResult(
                f"{assertion.agent}.tool({assertion.tool}).error",
                False,
                f"Error does not contain '{assertion.error_contains}': {error_msg[:200]}",
            )

    # Check error message matches regex pattern
    if assertion.error_matches:
        error_msg = tc.error_message or tc.result or ""
        try:
            if not re.search(assertion.error_matches, error_msg):
                return AssertionResult(
                    f"{assertion.agent}.tool({assertion.tool}).error_matches",
                    False,
                    f"Error does not match pattern '{assertion.error_matches}': {error_msg[:200]}",
                )
        except re.error as exc:
            return AssertionResult(
                f"{assertion.agent}.tool({assertion.tool}).error_matches",
                False,
                f"Invalid regex pattern '{assertion.error_matches}': {exc}",
            )

    # Arguments already matched above when picking `tc` from tool_calls.
    return AssertionResult(
        f"{assertion.agent}.tool({assertion.tool})",
        True,
        f"Tool called with status={tc.status}"
        + (" and matching arguments" if merged_expected else ""),
    )


def _match_value(expected: object, actual: object) -> bool:
    """Match a value with three modes: exact, wildcard, any-of list.

    Comparison is type-aware: values must match both type and content,
    except UUIDs are compared as strings since YAML loads them as strings.
    """
    if expected == "*":
        return actual is not None
    # Normalize UUIDs to strings for comparison
    from uuid import UUID
    if isinstance(actual, UUID):
        actual = str(actual)
    if isinstance(expected, UUID):
        expected = str(expected)
    if isinstance(expected, list):
        return actual in expected or str(actual) in [str(v) for v in expected]
    if type(expected) == type(actual):
        return expected == actual
    # Allow numeric cross-type (YAML may parse "1" as int, DB may return str)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return expected == actual
    # Allow bool/str cross-type (YAML "true" vs DB True)
    if isinstance(expected, bool) and isinstance(actual, str):
        return str(expected).lower() == actual.lower()
    if isinstance(actual, bool) and isinstance(expected, str):
        return str(actual).lower() == expected.lower()
    # Strict: no implicit str() coercion — mismatched types fail
    return False
