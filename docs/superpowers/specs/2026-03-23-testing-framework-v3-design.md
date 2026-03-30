# Testing Framework v3 — Design Spec

## Problem

The current testing framework (v2) has three gaps:

1. **Seeding is DB-only** — Tool calls are recorded as metadata but never executed. No way to test that MCP tools actually work, that Gitea repos have the right files, or that the full agent pipeline produces correct side-effects.
2. **Only 3 tests exist** — All test the router. No coverage for planner, BA, architect, builder, deployer, summarizer, HITL flows, approval workflows, or tool execution.
3. **No graphs** — The UI shows flat pass/fail badges. No trends, no per-agent breakdowns, no historical analysis.

## Design

### 1. Three Seed Modes

Every test definition specifies a `mode` that controls how world state is created:

```yaml
test:
  name: my-test
  mode: live | replay | record_only   # NEW — defaults to "record_only" (backwards compat)
```

#### Mode: `record_only` (current behavior)
- Inserts DB records directly from YAML
- Optionally creates Gitea repos via REST API
- No tool execution, no LLM calls
- Fast (~1-2s per session)
- Use for: setting up world state before testing a specific agent

#### Mode: `replay`
- Reads tool calls from YAML and **actually executes them** against MCP servers
- Executes in order, using the YAML-defined arguments
- Per-tool-call override: `execute: false` skips execution and uses the YAML `result` as mock
- Global blocklist in `testing/profiles/replay_config.yaml` for expensive tools
- If a tool is blocklisted and has no YAML `result`, returns generic success: `{"status": "ok", "message": "mocked"}`
- DB records are still created (session, agent_runs, tool_calls with real results)
- Use for: testing tool integration, verifying MCP servers work, testing tool side-effects

#### Mode: `live`
- Runs the **full agent pipeline** through the orchestrator with LLM calls
- Uses HITL simulator for human interactions (same as current test execution)
- Seeds history sessions first (using their own mode — can mix modes)
- The test's `run.message` triggers a real session with real agent execution
- Use for: end-to-end testing of agent behavior, regression testing

#### How modes compose

A test can reference sessions that use different modes:

```yaml
test:
  name: architect-design-quality
  mode: live                           # This test runs live agents
  sessions:
    - weather-dashboard-completed      # This session is record_only (fast setup)
  seed_sessions:                       # NEW — sessions with explicit mode override
    - session: ba-wrote-fd
      mode: replay                     # This one replays tool calls
  run:
    message: "Review the functional design"
    real_agents: [architect]
```

**Seeding rules:**
- `sessions` entries are always seeded as `record_only` (backwards compatible)
- `seed_sessions` entries specify their own mode
- Seeding order: all `sessions` first (in listed order), then `seed_sessions` (in listed order)
- A session cannot appear in both lists (validation error)
- `after:` chain resolution works across both lists

**What `test.mode` means:**
- `test.mode` is a **tag/category** for filtering in the UI (e.g. "show me all live tests")
- It does NOT control execution behavior — that's determined by:
  - `sessions` list → always `record_only`
  - `seed_sessions` entries → their own `mode` field
  - `run` block → always triggers live agent execution via the orchestrator

### 2. Replay Config (Blocklist + Defaults)

```yaml
# testing/profiles/replay_config.yaml
replay:
  # Tools that are always mocked (never executed during replay).
  # Everything else — including builtin tools — is executed for real.
  # Builtin tools (set_intent, done, make_plan, etc.) run through the
  # orchestrator context so they create real DB state.
  blocklist:
    - coding:execute_coding_task    # Too slow, creates sandboxes
    - docker:build_image            # Side-effects on host
    - docker:deploy_container       # Side-effects on host

  # Default mock results for blocklisted tools (optional)
  default_results:
    "coding:execute_coding_task": |
      Task completed successfully. Files created as specified.
    "docker:build_image": |
      {"image_id": "sha256:mock123", "tag": "latest"}
    "docker:deploy_container": |
      {"container_id": "mock-container-1", "url": "http://localhost:3000"}

  # Timeout per tool call execution (seconds)
  timeout: 30

  # What to do when a replay tool call fails (connection error, timeout, etc.)
  # - mock: log warning, use mock result (default — prevents flaky tests)
  # - fail: propagate error, fail the test
  # - skip: skip the tool call entirely
  on_error: mock
```

Per-tool-call override in session YAML (existing `result` field, new `execute` field):

```yaml
tool_calls:
  - tool: "coding:make_design"
    arguments: {path: "technical_design.md", content: "..."}
    execute: true                     # Force execute even if blocklisted
    status: completed

  - tool: "coding:execute_coding_task"
    arguments: {task: "Build the app"}
    execute: false                    # Force mock even if not blocklisted
    result: "Built successfully"      # Mock result to use
    status: completed
    outcome:                          # Still create files in Gitea
      target: gitea
      files:
        - path: "src/app.py"
          content: "print('hello')"
```

### 3. Extended Seed Schema

Changes to `seed_schema.py`:

```python
class ToolCallFixture(BaseModel):
    tool: str
    arguments: dict = {}
    status: str = "completed"
    result: str | None = None
    error_message: str | None = None
    answer: str | None = None          # existing — creates HITL Question
    approval: ApprovalFixture | None   # existing
    outcome: ToolCallOutcome | None    # existing
    execute: bool | None = None        # NEW — per-tool override (None = use default)

class SessionFixture(BaseModel):
    metadata: SessionMetadata
    agents: list[AgentRunFixture] = []
    messages: list[MessageFixture] = []
    mode: str = "record_only"          # NEW — default mode for this session
```

### 4. Replay Executor

New module: `druppie/testing/replay_executor.py`

The replay executor needs an orchestrator context to execute tools — both MCP tools
(which go through `MCPClient.call_tool` requiring session_id, agent_run_id, agent_id)
and builtin tools (which modify DB state via the orchestrator). The executor creates
a lightweight session + agent_run in the DB first, then uses the existing tool
execution pipeline.

```python
class ReplayExecutor:
    """Executes tool calls from YAML through the real orchestrator pipeline."""

    def __init__(self, replay_config: ReplayConfig, tool_executor: ToolExecutor):
        self.config = replay_config
        self.executor = tool_executor  # The existing ToolExecutor from execution/

    def should_execute(self, tool_call: ToolCallFixture) -> bool:
        """Check per-call override > blocklist > default (execute)."""
        if tool_call.execute is not None:
            return tool_call.execute
        return tool_call.tool not in self.config.blocklist

    def get_mock_result(self, tool_call: ToolCallFixture) -> str:
        """Get mock result: YAML result > config default > generic."""
        if tool_call.result:
            return tool_call.result
        default = self.config.default_results.get(tool_call.tool)
        if default:
            return default
        return '{"status": "ok", "message": "mocked"}'

    async def execute_tool(
        self, tool_call: ToolCallFixture,
        session_id: UUID, agent_run_id: UUID, agent_id: str,
    ) -> str:
        """Execute a single tool call through the orchestrator, or return mock."""
        if not self.should_execute(tool_call):
            return self.get_mock_result(tool_call)

        try:
            # Route through the real tool execution pipeline:
            # - builtin tools → builtin_tools.py (modifies DB state)
            # - MCP tools → MCPClient.call_tool (calls real MCP servers)
            result = await self.executor.execute(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                session_id=session_id,
                agent_run_id=agent_run_id,
                agent_id=agent_id,
            )
            return result
        except Exception as e:
            if self.config.on_error == "fail":
                raise
            elif self.config.on_error == "skip":
                return ""
            else:  # "mock" (default)
                logger.warning("Replay tool %s failed, using mock: %s", tool_call.tool, e)
                return self.get_mock_result(tool_call)

    async def replay_session(self, fixture: SessionFixture, db: DbSession) -> None:
        """Replay all tool calls in a session fixture.

        1. Create session + agent_run DB records (gives us IDs for the orchestrator)
        2. Execute each tool call in order through the real pipeline
        3. Update DB records with actual results
        """
        # Step 1: Create session and agent_run records
        session_id = create_session_record(fixture, db)

        for agent_fixture in fixture.agents:
            agent_run_id = create_agent_run_record(agent_fixture, session_id, db)

            # Step 2: Execute tool calls in order
            for tc in agent_fixture.tool_calls:
                result = await self.execute_tool(
                    tc, session_id, agent_run_id, agent_fixture.id,
                )
                # Step 3: Update the tool call record with the real result
                update_tool_call_result(tc, result, agent_run_id, db)

            # Handle outcome blocks (Gitea file creation) same as record_only
            for tc in agent_fixture.tool_calls:
                if tc.outcome:
                    replay_outcome(tc.outcome, fixture, db)
```

### 5. Updated Seed Loader

The existing `seed_loader.py` gets a mode parameter:

```python
async def seed_fixture(
    fixture: SessionFixture,
    db: DbSession,
    gitea_url: str | None = None,
    mode: str | None = None,        # NEW — overrides fixture.metadata mode
    replay_executor: ReplayExecutor | None = None,  # NEW
) -> dict:
    effective_mode = mode or fixture.mode or "record_only"

    if effective_mode == "record_only":
        # Current behavior — insert DB records directly
        return _seed_record_only(fixture, db, gitea_url)

    elif effective_mode == "replay":
        # Execute tool calls, then insert DB records with real results
        return await _seed_replay(fixture, db, gitea_url, replay_executor)

    elif effective_mode == "live":
        # Not handled here — live mode is handled by the test runner
        raise ValueError("live mode is handled by TestRunner, not seed_loader")
```

### 6. Test Definition Schema (Extended)

```yaml
# Full example of all three modes in one test suite:

# --- record_only test (fast, for unit-testing assertions) ---
test:
  name: router-create-recipe
  mode: record_only
  description: "Router creates new project for recipe app request"
  sessions:
    - weather-dashboard-completed
    - todo-app-builder-failed
  run:
    message: "build me a recipe sharing app"
    real_agents: [router]
  hitl: non-technical-pm
  judge: default
  evals:
    - eval: router-correct-intent
      expected:
        intent: create_project
        project_name: "*"

# --- replay test (tool integration) ---
test:
  name: architect-writes-design-file
  mode: replay
  description: "Verify architect's make_design tool creates real file"
  sessions:
    - weather-dashboard-completed
  seed_sessions:
    - session: ba-approved-fd
      mode: replay                    # Replay BA's tool calls to create real FD file
  run:
    message: "Design the weather dashboard architecture"
    real_agents: [architect]
  evals:
    - eval: architect-produces-design
  evaluate:
    assertions:
      - agent: architect
        tool_called: coding:make_design
        completed: true

# --- live test (full E2E) ---
test:
  name: e2e-create-project-full-pipeline
  mode: live
  description: "Full pipeline: router → planner → BA → architect"
  sessions: []
  run:
    message: "build me a weather dashboard"
    real_agents: [router, planner, business_analyst, architect]
  hitl: non-technical-pm
  judges: [default, strict]
  evals:
    - eval: router-correct-intent
      expected:
        intent: create_project
    - eval: architect-produces-design
```

### 7. Comprehensive Test Suite

#### 7.1 Router Tests (expand from 3 → 8)

| Test | Mode | Description |
|------|------|-------------|
| `router-create-recipe` | live | Creates project for new request |
| `router-update-weather-5-projects` | live | Picks correct project from 5 |
| `router-general-chat` | live | Classifies question as general_chat |
| `router-ambiguous-request` | live | Asks clarifying question on ambiguous input |
| `router-update-nonexistent` | live | Falls back to create_project when project not found |
| `router-create-dutch` | live | Handles Dutch language request |
| `router-empty-projects` | live | Routes create_project with no existing projects |
| `router-gibberish` | live | Handles nonsensical input gracefully |

#### 7.2 Planner Tests (new)

| Test | Mode | Description |
|------|------|-------------|
| `planner-create-project-initial` | live | Plans BA as first step for create_project |
| `planner-update-project-initial` | live | Plans developer (branch) as first step |
| `planner-general-chat-routing` | live | Routes to correct agent for chat |
| `planner-after-ba-approved` | live | Plans architect after BA approval |
| `planner-after-architect-feedback` | live | Routes back to BA on DESIGN_FEEDBACK |
| `planner-after-architect-approved` | live | Plans builder_planner after DESIGN_APPROVED |
| `planner-mandatory-sequence` | live | Doesn't skip agents in sequence |

#### 7.3 Business Analyst Tests (new)

| Test | Mode | Description |
|------|------|-------------|
| `ba-gathers-requirements` | live | Asks clarifying questions via HITL |
| `ba-writes-fd` | live | Creates functional_design.md |
| `ba-revision-after-feedback` | live | Revises FD after architect feedback |
| `ba-design-rejected` | live | Signals DESIGN_REJECTED appropriately |

#### 7.4 Architect Tests (expand from 0 → 5)

| Test | Mode | Description |
|------|------|-------------|
| `architect-approves-design` | live | Writes technical_design.md, signals DESIGN_APPROVED |
| `architect-design-in-dutch` | live | technical_design.md is in Dutch |
| `architect-gives-feedback` | live | Signals DESIGN_FEEDBACK with specific items |
| `architect-rejects-design` | live | Signals DESIGN_REJECTED, communicates with user |
| `architect-general-chat` | live | Answers architecture questions |

#### 7.5 Tool Integration Tests (new — replay mode)

**Basic tool execution (Layer 1 — result validators):**

| Test | Mode | Description | Validates |
|------|------|-------------|-----------|
| `tool-coding-read-file` | replay | coding:read_file returns file content | not_empty |
| `tool-coding-list-dir` | replay | coding:list_dir returns directory listing | not_empty, no_error |
| `tool-coding-make-design` | replay | coding:make_design creates file | not_empty |
| `tool-coding-run-git` | replay | coding:run_git executes git command | no_error |
| `tool-registry-list-components` | replay | registry:list_components returns data | not_empty, json_parseable |
| `tool-registry-get-agent` | replay | registry:get_agent returns agent def | not_empty, contains:"router" |
| `tool-filesearch-search-files` | replay | filesearch:search_files finds results | not_empty |
| `tool-web-fetch-url` | replay | web:fetch_url returns content | not_empty |
| `tool-archimate-list-models` | replay | archimate:list_models returns models | not_empty |
| `tool-archimate-search` | replay | archimate:search_model returns results | not_empty |

**Side-effect verification (Layer 2 — verify real state):**

| Test | Mode | Description | Verifies |
|------|------|-------------|----------|
| `tool-make-design-creates-file` | replay | make_design actually creates the file | file_exists, file_not_empty |
| `tool-make-design-mermaid-valid` | replay | make_design with valid mermaid passes | mermaid_valid |
| `tool-run-git-creates-branch` | replay | run_git checkout -b creates branch | git_branch_exists |
| `tool-run-git-commits-file` | replay | run_git add+commit persists file | file_exists |

**Pre-validate rejection (Layer 3 — bad input rejected):**

| Test | Mode | Description | Asserts |
|------|------|-------------|---------|
| `tool-make-design-bad-mermaid` | replay | Invalid mermaid syntax rejected | status: failed, error_contains: "mermaid" |
| `tool-read-file-nonexistent` | replay | Reading missing file returns error | status: failed |
| `tool-run-git-invalid-command` | replay | Invalid git command returns error | status: failed, no_error: false |

#### 7.6 Workflow / E2E Tests (new — live mode)

| Test | Mode | Description |
|------|------|-------------|
| `e2e-create-project-to-architect` | live | router → planner → BA → architect pipeline |
| `e2e-general-chat-architect` | live | General chat routed to architect |
| `e2e-general-chat-ba` | live | General chat routed to BA |
| `e2e-update-project-branch-setup` | live | developer creates branch for update_project |
| `e2e-hitl-approval-flow` | live | Tool approval pauses and resumes correctly |
| `e2e-ba-architect-feedback-loop` | live | BA → architect → feedback → BA → architect loop |

#### 7.7 HITL Tests (new)

| Test | Mode | Description |
|------|------|-------------|
| `hitl-free-text-question` | live | Agent asks free-text, simulator responds |
| `hitl-multiple-choice` | live | Agent asks MC, simulator picks correct option |
| `hitl-approval-architect` | live | Architect approval pauses and resumes |

#### 7.8 Edge Case Tests (new)

| Test | Mode | Description |
|------|------|-------------|
| `edge-max-iterations` | live | Agent hitting max_iterations stops |
| `edge-tool-failure` | live | Agent handles tool call failure gracefully |
| `edge-empty-message` | live | Router handles empty message |

### 8. New Eval Definitions

Expand from 2 → 12 evals:

| Eval | Tags | Assertions | Judge Checks |
|------|------|------------|--------------|
| `router-correct-intent` | router | agent completed, set_intent called | Intent classified correctly |
| `architect-produces-design` | architect | agent completed | Design covers requirements, written in Dutch |
| `planner-correct-next-agent` | planner | agent completed, make_plan called | Planned the correct next agent |
| `planner-two-step-plan` | planner | make_plan called | Plan has exactly 2 steps (agent + planner) |
| `ba-writes-fd` | ba | agent completed, make_design called | FD covers user requirements |
| `ba-asks-questions` | ba, hitl | hitl_ask_question or hitl_ask_multiple_choice called | Questions are relevant to requirements |
| `architect-design-quality` | architect, design | agent completed | Technical design is thorough and follows template |
| `agent-uses-done` | agent, common | done called | Agent signals clear status |
| `agent-status-signal` | agent, common | done called | Done summary contains valid status signal |
| `tool-returns-valid-result` | tool | tool call completed | Tool result is non-empty and parseable |
| `hitl-question-quality` | hitl | question tool called | Question is clear and well-formed |
| `workflow-agent-sequence` | workflow | all real_agents completed | Agents executed in correct order |

### 9. Three-Layer Tool Verification

Tools aren't just tested for "was it called" — we verify correctness at three layers:

#### Layer 1: Result Validators (post-execution checks on tool output)

After a tool executes, optional validators run on its result string. Validators are
defined per-tool and reusable across tests. They catch things like: empty results,
unparseable JSON, error messages disguised as success.

New assertion type: `result_valid`

```yaml
# In an eval definition
assertions:
  - agent: architect
    tool_called: coding:make_design
    result_valid:                       # NEW — validate the tool result
      - not_empty                       # Result string is non-empty
      - no_error                        # Result doesn't contain error indicators
      - json_parseable                  # Result is valid JSON (when expected)
```

Built-in validators (extensible):
- `not_empty` — result is not empty/whitespace
- `no_error` — result doesn't match error patterns ("error", "failed", "exception")
- `json_parseable` — result is valid JSON
- `contains: <string>` — result contains a substring
- `matches: <regex>` — result matches a regex pattern

#### Layer 2: Side-Effect Verification (check real state after execution)

After all tool calls execute, verify the actual world state: files exist in Gitea,
content is correct, git branches exist, etc. This catches tools that "succeed" but
produce broken output.

New block: `verify` on assertions and at test level.

```yaml
# In a test definition
test:
  name: architect-writes-valid-design
  # ...
  evaluate:
    assertions:
      - agent: architect
        tool_called: coding:make_design
        completed: true
    verify:                             # NEW — post-execution state checks
      - file_exists: "technical_design.md"
      - file_contains:
          path: "technical_design.md"
          content: "## Architecturale Oplossing"
      - file_not_empty: "technical_design.md"
      - mermaid_valid: "technical_design.md"   # Parse all ```mermaid blocks
      - git_branch_exists: "main"
      - gitea_repo_exists: true
```

Built-in verifiers (extensible):
- `file_exists: <path>` — file exists in the project repo (via Gitea API or coding MCP)
- `file_not_empty: <path>` — file exists and has content
- `file_contains: {path, content}` — file contains expected substring
- `file_matches: {path, pattern}` — file content matches regex
- `mermaid_valid: <path>` — all `` ```mermaid `` blocks in the file parse without errors
  (uses the existing `mermaid_validator.py`)
- `git_branch_exists: <branch>` — branch exists in repo
- `gitea_repo_exists: true` — project repo exists in Gitea
- `json_schema: {path, schema}` — file content validates against a JSON schema

Verifiers run after all assertions complete. Each produces a pass/fail result stored
in `TestAssertionResult` with `assertion_type = "verify"`.

#### Layer 3: Pre-Validate Error Propagation (MCP server rejects bad input)

The existing `pre_validate` system (backlog #79, being cleaned up in the module migration PR)
validates tool input before execution — e.g., mermaid syntax in `make_design` content.
When `pre_validate` fails, the tool call errors and the agent must retry or handle it.

Tests verify this works correctly by intentionally providing bad input and asserting
the tool call failed with a validation error:

```yaml
# Test that bad mermaid is rejected
test:
  name: tool-make-design-invalid-mermaid
  mode: replay
  description: "make_design rejects invalid mermaid syntax"
  sessions: []
  seed_sessions:
    - session: architect-bad-mermaid     # Session with invalid mermaid in make_design
      mode: replay
  evaluate:
    assertions:
      - agent: architect
        tool_called: coding:make_design
        status: failed                   # NEW — assert tool call status
        error_contains: "mermaid"        # NEW — assert error message content
```

New assertion fields:
- `status: completed | failed | error` — assert the tool call's status
- `error_contains: <string>` — assert the error message contains a substring
- `error_matches: <regex>` — assert the error message matches a pattern

#### How the Three Layers Compose

```
Tool Call Execution
  │
  ├─ Layer 3: pre_validate runs BEFORE execution
  │   └─ Bad input → tool_call.status = "failed", error_message set
  │       └─ Test asserts: status: failed, error_contains: "..."
  │
  ├─ Layer 1: result validators run AFTER execution
  │   └─ Tool returned something → check result quality
  │       └─ Test asserts: result_valid: [not_empty, no_error, ...]
  │
  └─ Layer 2: side-effect verifiers run AFTER all tool calls
      └─ Check real world state (files, repos, branches)
          └─ Test verifies: file_exists, mermaid_valid, ...
```

All three layers produce `TestAssertionResult` rows with appropriate `assertion_type`
values (`"result_valid"`, `"verify"`, `"status_check"`), queryable in the analytics dashboard.

### 10. Dashboard — Eval Analytics Page

New page: `/analytics` (linked from test history)

**Data model**: We extend the API to return richer data for charts. The DB already stores everything we need (TestRun, TestRunTag, assertion/judge counts, duration, batch_id, created_at).

#### 10.1 New API Endpoints

```
GET /evaluations/analytics/summary
  → { total_runs, total_passed, total_failed, pass_rate, avg_duration_ms }

GET /evaluations/analytics/trends?days=30&group_by=day
  → [{ date, total, passed, failed, pass_rate }]

GET /evaluations/analytics/by-agent?batch_id=optional
  → [{ agent, total, passed, failed, pass_rate, avg_duration_ms }]

GET /evaluations/analytics/by-eval?batch_id=optional
  → [{ eval_name, total, passed, failed, pass_rate }]

GET /evaluations/analytics/by-tool?batch_id=optional
  → [{ tool, total, passed, failed, pass_rate }]  (derived from tool assertions)

GET /evaluations/analytics/by-test?batch_id=optional
  → [{ test_name, total, passed, failed, pass_rate, avg_duration_ms }]

GET /evaluations/analytics/batch/{batch_id}
  → { batch_id, created_at, total, passed, failed,
      by_agent: [...], by_eval: [...], by_test: [...], duration_ms }
```

#### 10.2 DB Changes

Add columns to `TestRun`:

```python
# New fields on TestRun model
agent_id = Column(String(100))            # Primary agent tested (first in real_agents)
mode = Column(String(20))                 # record_only, replay, live
```

Add new model for per-assertion result storage (fully normalized — no CSV columns):

```python
class TestAssertionResult(Base):
    __tablename__ = "test_assertion_results"
    id = Column(UUID, primary_key=True)
    test_run_id = Column(UUID, ForeignKey("test_runs.id", ondelete="CASCADE"))
    assertion_type = Column(String(50))   # "completed", "tool_called", "judge_check",
                                         # "result_valid", "verify", "status_check"
    agent_id = Column(String(100))
    tool_name = Column(String(200))       # e.g. "coding:make_design"
    eval_name = Column(String(200))
    passed = Column(Boolean)
    message = Column(Text)
    judge_reasoning = Column(Text)        # For judge checks only
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_tar_test_run_id", "test_run_id"),
        Index("idx_tar_agent_id", "agent_id"),
        Index("idx_tar_eval_name", "eval_name"),
        Index("idx_tar_tool_name", "tool_name"),
        Index("idx_tar_assertion_type", "assertion_type"),
    )
```

Analytics queries derive eval_names and tool_names via JOINs on this table
(e.g. `SELECT DISTINCT eval_name FROM test_assertion_results WHERE test_run_id = ?`).
No denormalized CSV columns — follows the project rule of proper relational tables.

Also add index on `TestRun.created_at` for time-series trend queries:

```python
# Add to TestRun.__table_args__
Index("idx_test_runs_created_at", "created_at"),
Index("idx_test_runs_agent_id", "agent_id"),
```

#### 10.3 Frontend — Analytics Page

**Charting library**: `recharts` — lightweight, React-native, good for bar/line/pie charts. Works with the React + Vite + Tailwind stack. Must be added as a new npm dependency (`npm install recharts`).

**Page layout (scrollable):**

```
┌─────────────────────────────────────────────────────┐
│  ← Back to Tests                    [Date Range ▼]  │
│                                                     │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │ Total    │ Passed   │ Failed   │ Pass Rate    │  │
│  │  142     │  128     │  14      │  90.1%       │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
│                                                     │
│  Pass Rate Over Time                                │
│  ┌─────────────────────────────────────────────┐    │
│  │  ──────────────────────────────  100%        │    │
│  │  ─────────────────               80%        │    │
│  │                                  60%        │    │
│  │  Mar 15  Mar 17  Mar 19  Mar 21  Mar 23     │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  Results by Agent              Results by Eval      │
│  ┌───────────────────┐  ┌───────────────────────┐   │
│  │ ██████ router 95% │  │ ██████ intent 97%     │   │
│  │ █████ planner 88% │  │ █████ design 85%      │   │
│  │ ████ architect 80% │ │ ████ fd-quality 78%   │   │
│  │ ████ ba 82%       │  │ ████ done-signal 90%  │   │
│  └───────────────────┘  └───────────────────────┘   │
│                                                     │
│  Results by Tool                                    │
│  ┌──────────────────────────────────────────────┐   │
│  │ ██████ set_intent 97%                        │   │
│  │ ██████ make_plan 92%                         │   │
│  │ █████ make_design 85%                        │   │
│  │ █████ read_file 88%                          │   │
│  │ ████ run_git 80%                             │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  Slowest Tests (top 10)                             │
│  ┌──────────────────────────────────────────────┐   │
│  │ 1. e2e-create-project    4m 12s              │   │
│  │ 2. architect-approves    45.2s               │   │
│  │ 3. ba-writes-fd          38.1s               │   │
│  │ ...                                          │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  Recent Batches                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ Batch 2026-03-23 14:30  12/14 passed [View]  │   │
│  │ Batch 2026-03-23 10:15  10/10 passed [View]  │   │
│  │ Batch 2026-03-22 16:00   8/10 passed [View]  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Batch detail page** (clicking [View] or the link from test history):

```
┌─────────────────────────────────────────────────────┐
│  ← Back to Analytics          Batch: 2026-03-23     │
│                                                     │
│  Summary: 12/14 passed (85.7%)  Duration: 4m 32s    │
│                                                     │
│  Pass/Fail by Agent (pie)   Pass/Fail by Test (bar) │
│  ┌──────────────────┐  ┌───────────────────────┐    │
│  │   🟢 router      │  │ █ router-create  ✓    │    │
│  │   🟢 planner     │  │ █ router-update  ✓    │    │
│  │   🔴 architect   │  │ █ planner-init   ✓    │    │
│  │   🟢 ba          │  │ █ architect-appr ✗    │    │
│  └──────────────────┘  └───────────────────────┘    │
│                                                     │
│  Individual Test Results (expandable table)          │
│  ┌──────────────────────────────────────────────┐   │
│  │ ✓ router-create-recipe     1.2s  default     │   │
│  │ ✓ router-general-chat      0.8s  default     │   │
│  │ ✗ architect-approves       45s   strict  [▼] │   │
│  │   └ Assertion: completed ✓                   │   │
│  │   └ Assertion: make_design called ✓          │   │
│  │   └ Judge: design in Dutch ✗                 │   │
│  │     "Reasoning: Design was in English..."    │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 11. Frontend Routing

```
/admin/tests            → Evaluations.jsx (existing — run tests, history list)
/admin/tests/analytics  → Analytics.jsx (new — global graphs + trends)
/admin/tests/batch/:id  → BatchDetail.jsx (new — single batch graphs + drill-down)
```

Link from history: each batch row in Evaluations.jsx gets a "📊 Analytics" link → `/admin/tests/batch/:id`.
Global analytics link at top of Evaluations.jsx → `/admin/tests/analytics`.

### 12. Cost Tiers

Live tests invoke real LLMs and can be slow/expensive. Tests are tagged with cost tiers
so you can run fast tests during development and full suites in CI:

| Tier | Tag | What runs | Approx time |
|------|-----|-----------|-------------|
| fast | `tier:fast` | record_only + replay tests only | ~10s |
| standard | `tier:standard` | fast + cheap live tests (router, single-agent) | ~2-3min |
| full | `tier:full` | everything including multi-agent E2E | ~15-30min |

The existing `RunTestsRequest` tag filter supports this: `runTests({tag: "tier:fast"})`.
All tests MUST have a `tier:*` tag. Default tier for new tests: `tier:standard`.

### 13. V1 Eval Deprecation

The v1 evaluation system (`eval_schema.py` with `EvaluationDefinition`, `rubrics`, `JudgeEngine`,
and `EvaluationResult` DB model) is deprecated. All new evals use the v2 format exclusively
(`EvalDefinition` with `assertions` + `judge.checks`, stored via `TestRun` + `TestAssertionResult`).

The v1 API endpoints (`/evaluations/benchmark-runs`, `/evaluations/results`) remain for
reading historical data but no new v1 evals will be created.

### 14. Implementation Modules

| File | Purpose |
|------|---------|
| `druppie/testing/replay_config.py` | Pydantic model for replay_config.yaml |
| `druppie/testing/replay_executor.py` | Tool call execution against MCP servers |
| `druppie/testing/seed_loader.py` | Extended with mode parameter + replay support |
| `druppie/testing/seed_schema.py` | Extended with `execute` field + session `mode` |
| `druppie/testing/v2_schema.py` | Extended with `mode`, `seed_sessions` |
| `druppie/testing/v2_runner.py` | Extended to handle all three modes |
| `druppie/db/models/test_assertion_result.py` | New model for per-assertion storage |
| `druppie/db/models/test_run.py` | New columns (agent_id, mode) + indexes |
| `druppie/api/routes/evaluations.py` | New analytics endpoints |
| `frontend/src/pages/Analytics.jsx` | New — global analytics page |
| `frontend/src/pages/BatchDetail.jsx` | New — batch detail with graphs |
| `frontend/src/pages/Evaluations.jsx` | Add links to analytics/batch pages |
| `frontend/src/services/api.js` | New analytics API client functions |
| `testing/profiles/replay_config.yaml` | Blocklist + default mock results |
| `testing/tests/*.yaml` | ~35 new test definitions |
| `testing/evals/*.yaml` | ~10 new eval definitions |
| `testing/sessions/*.yaml` | New sessions for replay/tool testing |

### 15. Extensibility

Adding a new test is always the same pattern:

```yaml
# 1. Pick a mode
test:
  mode: live | replay | record_only

# 2. Define world state (optional)
  sessions: [existing-session-id]
  seed_sessions:
    - session: custom-session
      mode: replay

# 3. Define what to run
  run:
    message: "the user input"
    real_agents: [agent1, agent2]

# 4. Define what to check
  evals:
    - eval: some-eval
      expected: {key: value}
  evaluate:
    assertions:
      - agent: agent1
        tool_called: server:tool
    judge:
      checks:
        - "Did the agent do the right thing?"
```

Adding a new eval is:

```yaml
eval:
  name: my-eval
  tags: [agent-name, category]
  assertions:
    - agent: agent-name
      completed: true
      tool_called: server:tool
  judge:
    checks:
      - "Natural language question about quality"
```

Adding a new session (world state) is:

```yaml
metadata:
  id: my-session
  title: "Description"
  status: completed
  user: admin
  intent: create_project
  project_name: my-project
agents:
  - id: router
    status: completed
    tool_calls:
      - tool: "builtin:set_intent"
        arguments: {intent: create_project, project_name: my-project}
        execute: false              # Skip execution during replay
        result: "Intent set"
        status: completed
```
