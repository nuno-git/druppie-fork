# Database Redesign - Simplified Schema

## Goals

1. **1:1 mapping** between database tables and domain models
2. **Remove unnecessary tables** - let MCPs handle their own state
3. **Clear naming** - consistent naming conventions
4. **Simpler is better** - fewer tables, clearer purpose

---

## Tables to REMOVE

### 1. `workspaces` - Move to Coding MCP
The Coding MCP already manages workspaces (git clones) on the filesystem.
The main database doesn't need to track workspace state.

**Before:** Session → Workspace (in DB) → local_path
**After:** Coding MCP manages workspace lifecycle internally

### 2. `builds` - Move to Docker MCP
Docker containers already have labels. The Docker MCP can track:
- `druppie.project_id`
- `druppie.session_id`
- `druppie.branch`

No need to duplicate this in the database.

### 3. `deployments` - Move to Docker MCP
Same as builds - Docker container labels are the source of truth.
The DeploymentService queries Docker MCP directly.

### 4. `session_events` - Unnecessary denormalization
This table was created for "easy timeline display" but it duplicates
information already in messages, agent_runs, tool_calls, etc.

The repository layer can build the timeline from existing tables.

---

## Tables to KEEP (Simplified)

### Core Tables

| Table | Purpose | Primary Key |
|-------|---------|-------------|
| `users` | User accounts (synced from Keycloak) | UUID |
| `user_roles` | User role mappings | (user_id, role) |
| `projects` | Project metadata (links to Gitea repo) | UUID |
| `sessions` | Conversation sessions | UUID |

### Execution Tables

| Table | Purpose | Primary Key |
|-------|---------|-------------|
| `messages` | User/assistant messages | UUID |
| `agent_runs` | Agent executions (including pending plans) | UUID |
| `llm_calls` | LLM API calls for debugging | UUID |
| `tool_calls` | Tool executions | UUID |

### Interaction Tables

| Table | Purpose | Primary Key |
|-------|---------|-------------|
| `approvals` | Tool approval requests | UUID |
| `questions` | HITL questions (renamed from hitl_questions) | UUID |

---

## 1:1 Naming Convention

```
Database Table    SQLAlchemy Model    Domain Model(s)
─────────────────────────────────────────────────────
users             User                UserInfo
projects          Project             ProjectSummary, ProjectDetail
sessions          Session             SessionSummary, SessionDetail
messages          Message             Message
agent_runs        AgentRun            AgentRunSummary, AgentRunDetail
llm_calls         LlmCall             LlmCallSummary
tool_calls        ToolCall            ToolCallSummary, ToolCallDetail
approvals         Approval            ApprovalSummary, ApprovalDetail
questions         Question            QuestionSummary, QuestionDetail
```

**Pattern:**
- Summary = lightweight, for lists
- Detail = full data, for single-item views

---

## Session Timeline

The session detail includes a timeline of events in chronological order.

### Option A: Separate lists (simpler)
```python
class SessionDetail(SessionSummary):
    messages: list[Message]           # All messages
    agent_runs: list[AgentRunSummary] # All agent runs
```
Frontend merges and sorts by timestamp.

### Option B: Pre-merged timeline (better UX)
```python
class TimelineEntry(BaseModel):
    """One entry in the session timeline."""
    timestamp: datetime
    entry_type: Literal["message", "agent_run"]
    message: Message | None = None
    agent_run: AgentRunSummary | None = None

class SessionDetail(SessionSummary):
    timeline: list[TimelineEntry]  # Pre-sorted by timestamp
```

**Recommendation:** Option B - the API does the work so frontend is simpler.

Rename `ChatItem` → `TimelineEntry` for clarity.

---

## Schema Changes

### Remove
```sql
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS builds;
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS session_events;
```

### Rename
```sql
ALTER TABLE hitl_questions RENAME TO questions;
ALTER TABLE hitl_question_choices RENAME TO question_choices;
```

### No changes needed
- users, user_roles, user_tokens
- projects
- sessions
- messages
- agent_runs
- llm_calls
- tool_calls
- approvals

---

## File Changes

### Database Models (druppie/db/models/)
- DELETE: workspace.py, build.py, event.py
- RENAME: question.py (HitlQuestion → Question)
- UPDATE: __init__.py to remove deleted exports

### Domain Models (druppie/domain/)
- RENAME: ChatItem → TimelineEntry
- RENAME: QuestionDetail (keep name, it's already good)
- UPDATE: session.py to use TimelineEntry

### Repositories
- DELETE: Any workspace/build/deployment repo methods
- UPDATE: session_repository.py to build timeline from messages + agent_runs

---

## Migration Steps

1. Update domain models (rename ChatItem → TimelineEntry)
2. Update db models (delete workspace, build, event files)
3. Rename HitlQuestion → Question in db models
4. Update repositories to match
5. Update __init__.py exports
6. Test all imports
