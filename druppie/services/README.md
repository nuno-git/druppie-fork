# Services Layer

The services layer contains **business logic** and orchestrates repositories. Services sit between the API routes and repositories, implementing authorization checks, cross-entity coordination, and workflow management.

## Architecture

```
API Route
    |
    v
  Service  (business logic, authorization, orchestration)
    |
    v
  Repository  (data access)
```

Services receive repositories via constructor injection. They are created by FastAPI dependency injection functions in `api/deps.py`.

## Files

### `__init__.py`
Central export hub for all services:
`SessionService`, `ApprovalService`, `QuestionService`, `ProjectService`, `DeploymentService`, `WorkflowService`.

### `session_service.py`
Manages session retrieval with authorization.

**Constructor**: `SessionService(session_repo: SessionRepository)`

Key methods:
- `get_list(user_id, user_roles)` -- returns sessions for a user. Admins see all sessions.
- `get_detail(session_id, user_id, user_roles)` -- returns `SessionDetail` with full timeline. Checks ownership (user must own the session or be admin).
- `delete(session_id, user_id, user_roles)` -- deletes a session with ownership check.

The authorization pattern is consistent: every read/write checks that the calling user either owns the resource or has the `admin` role.

### `project_service.py`
Manages project CRUD with authorization.

**Constructor**: `ProjectService(project_repo: ProjectRepository)`

Key methods:
- `get_list(user_id, user_roles)` -- returns projects for a user. Admins see all.
- `get_detail(project_id, user_id, user_roles)` -- returns `ProjectDetail` with ownership check.
- `create(name, description, user_id)` -- creates a new project.
- `update(project_id, user_id, user_roles, **fields)` -- partial update with ownership check.

### `approval_service.py`
Manages the approval workflow for tool calls that require human approval.

**Constructor**: `ApprovalService(approval_repo: ApprovalRepository)`

Key methods:
- `get_pending(user_roles)` -- returns `PendingApprovalList` filtered to approvals the user can act on based on their roles.
- `get_detail(approval_id)` -- returns `ApprovalDetail`.
- `approve(approval_id, user_id, user_roles)` -- approves a pending request. Validates that the user has the required role.
- `reject(approval_id, user_id, user_roles, reason)` -- rejects with a reason.

The role check ensures that only users with the role specified in `required_role` (or admins) can approve/reject.

### `question_service.py`
Manages HITL (Human-in-the-Loop) questions from agents.

**Constructor**: `QuestionService(question_repo: QuestionRepository, session_repo: SessionRepository)`

Needs `session_repo` because questions belong to sessions, and ownership is checked at the session level.

Key methods:
- `get_pending(session_id, user_id)` -- returns `PendingQuestionList` for a session, with ownership check.
- `get_detail(question_id)` -- returns `QuestionDetail`.
- `answer(question_id, answer, user_id)` -- records the answer. Validates the question is still pending and the user owns the session.

### `deployment_service.py`
Manages container deployments via the Docker MCP server.

Key methods:
- `get_deployments(user_id, user_roles)` -- lists active deployments for the user's projects.
- `get_deployment(project_id)` -- gets deployment status for a specific project by querying the Docker MCP.
- `stop_deployment(project_id, user_id)` -- stops a running container.

This service differs from others because it communicates with the Docker MCP server via HTTP rather than just querying the database.

### `workflow_service.py`
Wraps the execution `Orchestrator` to provide workflow management for the API layer.

**Constructor**: `WorkflowService(orchestrator: Orchestrator)`

Key methods:
- `process_message(message, user_id, session_id, project_id)` -- entry point for new user messages. Delegates to `Orchestrator.process_message()`.
- `resume_after_approval(session_id, approval_id)` -- resumes a paused workflow after approval. Delegates to `Orchestrator.resume_after_approval()`.
- `resume_after_answer(session_id, question_id, answer)` -- resumes after HITL question is answered. Delegates to `Orchestrator.resume_after_answer()`.

This service is a thin wrapper -- it exists so that routes don't need to know about the execution layer directly.

## Layer Connections

- **Depends on**: `druppie.repositories` (data access), `druppie.domain` (models and enums), `druppie.execution` (via WorkflowService).
- **Depended on by**: `druppie.api.routes` (called from route handlers).

## Conventions

1. Services receive repositories via constructor, not via direct import.
2. Authorization is enforced in the service layer, not in routes or repositories.
3. Services return domain models (Pydantic) -- never raw ORM objects or dicts.
4. Services that cannot find a resource raise exceptions that the API layer catches and converts to HTTP errors.
5. Transaction commits happen in the service layer when the business operation is complete.
