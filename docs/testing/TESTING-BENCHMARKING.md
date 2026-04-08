# Testing & Benchmarking Framework

## What Is This?

A framework for testing Druppie's AI agent pipeline end-to-end. You write tests as YAML files, run them from the admin UI (or API), and get back a report of what passed and what failed.

It tests the full agent chain: Router -> Planner -> BA -> Architect -> Builder, including real tool calls, HITL (human-in-the-loop) interactions, and LLM decisions.

---

## The Big Picture

```
testing/
  setup/          Session fixtures — world state that "already happened"
  tools/          Tool tests — verify MCP tools work against real services (FREE)
  agents/         Agent tests — run real agents with real LLMs (costs tokens)
    manual/       Agent tests that need user input first
  checks/         Reusable assertion + judge bundles
  profiles/       Config (HITL personas, judge, replay)
```

Three test-related folders, each with a clear purpose:

| Folder | What it does | Cost | Speed |
|--------|-------------|------|-------|
| `setup/` | Seed DB with world state (not a test, just context) | Free | ~1-2s |
| `tools/` | Replay tool call chains through real MCP services | Free | ~5-30s |
| `agents/` | Run real agents with real LLMs, assert + judge | LLM tokens | ~30s-min |

---

## How It All Connects

Each layer produces real state the next layer can use:

```
setup (DB insert)  →  tool chain (real MCP)  →  agent execution (real LLM)
    fast context        real side effects         real decisions
```

- A **tool test** can reference `setup:` sessions for DB context, then replay its `chain:`
- An **agent test** can reference `setup:` sessions AND `extends:` a tool test chain
- This means: seed 5 projects → create real Gitea repo via tool chain → run real architect on it

---

## Setup Files (`testing/setup/*.yaml`)

These are session fixtures — world state that "already happened". They describe projects, agent runs, tool calls that exist in the DB before a test runs.

```yaml
metadata:
  id: weather-dashboard-completed
  title: "build a weather dashboard"
  status: completed
  user: admin
  intent: create_project
  project_name: weather-dashboard

agents:
  - id: router
    status: completed
    tool_calls:
      - tool: builtin:set_intent
        arguments:
          intent: create_project
          project_name: weather-dashboard
        result: "Intent set to create_project"

messages:
  - role: user
    content: "build a weather dashboard"
```

Setup files are not tests. They're referenced by tool and agent tests via the `setup:` field.

---

## Tool Tests (`testing/tools/*.yaml`)

Test MCP tool calls by replaying a chain of tool calls through real services. No LLM involved. Free.

The chain is the test — earlier steps create state that later steps depend on.

```yaml
tool-test:
  name: coding-list-dir
  description: Router creates project, architect lists directory
  tags: [coding, filesystem]

  chain:
    - agent: router
      tool: builtin:set_intent
      arguments:
        intent: create_project
        project_name: weather-dashboard
      status: completed

    - agent: architect
      tool: coding:list_dir
      arguments:
        path: "."
      status: completed
      assert:                          # check THIS specific step
        completed: true
        result: [not_empty, no_error]
```

### Key features

- `chain:` — sequential tool calls, all executed through real MCP
- `assert:` on chain steps — check specific tool call results
- `setup:` — seed DB context before the chain runs
- `extends:` — run another tool test's chain first
- `mock: true` — force-mock expensive tools (with `outcome:` for file creation)

### Result validators (for `assert.result`)

- `not_empty` — result is non-empty
- `no_error` — no error patterns in result
- `json_parseable` — valid JSON
- `{ contains: "text" }` — substring check
- `{ matches: "regex" }` — regex check

---

## Agent Tests (`testing/agents/*.yaml`)

Test real agent execution with real LLMs. Assert on behavior, evaluate with LLM judge.

```yaml
agent-test:
  name: router-create-recipe
  description: Router creates new project for recipe app request
  tags: [router]

  setup:                               # seed context (DB insert)
    - weather-dashboard-completed
    - todo-app-builder-failed

  message: "build me a recipe sharing app"
  agents: [router]                     # which agents to run
  hitl: non-technical-pm               # HITL simulator profile

  assert:                              # check references
    - check: router-correct-intent
      expected:
        intent: create_project
        project_name: "*"              # wildcard — just check it exists
```

### Key features

- `setup:` — seed DB context (fast insert)
- `extends:` — run a tool test chain first (creates real Gitea repos, files)
- `message:` — user message to send to the agent pipeline
- `agents:` — which agents to actually run (stops after these complete)
- `hitl:` — HITL simulator profile
- `assert:` — check references with expected values
- `judge:` — inline LLM judge checks (natural language)
- `verify:` — side-effect checks against Gitea

### Multi-project setup + update test

```yaml
agent-test:
  name: router-update-weather-5-projects
  description: Router picks weather-dashboard from 5 existing projects
  tags: [router, multi-project]

  setup:
    - weather-dashboard-completed
    - todo-app-builder-failed
    - calculator-architect-paused
    - portfolio-completed
    - blog-platform-tester-running

  message: "update the weather dashboard to add dark mode"
  agents: [router]

  assert:
    - check: router-correct-intent
      expected:
        intent: update_project
        project_id: "@project:weather-dashboard"   # resolves to actual UUID
```

### Extending a tool chain

```yaml
agent-test:
  name: architect-reviews-files
  tags: [architect, integration]

  setup:
    - weather-dashboard-completed

  extends: coding-list-dir             # run this tool chain first

  message: "review the project structure and create an architecture document"
  agents: [architect]
  hitl: developer

  assert:
    - check: architect-produces-design

  verify:
    - file_exists: "docs/architecture.md"
```

---

## Manual Tests (`testing/agents/manual/*.yaml`)

Agent tests that need user input before running. Presence of `inputs:` makes it manual.

```yaml
agent-test:
  name: manual-router-custom-message
  description: "Route a custom message: {{user_message}}"
  tags: [router, manual]

  inputs:
    - name: user_message
      label: "User message to classify"
      type: textarea
      default: "I want to build something cool"
    - name: expected_intent
      label: "Expected intent"
      type: select
      options: [create_project, update_project, general_chat]

  message: "{{user_message}}"
  agents: [router]

  assert:
    - check: router-correct-intent
      expected:
        intent: "{{expected_intent}}"
```

---

## Checks (`testing/checks/*.yaml`)

Reusable assertion + judge bundles. They define *what to check*, not *what the correct answer is*. Tests supply expected values.

```yaml
check:
  name: router-correct-intent
  description: Router called set_intent with the correct intent
  tags: [router, intent]

  assert:
    - agent: router
      completed: true
    - agent: router
      tool: builtin:set_intent

  judge:
    - "The router should classify the intent correctly based on the user message"
```

The `assert:` part runs for both tool and agent tests. The `judge:` part only runs for agent tests.

### Available checks

| Check | What it verifies |
|-------|-----------------|
| `router-correct-intent` | Router completed + called `set_intent` |
| `planner-correct-next-agent` | Planner completed + called `make_plan` |
| `planner-two-step-plan` | Plan has 2 steps (agent + planner) |
| `ba-writes-fd` | BA completed + called `make_design` |
| `ba-asks-questions` | BA completed + asks HITL questions |
| `architect-produces-design` | Architect completed + design produced |
| `architect-design-quality` | NORA model, sections, mermaid diagrams |
| `agent-status-signal` | Agent's `done()` has a valid status signal |
| `agent-uses-done` | Agent calls `done()` |
| `hitl-question-quality` | HITL questions are clear and relevant |
| `tool-result-valid` | Tool returns non-empty valid result |
| `workflow-agent-sequence` | Agents run in correct workflow order |

---

## Assertion Types

### 1. Agent completed/failed

```yaml
assert:
  - agent: router
    completed: true    # or false for expected failures
```

### 2. Tool was called (with optional argument matching)

```yaml
assert:
  - agent: router
    tool: builtin:set_intent
```

With expected values in the test:
```yaml
expected:
  intent: create_project          # exact match
  project_name: "*"               # wildcard — just check it exists
  intent: [create_project, update_project]  # any of these
  project_id: "@project:weather"  # resolves to real UUID at runtime
```

### 3. Tool result validation (on chain steps)

```yaml
assert:
  completed: true
  result: [not_empty, no_error, { contains: "src/" }]
```

---

## Verify Checks (Gitea Side-Effects)

```yaml
verify:
  - file_exists: "docs/functional-design.md"
  - file_not_empty: "docs/functional-design.md"
  - file_contains: { path: "docs/fd.md", content: "Requirements" }
  - file_matches: { path: "docs/arch.md", pattern: "```mermaid" }
  - mermaid_valid: "docs/architecture.md"
  - gitea_repo_exists: true
  - git_branch_exists: "main"
```

---

## HITL Simulation

When a live agent test triggers a HITL pause, the simulator auto-answers.

### Profiles (`testing/profiles/hitl.yaml`)

| Profile | Persona |
|---------|---------|
| `non-technical-pm` | Simple answers, no jargon |
| `dutch-water-authority` | Answers in Dutch, water domain expertise |
| `developer` | Technical, precise answers |
| `default` | Generic helpful user |

---

## LLM Judge

For agent tests, an LLM evaluates behavior against natural-language criteria.

```yaml
# In a check file (reusable):
judge:
  - "The router should classify the intent correctly"

# In an agent test (inline, test-specific):
judge:
  - "The technical_design.md MUST be written in Dutch"
```

Judge checks only run for agent tests (tool tests have no LLM to judge).

---

## Running Tests

### From the Admin UI

1. Go to **Admin > Evaluations**
2. Click **Select Tests** — filter by Agent / Tool / Manual
3. Select tests and click **Run**
4. Watch real-time progress
5. Results appear in the batch list

### From the API

```bash
# Run specific tests
curl -X POST /api/evaluations/run-tests \
  -d '{"test_names": ["router-create-recipe", "coding-list-dir"]}'

# Run all
curl -X POST /api/evaluations/run-tests -d '{"run_all": true}'

# Run by tag
curl -X POST /api/evaluations/run-tests -d '{"tag": "router"}'

# Poll progress
curl /api/evaluations/run-status/{run_id}

# Cleanup test users
curl -X DELETE /api/evaluations/test-users
```

---

## User Isolation

Each test creates a unique throwaway user (`t-<8char-hash>`). All seeded sessions and execution belong to this user. Tests never interfere with each other or real data. Cleanup: delete all `t-*` users.

---

## Writing New Tests

### 1. Tool test — verify a tool works

```yaml
tool-test:
  name: my-tool-test
  tags: [coding]

  chain:
    - agent: router
      tool: builtin:set_intent
      arguments: { intent: create_project, project_name: test }
      status: completed

    - agent: architect
      tool: coding:list_dir
      arguments: { path: "." }
      assert:
        completed: true
        result: [not_empty]
```

### 2. Agent test — verify agent behavior

```yaml
agent-test:
  name: my-agent-test
  tags: [router]

  message: "build me a todo app"
  agents: [router]
  hitl: non-technical-pm

  assert:
    - check: router-correct-intent
      expected:
        intent: create_project
```

### 3. Full pipeline with tool chain + agent

```yaml
agent-test:
  name: my-e2e-test
  tags: [e2e]

  setup:
    - weather-dashboard-completed

  extends: coding-list-dir       # real Gitea repo with files

  message: "review the project"
  agents: [router, planner, architect]
  hitl: developer

  assert:
    - check: architect-produces-design

  verify:
    - file_exists: "docs/architecture.md"

  judge:
    - "The architect should reference actual files"
```
