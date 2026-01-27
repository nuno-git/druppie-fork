# Codebase Simplification Opportunities

Analysis of the codebase with recommendations for simplification.

## Current State

### File Size Analysis (Top 10)

| File | Lines | Purpose |
|------|-------|---------|
| `loop.py` | 1986 | Main execution loop |
| `coding/server.py` | 1382 | MCP coding tools |
| `approvals.py` | 1323 | Approval API routes |
| `crud.py` | 1234 | Database operations |
| `mcp_client.py` | 1183 | MCP HTTP client |
| `sessions.py` | 1039 | Session API routes |
| `runtime.py` | 865 | Agent runtime |
| `projects.py` | 822 | Project API routes |
| `models.py` | 755 | SQLAlchemy models |

**Total Python code**: ~15,000+ lines in backend alone.

---

## High-Priority Simplifications

### 1. Split `loop.py` (1986 lines)

**Problem**: Single file handles session creation, router/planner execution, workflow execution, approval resumption, HITL resumption, state persistence.

**Recommendation**: Split into focused modules:

```
druppie/core/
├── loop.py           # Minimal orchestration (200 lines)
├── session_manager.py    # Session CRUD, status updates
├── workflow_executor.py  # Workflow step execution
├── approval_handler.py   # Approval pause/resume
├── hitl_handler.py       # HITL question handling
└── persistence.py        # _persist_agent_data, token tracking
```

**Benefit**: Each file has single responsibility, easier to debug specific flows.

### 2. Consolidate API Response Models

**Problem**: Many similar response models across route files.

**Example** (from different files):
```python
# sessions.py
class SessionResponse(BaseModel): ...
class SessionListResponse(BaseModel): ...
class PaginatedSessionsResponse(BaseModel): ...

# chat.py
class ChatResponse(BaseModel): ...
class ChatStatusResponse(BaseModel): ...
```

**Recommendation**: Create `druppie/api/schemas.py` with shared models:
```python
# All response models in one place
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
```

### 3. Remove Duplicate CRUD Functions

**Problem**: `crud.py` has similar patterns repeated:

```python
def create_session(...): ...
def get_session(...): ...
def update_session(...): ...
def delete_session(...): ...

def create_project(...): ...
def get_project(...): ...
def update_project(...): ...
def delete_project(...): ...
# ... repeated for 15+ entities
```

**Recommendation**: Create generic CRUD mixin:
```python
class CRUDBase(Generic[T]):
    def create(self, db, obj): ...
    def get(self, db, id): ...
    def update(self, db, id, **kwargs): ...
    def delete(self, db, id): ...

session_crud = CRUDBase[Session]()
project_crud = CRUDBase[Project]()
```

**Benefit**: Reduces `crud.py` from 1234 to ~400 lines.

### 4. Simplify Approval Flow

**Problem**: Approval handling is split across:
- `mcp_client.py` (creates approval)
- `loop.py` (saves agent_state)
- `approvals.py` API (resolves approval)
- `runtime.py` (resumes agent)

**Recommendation**: Create `ApprovalManager` class:
```python
class ApprovalManager:
    def request_approval(self, tool_call, agent_state) -> Approval
    def resolve(self, approval_id, user_id, approved: bool)
    def get_resumable_state(self, approval_id) -> AgentState
    def resume(self, approval_id, tool_result) -> ExecutionResult
```

### 5. Unify Token Tracking

**Problem**: Token updates scattered across:
- `execution_context.py` (in-memory accumulation)
- `runtime.py` (agent-level tracking)
- `loop.py` (`update_agent_run_tokens`, `update_session_tokens`)
- `crud.py` (database updates)

**Recommendation**: Create `TokenTracker` class:
```python
class TokenTracker:
    def __init__(self, session_id): ...
    def record_llm_call(self, agent_run_id, tokens): ...
    def get_session_total(self) -> int
    def persist(self, db): ...  # Single point of DB update
```

---

## Medium-Priority Simplifications

### 6. Remove Redundant Session State Reconstruction

**Problem**: Multiple places reconstruct session state from DB:
- `get_execution_state()` in loop.py
- `_get_session_state()` in loop.py
- Various places in `sessions.py`

**Recommendation**: Single `SessionStateBuilder` with caching.

### 7. Consolidate WebSocket Events

**Problem**: Event emission duplicated:
- `ExecutionContext.emit()`
- `connection_manager.broadcast()`
- Various API endpoints emitting directly

**Recommendation**: All events go through `ExecutionContext.emit()` which handles both DB persistence and WebSocket broadcast.

### 8. Simplify MCP Client

**Problem**: `mcp_client.py` (1183 lines) handles:
- HTTP calls to MCP servers
- Approval rule checking
- Tool schema validation
- Context injection

**Recommendation**: Split into:
- `mcp_http.py` - Pure HTTP client (200 lines)
- `mcp_approval.py` - Approval rule checking (200 lines)
- `mcp_tools.py` - Tool registry and validation (200 lines)

### 9. Agent Definition Loading

**Problem**: YAML agent loading repeated in:
- `runtime.py`
- `agents.py` API
- `loop.py`

**Recommendation**: `AgentRegistry` singleton that loads once:
```python
class AgentRegistry:
    _agents: dict[str, AgentConfig] = {}

    def get(self, agent_id: str) -> AgentConfig
    def list_all(self) -> list[AgentConfig]
```

---

## Low-Priority Simplifications

### 10. Remove Deprecated Fields

The database has some unused/deprecated columns that could be cleaned up:
- Check if all workflow step statuses are actually used
- Check if `user_tokens` table is used (vs Keycloak tokens)

### 11. Consolidate Build/Deploy Logic

`builder.py` and `projects.py` API have overlapping build logic.

### 12. Standardize Error Handling

Some routes use `raise HTTPException()`, others use error classes from `errors.py`. Standardize on one approach.

---

## Implementation Priority

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Split `loop.py` | High | High - easier debugging |
| 2 | Generic CRUD | Medium | Medium - less code |
| 3 | Consolidate response models | Low | Medium - consistency |
| 4 | `ApprovalManager` class | Medium | High - clearer flow |
| 5 | `TokenTracker` class | Medium | Medium - reliability |
| 6 | Split `mcp_client.py` | Medium | Medium - easier to maintain |

---

## Suggested First Steps

1. **Create `docs/` folder** (done)
2. **Document current architecture** (done - ARCHITECTURE.md)
3. **Create debug cheatsheet** (done - DEBUG_CHEATSHEET.md)
4. **Add inline comments to loop.py** explaining each major section
5. **Extract `_persist_agent_data` into `persistence.py`** as first split
6. **Create generic CRUD base class** to reduce duplication

---

## What NOT to Change

- **Database schema** - Already well-normalized
- **YAML-based config** - Good separation of concerns
- **MCP microservices** - Good architecture
- **Event-driven WebSocket** - Works well
- **SQLAlchemy models** - Clean mapping

The core architecture is sound. The simplifications are about code organization, not architectural changes.
