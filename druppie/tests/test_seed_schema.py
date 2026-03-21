"""Tests for YAML fixture schema validation."""

import pytest
from pydantic import ValidationError
from druppie.testing.seed_schema import (
    SessionFixture, SessionMetadata, AgentRunFixture,
    ToolCallFixture, ApprovalFixture, MessageFixture,
    OutcomeFile, ToolCallOutcome,
)


def test_minimal_fixture():
    """Metadata only, no agents."""
    f = SessionFixture(
        metadata=SessionMetadata(id="test", title="Test", status="completed")
    )
    assert f.metadata.id == "test"
    assert f.agents == []
    assert f.messages == []


def test_full_fixture():
    """Complete fixture with agents, tool calls, messages."""
    f = SessionFixture(
        metadata=SessionMetadata(
            id="todo-app", title="build a todo app", status="completed",
            intent="create_project", project_name="todo-app",
        ),
        agents=[
            AgentRunFixture(
                id="router", status="completed",
                tool_calls=[
                    ToolCallFixture(
                        tool="builtin:set_intent",
                        arguments={"intent": "create_project"},
                        status="completed",
                    ),
                    ToolCallFixture(
                        tool="builtin:done",
                        arguments={"summary": "Agent router: done"},
                        status="completed",
                    ),
                ],
            ),
        ],
        messages=[
            MessageFixture(role="user", content="build a todo app"),
        ],
    )
    assert len(f.agents) == 1
    assert len(f.agents[0].tool_calls) == 2


def test_tool_call_splits_server_and_name():
    tc = ToolCallFixture(tool="coding:write_file")
    assert tc.mcp_server == "coding"
    assert tc.tool_name == "write_file"


def test_tool_call_builtin():
    tc = ToolCallFixture(tool="builtin:done")
    assert tc.mcp_server == "builtin"
    assert tc.tool_name == "done"


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        SessionMetadata(id="x", title="x", status="invalid_status")


def test_invalid_agent_status_rejected():
    with pytest.raises(ValidationError):
        AgentRunFixture(id="router", status="invalid")


def test_invalid_tool_status_rejected():
    with pytest.raises(ValidationError):
        ToolCallFixture(tool="builtin:done", status="invalid")


def test_defaults():
    meta = SessionMetadata(id="x", title="x", status="completed")
    assert meta.user == "admin"
    assert meta.language == "en"
    assert meta.hours_ago == 0
    assert meta.intent is None
    assert meta.project_name is None


def test_approval_fixture():
    tc = ToolCallFixture(
        tool="coding:make_design",
        approval=ApprovalFixture(
            required_role="architect", status="approved", approved_by="architect"
        ),
    )
    assert tc.approval.required_role == "architect"
    assert tc.approval.status == "approved"


def test_hitl_answer():
    tc = ToolCallFixture(
        tool="builtin:hitl_ask_question",
        arguments={"question": "What features?"},
        answer="CRUD operations",
    )
    assert tc.answer == "CRUD operations"


def test_agent_with_error():
    agent = AgentRunFixture(
        id="builder", status="failed",
        error_message="Sandbox timeout",
    )
    assert agent.error_message == "Sandbox timeout"
    assert agent.tool_calls == []


def test_all_session_statuses():
    """Every valid session status is accepted."""
    valid = [
        "active", "paused_approval", "paused_hitl", "paused_sandbox",
        "paused", "paused_crashed", "completed", "failed",
    ]
    for status in valid:
        meta = SessionMetadata(id="x", title="x", status=status)
        assert meta.status == status


def test_all_agent_run_statuses():
    """Every valid agent run status is accepted."""
    valid = [
        "pending", "running", "paused_tool", "paused_hitl",
        "paused_sandbox", "paused_user", "completed", "failed", "cancelled",
    ]
    for status in valid:
        agent = AgentRunFixture(id="a", status=status)
        assert agent.status == status


def test_all_tool_call_statuses():
    """Every valid tool call status is accepted."""
    valid = [
        "pending", "waiting_approval", "waiting_answer",
        "waiting_sandbox", "executing", "completed", "failed",
    ]
    for status in valid:
        tc = ToolCallFixture(tool="builtin:done", status=status)
        assert tc.status == status


def test_message_roles():
    """All valid message roles are accepted."""
    for role in ("user", "assistant", "system"):
        msg = MessageFixture(role=role, content="hello")
        assert msg.role == role


def test_invalid_message_role_rejected():
    with pytest.raises(ValidationError):
        MessageFixture(role="tool", content="hello")


def test_message_with_agent_id():
    msg = MessageFixture(
        role="assistant", content="I will help you.", agent_id="business_analyst"
    )
    assert msg.agent_id == "business_analyst"


def test_tool_call_without_colon():
    """A bare tool name (no server prefix) still works."""
    tc = ToolCallFixture(tool="some_tool")
    assert tc.mcp_server == "some_tool"
    assert tc.tool_name == "some_tool"


def test_agent_with_planned_prompt():
    agent = AgentRunFixture(
        id="business_analyst", status="completed",
        planned_prompt="Analyze the user request.",
    )
    assert agent.planned_prompt == "Analyze the user request."


def test_outcome_on_execute_coding_task():
    """Tool call with outcome block parses correctly."""
    tc = ToolCallFixture(
        tool="builtin:execute_coding_task",
        arguments={"task": "Build it", "agent": "druppie-builder"},
        status="completed",
        result="Sandbox completed successfully",
        outcome=ToolCallOutcome(
            target="gitea",
            files=[
                OutcomeFile(path="src/App.jsx", content="export default function App() {}"),
                OutcomeFile(path="README.md", from_file="/tmp/readme.md"),
            ],
            commit_message="Initial implementation",
            push=True,
        ),
    )
    assert tc.outcome is not None
    assert tc.outcome.target == "gitea"
    assert len(tc.outcome.files) == 2
    assert tc.outcome.files[0].path == "src/App.jsx"
    assert tc.outcome.files[0].content is not None
    assert tc.outcome.files[1].from_file == "/tmp/readme.md"
    assert tc.outcome.commit_message == "Initial implementation"
    assert tc.outcome.push is True


def test_outcome_defaults():
    """ToolCallOutcome defaults are sensible."""
    outcome = ToolCallOutcome()
    assert outcome.target == "gitea"
    assert outcome.branch is None
    assert outcome.files == []
    assert outcome.commit_message == "Automated commit"
    assert outcome.push is True


def test_tool_call_without_outcome():
    """Tool call without outcome block has None."""
    tc = ToolCallFixture(tool="builtin:done")
    assert tc.outcome is None
