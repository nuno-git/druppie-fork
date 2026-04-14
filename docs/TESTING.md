# Testing Framework

Druppie uses an end-to-end testing framework that executes real MCP tool calls against real services. No fake seeding — every session, project, and file is created through the actual tool pipeline.

## Overview

The framework supports three test types:

| Type | Description | LLM calls? |
|------|-------------|------------|
| **Tool tests** | Chains of real MCP tool calls replayed from YAML | No (deterministic) |
| **Agent tests** | Real LLM agents execute with assertions and judge checks | Yes |
| **Judge evals** | Tests the LLM judge itself by checking expected outcomes | Yes (judge only) |

## Test Structure

```
testing/
├── tools/          # Tool tests — chains of real MCP tool calls
├── agents/         # Agent tests — real LLM agent execution
├── checks/         # Reusable assertion bundles
└── profiles/       # HITL simulator and judge LLM profiles
```

## How It Works

### Tool Tests

A tool test defines a chain of tool calls that execute one by one through real MCP servers. Each step creates real DB records, Gitea repos, and files.

```yaml
tool-test:
  name: create-todo-app
  chain:
    - agent: router
      tool: builtin:set_intent
      arguments: { intent: create_project, project_name: todo-app }
      assert:
        result: [not_empty, { contains: "todo-app" }]

    - agent: router
      tool: builtin:done
      arguments: { summary: "Created project" }
      assert:
        completed: true

    - agent: builder
      tool: coding:execute_coding_task
      mock: true                    # skip sandbox
      mock_result: "Files created"
      outcome:                      # but create real files in Gitea
        files:
          - path: src/App.jsx
            content: "..."
```

Key features:
- `mock: true` — skip real execution, use mock_result
- `approval:` — auto-resolve approval gates
- `outcome:` — create files in Gitea for mocked execute_coding_task
- `assert:` — inline assertions on tool results
- `verify:` — side-effect checks (Gitea repo/file existence)
- `extends:` — inherit chain from another tool test (runs in the same session)
- `judge:` — LLM judge evaluates quality

### Extends Mechanism

Tests can extend a base pipeline with `extends: <test-name>`. The base chain and the test's own chain run in the **same session**, so side effects (project creation, Gitea repos) from the base are visible to the extending test's assertions and verify checks.

```yaml
tool-test:
  name: create-expense-tracker
  extends: setup-create-project-pipeline   # runs router→BA→architect first
  chain:
    - agent: builder                        # then appends builder steps
      tool: coding:execute_coding_task
      ...
```

### Agent Tests

Agent tests run real LLM agents after setting up state via tool tests.

```yaml
agent-test:
  name: architect-reviews-fd
  setup:
    - setup-project-with-fd       # tool test creates project + FD
  continue_session: true          # architect runs in SAME session

  message: "Review the functional design"
  agents: [architect]
  hitl: non-technical-pm          # auto-answers HITL questions

  assert:
    - check: architect-produces-td
  judge:
    context: [architect]
    checks:
      - "The architect should have approved or rejected the design"
```

Two modes:
- **New session** (default): setup creates sessions, message starts a fresh one
- **Continue session**: architect runs directly in the last setup session

## Assertion Types

Every test produces assertions that are stored and displayed in the analytics UI. There are three categories of assertions plus two judge evaluation types:

### Assertions (code checks)

| Type | UI Label | What it checks | Example |
|------|----------|----------------|---------|
| `completed` | **Agent Status** | Did the agent finish by calling `done()`? | `summarizer.completed` → "Expected completed, got completed" |
| `tool` | **Tool Call** | Was a specific tool called with expected args/result? | `architect.tool(coding:make_design)` → checks tool was called |
| `verify` | **Side Effect** | Does a file/repo actually exist in Gitea? | `file_exists: docs/functional-design.md` → hits Gitea API |

### LLM Judge (quality evaluation)

| Type | UI Label | What it checks |
|------|----------|----------------|
| `judge_check` | **LLM Judge** | LLM evaluates output quality against a natural-language criterion |
| `judge_eval` | **Judge Eval** | Tests the judge itself — checks if verdict matches expected outcome |

### YAML Syntax

```yaml
# Inline assertions on chain steps
- agent: router
  tool: builtin:set_intent
  assert:
    result: [not_empty, { contains: "todo-app" }]  # Tool Call assertion
    completed: true                                   # Agent Status assertion

# Side-effect verification (top-level)
verify:
  - gitea_repo_exists: true
  - file_exists: docs/functional-design.md
  - file_not_empty: docs/technical-design.md

# LLM judge checks (top-level)
judge:
  checks:
    - "The functional design should be in Dutch"
```

## Running Tests

**From the UI:** Evaluations page → select tests → Run

**From API:**
```bash
POST /api/evaluations/run-tests {"test_name": "create-todo-app"}
POST /api/evaluations/run-tests {"run_all": true}
POST /api/evaluations/run-tests {"tag": "architect"}
```

## Analytics

The Analytics page (`/admin/analytics`) shows per-batch results with:
- Summary cards: Tests, Assertions (all types combined), LLM Judge, Duration
- Check Explorer: filter by specific check across all tests, grouped by Agent Status / Tool Call / Side Effect / LLM Judge
- Drill-down per test run with raw LLM I/O for judge checks
- Filtering by type (Agent Status, Tool Call, Side Effect), agent, tool, and check text

## Configuration

### Profiles (`testing/profiles/`)

- `hitl.yaml` — personas for auto-answering HITL questions during agent tests
- `judges.yaml` — LLM model config for judge evaluations

### Mocking

Each test step controls its own mocking via `mock: true`. There is no global blocklist — tests are explicit about what's real and what's mocked.

For more details, see [testing/README.md](../testing/README.md).
