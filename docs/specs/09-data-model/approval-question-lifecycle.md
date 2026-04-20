# Approval + Question Lifecycles

Both follow a similar two-phase pattern.

## Approvals

```
   ┌─────────┐
   │ PENDING │ ◄── inserted when tool_call gated
   └────┬────┘
        │ POST /api/approvals/{id}/approve   OR   /reject
        ▼
   ┌────────────────────────────┐
   │ Phase 1 (fast, sync):      │
   │   UPDATE approvals ...     │
   │   COMMIT                   │
   └────────────────────────────┘
        │
        ▼
   APPROVED / REJECTED (terminal state for approval row)
        │
        ▼
   ┌────────────────────────────┐
   │ Phase 2 (background):      │
   │   spawn resume task        │
   │   execute tool OR fail     │
   │   resume agent             │
   └────────────────────────────┘
```

States:
- `PENDING` — awaiting human.
- `APPROVED` — allowed; resolved_by + resolved_at set.
- `REJECTED` — denied; rejection_reason + resolved_by + resolved_at set.

## Questions (HITL)

```
   ┌─────────┐
   │ PENDING │ ◄── inserted when hitl_ask_* tool called
   └────┬────┘
        │ POST /api/questions/{id}/answer
        ▼
   ┌────────────────────────────┐
   │ Phase 1:                   │
   │   UPDATE questions ...     │
   │   COMMIT                   │
   └────────────────────────────┘
        │
        ▼
   ANSWERED
        │
        ▼
   ┌────────────────────────────┐
   │ Phase 2 (background):      │
   │   resume agent with answer │
   └────────────────────────────┘
```

States (from `QuestionStatus` in `druppie/domain/common.py`):
- `PENDING` — awaiting answer.
- `ANSWERED` — answer + answered_at set.

There is no dedicated `CANCELLED` state for questions. When a user cancels the session, the question row is left as `PENDING`; the session-level `ACTIVE → FAILED`/`PAUSED` transition is what effectively drops the outstanding question.

## Why two phases

The HTTP response must be fast (the UI is waiting). The orchestrator resume takes seconds to minutes. Splitting them:
- Fast phase commits the user's decision.
- Slow phase runs asynchronously.
- If slow phase crashes mid-way, the decision is still recorded. A user Resume will continue.

## Authorization

Approvals:
- Global-role approvals: `required_role IN user_roles`.
- Session-owner approvals: `required_role = 'session_owner' AND session.user_id = current_user`.
- Admin bypass.

Questions:
- Only the session owner (or admin) can answer.

## Storage of arguments

`approvals.arguments` is a JSON snapshot of what the agent wanted to do. After approval, the stored args are the ones used for execution — even if the tool definition or agent has changed since, the approved args are what run.

This is a deliberate decision: an approver is authorising the specific arguments, not a future version of the tool.

## Choices (questions)

For multiple-choice questions:
- `choices: JSON = [{"text": "Option A"}, {"text": "Option B"}, {"text": "Other"}]` (system auto-appends "Other" / "Anders").
- `selected_indices: JSON = [0, 2]` — which choices the user picked.
- `answer: TEXT` — display string of chosen texts OR free-form text if "Other" selected.

The agent sees the rendered `answer` string in its tool result, not the indices.

## Cancellation

A session-level Cancel sets the session to PAUSED. Open approvals and questions are NOT auto-resolved — they remain PENDING. If the user later deletes the session, they cascade away. If the user resumes, the agent is still parked on the same approval/question.

## Audit trail

- `approvals.resolved_by` — who clicked approve/reject.
- `questions.answer` — verbatim.
- Both have `created_at` and resolution timestamps.
- Deletion cascades with session — no separate audit log today.
