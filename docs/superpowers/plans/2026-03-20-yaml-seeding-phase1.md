# Phase 1: YAML Seeding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace `scripts/seed_builder_retry.py` (679 lines of hardcoded Python/SQL) with a declarative YAML fixture system that reads YAML files, validates with Pydantic, generates deterministic UUIDs, and inserts records via SQLAlchemy.

**Architecture:** YAML fixture files in `fixtures/sessions/` define session state declaratively. A Pydantic schema validates the format. A loader reads validated fixtures and creates DB records (record-only mode — no MCP execution, no Gitea). Deterministic UUIDs from human-readable IDs ensure idempotent seeding.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x (sync), Pydantic 2.x, PyYAML, pytest

---

## File Structure

```
fixtures/
  sessions/
    00-todo-app-builder-failed.yaml
    01-weather-dashboard-completed.yaml
    02-calculator-paused-approval.yaml
    03-blog-platform-active.yaml
    04-gibberish-router-failed.yaml
    05-general-chat-simple.yaml
    06-ecommerce-completed.yaml
    07-kanban-board-active.yaml
    08-portfolio-completed.yaml
    09-recipe-app-builder-failed.yaml
    10-weather-update-completed.yaml

druppie/
  fixtures/
    __init__.py
    schema.py          # Pydantic validation models
    ids.py             # Deterministic UUID generation
    loader.py          # YAML → DB records (record-only mode)

scripts/
  seed.py             # CLI entry point

druppie/tests/
  test_fixture_ids.py
  test_fixture_schema.py
  test_fixture_loader.py
```

---

## Task 1: Deterministic UUID Generation

**Files:**
- Create: `druppie/fixtures/ids.py`
- Create: `druppie/tests/test_fixture_ids.py`

- [ ] **Step 1: Write `ids.py`**

```python
"""Deterministic UUID generation for YAML fixtures."""
import uuid

FIXTURE_NAMESPACE = uuid.UUID("d1a7e5f0-cafe-4b1d-b0a1-f1x7ure5eed5")

def fixture_uuid(session_id: str, *parts: str | int) -> uuid.UUID:
    name = session_id + ":" + ":".join(str(p) for p in parts) if parts else session_id
    return uuid.uuid5(FIXTURE_NAMESPACE, name)
```

- [ ] **Step 2: Write tests**

Test that: same inputs → same UUID, different inputs → different UUIDs, valid v5 UUID format, various part combinations work.

- [ ] **Step 3: Run tests**

Run: `cd /home/nuno/Documents/cleaner-druppie-research-e2e && python -m pytest druppie/tests/test_fixture_ids.py -v`

- [ ] **Step 4: Commit**

```bash
git add druppie/fixtures/ids.py druppie/fixtures/__init__.py druppie/tests/test_fixture_ids.py
git commit -m "feat: add deterministic UUID generation for YAML fixtures"
```

---

## Task 2: Pydantic Validation Schema

**Files:**
- Create: `druppie/fixtures/schema.py`
- Create: `druppie/tests/test_fixture_schema.py`

- [ ] **Step 1: Write `schema.py`**

Define Pydantic models: `SessionFixture`, `SessionMetadata`, `AgentRunFixture`, `ToolCallFixture`, `ApprovalFixture`, `MessageFixture`. The `ToolCallFixture.tool` field uses `server:name` format (e.g., `builtin:set_intent`) with properties to split them.

Key fields:
- `SessionMetadata`: id, title, status, user, intent, project_name, language, hours_ago
- `AgentRunFixture`: id (agent_id), status, error_message, planned_prompt, tool_calls
- `ToolCallFixture`: tool, arguments, status, result, error_message, answer (for HITL), approval
- `ApprovalFixture`: required_role, status, approved_by
- `MessageFixture`: role, content, agent_id

- [ ] **Step 2: Write tests**

Test valid YAML parsing, missing required fields raise ValidationError, tool property splits server/name, invalid status values rejected, minimal fixture valid.

- [ ] **Step 3: Run tests**

Run: `cd /home/nuno/Documents/cleaner-druppie-research-e2e && python -m pytest druppie/tests/test_fixture_schema.py -v`

- [ ] **Step 4: Commit**

```bash
git add druppie/fixtures/schema.py druppie/tests/test_fixture_schema.py
git commit -m "feat: add Pydantic validation schema for YAML fixtures"
```

---

## Task 3: YAML Loader (Record-Only Mode)

**Files:**
- Create: `druppie/fixtures/loader.py`
- Update: `druppie/fixtures/__init__.py`

This is the main work. The loader reads YAML, validates, and inserts DB records.

- [ ] **Step 1: Implement `load_fixtures()`**

Glob `*.yaml` files sorted alphabetically, parse with `yaml.safe_load`, validate with `SessionFixture`.

- [ ] **Step 2: Implement `seed_fixture()`**

Core logic:
1. Generate session UUID from `fixture.metadata.id` using `fixture_uuid()`
2. Delete existing records for idempotency
3. Look up user by username (create if not exists)
4. Create Project if `project_name` is set (placeholder repo fields for record-only)
5. Create Session record
6. Create user message (sequence 0)
7. For each agent run:
   - Create AgentRun (sequence = index + 1)
   - For active runs: create synthetic LlmCall (provider="zai", model="glm-4.7")
   - For each tool call: create ToolCall, plus Approval/Question records as needed
   - For completed agents: create assistant message from done() summary
8. Compute session token totals

Token counts: completed → prompt=3000, completion=1000. Running → prompt=1500, completion=0. Pending → 0/0.

- [ ] **Step 3: Implement `seed_all()`**

Load all fixtures, seed each, return count.

- [ ] **Step 4: Run existing tests to verify no imports broken**

Run: `cd /home/nuno/Documents/cleaner-druppie-research-e2e && python -m pytest druppie/tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add druppie/fixtures/loader.py druppie/fixtures/__init__.py
git commit -m "feat: add YAML fixture loader with record-only mode"
```

---

## Task 4: Convert 11 Sessions to YAML Fixtures

**Files:**
- Create: `fixtures/sessions/00-todo-app-builder-failed.yaml` through `10-weather-update-completed.yaml`

Reference: `/home/nuno/Documents/cleaner-druppie-research-e2e/scripts/seed_builder_retry.py` lines 144-344

- [ ] **Step 1: Create all 11 YAML files**

Convert each session from the SESSIONS list. Key mappings:
- ns → metadata.id (human readable)
- title → metadata.title
- status → metadata.status
- intent → metadata.intent
- project_name → metadata.project_name
- hours_ago → metadata.hours_ago
- agents tuple (agent_id, status, error, prompt) → agents list with tool_calls

Every completed agent gets a `builtin:done` tool call. Router gets `builtin:set_intent` if intent is set. Planner gets `builtin:make_plan`. Failed agents get a failed tool call with error.

| File | Source ns | Status | Key Feature |
|------|-----------|--------|-------------|
| 00 | 0xA000 | failed | Builder failed, long planned_prompt |
| 01 | 0xA001 | completed | Full pipeline through deployer |
| 02 | 0xA002 | paused_approval | Architect running |
| 03 | 0xA003 | active | Tester running |
| 04 | 0xA004 | failed | No project, router failed |
| 05 | 0xA005 | completed | General chat, router only |
| 06 | 0xA006 | completed | No BA, skipped |
| 07 | 0xA007 | active | BA running |
| 08 | 0xA008 | completed | Full pipeline |
| 09 | 0xA009 | failed | Builder failed, different error |
| 10 | 0xA00A | completed | update_project intent |

- [ ] **Step 2: Validate all fixtures load without errors**

```python
from druppie.fixtures.loader import load_fixtures
from pathlib import Path
fixtures = load_fixtures(Path("fixtures/sessions"))
print(f"Loaded {len(fixtures)} fixtures")  # Should be 11
```

- [ ] **Step 3: Commit**

```bash
git add fixtures/
git commit -m "feat: convert 11 seed sessions to YAML fixture files"
```

---

## Task 5: CLI Seed Script

**Files:**
- Create: `scripts/seed.py`

- [ ] **Step 1: Write `seed.py`**

Minimal CLI: parse `--fixtures-dir` (default `fixtures/sessions/`), set up DB connection via `DATABASE_URL` env var (default `postgresql://druppie:druppie_secret@localhost:5533/druppie`), call `seed_all()`, print summary.

- [ ] **Step 2: Commit**

```bash
git add scripts/seed.py
git commit -m "feat: add YAML-based seed.py CLI script"
```

---

## Task 6: Integration Tests

**Files:**
- Create: `druppie/tests/test_fixture_loader.py`

- [ ] **Step 1: Write integration tests**

Test cases using SQLite in-memory (or PostgreSQL if UUID/JSON types cause issues):
1. Minimal session → Session + user message created
2. Completed router → AgentRun + LlmCall + ToolCalls + Message
3. Failed builder → AgentRun with error, failed ToolCall
4. Pending agent → AgentRun, no LlmCall/ToolCalls
5. Running agent → AgentRun + LlmCall, no ToolCalls
6. Tool call with approval → Approval record created
7. HITL tool call with answer → Question record created
8. Idempotency → seed twice, no duplicates
9. Token totals correct
10. Full round-trip with real YAML file

- [ ] **Step 2: Run tests**

Run: `cd /home/nuno/Documents/cleaner-druppie-research-e2e && python -m pytest druppie/tests/test_fixture_loader.py -v`

- [ ] **Step 3: Commit**

```bash
git add druppie/tests/test_fixture_loader.py
git commit -m "test: add integration tests for YAML fixture loader"
```

---

## Task 7: Manual Parity Verification

- [ ] **Step 1: Reset DB and seed with new script**

```bash
docker compose --profile reset-db run --rm reset-db
DATABASE_URL=postgresql://druppie:druppie_secret@localhost:5533/druppie python scripts/seed.py
```

- [ ] **Step 2: Verify session counts**

```sql
SELECT status, count(*) FROM sessions GROUP BY status;
-- Expected: failed=3, completed=5, active=2, paused_approval=1
```

- [ ] **Step 3: Verify agent run and tool call counts**

```sql
SELECT count(*) FROM agent_runs;  -- ~65 (same as original)
SELECT count(*) FROM tool_calls;  -- ~65 (same as original)
```

- [ ] **Step 4: Load frontend and verify sidebar**

Open http://localhost:5273, verify sessions appear with correct statuses.

- [ ] **Step 5: Commit verification notes**

```bash
git commit --allow-empty -m "chore: verified YAML seed parity with old seed script"
```

---

## Task Dependencies

```
Task 1 (ids.py) ──┐
                   ├──→ Task 3 (loader.py) ──→ Task 5 (seed.py CLI)
Task 2 (schema.py)┘         │                       │
                             ├──→ Task 6 (integration tests)
Task 4 (YAML files) ────────┘         │
                                       └──→ Task 7 (parity check)
```

Tasks 1 and 2 are independent and can run in parallel.
Task 4 can start after Tasks 1+2 (needs schema for validation).
Task 3 depends on Tasks 1+2.
Tasks 5 and 6 depend on Task 3.
Task 7 depends on everything.

---

## Notes

- **User lookup**: Loader must find `admin` user by username. If not found, create one (matching current seed script behavior).
- **SQLite vs PostgreSQL**: Tests may need adaptation for UUID/JSON column types. Start with SQLite; if issues, switch to PostgreSQL test container.
- **ON DELETE CASCADE**: Session deletion should cascade. Verify FK constraints. Project needs separate deletion.
- **Builder planned_prompt**: Session #0 has a very long prompt. Use YAML `|` block scalar.
- **No Gitea in Phase 1**: Record-only mode uses placeholder repo fields (repo_name=project_name, repo_owner="druppie_admin").
