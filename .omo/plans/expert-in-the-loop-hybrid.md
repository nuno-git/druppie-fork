# Implementation Plan: Developer Expert-in-the-Loop (Hybrid Approach)

**Approach**: Hybrid — PR #171 `ask_expert` for interactive gates (G1-G3) + existing docker tool approval for deployment gate (G4)
**Branch**: `pr-190` (base: `colab-dev`)
**Estimated Effort**: 2-3 days

---

## Overview

Add 4 developer expert-in-the-loop gates to the ultimate dev agent pipeline:

| Gate | Agent | Mechanism | Trigger |
|------|-------|-----------|---------|
| G1 — Plan Approval | `builder_planner` | `ask_expert_multiple_choice_question` | After writing `builder_plan.md` |
| G2 — Complex Choices | `builder_planner` | `ask_expert_multiple_choice_question` | When encountering architectural decisions with 2+ viable options |
| G3 — Test Review | `test_builder` | `ask_expert_multiple_choice_question` | After writing tests |
| G4 — Deploy Approval | `deployer` | `approval_overrides` on `docker:build` + `docker:compose_up` | Before deployment |

**Data flow:**
```
builder_planner ──[G1: approve plan?]──► test_builder ──[G3: accept tests?]──►
developer → test_executor → reviewer → deployer ──[G4: approve deploy?]──► done
         └─[G2: architectural choice?] (conditional, during G1 phase)
```

---

## Phase 1: Import PR #171 (ask_expert infrastructure)

**Goal**: Get the `ask_expert_question` and `ask_expert_multiple_choice_question` tools into the codebase.

### Step 1.1: Squash-cherry-pick the 3 core commits

Cherry-pick all 3 commits as one squashed operation to minimize conflict resolution effort:

```bash
git fetch origin pull/171/head:pr-171
git checkout pr-190

# Apply all 3 commits without committing
git cherry-pick --no-commit 0cca6a8c 5e84d3cd 916f7c5b
```

**Expected conflicts (8 total, all content-mergeable):**

| # | File | Conflict Nature | Resolution |
|---|------|-----------------|------------|
| 1 | `druppie/agents/definitions/general/architect.yaml` | pr-190 added `web:` tools section where PR 171 adds `experts:` block | Keep pr-190's `web:` tools, add `experts: [architect]` below it |
| 2 | `druppie/api/routes/questions.py` | Import: `create_tracked_task` vs `create_session_task` | Keep pr-190's `create_tracked_task`, add PR 171's `PendingQuestionList` import |
| 3 | `frontend/src/components/NavRail.jsx` | Icon imports: pr-190 added `Code2, Terminal`, PR 171 added `HelpCircle` | Keep all: `Code2, Terminal, HelpCircle` |
| 4 | `frontend/src/components/chat/SessionDetail.jsx` | Continue button guard + `canControlSession` wrapper | Keep pr-190's `paused_hitl` status, add PR 171's `canControlSession` guard |
| 5 | `druppie/agents/definitions/general/architect.yaml` (commit 2) | Same region, now replacing `extra_builtin_tools` with `experts:` | Should resolve with #1 above since squash |
| 6 | `druppie/domain/agent_definition.py` | `experts: list[str]` field insertion point | Insert `experts` field after `skills` field in pr-190's model |
| 7 | `druppie/execution/tool_executor.py` | Expert role validation block (~50 lines) | Insert ask_expert validation after HITL tool handling in pr-190's executor |
| 8 | `druppie/agents/definitions/general/architect.yaml` (commit 3) | ask_expert prompt section insertion | Place in pr-190's updated system prompt |

### Step 1.2: Verify the import

```bash
# After resolving all conflicts:
git add -A
git commit -m "feat(ask-expert): import PR #171 ask_expert tool infrastructure"

# Verify backend starts
docker compose --profile dev up -d --build druppie-backend-dev
docker compose exec druppie-backend-dev curl -s http://localhost:8000/health

# Verify frontend builds
cd frontend && npm run build
```

**Files added/modified by PR #171 (from this step):**

Backend (new logic):
- `druppie/agents/builtin_tools.py` — `ask_expert_question`, `ask_expert_multiple_choice_question` tool definitions
- `druppie/agents/loop.py` — Auto-enables ask_expert tools when `experts:` is declared in YAML
- `druppie/execution/tool_executor.py` — Validates `expert_role` against agent's allowed list, creates Question records
- `druppie/domain/agent_definition.py` — `experts: list[str]` field on AgentDefinition
- `druppie/domain/question.py` — `expert_role`, `answered_by`, `session_title`, `session_owner_username` on QuestionDetail
- `druppie/domain/session.py` — `username` on SessionSummary
- `druppie/db/models/question.py` — `expert_role`, `answered_by` columns on Question table
- `druppie/repositories/question_repository.py` — `get_pending_for_user_or_expert()`, `list_session_ids_with_expert_role()`
- `druppie/repositories/session_repository.py` — Expert session visibility
- `druppie/services/question_service.py` — `get_pending_for_user()`, role-based authorization
- `druppie/services/session_service.py` — `require_owner_or_admin()` gate
- `druppie/api/routes/questions.py` — `GET /api/questions/pending` endpoint
- `druppie/api/routes/sessions.py` — Session mutation authorization
- `druppie/api/deps.py` — QuestionRepository injection for session visibility
- `druppie/agents/definitions/general/architect.yaml` — `experts: [architect]` + mandatory ask_expert prompt rules

Frontend (new UI):
- `frontend/src/pages/Questions.jsx` — NEW: Full Questions page with expert/HITL grouping
- `frontend/src/components/NavRail.jsx` — "Questions" nav item with pending count badge
- `frontend/src/components/chat/SessionDetail.jsx` — Owner/expert/admin gating for controls
- `frontend/src/components/chat/SessionSidebar.jsx` — Expert session indicators
- `frontend/src/App.jsx` — Route for `/questions`
- `frontend/src/services/api.js` — `getPendingQuestions()` API client

**DB Reset Required**: New columns on `question` table → `docker compose --profile reset-db run --rm reset-db`

### Step 1.3: Test ask_expert with architect agent

Verify the imported infrastructure works by testing with the architect agent (already configured in PR #171):

1. Start a session that routes to the architect agent
2. Architect should call `ask_expert_multiple_choice_question(expert_role="architect", ...)` when encountering architectural decisions
3. A user with `architect` Keycloak role should see the question on the `/questions` page
4. Answering the question should resume the architect agent

---

## Phase 2: Add Expert Configuration to Subagent YAMLs

**Goal**: Enable `ask_expert` tools for the subagents that need developer gates.

### Step 2.1: Add `experts: [developer]` to builder_planner

**File**: `druppie/agents/definitions/coding/project/builder_planner.yaml`

**Change**: Add after the `role: subagent` line:

```yaml
experts:
  - developer
```

This enables both `ask_expert_question` and `ask_expert_multiple_choice_question` tools for this agent, restricted to `developer` role only.

### Step 2.2: Add `experts: [developer]` to test_builder

**File**: `druppie/agents/definitions/coding/project/test_builder.yaml`

**Change**: Add after the `role: subagent` line:

```yaml
experts:
  - developer
```

### Step 2.3: Add `experts: [developer]` to ultimate_dev

**File**: `druppie/agents/definitions/coding/project/ultimate_dev.yaml`

**Change**: Add after the `role: primary` line:

```yaml
experts:
  - developer
```

This allows the ultimate_dev orchestrator itself to ask the developer for final approval before signaling completion.

---

## Phase 3: Write Escalation Prompt Rules (The Core Logic)

**Goal**: Tell each agent WHEN and HOW to use `ask_expert` tools. This is the most critical step — the LLM must follow strict rules about when to escalate.

### Step 3.1: G1 — Plan Approval Prompt for builder_planner

**File**: `druppie/agents/definitions/coding/project/builder_planner.yaml`

**Add to system prompt** (after the main workflow instructions, before `=====` dividers):

```markdown
## EXPERT APPROVAL GATE — MANDATORY (DO NOT SKIP)

After you have completed the builder plan (`docs/builder-plan.md`) and before calling `done()`, you MUST:

1. Call `ask_expert_multiple_choice_question` with:
   - `expert_role`: "developer"
   - `question`: A concise summary of the plan including:
     * Components to build (list each)
     * Technologies and frameworks chosen
     * Estimated complexity (low/medium/high per component)
     * Key architectural decisions made
     * Total estimated effort
   - `choices`: [
       "✅ Approve plan — start building",
       "🔄 Request changes — I'll specify what",
       "🛑 Stop — do not proceed"
     ]
   - `multiple`: false

2. Wait for the developer's response:
   - If "Approve plan" → call `done()` with summary starting with "PLAN_APPROVED:"
   - If "Request changes" → revise the plan based on feedback, then re-ask (step 1 again)
   - If "Stop" → call `done()` with summary "PLAN_REJECTED: developer requested stop"

NEVER call `done()` without first getting developer approval on the plan.
NEVER skip this gate. This is a hard requirement enforced by the system.
```

### Step 3.2: G2 — Complex Choices Prompt for builder_planner

**File**: `druppie/agents/definitions/coding/project/builder_planner.yaml`

**Add to system prompt** (within the research/planning workflow section):

```markdown
## EXPERT CONSULTATION — For Complex Architectural Decisions

During your research phase (BEFORE writing the final plan), when you encounter a decision that:
- Has 2 or more viable technical approaches
- Materially affects the architecture, performance, or maintainability
- Involves choosing between different libraries, patterns, or paradigms

You MUST call `ask_expert_multiple_choice_question` with:
- `expert_role`: "developer"
- `question`: Clear description of the decision point including:
  * What the choice is about
  * The available options with PROS and CONS for each
  * Your recommendation and why
- `choices`: The options (as a list of clear, concise labels)
- `multiple`: false

Wait for the developer's choice, then incorporate it into your plan.

Do NOT ask for every minor decision. Only ask for decisions that:
- Significantly impact the codebase structure
- Have no clear "best" answer
- Would be costly to change later

Examples of when to ask:
- "Should we use REST or GraphQL for the API?"
- "State management: Redux vs Zustand vs Context?"
- "Database: PostgreSQL vs MongoDB?"

Examples of when NOT to ask:
- "Should we use const or let?" (trivial)
- "What CSS naming convention?" (easily changeable)
```

### Step 3.3: G3 — Test Review Prompt for test_builder

**File**: `druppie/agents/definitions/coding/project/test_builder.yaml`

**Add to system prompt** (after the test writing workflow, before completion instructions):

```markdown
## EXPERT TEST REVIEW GATE — MANDATORY (DO NOT SKIP)

After you have written ALL tests and before calling `done()`, you MUST:

1. Call `ask_expert_multiple_choice_question` with:
   - `expert_role`: "developer"
   - `question`: A summary of the test suite including:
     * Number of test files created
     * Number of test cases per file (approximate)
     * Test categories covered (unit, integration, e2e)
     * Key scenarios tested
     * Any edge cases intentionally skipped (with reason)
   - `choices`: [
       "✅ Accept tests — proceed to implementation",
       "🔄 Rewrite tests — I'll specify what to change",
       "📐 Adjust plan — tests reveal plan issues",
       "🛑 Stop — do not proceed"
     ]
   - `multiple`: false

2. Wait for the developer's response:
   - If "Accept tests" → call `done()` with summary starting with "TESTS_ACCEPTED:"
   - If "Rewrite tests" → revise based on feedback, then re-ask (step 1 again)
   - If "Adjust plan" → call `done()` with summary starting with "PLAN_ADJUSTMENT_NEEDED:" followed by what needs to change
   - If "Stop" → call `done()` with summary "TESTS_REJECTED: developer requested stop"

NEVER call `done()` without first getting developer review of the tests.
NEVER skip this gate. This is a hard requirement enforced by the system.
```

### Step 3.4: G4 — Deploy Approval via approval_overrides on deployer

**File**: `druppie/agents/definitions/coding/project/deployer.yaml`

**Add `approval_overrides`** to the YAML definition:

```yaml
approval_overrides:
  "docker:build":
    requires_approval: true
    required_role: developer
  "docker:compose_up":
    requires_approval: true
    required_role: developer
```

This gates the deployment on developer role approval. The existing `ApprovalCard` UI in the chat and Tasks page already handles this. When the deployer tries to `docker:build`, the tool execution pauses, creates an Approval record, and waits for a developer-role user to approve/reject.

**Also add to the deployer system prompt:**

```markdown
## DEPLOYMENT APPROVAL GATE

Before deploying, the system will automatically pause and ask a developer for approval.
When you reach the deployment step:
1. Ensure all code is committed and pushed
2. Attempt to run `docker:build` — this will trigger an approval request
3. Wait for the developer to approve or reject
4. If approved → continue with deployment
5. If rejected → call `done()` with summary "DEPLOYMENT_REJECTED: developer rejected deployment"

The developer sees the full build context before approving.
```

### Step 3.5: Handle Responses in ultimate_dev

**File**: `druppie/agents/definitions/coding/project/ultimate_dev.yaml`

The ultimate_dev agent orchestrates all subagents and reads their summaries. Update the orchestration logic in its system prompt to handle the new status signals:

```markdown
## SUBAGENT RESPONSE HANDLING

When a subagent completes, read its summary carefully:

- "PLAN_APPROVED:" → proceed to spawn test_builder
- "PLAN_REJECTED:" → call done() with "BUILD_CANCELLED: plan rejected by developer"
- "PLAN_ADJUSTMENT_NEEDED:" → re-spawn builder_planner with adjustment context
- "TESTS_ACCEPTED:" → proceed to spawn developer
- "TESTS_REJECTED:" → call done() with "BUILD_CANCELLED: tests rejected by developer"
- "DEPLOYMENT_REJECTED:" → call done() with "BUILD_CANCELLED: deployment rejected by developer"
- Test executor "FAIL" → spawn developer again with failure details (existing behavior)
- Reviewer "REJECT" → spawn developer again with review feedback (existing behavior)
```

---

## Phase 4: Completion Preconditions (Safety Nets)

**Goal**: Enforce that agents actually called `ask_expert` before completing, preventing the LLM from skipping gates.

### Step 4.1: Add completion_preconditions to builder_planner

**File**: `druppie/agents/definitions/coding/project/builder_planner.yaml`

```yaml
completion_preconditions:
  - summary_contains: "PLAN_APPROVED"
    required_tools:
      - tool_name: "ask_expert_multiple_choice_question"
        min_calls: 1
    error_message: >
      PRECONDITION FAILED: You cannot call done() with PLAN_APPROVED without
      first asking the developer to approve the plan via ask_expert_multiple_choice_question.
      The developer must explicitly approve before building can start.
```

### Step 4.2: Add completion_preconditions to test_builder

**File**: `druppie/agents/definitions/coding/project/test_builder.yaml`

```yaml
completion_preconditions:
  - summary_contains: "TESTS_ACCEPTED"
    required_tools:
      - tool_name: "ask_expert_multiple_choice_question"
        min_calls: 1
    error_message: >
      PRECONDITION FAILED: You cannot call done() with TESTS_ACCEPTED without
      first asking the developer to review the tests via ask_expert_multiple_choice_question.
      The developer must explicitly accept the tests before implementation can start.
```

---

## Phase 5: Testing

### Step 5.1: Unit Test — ask_expert tool registration

Verify that agents with `experts: [developer]` have `ask_expert_question` and `ask_expert_multiple_choice_question` in their available tools.

### Step 5.2: E2E Test — Full pipeline with expert gates

Use the existing E2E testing pattern:

```bash
# 1. Get auth token
TOKEN=$(curl -s -X POST "http://localhost:10302/realms/druppie/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=druppie-frontend&username=admin&password=Admin123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Run setup test to create session with pending developer
curl -s -X POST "http://localhost:10222/api/evaluations/run-tests" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"test_name": "setup-yaml-flow-hello-world"}'

# 3. Poll until complete
# ... (standard polling pattern)

# 4. Find session and pending developer agent run
# ... (standard session/agent lookup pattern)

# 5. Retry from developer with a prompt that triggers the pipeline
curl -s -X POST "http://localhost:10222/api/sessions/$SESSION_ID/retry-from/$AGENT_RUN_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"planned_prompt": "Create a simple hello world page"}'

# 6. Monitor — should see builder_planner pause with expert question
# The session should go to PAUSED_HITL status
# The developer user should see a pending question on /questions page

# 7. Answer the expert question as developer user
DEV_TOKEN=$(curl -s -X POST "http://localhost:10302/realms/druppie/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=druppie-frontend&username=developer&password=Developer123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Get pending questions for developer
curl -s "http://localhost:10222/api/questions/pending" -H "Authorization: Bearer $DEV_TOKEN"

# Answer the plan approval question
curl -s -X POST "http://localhost:10222/api/questions/$QUESTION_ID/answer" \
  -H "Authorization: Bearer $DEV_TOKEN" -H "Content-Type: application/json" \
  -d '{"answer": "✅ Approve plan — start building"}'

# 8. Continue monitoring — should see test_builder pause with expert question
# ... repeat answer pattern for test review gate

# 9. Continue to deploy — should see docker:build approval gate
# Approve via Tasks page or API
curl -s "http://localhost:10222/api/approvals" -H "Authorization: Bearer $DEV_TOKEN"
curl -s -X POST "http://localhost:10222/api/approvals/$APPROVAL_ID/approve" \
  -H "Authorization: Bearer $DEV_TOKEN" -H "Content-Type: application/json"
```

### Step 5.3: Playwright Test — Questions page UI

Verify the `/questions` page shows expert questions correctly:
1. Login as `developer` user
2. Navigate to Questions page
3. Should see pending expert questions grouped under "Expert questions" (purple)
4. Answer a question → agent should resume

### Step 5.4: Edge Case Tests

| Test Case | Expected Behavior |
|-----------|-------------------|
| Developer rejects plan | builder_planner revises plan, re-asks |
| Developer rejects 3 times | builder_planner stops (avoid infinite loop) |
| Developer stops during test review | ultimate_dev cancels build pipeline |
| Session started by analyst, expert question to developer role | Developer sees question on /questions page, analyst does not |
| Admin user views expert session | Admin can see session (read-only) and answer expert questions |
| Agent tries `ask_expert_question` with wrong role | Tool executor rejects with error |

---

## File Change Summary

### New files (from PR #171):
- `frontend/src/pages/Questions.jsx` — Expert questions page

### Modified backend files:

| File | Change | Phase |
|------|--------|-------|
| `druppie/agents/builtin_tools.py` | +ask_expert tool definitions | 1 |
| `druppie/agents/loop.py` | Auto-enable ask_expert when experts: set | 1 |
| `druppie/execution/tool_executor.py` | Expert role validation | 1 |
| `druppie/domain/agent_definition.py` | `experts: list[str]` field | 1 |
| `druppie/domain/question.py` | Expert fields on QuestionDetail | 1 |
| `druppie/domain/session.py` | `username` on SessionSummary | 1 |
| `druppie/db/models/question.py` | `expert_role`, `answered_by` columns | 1 |
| `druppie/repositories/question_repository.py` | Expert query methods | 1 |
| `druppie/repositories/session_repository.py` | Expert session visibility | 1 |
| `druppie/services/question_service.py` | Expert authorization | 1 |
| `druppie/services/session_service.py` | `require_owner_or_admin()` | 1 |
| `druppie/api/routes/questions.py` | `GET /api/questions/pending` | 1 |
| `druppie/api/routes/sessions.py` | Session mutation auth | 1 |
| `druppie/api/deps.py` | QuestionRepository injection | 1 |
| `druppie/agents/definitions/general/architect.yaml` | `experts: [architect]` + prompt | 1 |
| `druppie/agents/definitions/coding/project/builder_planner.yaml` | `experts: [developer]` + G1+G2 prompts + preconditions | 2, 3, 4 |
| `druppie/agents/definitions/coding/project/test_builder.yaml` | `experts: [developer]` + G3 prompt + preconditions | 2, 3, 4 |
| `druppie/agents/definitions/coding/project/ultimate_dev.yaml` | `experts: [developer]` + response handling | 2, 3 |
| `druppie/agents/definitions/coding/project/deployer.yaml` | `approval_overrides` + G4 prompt | 3 |

### Modified frontend files:

| File | Change | Phase |
|------|--------|-------|
| `frontend/src/App.jsx` | `/questions` route | 1 |
| `frontend/src/components/NavRail.jsx` | Questions nav item + badge | 1 |
| `frontend/src/components/chat/SessionDetail.jsx` | Owner/expert/admin gating | 1 |
| `frontend/src/components/chat/SessionSidebar.jsx` | Expert session indicators | 1 |
| `frontend/src/services/api.js` | `getPendingQuestions()` | 1 |

---

## Execution Order

```
Phase 1 (import PR #171)     ← Blocking: everything depends on this
  │
  ├─ Phase 2 (YAML experts:) ← Can start as soon as Phase 1 is committed
  │   │
  │   └─ Phase 3 (prompts)   ← Depends on Phase 2 (experts must be set first)
  │       │
  │       └─ Phase 4 (preconditions) ← Depends on Phase 3 (prompts define signals)
  │
  └─ Phase 5 (testing)       ← After Phases 1-4 are complete
```

**Phases 2, 3, and 4 can be done on the same files in one pass** (edit builder_planner once: add experts + prompt + preconditions). They're separated for clarity, not for sequential execution.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| PR #171 cherry-pick conflicts are worse than expected | Delays Phase 1 by hours | Fall back to Option C: manual port of ask_expert logic into pr-190's current files |
| LLM ignores ask_expert escalation rules | Gates get skipped | Completion preconditions (Phase 4) enforce tool call minimum — agent literally cannot complete without calling ask_expert |
| Developer approval fatigue (too many questions) | Poor UX | G2 (complex choices) is conditional — only triggered for significant decisions. G1/G3/G4 are 3 gates total for the entire pipeline |
| Infinite loop on rejection | Agent keeps re-asking | Add instruction: "After 3 rejections on the same gate, call done() with REJECTED status" |
| Expert question routing to wrong role | Developer never sees question | PR 171 has multi-layer validation: YAML config → executor validation → service authorization. Only `developer` role is configured |
| Questions page doesn't poll fast enough | Developer doesn't see question | Questions page auto-refreshes every 5 seconds (from PR 171). Session detail also shows inline question cards |
