# Errors

`druppie/api/errors.py` defines four exception classes that routes translate into HTTP responses.

## Hierarchy

```python
class DruppieError(Exception):
    """Base."""

class NotFoundError(DruppieError):
    def __init__(self, entity: str, id: str | UUID):
        super().__init__(f"{entity} {id} not found")

class AuthorizationError(DruppieError):
    def __init__(self, message: str = "Not authorized"):
        super().__init__(message)

class ConflictError(DruppieError):
    """Invalid state transition, e.g. resume ACTIVE session."""

class ValidationError(DruppieError):
    def __init__(self, message: str, field: str | None = None):
        self.field = field
        super().__init__(message)
```

## HTTP mapping

Routes catch these and translate. No single handler does it — each route wraps its service call with a small try block:

```python
try:
    session = service.get_detail(session_id, user_id, roles)
except NotFoundError as e:
    raise HTTPException(404, str(e))
except AuthorizationError as e:
    raise HTTPException(403, str(e))
```

Convention:
- `NotFoundError` → 404
- `AuthorizationError` → 403
- `ConflictError` → 409
- `ValidationError` → 422

Unhandled exceptions propagate to FastAPI's default handler, which returns 500 and logs the traceback. There is no custom exception middleware.

## When services raise each

- **NotFoundError** — after `repo.get_by_id(id)` returns None.
- **AuthorizationError** — after explicit checks in the service: not owner + not admin, wrong role, session owner mismatch.
- **ConflictError** — after lock acquisition reveals a state that prohibits the action: `lock_for_retry` on an ACTIVE session, `resume` on a COMPLETED session, webhook on an already-completed tool call.
- **ValidationError** — rarely raised by services; Pydantic handles most request validation. Used for invariants that Pydantic can't enforce (e.g. "answer must be set if question is not choice-only").

## What the frontend does

Every API call in `src/services/api.js` parses the error body and throws:

```js
if (!response.ok) {
  const err = await response.json().catch(() => ({}));
  throw new Error(err.detail || err.message || `HTTP ${response.status}`);
}
```

React Query catches these, exposes them as `error` on the hook, and UI components render them inline (toast, error card, or inline red text).

## Internal API errors

Internal endpoints (e.g. the sandbox register) use a separate path:
- 401 if HMAC missing/invalid.
- 404 if referenced tool call / session is gone (can happen if user deleted the session while sandbox was running).

These are not shown to users — the sandbox side logs and aborts.
