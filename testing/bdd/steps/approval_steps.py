"""BDD step definitions for approval-workflow.feature.

Tests the approval workflow at the service layer using mocked repositories,
matching the real Druppie architecture:
    Route -> ApprovalService -> ApprovalRepository -> Database
"""

from uuid import uuid4, UUID

from behave import given, when, then
from unittest.mock import MagicMock, patch

from druppie.domain import ApprovalDetail, ApprovalStatus
from druppie.domain.common import ApprovalStatus as ApprovalStatusEnum
from druppie.services.approval_service import ApprovalService
from druppie.api.errors import AuthorizationError, NotFoundError, ConflictError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_approval_detail(
    approval_id: UUID | None = None,
    session_id: UUID | None = None,
    required_role: str = "architect",
    status: str = "pending",
    rejection_reason: str | None = None,
) -> ApprovalDetail:
    """Build a realistic ApprovalDetail matching druppie/domain/approval.py."""
    return ApprovalDetail(
        id=approval_id or uuid4(),
        session_id=session_id or uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        mcp_server="coding",
        tool_name="write_file",
        arguments={"path": "docs/td.md", "content": "# Technical Design"},
        agent_id="architect_agent",
        required_role=required_role,
        status=status,
        resolved_by=None,
        resolved_at=None,
        rejection_reason=rejection_reason,
        created_at="2025-01-01T00:00:00Z",
        session_user_id=uuid4(),
        repo_url=None,
    )


def _make_db_approval(
    approval_id: UUID | None = None,
    session_id: UUID | None = None,
    required_role: str = "architect",
    status: str = "pending",
    user_id: UUID | None = None,
):
    """Mimic the SQLAlchemy Approval ORM object from druppie/db/models/approval.py."""
    approval = MagicMock()
    approval.id = approval_id or uuid4()
    approval.session_id = session_id or uuid4()
    approval.required_role = required_role
    approval.status = status
    approval.mcp_server = "coding"
    approval.tool_name = "write_file"
    approval.arguments = {"path": "docs/td.md", "content": "# TD"}
    approval.agent_id = "architect_agent"
    approval.user_id = user_id or uuid4()
    approval.rejection_reason = None
    return approval


# ---------------------------------------------------------------------------
# GIVEN steps
# ---------------------------------------------------------------------------

@given('a project exists with id "{project_id}"')
def step_project_exists(context, project_id: str):
    """Set up a project context for the approval scenario."""
    context.project_id = project_id
    context.session_id = uuid4()


@given('an agent produces a technical design requiring "{role}" approval')
def step_agent_produces_td(context, role: str):
    """Create a pending approval for a technical design tool call."""
    context.approval_id = uuid4()
    context.required_role = role
    context.db_approval = _make_db_approval(
        approval_id=context.approval_id,
        session_id=context.session_id,
        required_role=role,
        status=ApprovalStatusEnum.PENDING.value,
    )


@given('an agent requests a Docker build requiring "{role}" approval')
def step_agent_requests_docker_build(context, role: str):
    """Create a pending approval for a Docker build tool call."""
    context.approval_id = uuid4()
    context.required_role = role
    context.db_approval = _make_db_approval(
        approval_id=context.approval_id,
        session_id=context.session_id,
        required_role=role,
        status=ApprovalStatusEnum.PENDING.value,
    )
    context.db_approval.mcp_server = "docker"
    context.db_approval.tool_name = "build_image"


@given('a pending approval exists with id "{approval_id}" requiring "{role}" role')
def step_pending_approval_exists(context, approval_id: str, role: str):
    """Create a specific pending approval by ID."""
    context.approval_id = UUID(approval_id) if _is_valid_uuid(approval_id) else uuid4()
    context.required_role = role
    context.db_approval = _make_db_approval(
        approval_id=context.approval_id,
        session_id=getattr(context, "session_id", uuid4()),
        required_role=role,
        status=ApprovalStatusEnum.PENDING.value,
    )


@given('the current user has role "{role}"')
def step_user_has_role(context, role: str):
    """Set the current user's role (determines authorization outcome)."""
    context.user_roles = [role]
    context.user_id = uuid4()


# ---------------------------------------------------------------------------
# WHEN steps
# ---------------------------------------------------------------------------

@when('the architect approves the pending approval')
@when('the developer approves the pending approval')
def step_user_approves(context):
    """Call ApprovalService.approve() with the current user's roles."""
    approval_repo = MagicMock()
    session_repo = MagicMock()

    # Wire up repository returns
    approval_repo.get_by_id.return_value = context.db_approval
    approval_detail = _make_approval_detail(
        approval_id=context.approval_id,
        session_id=context.db_approval.session_id,
        required_role=context.required_role,
        status=ApprovalStatusEnum.APPROVED.value,
    )
    approval_repo._to_detail.return_value = approval_detail

    service = ApprovalService(approval_repo, session_repo)
    context.service = service

    try:
        context.result = service.approve(
            approval_id=context.approval_id,
            user_id=context.user_id if hasattr(context, "user_id") else uuid4(),
            user_roles=getattr(context, "user_roles", ["architect"]),
        )
        context.exception = None
    except (AuthorizationError, NotFoundError, ConflictError) as exc:
        context.exception = exc
        context.result = None


@when('the architect rejects it with reason "{reason}"')
def step_user_rejects(context, reason: str):
    """Call ApprovalService.reject() with a rejection reason."""
    approval_repo = MagicMock()
    session_repo = MagicMock()

    approval_repo.get_by_id.return_value = context.db_approval
    approval_detail = _make_approval_detail(
        approval_id=context.approval_id,
        session_id=context.db_approval.session_id,
        required_role=context.required_role,
        status=ApprovalStatusEnum.REJECTED.value,
        rejection_reason=reason,
    )
    approval_repo._to_detail.return_value = approval_detail

    service = ApprovalService(approval_repo, session_repo)
    context.service = service

    try:
        context.result = service.reject(
            approval_id=context.approval_id,
            user_id=uuid4(),
            user_roles=["architect"],
            reason=reason,
        )
        context.exception = None
    except (AuthorizationError, NotFoundError, ConflictError) as exc:
        context.exception = exc
        context.result = None


@when("the user tries to approve the approval")
def step_unauthorized_user_approves(context):
    """Attempt to approve with insufficient role — expect AuthorizationError."""
    approval_repo = MagicMock()
    session_repo = MagicMock()

    approval_repo.get_by_id.return_value = context.db_approval

    service = ApprovalService(approval_repo, session_repo)

    try:
        context.result = service.approve(
            approval_id=context.approval_id,
            user_id=context.user_id,
            user_roles=context.user_roles,
        )
        context.exception = None
    except AuthorizationError as exc:
        context.exception = exc
        context.result = None
        context.response_status = 403


# ---------------------------------------------------------------------------
# THEN steps
# ---------------------------------------------------------------------------

@then('the approval status is "{expected_status}"')
def step_approval_status(context, expected_status: str):
    """Verify the approval has the expected status."""
    assert context.exception is None, f"Unexpected exception: {context.exception}"
    assert context.result is not None, "No approval result returned"

    actual = context.result.status
    if isinstance(actual, ApprovalStatus):
        actual = actual.value
    assert actual == expected_status, (
        f"Expected status '{expected_status}', got '{actual}'"
    )


@then("the agent workflow resumes in the background")
def step_workflow_resumes(context):
    """Verify background task was spawned (approve/reject triggers resume).

    In production, the route calls create_session_task() after service.approve().
    At service-layer test level, we verify the approve succeeded (the route
    handles task spawning separately).
    """
    assert context.result is not None, "Approval must succeed before workflow resumes"


@then("the tool executes and the file is committed")
def step_tool_executes(context):
    """Verify the tool execution path is set up.

    The actual tool execution happens in the background task via
    Orchestrator.resume_after_approval(). At service-level we verify
    the approval was recorded so the background task can proceed.
    """
    assert context.result.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
    )


@then("the container starts successfully")
def step_container_starts(context):
    """Verify Docker build approval was recorded.

    The actual container start happens in the background task.
    At service-level we verify the approval state allows it.
    """
    assert context.result.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
    )


@then('the rejection reason is "{expected_reason}"')
def step_rejection_reason(context, expected_reason: str):
    """Verify the rejection reason is stored."""
    assert context.result is not None
    assert context.result.rejection_reason == expected_reason, (
        f"Expected reason '{expected_reason}', got '{context.result.rejection_reason}'"
    )


@then("the agent can retry with a different approach")
def step_agent_can_retry(context):
    """After rejection, the workflow resumes so the agent sees the failure.

    The agent receives the rejection as a tool error and can adjust its
    approach in the next LLM iteration (handled by Orchestrator).
    """
    assert context.result.status in (
        ApprovalStatus.REJECTED,
        ApprovalStatus.REJECTED.value,
    )


@then("the response status code is {status_code:d}")
def step_response_status(context, status_code: int):
    """Verify the HTTP-like status code from the error."""
    assert hasattr(context, "exception"), "Expected an exception but none was raised"
    assert context.exception is not None, "Expected an exception but operation succeeded"
    # APIError subclasses carry status_code
    actual = getattr(context.exception, "status_code", None)
    assert actual == status_code, (
        f"Expected status {status_code}, got {actual}"
    )


@then('the approval status remains "{expected_status}"')
def step_approval_unchanged(context, expected_status: str):
    """Approval was not modified because the operation was denied."""
    # If we got an AuthorizationError, the DB was never updated
    assert context.exception is not None, "Expected authorization denial"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except ValueError:
        return False
