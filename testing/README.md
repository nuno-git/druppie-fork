# Testing Framework

Tests execute real MCP tool calls against real services. No fake seeding — every session, project, and file is created through the actual tool pipeline.

## Structure

```
testing/
├── tools/          # Tool tests — chains of real MCP tool calls
├── agents/         # Agent tests — real LLM agent execution with setup
├── checks/         # Reusable assertion bundles (referenced by agent tests)
└── profiles/       # Configuration (HITL personas, judge LLM profiles)
```

## Tool Tests (`tools/`)

A tool test is a chain of tool calls executed one by one through real MCP servers. Each step creates real DB records, real Gitea repos, and real files.

```yaml
tool-test:
  name: create-todo-app
  tags: [e2e, create-project]

  chain:
    - agent: router
      tool: builtin:set_intent
      arguments:
        intent: create_project
        project_name: todo-app
      assert:
        result:
          - not_empty
          - { contains: "todo-app" }

    - agent: router
      tool: builtin:done
      arguments: { summary: "Created project" }
      assert:
        completed: true            # checks AGENT status, only on done steps

    - agent: business_analyst
      tool: coding:make_design
      approval:                    # resolve approval gate
        status: approved
        by: analyst
      arguments:
        path: docs/functional-design.md
        content: "..."

    - agent: builder
      tool: coding:execute_coding_task
      mock: true                   # don't run sandbox
      mock_result: "Files created"
      outcome:                     # but create these files in Gitea
        files:
          - path: src/App.jsx
            content: "..."

  verify:                          # check Gitea side-effects
    - gitea_repo_exists: true
    - file_exists: docs/functional-design.md
```

### Assertions

Two types of inline assertions on chain steps:

**`completed: true/false`** — checks the **agent run status**, not the tool call.
An agent is marked `completed` when it calls `builtin:done`. Without `done`, the
agent stays as `running`. Only use this on `done` steps or in top-level checks.

```yaml
# Correct: assert on the done step
- agent: router
  tool: builtin:done
  arguments: { summary: "Done" }
  assert:
    completed: true

# Wrong: assert on a regular tool (checks the agent, not the tool)
- agent: router
  tool: builtin:set_intent
  assert:
    completed: true  # ← this checks if ROUTER completed, not if set_intent succeeded
```

**`result:`** — validates the tool call's result string. For failed tool calls,
both `result` and `error_message` are checked (combined). Validators:
- `not_empty` — result is non-empty
- `no_error` — no error indicators in result
- `json_parseable` — result is valid JSON
- `{contains: "text"}` — result contains substring
- `{matches: "regex"}` — result matches regex pattern

### Other step options

- **`approval:`** — resolve approval gates (tools like `make_design` require role approval)
  - `status: approved` or `status: rejected`
  - `by: architect` — which user approves
  - `reason: "..."` — rejection reason
- **`mock: true`** — skip real execution, use `mock_result` instead. Each test
  decides what to mock — there is no global blocklist.
- **`outcome:`** — for mocked `execute_coding_task`, create real files in Gitea
- **`verify:`** — post-test side-effect checks (file exists, repo exists, etc.)

### Judge checks

Tool tests can include LLM judge checks that evaluate quality:

```yaml
tool-test:
  name: my-test
  chain: [...]

  # LLM Judge — verdict IS the result
  judge:
    context: business_analyst    # which agent runs to show the judge
    checks:
      - "FD should be in Dutch"

      # Judge Eval — testing the judge itself
      - check: "FD should not mention frameworks"
        expected: false          # we expect the judge to FAIL this
```

Context options: `"all"`, `"business_analyst"`, or `["business_analyst", "architect"]`

## Agent Tests (`agents/`)

Agent tests run real LLM agents after setting up prerequisite state via tool tests.

There are two modes:

### New session (default)

Each setup tool test creates its own session. The `message` starts a **new** session
via the orchestrator (router → planner → agents). Use this when you need existing
projects/context but want a fresh conversation.

```yaml
agent-test:
  name: router-picks-correct-project

  setup:                           # tool tests to run first (same user)
    - create-weather-dashboard     # → session 1 with project
    - create-todo-app              # → session 2 with project

  message: "update the weather dashboard to add dark mode"
  agents: [router]                 # starts new session, runs router
```

### Continue session (`continue_session: true`)

Continues the **last** setup session instead of creating a new one. The specified
`agents` are created directly in the existing session — no router/planner restart.
Use this when you need the agent to work in the same workspace/project context.

```yaml
agent-test:
  name: architect-reviews-fd

  setup:
    - setup-project-with-fd        # creates session with FD written
  continue_session: true           # continues THIS session (always the last one)

  message: "Review the functional design and create the technical design"
  agents: [architect]              # architect runs directly in the setup session
```

When `continue_session: true`:
- The last setup session is reused (not a new one)
- No router/planner — the listed agents run directly
- The agent sees the full session history (previous tool calls, files, project)
- If you have multiple setups, the **last** one is continued

### Flow

**New session (default):**
1. Create isolated test user
2. Run each `setup` tool test → creates real sessions + projects for that user
3. Send `message` through real orchestrator, bounded to listed `agents`
4. Run assertions against the resulting session

**Continue session:**
1. Create isolated test user
2. Run each `setup` tool test → creates real sessions
3. Continue the last setup session — run `agents` directly in it
4. Run assertions against that same session

### Expected values

- Exact match: `intent: update_project`
- Wildcard: `project_name: "*"` (just check key exists)
- Any-of: `intent: ["update_project", "create_project"]`
- Dynamic reference: `project_id: "@project:weather-dashboard"` (resolves to UUID)

## Checks (`checks/`)

Reusable assertion bundles referenced by agent tests via `check: name`.
Checks can include both code assertions AND judge checks.

```yaml
check:
  name: architect-produces-td
  assert:
    - agent: architect
      completed: true
    - agent: architect
      tool: coding:make_design
  judge:
    context: architect             # which agent runs the judge sees
    checks:
      - "The TD must be in Dutch"
      - "The TD must not copy the FD verbatim"
```

## Evaluation Types

The testing framework has three distinct evaluation types, tracked separately in analytics:

| Type | What it does | Example |
|------|-------------|---------|
| **Assertions** | Code checks on tool call results and agent status | `{contains: "todo-app"}`, `completed: true` |
| **LLM Judge** | LLM evaluates agent output quality — verdict IS the result | `"FD should be in Dutch"` |
| **Judge Eval** | Tests the judge itself — checks if judge verdict matches expected | `check: "...", expected: false` |

## Profiles (`profiles/`)

- **`hitl.yaml`** — HITL simulator personas (LLM-powered auto-answering for HITL questions during agent tests)
- **`judges.yaml`** — LLM judge profiles for evaluating agent output quality

## Running Tests

From the UI: Evaluations page → select test → Run.

From API:
```bash
# Run a single test
POST /api/evaluations/run-tests {"test_name": "create-todo-app"}

# Run all tests
POST /api/evaluations/run-tests {"run_all": true}

# Run by tag
POST /api/evaluations/run-tests {"tag": "router"}
```
