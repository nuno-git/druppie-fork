# Errors

`druppie/api/errors.py` defines a standardised error-handling stack: a base `APIError` exception, a set of convenience subclasses, an `ErrorCode` enum, an `ErrorResponse` Pydantic model, and three FastAPI exception handlers registered via `register_exception_handlers(app)` at startup (called from `druppie/api/main.py`).

## Hierarchy

```python
class APIError(Exception):
    """Base API exception carrying error_code, message, status_code, details."""
    def __init__(self, error_code: ErrorCode, message: str,
                 status_code: int = 400, details: dict | None = None): ...
    def to_response(self, request_id: str | None = None) -> ErrorResponse: ...

class NotFoundError(APIError):          # status 404
    def __init__(self, resource: str, resource_id: str, message: str | None = None): ...
    # Maps resource ∈ {session, project, workspace, approval, agent} to a specific ErrorCode.

class AuthenticationError(APIError):    # status 401, error_code AUTH_REQUIRED
class AuthorizationError(APIError):     # status 403, error_code ROLE_REQUIRED, takes optional required_roles
class ValidationError(APIError):        # status 422, error_code VALIDATION_ERROR
class ConflictError(APIError):          # status 409, error_code CONFLICT (overridable)
class ExternalServiceError(APIError):   # status 502, per-service code (LLM_ERROR, MCP_ERROR, GITEA_ERROR, KEYCLOAK_ERROR)
```

`ErrorCode` is a string enum grouped by category (auth 1xxx, authz 2xxx, validation 3xxx, resource 4xxx, conflict 5xxx, external 6xxx, server 7xxx, business 8xxx).

## HTTP mapping

Routes generally raise these exceptions instead of `HTTPException` directly. The registered handlers serialise them into a consistent `ErrorResponse` body:

```json
{
  "error_code": "SESSION_NOT_FOUND",
  "message": "Session not found: abc-123",
  "details": {"session_id": "abc-123"},
  "timestamp": "2024-01-22T10:30:00Z",
  "request_id": "req-456"
}
```

Handlers registered by `register_exception_handlers`:
- `APIError`       → `api_error_handler` — uses the exception's own `status_code` and serialises `to_response()`.
- `HTTPException`  → `http_exception_handler` — wraps raw `HTTPException`s (from FastAPI or routes that still raise them) into the same `ErrorResponse` shape, inferring `error_code` from the status code.
- `Exception`      → `generic_exception_handler` — catch-all: logs, returns 500 + `INTERNAL_ERROR`.

Status code convention:
- `NotFoundError` → 404
- `AuthenticationError` → 401
- `AuthorizationError` → 403
- `ConflictError` → 409
- `ValidationError` → 422
- `ExternalServiceError` → 502

## When services raise each

- **NotFoundError** — after `repo.get_by_id(id)` returns None.
- **AuthorizationError** — after explicit checks in the service: not owner + not admin, wrong role, session owner mismatch.
- **ConflictError** — reserved for state-transition conflicts. Note: several services (e.g. `SessionService.lock_for_retry`, `lock_for_resume`) still raise plain `ValueError` for conflict conditions and rely on route-level `try/except ValueError → HTTPException(409, ...)`, rather than raising `ConflictError` directly.
- **ValidationError** — rarely raised by services; Pydantic handles most request validation. Used for invariants that Pydantic can't enforce.
- **ExternalServiceError** — wraps failures from LLM providers, MCP servers, Gitea, Keycloak.

## What the frontend does

Every API call in `src/services/api.js` parses the error body and throws:

```js
if (!response.ok) {
  const err = await response.json().catch(() => ({}));
  throw new Error(err.detail || err.message || `HTTP ${response.status}`);
}
```

React Query catches these, exposes them as `error` on the hook, and UI components render them inline (toast, error card, or inline red text). The `message` field of `ErrorResponse` is what surfaces to the user.

## Internal API errors

Internal endpoints (e.g. the sandbox webhook at `/api/sandbox-sessions/{id}/complete`) use a separate path:
- `403` if the HMAC `X-Signature` header is missing or mismatched, or the referenced session is gone.
- `404` only if the tool call row is missing at dispatch time.

These are not shown to end users — the sandbox side logs and aborts. See `druppie/api/routes/sandbox.py`.
