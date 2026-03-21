# Testing Framework v2: User-Isolated Tests

## Overview

A testing and benchmarking framework for Druppie where each test gets its own user with complete isolation — their own sessions, projects, and Gitea repos. Tests can run in parallel without conflicts.

Three concepts:
- **Sessions** — Reusable state definitions. Define what happened: projects, agent runs, tool calls, files in repos. Can chain via `after:` to build on each other.
- **Evals** — Reusable evaluation definitions. Define WHAT to check (assertions + judge checks) without specifying correct answers. Tests reference evals and provide the expected values.
- **Tests** — Reference sessions as their world, run a new message through real agents, reference evals with expected values, and evaluate the results.

## Directory Structure

```
testing/
  sessions/                    # Reusable state definitions
    weather-dashboard.yaml
    todo-app.yaml
    calculator.yaml
    weather-with-dark-mode.yaml    # after: weather-dashboard
    ...
  evals/                       # Reusable evaluation definitions (what to check)
    router-correct-intent.yaml
    architect-produces-design.yaml
    ...
  tests/                       # Test definitions (world + run + evals with expected answers)
    router-update-weather-5-projects.yaml
    router-create-recipe.yaml
    architect-design-quality.yaml
    ...
  reports/                     # Generated test reports
    2026-03-21-203000.md
    ...

druppie/testing/               # Python code
  ...

scripts/
  test_runner.py               # CLI entry point for running tests
```

## Part 1: Session Definitions

Sessions are reusable building blocks that define state. They are NOT tests — they just define what a user's world looks like.

### Format

```yaml
# testing/sessions/weather-dashboard.yaml
session:
  name: weather-dashboard
  title: "build me a weather dashboard"
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
          status: completed
        - tool: builtin:done
          arguments:
            summary: "Agent router: Classified as create_project, project 'weather-dashboard'."
          status: completed
    - id: planner
      status: completed
      tool_calls:
        - tool: builtin:make_plan
          arguments:
            steps:
              - agent_id: business_analyst
                prompt: "Gather requirements"
              - agent_id: architect
                prompt: "Design architecture"
              - agent_id: builder
                prompt: "Implement"
          status: completed
        - tool: builtin:done
          status: completed
    - id: business_analyst
      status: completed
      planned_prompt: "Gather requirements"
      tool_calls:
        - tool: builtin:done
          arguments:
            summary: "Agent business_analyst: DESIGN_APPROVED. Created SPEC.md."
          status: completed
    - id: architect
      status: completed
      planned_prompt: "Design architecture"
      tool_calls:
        - tool: builtin:done
          arguments:
            summary: "Agent architect: DESIGN_APPROVED. Wrote technical_design.md."
          status: completed
    - id: builder
      status: completed
      planned_prompt: "Implement"
      tool_calls:
        - tool: builtin:execute_coding_task
          arguments:
            task: "Implement weather dashboard"
            agent: druppie-builder
          status: completed
          outcome:
            target: gitea
            files:
              - path: src/App.jsx
                content: |
                  import React, { useState, useEffect } from 'react';
                  import WeatherCard from './components/WeatherCard';

                  export default function App() {
                    const [weather, setWeather] = useState(null);
                    useEffect(() => {
                      fetch('/api/weather?city=Amsterdam')
                        .then(r => r.json())
                        .then(setWeather);
                    }, []);
                    return (
                      <div className="app">
                        <h1>Weather Dashboard</h1>
                        {weather && <WeatherCard data={weather} />}
                      </div>
                    );
                  }
              - path: src/components/WeatherCard.jsx
                content: |
                  import React from 'react';
                  export default function WeatherCard({ data }) {
                    return (
                      <div className="weather-card">
                        <h2>{data.city}</h2>
                        <p>{data.temperature}°C - {data.description}</p>
                      </div>
                    );
                  }
              - path: package.json
                content: |
                  {
                    "name": "weather-dashboard",
                    "version": "1.0.0",
                    "dependencies": { "react": "^18.2.0", "react-dom": "^18.2.0" },
                    "scripts": { "dev": "vite", "build": "vite build" }
                  }
              - path: Dockerfile
                content: |
                  FROM node:18-alpine
                  WORKDIR /app
                  COPY package*.json ./
                  RUN npm install
                  COPY . .
                  RUN npm run build
                  CMD ["npm", "start"]
            commit_message: "Implement weather dashboard - all 18 tests passing"
            push: true
        - tool: builtin:done
          arguments:
            summary: "Agent builder: Implemented weather dashboard, all 18 tests passing."
          status: completed
    - id: deployer
      status: completed
      tool_calls:
        - tool: builtin:done
          arguments:
            summary: "Agent deployer: Deployed weather dashboard container."
          status: completed
  messages:
    - role: user
      content: "build me a weather dashboard"
```

### Session Chaining

Sessions can reference another session as their starting point with `after:`. The referenced session is seeded first, then this session is seeded on top.

```yaml
# testing/sessions/weather-with-dark-mode.yaml
session:
  name: weather-with-dark-mode
  after: weather-dashboard
  title: "add dark mode to the weather dashboard"
  intent: update_project
  project_name: weather-dashboard     # links to existing project from parent session
  agents:
    - id: router
      status: completed
      tool_calls:
        - tool: builtin:set_intent
          arguments:
            intent: update_project
            project_name: weather-dashboard
          status: completed
        - tool: builtin:done
          status: completed
    - id: builder
      status: completed
      tool_calls:
        - tool: builtin:execute_coding_task
          arguments:
            task: "Add dark mode toggle"
            agent: druppie-builder
          status: completed
          outcome:
            target: gitea
            files:
              - path: src/theme.js
                content: |
                  export function toggleDarkMode() {
                    document.body.classList.toggle('dark-mode');
                    localStorage.setItem('theme',
                      document.body.classList.contains('dark-mode') ? 'dark' : 'light');
                  }
            commit_message: "Add dark mode toggle"
            push: true
        - tool: builtin:done
          status: completed
  messages:
    - role: user
      content: "add dark mode to the weather dashboard"
```

Multiple sessions can reference the same parent — the parent is seeded once, and each child builds on it independently (via separate test users).

---

## Part 2: Eval Definitions

### Format

Evals define what to check — which agent, which tool call, which assertions, which judge checks. They do NOT define what the correct answer is — that comes from the test.

```yaml
# testing/evals/router-correct-intent.yaml
eval:
  name: router-correct-intent
  description: "Router should call set_intent with the correct intent and project"
  tags: [router, intent-classification]
  assertions:
    - agent: router
      completed: true
    - agent: router
      tool_called: builtin:set_intent
      # arguments not specified here — the test provides expected values
  judge:
    checks:
      - "The router should classify the intent correctly based on the user message"
```

```yaml
# testing/evals/architect-produces-design.yaml
eval:
  name: architect-produces-design
  description: "Architect should produce a technical design document"
  tags: [architect, design-quality]
  assertions:
    - agent: architect
      completed: true
  judge:
    checks:
      - "The architect should produce a design that covers the user's requirements"
      - "The technical design should be written in Dutch"
```

### How Evals Connect to Tests

Tests reference evals and provide `expected` values that fill in the blanks:

```yaml
# In a test file
evals:
  - eval: router-correct-intent
    expected:
      intent: update_project
      project_name: weather-dashboard
```

The `expected` values are used in two ways:
1. **Assertions** — The eval's `tool_called: builtin:set_intent` assertion checks the tool was called. The test's `expected` values are matched against the actual tool call arguments.
2. **Judge context** — The judge LLM receives the `expected` values so it knows what "correct" means for this test.

### Argument Matching

Three matching modes for `expected` values:

- **Exact match** — `project_name: weather-dashboard` — must be exactly this value
- **Wildcard** — `project_name: "*"` — any value is accepted, just checks the argument exists
- **Any-of list** — `project_name: [recipe-app, recipe-application, recipe-website]` — any of these values is accepted

Examples:
```yaml
# Exact: must be update_project
expected:
  intent: update_project
  project_name: weather-dashboard

# Wildcard: any project name is fine
expected:
  intent: create_project
  project_name: "*"

# Any-of: multiple acceptable names
expected:
  intent: create_project
  project_name: [recipe-app, recipe-application, recipe-website]
```

---

## Part 3: Test Definitions

Tests reference sessions as their world, run a new message, and evaluate using reusable evals (with expected values) and/or inline evaluate blocks.

### Format

```yaml
# testing/tests/router-update-weather-5-projects.yaml
test:
  name: router-update-weather-5-projects
  description: "Router picks weather-dashboard from 5 existing projects"

  sessions:
    - weather-dashboard
    - todo-app
    - calculator
    - portfolio
    - blog

  run:
    message: "update the weather dashboard to add dark mode"
    real_agents: [router]

  user_prompt: "You want to update the weather dashboard."

  # Reusable evals with expected answers for THIS test
  evals:
    - eval: router-correct-intent
      expected:
        intent: update_project
        project_name: weather-dashboard

  # Optional: test-specific checks (not reusable)
  evaluate:
    assertions:
      - agent: router
        completed: true
    judge:
      checks:
        - "Router should not ask the user which project to update when the message clearly mentions weather dashboard"
```

Another test reusing the same eval with different expected values:
```yaml
# testing/tests/router-create-recipe.yaml
test:
  name: router-create-recipe
  sessions: [weather-dashboard, todo-app]
  run:
    message: "build me a recipe sharing app"
    real_agents: [router]
  user_prompt: "You want a new recipe app."
  evals:
    - eval: router-correct-intent
      expected:
        intent: create_project
        project_name: "*"              # any name is fine for a new project
```

### Tags

Tags are freeform strings used for grouping and analytics. Recommended conventions:
- Agent name: `router`, `architect`, `builder`, `business_analyst`
- Intent: `create_project`, `update_project`, `general_chat`
- Capability: `project-selection`, `design-quality`, `tool-compliance`, `hitl-questions`
- Difficulty: `simple`, `complex`, `edge-case`

### Real Agents vs Skipped

`real_agents` lists which agents execute with real LLM calls. The test runner:
1. Seeds all sessions (history)
2. Creates a new session with the `run.message`
3. Sends it through the orchestrator
4. Only agents in `real_agents` get actual LLM calls
5. Execution stops after the last real agent completes
6. Evaluation runs against the resulting DB state

If `real_agents` is omitted or empty, ALL agents run for real (full end-to-end test). This is expensive but tests the whole pipeline.

### HITL Simulation

When a real agent asks a HITL question (via `hitl_ask_question` or `hitl_ask_multiple_choice_question`), the test runner intercepts the pause and sends the question to an LLM with the `user_prompt` as its persona.

The LLM sees: the persona prompt, the conversation history so far, and the question. It generates a natural answer.

If `user_prompt` is omitted, a default prompt is used: "You are a helpful user who gives clear, concise answers to questions."

### Evaluation

**Assertions** are deterministic checks:
- `completed: true/false` — agent finished with this status
- `tool_called: server:tool_name` — agent called this tool
- `arguments: {key: value}` — the tool call had these argument values
- `result_contains: "text"` — the tool call result contains this text

**Judge checks** are LLM-evaluated:
- Each check is a natural language description of expected behavior
- The judge LLM sees the full agent execution trace (tool calls, results, messages) and scores each check as pass/fail with reasoning
- `model` specifies which LLM judges (defaults to `claude-sonnet-4-6`)

---

## Part 4: Test Execution

### Per-Test Isolation

Each test run creates:
1. **A Gitea user** — `test-{test-name}-{timestamp}` (e.g., `test-router-update-1711054800`)
2. **A Keycloak user** (or Druppie DB user) — same username, test password
3. **Gitea repos** — one per project in the session history, owned by the test user
4. **DB records** — sessions, agent runs, tool calls, etc. all linked to the test user

This means:
- Tests never share state
- The same test can run multiple times without cleanup
- Multiple tests can run in parallel
- Old test data accumulates until explicitly deleted

### Execution Flow

```
For each test:
  1. Create test user in Gitea + Druppie DB
     - Username: test-{test-name}-{unix-timestamp}
     - Password: TestUser123!

  2. Resolve session chain
     - For each session in test.sessions:
       - If session has `after:`, recursively resolve the parent first
       - Deduplicate (each session seeded only once)
     - Result: ordered list of sessions to seed

  3. Seed sessions
     - For each session (in resolved order):
       - Create Project + Gitea repo (if project_name set)
       - Create Session, AgentRuns, ToolCalls, Messages, etc.
       - Replay outcome blocks (create files in Gitea repos)
       - Link everything to the test user

  4. Run the test
     - Create new session with run.message
     - Send through orchestrator as the test user
     - For agents in real_agents: execute with real LLM
     - For HITL pauses: answer via LLM with user_prompt
     - Stop after last real_agent completes

  5. Evaluate
     - Run assertions against DB state
     - Run judge checks with LLM
     - Record all results

  6. Store results
     - Create TestRun record (links to benchmark_run)
     - Store assertion results + judge scores
     - Tag with test.tags + eval tags
     - Generate report section
```

### Parallel Execution

Tests are independent by design. The test runner can execute multiple tests concurrently:

```bash
python scripts/test_runner.py --all --parallel=4
```

Each test gets its own user, so there are no conflicts.

### Cleanup

Test users and their data accumulate by default. Cleanup options:
- **Admin UI**: "Delete all test users" button removes all users matching `test-*` pattern, their sessions, projects, repos, and evaluation results
- **CLI**: `python scripts/test_runner.py --cleanup`
- **Per-run**: `python scripts/test_runner.py --all --cleanup-after` deletes test data after results are stored (keeps results, deletes user/sessions/repos)

---

## Part 5: Results & Analytics

### Storage

Results are stored in the existing `benchmark_runs` and `evaluation_results` tables with additions:

- `benchmark_runs.run_type` = `"test"` for test runs
- `evaluation_results` stores both assertion results and judge scores
- Tags stored in a new `test_run_tags` table (normalized, per CLAUDE.md rules):

```sql
CREATE TABLE test_runs (
    id UUID PRIMARY KEY,
    benchmark_run_id UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    test_name VARCHAR(255) NOT NULL,
    test_description TEXT,
    test_user VARCHAR(255),           -- the created test user
    sessions_seeded INTEGER,          -- how many sessions were seeded
    assertions_total INTEGER,
    assertions_passed INTEGER,
    judge_checks_total INTEGER,
    judge_checks_passed INTEGER,
    status VARCHAR(50),               -- passed, failed, error
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE test_run_tags (
    id UUID PRIMARY KEY,
    test_run_id UUID REFERENCES test_runs(id) ON DELETE CASCADE,
    tag VARCHAR(100) NOT NULL
);

CREATE INDEX idx_test_run_tags_tag ON test_run_tags(tag);
```

Results are grouped by eval tags (from the eval definitions) as well as test tags. The analytics show pass rate per eval across different tests — so you can see how well `router-correct-intent` performs across all tests that reference it.

### Generated Report

After a test run, a markdown report is generated and stored:

```markdown
# Test Run: 2026-03-21 20:30

**Total: 8/10 passed** | Duration: 45.2s | Judge: claude-sonnet-4-6

## Results by Tag

### router (3 tests) — 100% pass rate
| Test | Status | Duration | Assertions | Judge |
|------|--------|----------|------------|-------|
| router-update-selects-weather | PASS | 4.2s | 3/3 | 1/1 |
| router-update-selects-todo | PASS | 3.8s | 3/3 | 1/1 |
| router-create-not-update | PASS | 4.0s | 2/2 | 1/1 |

### architect (2 tests) — 50% pass rate
| Test | Status | Duration | Assertions | Judge |
|------|--------|----------|------------|-------|
| architect-design-quality | PASS | 12.1s | 2/2 | 2/2 |
| architect-nora-compliance | FAIL | 11.5s | 2/2 | 0/1 |
  > Judge: "The design does not reference the NORA 5-layer model"

### project-selection (3 tests) — 100% pass rate
...
```

The report is saved to `testing/reports/YYYY-MM-DD-HHMMSS.md` and also stored in the DB for the admin UI.

### Admin UI

The admin evaluations page (`/admin/evaluations`) shows:

1. **Test Runs tab** — list of test runs with overall pass/fail, filterable by tags
2. **Tag Analytics tab** — pass rate per tag over time (shows trends)
3. **Eval Analytics tab** — pass rate per eval across different tests (shows which evals fail most often)
4. **Test Detail** — click a run to see all individual test results
5. **Result Detail** — click a test result to see assertions, judge checks, reasoning
6. **Actions**:
   - "Run All Tests" button
   - "Run Tests by Tag" dropdown
   - "Delete All Test Users" button
   - "Delete Test Run" per-run button

---

## Part 6: CLI & Docker

### CLI

```bash
# List all tests
python scripts/test_runner.py --list

# Run a specific test
python scripts/test_runner.py --test=router-update-selects-weather

# Run tests by tag
python scripts/test_runner.py --tag=router

# Run all tests
python scripts/test_runner.py --all

# Run all tests, 4 in parallel
python scripts/test_runner.py --all --parallel=4

# Run with specific judge model
python scripts/test_runner.py --all --judge-model=claude-opus-4-6

# Dry run (validate test files without executing)
python scripts/test_runner.py --all --dry-run

# Cleanup test users
python scripts/test_runner.py --cleanup

# Run and cleanup after
python scripts/test_runner.py --all --cleanup-after
```

### Docker Compose

```bash
# Run integration tests (DB only, no LLM)
docker compose --profile test-integration up --abort-on-container-exit

# Run full test suite (requires LLM API key)
docker compose --profile test-full up --abort-on-container-exit
```

---

## Summary of Changes from v1

| v1 (Current) | v2 (This Spec) |
|---|---|
| Seeds, evaluations, scenarios are separate concepts | Sessions + evals + tests are the three concepts |
| Scenarios duplicate agent definitions from seeds | Tests reference sessions by name |
| Evaluations bake in the correct answers | Evals define WHAT to check; tests provide expected values |
| No argument matching modes | Three modes: exact, wildcard (`*`), any-of list |
| Scripted HITL answers (question_contains matching) | LLM simulator with a prompt per test |
| CLI-only | CLI + admin UI + reports |
| No test isolation | Each test gets its own user + repos |
| No analytics grouping | Tags + eval-level analytics for filtering and trends |
| No parallel execution | User isolation enables parallel runs |
| No composition | Sessions chain via `after:` |
