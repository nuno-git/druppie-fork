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
- `judge:` — LLM judge evaluates quality

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

### Three Evaluation Types

| Type | YAML syntax | What it does |
|------|-------------|-------------|
| **Assertions** | `assert: { result: [{contains: "text"}] }` | Code checks on tool call results |
| **LLM Judge** | `judge: { checks: ["FD should be in Dutch"] }` | LLM evaluates quality — verdict IS the result |
| **Judge Eval** | `judge: { checks: [{check: "...", expected: false}] }` | Tests the judge itself — checks if verdict matches expected |

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
- Summary cards: Tests, Assertions, LLM Judge, Judge Eval, Duration
- Check Explorer: filter by specific check across all tests
- Drill-down per test run with raw LLM I/O for judge checks
- Cross-test filtering by agent, type, and check text

## Configuration

### Profiles (`testing/profiles/`)

- `hitl.yaml` — personas for auto-answering HITL questions during agent tests
- `judges.yaml` — LLM model config for judge evaluations

### Mocking

Each test step controls its own mocking via `mock: true`. There is no global blocklist — tests are explicit about what's real and what's mocked.

For more details, see [testing/README.md](../testing/README.md).
