# Debugging Cheatsheet

Quick reference for common debugging tasks.

## Session States at a Glance

| Status | Meaning | What's Blocking |
|--------|---------|-----------------|
| `active` | Running | Nothing, still executing |
| `paused_approval` | Waiting | Check `approvals` table for `status='pending'` |
| `paused_hitl` | Waiting | Check `hitl_questions` table for `status='pending'` |
| `completed` | Done | Nothing |
| `failed` | Error | Check `session_events` for error events |

## Quick Queries

### Find what's blocking a session

```sql
-- Session status
SELECT id, status, title FROM sessions WHERE id = 'SESSION_ID';

-- Pending approvals
SELECT id, tool_name, required_role, created_at
FROM approvals
WHERE session_id = 'SESSION_ID' AND status = 'pending';

-- Pending questions
SELECT id, question, agent_id, created_at
FROM hitl_questions
WHERE session_id = 'SESSION_ID' AND status = 'pending';
```

### Token audit

```sql
-- Session total vs sum of agent runs
SELECT
    s.total_tokens as session_total,
    COALESCE(SUM(ar.total_tokens), 0) as agent_sum,
    s.total_tokens - COALESCE(SUM(ar.total_tokens), 0) as difference
FROM sessions s
LEFT JOIN agent_runs ar ON ar.session_id = s.id
WHERE s.id = 'SESSION_ID'
GROUP BY s.id;
```

### Execution timeline

```sql
SELECT
    timestamp,
    event_type,
    agent_id,
    tool_name,
    title
FROM session_events
WHERE session_id = 'SESSION_ID'
ORDER BY timestamp;
```

### Check resumption state saved

```sql
-- For approvals
SELECT id, tool_name,
    agent_state IS NOT NULL as has_agent_state,
    agent_state->>'agent_id' as paused_agent
FROM approvals
WHERE session_id = 'SESSION_ID';

-- For HITL questions
SELECT id, question,
    agent_state IS NOT NULL as has_agent_state
FROM hitl_questions
WHERE session_id = 'SESSION_ID';
```

## Log Commands

```bash
# Backend logs (most useful)
docker logs druppie-new-backend -f --tail 100

# Filter for specific session
docker logs druppie-new-backend 2>&1 | grep "SESSION_ID"

# Filter for approvals
docker logs druppie-new-backend 2>&1 | grep -i "approval"

# Filter for tool calls
docker logs druppie-new-backend 2>&1 | grep -i "tool_call"

# Filter for errors
docker logs druppie-new-backend 2>&1 | grep -i "error\|exception\|failed"

# MCP servers
docker logs mcp-coding -f --tail 50
docker logs mcp-docker -f --tail 50
```

## Database Access

```bash
# Connect to PostgreSQL
docker exec -it druppie-postgres psql -U druppie -d druppie

# Quick table counts
\dt
SELECT 'sessions' as table_name, COUNT(*) FROM sessions
UNION ALL SELECT 'approvals', COUNT(*) FROM approvals
UNION ALL SELECT 'hitl_questions', COUNT(*) FROM hitl_questions
UNION ALL SELECT 'agent_runs', COUNT(*) FROM agent_runs;
```

## Common Issues

### Issue: Session stuck at paused_approval forever

**Diagnosis:**
```sql
SELECT a.id, a.tool_name, a.required_role, a.status,
       u.username as resolved_by
FROM approvals a
LEFT JOIN users u ON a.resolved_by = u.id
WHERE a.session_id = 'SESSION_ID'
ORDER BY a.created_at DESC;
```

**Common causes:**
1. No user with required role logged in
2. Approval was rejected but session not updated
3. `agent_state` not saved, resume fails silently

### Issue: Agent asks same question twice

**Diagnosis:**
```sql
-- Check if clarifications were saved
SELECT agent_state->>'hitl_clarifications' as clarifications
FROM approvals
WHERE session_id = 'SESSION_ID'
ORDER BY created_at DESC
LIMIT 1;
```

**Common cause:** Clarifications lost during pause/resume cycle.

### Issue: Tokens = 0 despite completed session

**Diagnosis:**
```sql
-- Check if LLM calls were recorded
SELECT COUNT(*), SUM(total_tokens)
FROM llm_calls
WHERE session_id = 'SESSION_ID';

-- Check agent run tokens
SELECT agent_id, total_tokens
FROM agent_runs
WHERE session_id = 'SESSION_ID';
```

**Common cause:** `_persist_agent_data()` not called before returning.

### Issue: Workflow doesn't continue after approval

**Diagnosis:**
```sql
-- Check workflow state
SELECT w.status, w.current_step,
       ws.step_index, ws.agent_id, ws.status as step_status
FROM workflows w
JOIN workflow_steps ws ON ws.workflow_id = w.id
WHERE w.session_id = 'SESSION_ID'
ORDER BY ws.step_index;
```

**Common cause:** `current_step` not incremented, or step marked failed.

## Frontend Debug Page

Navigate to: `http://localhost:5273/debug/SESSION_ID`

Shows:
- Event timeline with timestamps
- Per-agent token breakdown
- Raw LLM calls (expand for full request/response)
- Tool call parameters

## API Debug Endpoints

```bash
# Session status
curl http://localhost:8100/api/chat/SESSION_ID/status

# Execution trace
curl http://localhost:8100/api/sessions/SESSION_ID/trace

# Pending approvals
curl http://localhost:8100/api/approvals

# Admin table browser
curl http://localhost:8100/api/admin/tables
curl http://localhost:8100/api/admin/table/sessions?limit=10
```

## Key Files to Check

| What | File | Line to look for |
|------|------|------------------|
| Session persistence | `druppie/core/loop.py` | `_persist_agent_data` |
| Token update | `druppie/core/loop.py` | `update_session_tokens` |
| Approval creation | `druppie/core/mcp_client.py` | `create_approval` |
| Agent state save | `druppie/core/loop.py` | `update_approval.*agent_state` |
| Resumption | `druppie/core/loop.py` | `resume_from_step_approval` |
| HITL handling | `druppie/core/loop.py` | `resume_from_question_answer` |

## Reset Commands

```bash
# Restart backend only
docker restart druppie-new-backend

# Full restart
./setup.sh restart

# Clean database (WARNING: deletes all data)
./setup.sh clean && ./setup.sh all
```
