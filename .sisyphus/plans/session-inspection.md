# Plan: Session Inspection Improvements

Two features:
1. **Session Summary Mode** - Truncated view that cuts away full LLM calls
2. **Developer Auth Bypass** - Skip Keycloak, use username-only auth in dev

---

## Feature 1: Session Summary Mode

### Goal
Add a `summary` query parameter to session API endpoints. When `summary=true`, the response strips full LLM call content and truncates tool call arguments/results to ~50 words.

### What Gets Truncated

In the current response tree:
```
SessionDetail
  └── timeline: list[TimelineEntry]
        └── agent_run: AgentRunDetail
              ├── status, agent_id, agent_name          ← KEEP
              ├── input_message                          ← KEEP
              ├── llm_calls: list[LLMCallDetail]         ← STRIP entirely in summary mode
              │     ├── messages: list[LLMMessage]       ← (prompt/completions - very verbose)
              │     └── tool_calls: list[ToolCallDetail]
              │           ├── name, status               ← KEEP
              │           ├── arguments                  ← TRUNCATE to 50 words
              │           └── result                     ← TRUNCATE to 50 words
              └── output_message                         ← KEEP
```

**Summary mode behavior:**
- Remove `llm_calls` entirely (no LLM prompt/completion details)
- Show `agent_run.status`, `agent_run.agent_id`, `agent_run.agent_name`
- Extract tool calls from the first LLM call (if any) and lift them to the agent_run level
- Truncate `tool_call.arguments` and `tool_call.result` to 50 words
- Keep all other fields as-is

### Implementation Plan

#### Step 1: Add truncation utility
**File**: `druppie/services/summary_utils.py` (new file)

Create a `truncate_to_words(text: str, max_words: int = 50) -> str` function:
- If text is None/empty, return as-is
- Split by whitespace, if word count <= max_words, return as-is
- Otherwise: take first N words + append `"... [truncated, {total} words total]"`
- Handle both string and dict/list inputs (JSON-serialize first if needed)

#### Step 2: Add summary response builder
**File**: `druppie/services/summary_utils.py`

Create a `build_session_summary(detail: SessionDetail) -> SessionSummaryView` function:
- Walk the timeline
- For each agent_run: keep status, agent_id, agent_name, input_message, output_message, started_at, completed_at
- Extract tool_calls from llm_calls (flatten from nested position)
- For each tool_call: keep name, status, server_name, approval fields; truncate arguments and result
- Return a new `SessionSummaryView` model

#### Step 3: Add domain model for summary view
**File**: `druppie/domain/session.py`

Add two new models:

```python
class ToolCallSummary(BaseModel):
    """Truncated tool call for summary view."""
    id: str
    name: str
    server_name: str | None
    status: str
    arguments: str | None          # truncated to 50 words
    result: str | None             # truncated to 50 words
    started_at: datetime | None
    completed_at: datetime | None
    approval: ApprovalSummary | None  # keep as-is, it's small

class AgentRunSummaryView(BaseModel):
    """Summary view of agent run - no LLM calls, truncated tool results."""
    id: str
    agent_id: str
    agent_name: str
    status: str
    input_message: str | None
    output_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    tool_calls: list[ToolCallSummary]  # lifted from llm_calls, truncated
    error: str | None
```

Update `TimelineEntry` (or add a new `TimelineEntrySummary`) to use `AgentRunSummaryView` instead of `AgentRunDetail`.

Add `SessionSummaryView(BaseModel)`:
```python
class SessionSummaryView(BaseModel):
    """Summary view of a session with truncated data."""
    id: str
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    project: ProjectSummary | None
    timeline: list[TimelineEntrySummary]  # uses AgentRunSummaryView
```

#### Step 4: Add query parameter to API routes
**File**: `druppie/api/routes/sessions.py`

- Add `summary: bool = Query(default=False)` to `GET /sessions/{session_id}`
- If `summary=true`: call service to get full detail → run `build_session_summary()` → return `SessionSummaryView`
- If `summary=false` (default): return full `SessionDetail` as before (no behavior change)

Also add to `GET /sessions` list endpoint? → **No.** List already returns `SessionSummary` (lightweight). Summary mode is only useful for session detail.

#### Step 5: Export new models
**File**: `druppie/domain/__init__.py`

Add exports for `SessionSummaryView`, `AgentRunSummaryView`, `ToolCallSummary`, `TimelineEntrySummary`.

### Files Changed
| File | Change |
|------|--------|
| `druppie/services/summary_utils.py` | **NEW** - truncation + summary builder |
| `druppie/domain/session.py` | Add `SessionSummaryView`, `TimelineEntrySummary` |
| `druppie/domain/agent_run.py` | Add `AgentRunSummaryView`, `ToolCallSummary` |
| `druppie/domain/__init__.py` | Export new models |
| `druppie/api/routes/sessions.py` | Add `summary` query param |

### Alternative Approaches Considered
1. **Post-processing on the full SessionDetail** - Walk the model and mutate fields in-place. **Rejected**: violates immutability, harder to test, mixes concerns.
2. **Separate DB query for summary** - Query only needed fields from DB. **Rejected**: over-engineering, the full query is fast enough, and we'd duplicate repository logic.
3. **Selected approach**: Build full detail, then transform to summary model. Clean separation, easy to test, no DB changes.

---

## Feature 2: Developer Auth Bypass

### Goal
When `DEV_MODE=true` env var is set, allow API access by passing `X-Dev-User` header with just a username (no password, no Keycloak). Maps to existing Keycloak test users.

### Security Model
- **Only works when `DEV_MODE=true`** is explicitly set in environment
- Must NEVER work in production (no `DEV_MODE` in prod env)
- Username must match a known user in the system
- All roles/permissions are assigned based on the user mapping

### Implementation Plan

#### Step 1: Add DEV_MODE config
**File**: `druppie/core/config.py`

Add:
```python
DEV_MODE: bool = False
DEV_MODE_DEFAULT_USER: str = "admin"
```

Read from environment variables `DEV_MODE` and `DEV_MODE_DEFAULT_USER`.

#### Step 2: Create dev auth dependency
**File**: `druppie/api/deps.py`

Add a new dependency function alongside existing `get_current_user`:

```python
async def get_current_user_dev(request: Request) -> tuple[str, list[str]]:
    """Dev-mode auth: accept X-Dev-User header, bypass Keycloak."""
    dev_user = request.headers.get("X-Dev-User", settings.DEV_MODE_DEFAULT_USER)
    
    # Map to known users and their roles
    user_map = {
        "admin": ("admin", ["admin"]),
        "architect": ("architect", ["architect"]),
        "developer": ("developer", ["developer"]),
        "analyst": ("analyst", ["business_analyst"]),
        "normal_user": ("normal_user", ["user"]),
    }
    
    if dev_user not in user_map:
        raise HTTPException(status_code=401, detail=f"Unknown dev user: {dev_user}")
    
    username, roles = user_map[dev_user]
    return username, roles
```

#### Step 3: Create auth selector
**File**: `druppie/api/deps.py`

Create a single auth dependency that picks the right backend:

```python
def get_auth_dependency():
    """Returns the appropriate auth dependency based on DEV_MODE."""
    if settings.DEV_MODE:
        return get_current_user_dev
    return get_current_user  # existing Keycloak auth
```

Update all route files to use this selector instead of directly referencing `get_current_user`.

#### Step 4: Update route files
**Files**: `druppie/api/routes/*.py`

Replace `Depends(get_current_user)` with `Depends(get_auth_dependency())` in all route files. This is a mechanical find-and-replace.

Alternatively (less invasive): Override at the app level using middleware:

```python
# In main.py
if settings.DEV_MODE:
    app.middleware("http")(dev_auth_middleware)
```

**Preferred approach**: Middleware-based. Less files to change, easier to remove, zero risk of accidentally shipping dev auth to prod (middleware only added when DEV_MODE=true).

#### Step 5: Add middleware approach
**File**: `druppie/api/main.py`

```python
from starlette.middleware.base import BaseHTTPMiddleware

class DevAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.DEV_MODE:
            dev_user = request.headers.get("X-Dev-User", settings.DEV_MODE_DEFAULT_USER)
            # Inject user info into request state
            request.state.user = dev_user
            request.state.roles = DEV_USER_ROLES.get(dev_user, [])
        response = await call_next(request)
        return response
```

**Wait** - middleware approach has a problem: the `Depends(get_current_user)` will still run and fail. We need to either:
- Replace the dependency itself (approach from Step 3)
- Or make `get_current_user` check for dev mode first

**Best approach**: Modify `get_current_user` itself to short-circuit when `DEV_MODE=true`:

```python
async def get_current_user(request: Request, authorization: str = Header(None)):
    # Dev mode bypass
    if settings.DEV_MODE:
        dev_user = request.headers.get("X-Dev-User", settings.DEV_MODE_DEFAULT_USER)
        if dev_user in DEV_USER_ROLES:
            return dev_user, DEV_USER_ROLES[dev_user]
        raise HTTPException(401, detail=f"Unknown dev user: {dev_user}")
    
    # Normal Keycloak flow (existing code)
    ...
```

This is the **simplest and safest** approach:
- Zero route file changes
- Existing `Depends(get_current_user)` works unchanged
- Dev mode is a single `if` at the top of the existing function
- Impossible to accidentally enable in prod (requires `DEV_MODE=true` env var)

### Files Changed
| File | Change |
|------|--------|
| `druppie/core/config.py` | Add `DEV_MODE`, `DEV_MODE_DEFAULT_USER` settings |
| `druppie/api/deps.py` | Add dev-mode short-circuit in `get_current_user` |
| `.env.example` | Add `DEV_MODE=false` with documentation |

### Files NOT Changed
- No route files modified (auth bypass is transparent)
- No domain/repository changes
- No frontend changes needed (curl/API-level feature)

### Usage
```bash
# Enable dev mode
export DEV_MODE=true

# Use any API endpoint with just a username
curl -H "X-Dev-User: admin" http://localhost:10222/api/sessions
curl -H "X-Dev-User: developer" http://localhost:10222/api/sessions/{id}?summary=true

# Without X-Dev-User header, defaults to admin
curl http://localhost:10222/api/sessions
```

---

## Combined Usage Example

```bash
# Dev mode + summary view - perfect for debugging
curl -s -H "X-Dev-User: admin" "http://localhost:10222/api/sessions/{id}?summary=true" | jq .
```

---

## Execution Order

1. **Feature 2 first** (dev auth bypass) - simpler, enables easier testing of Feature 1
2. **Feature 1** (session summary mode) - can be tested immediately with dev auth
3. **Integration test** - verify both features work together

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Dev auth leaked to prod | `DEV_MODE` defaults to `False`, checked at function entry, no middleware auto-load |
| Summary truncation loses critical info | 50-word limit is generous, full detail always available via default endpoint |
| Breaking existing API consumers | Both features are additive: `summary=false` is default, `DEV_MODE=false` is default |
