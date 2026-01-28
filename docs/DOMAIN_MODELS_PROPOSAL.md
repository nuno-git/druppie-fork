# Proposal: Domain Models as Universal Contract

## Goal

Make the entire application use domain models consistently. The database is the single source of truth.

## Current Problem

```python
# MainLoop returns arbitrary dicts
async def process_message(...) -> dict[str, Any]:
    return {
        "success": True,
        "response": "...",
        "session_id": "...",
        "paused": True,
        "approval_id": "...",
    }

# chat.py has to parse these dicts
result = await loop.process_message(...)
if result.get("paused"):
    if result.get("approval_id"):
        status = "paused_approval"
    # ... complex parsing logic
```

## Solution: Database is Source of Truth

MainLoop already saves everything to the database. It should just return the session_id, and callers fetch the SessionDetail to see what happened.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CHAT ROUTE                                 │
│                                                                      │
│   1. Call MainLoop.process_message() → returns session_id           │
│   2. Call SessionService.get_detail(session_id) → returns SessionDetail │
│   3. Return SessionDetail to frontend                               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          MAIN LOOP                                   │
│                                                                      │
│   1. Creates/updates session in DB                                  │
│   2. Runs agents, saves agent_runs, messages, etc.                  │
│   3. Updates session.status (completed, paused_approval, etc.)      │
│   4. Returns session_id (just the ID, nothing else)                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          DATABASE                                    │
│                                                                      │
│   Session (status = paused_approval | paused_hitl | completed)      │
│   ChatItem (messages, agent_runs in timeline)                       │
│   Approval (pending approval with details)                          │
│   HitlQuestion (pending question with details)                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Existing Models We Reuse

```python
# Session status already has what we need
class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED_APPROVAL = "paused_approval"
    PAUSED_HITL = "paused_hitl"
    COMPLETED = "completed"
    FAILED = "failed"

# SessionDetail already includes everything
class SessionDetail(BaseModel):
    id: UUID
    status: SessionStatus  # ← tells us if paused/completed
    chat: list[ChatItem]   # ← includes all messages and agent runs
    # ... pending approvals/questions visible in chat timeline
```

## Changes Required

### 1. Update MainLoop return type

```python
# core/loop.py

# Before
async def process_message(...) -> dict[str, Any]:
    ...
    return {
        "success": True,
        "response": response,
        "session_id": session_id,
        "paused": True,
        "approval_id": str(approval.id),
    }

# After
async def process_message(...) -> UUID:
    ...
    # All data is saved to DB, just return the session ID
    return UUID(session_id)
```

### 2. Update resume methods

```python
# Before
async def resume_from_approval(...) -> dict[str, Any]:
    return {"success": True, "response": "..."}

# After
async def resume_from_approval(...) -> UUID:
    # Resumes execution, updates DB
    return session_id
```

### 3. Simplify chat.py

```python
# Before (~180 lines with dict parsing)
@router.post("/chat")
async def chat(request: ChatRequest, ...) -> ChatResponse:
    result = await loop.process_message(...)

    # Parse dict to determine status
    status = "completed"
    approval_id = None
    if result.get("paused"):
        if result.get("approval_id"):
            status = "paused_approval"
            approval_id = result.get("approval_id")

    return ChatResponse(
        success=result.get("success"),
        session_id=result.get("session_id"),
        status=status,
        ...
    )

# After (~20 lines)
@router.post("/chat")
async def chat(
    request: ChatRequest,
    session_service: SessionService = Depends(get_session_service),
    loop: MainLoop = Depends(get_loop),
    user: dict = Depends(get_current_user),
) -> SessionDetail:
    session_id = await loop.process_message(
        message=request.message,
        session_id=UUID(request.session_id) if request.session_id else None,
        user_id=user.get("sub"),
        project_id=UUID(request.project_id) if request.project_id else None,
    )
    return session_service.get_detail(session_id, UUID(user["sub"]), get_user_roles(user))
```

### 4. Update WorkflowService

```python
# Before
async def resume_from_approval(self, session_id, approval_id) -> dict:
    return await self.main_loop.resume_from_approval(...)

# After
async def resume_from_approval(self, session_id, approval_id) -> UUID:
    return await self.main_loop.resume_from_approval(...)
```

### 5. Update approvals.py and questions.py

```python
# Before - returns workflow_result dict
return ApprovalResponse(
    approval=approval,
    workflow_resumed=True,
    workflow_result={"success": True, ...},
)

# After - returns session_id, caller can fetch session if needed
return ApprovalResponse(
    approval=approval,
    workflow_resumed=True,
    session_id=session_id,  # Just the ID
)
```

## Files to Change

| File | Change |
|------|--------|
| `core/loop.py` | Return `UUID` instead of `dict` |
| `api/routes/chat.py` | Fetch SessionDetail after process_message |
| `services/workflow_service.py` | Return `UUID` |
| `api/routes/approvals.py` | Simplify response |
| `api/routes/questions.py` | Simplify response |

## Benefits

1. **No new models** - Reuse existing SessionDetail, ChatItem
2. **Single source of truth** - Database, not return values
3. **Type safety** - UUID return is clear and typed
4. **Simpler code** - chat.py becomes trivial
5. **Consistent** - Same pattern everywhere

## Implementation Steps

1. Update `MainLoop.process_message()` to return `UUID`
2. Update `MainLoop.resume_from_approval()` to return `UUID`
3. Update `MainLoop.resume_from_question()` to return `UUID`
4. Update `chat.py` to fetch SessionDetail
5. Update `WorkflowService` return types
6. Update `approvals.py` response
7. Update `questions.py` response
