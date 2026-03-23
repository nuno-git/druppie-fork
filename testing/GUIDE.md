# Testing Framework Guide

This guide explains how to create, run, and extend tests for Druppie's agent platform.

## Quick Start

```bash
# Run all tests from the admin UI
# 1. Open http://localhost:5374/admin/evaluations
# 2. Click "Run Tests" → select tests → click "Run"

# Or from CLI:
cd druppie
python scripts/test_runner.py --all           # Run all tests
python scripts/test_runner.py --tag=router    # Run tests by tag
python scripts/test_runner.py --test=router-create-recipe  # Run specific test
python scripts/test_runner.py --list          # List available tests
python scripts/test_runner.py --cleanup       # Delete test users
```

## Concepts

### Three Seed Modes

Tests support three modes for setting up world state:

| Mode | What it does | Speed | Use for |
|------|-------------|-------|---------|
| `record_only` | Inserts DB records directly from YAML | ~1-2s | Fast world-state setup before testing a specific agent |
| `replay` | Executes tool calls against real MCP servers | ~5-30s | Testing tool integration, verifying MCP servers |
| `live` | Runs full agent pipeline with LLM calls | ~30s-5min | End-to-end agent behavior testing |

### Three Verification Layers

| Layer | What it checks | Example |
|-------|---------------|---------|
| **Layer 1: Result Validators** | Tool output quality | `result_valid: [not_empty, no_error]` |
| **Layer 2: Side-Effect Verifiers** | Real world state after execution | `verify: [{file_exists: "design.md"}]` |
| **Layer 3: Pre-Validate Errors** | MCP server rejects bad input | `status: failed, error_contains: "mermaid"` |

### Cost Tiers

Tag tests with tiers to control what runs:

| Tag | What runs | Time |
|-----|-----------|------|
| `tier:fast` | record_only + replay tests | ~10s |
| `tier:standard` | + cheap live tests (router, single-agent) | ~2-3min |
| `tier:full` | everything including multi-agent E2E | ~15-30min |

## File Structure

```
testing/
├── GUIDE.md              ← You are here
├── sessions/             ← World state definitions (YAML)
│   ├── 00-todo-app-builder-failed.yaml
│   ├── 01-weather-dashboard-completed.yaml
│   └── ...
├── tests/                ← Test definitions (YAML)
│   ├── router-create-recipe.yaml
│   ├── planner-create-project-initial.yaml
│   └── ...
├── evals/                ← Evaluation definitions (YAML)
│   ├── router-correct-intent.yaml
│   ├── architect-produces-design.yaml
│   └── ...
├── profiles/
│   ├── hitl.yaml         ← HITL simulator profiles
│   ├── judges.yaml       ← Judge LLM profiles
│   └── replay_config.yaml ← Blocklist + mock results
└── reports/              ← Generated test reports
```

## Creating a Test

### Step 1: Choose a mode

Pick the right mode for what you're testing:

- Testing agent decision-making? → `live`
- Testing MCP tool integration? → `replay`
- Testing assertion/eval logic? → `record_only`

### Step 2: Define world state (optional)

If your test needs existing sessions/projects in the DB:

```yaml
test:
  sessions:
    - weather-dashboard-completed    # Always record_only (fast)
    - todo-app-builder-failed
  seed_sessions:                     # Optional: sessions with explicit mode
    - session: ba-wrote-fd
      mode: replay                   # Execute tool calls for real
```

### Step 3: Define what to run

```yaml
test:
  run:
    message: "build me a recipe sharing app"    # User input
    real_agents: [router]                        # Stop after these agents complete
    # Empty list = run all agents (full pipeline)
```

### Step 4: Define what to check

```yaml
test:
  # Reference reusable evals (with expected values for this test)
  evals:
    - eval: router-correct-intent
      expected:
        intent: create_project
        project_name: "*"              # Wildcard: just check it exists

  # Or inline assertions specific to this test
  evaluate:
    assertions:
      - agent: router
        completed: true
        tool_called: builtin:set_intent
        result_valid: [not_empty]      # Layer 1 validator
        status: completed              # Layer 3 status check
    verify:                            # Layer 2 side-effect checks
      - file_exists: "technical_design.md"
      - mermaid_valid: "technical_design.md"
    judge:
      checks:
        - "The router classified the intent correctly"
```

### Complete example

```yaml
test:
  name: router-create-recipe
  mode: live
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
```

## Creating an Eval

Evals define **what to check** (reusable across tests). Tests provide **expected values**.

```yaml
eval:
  name: router-correct-intent
  description: "Router should call set_intent with the correct intent and project"
  tags: [router, intent-classification, tier:standard]
  assertions:
    - agent: router
      completed: true
    - agent: router
      tool_called: builtin:set_intent
  judge:
    checks:
      - "The router should classify the intent correctly based on the user message"
```

### Assertion types

| Field | What it checks |
|-------|---------------|
| `completed: true/false` | Agent completed or failed |
| `tool_called: "server:tool"` | Tool was called (with optional arg matching) |
| `result_valid: [validators]` | Tool result passes validators |
| `status: completed/failed` | Tool call status |
| `error_contains: "text"` | Error message contains text |

### Result validators (Layer 1)

| Validator | What it checks |
|-----------|---------------|
| `not_empty` | Result is non-empty |
| `no_error` | No error indicators in result |
| `json_parseable` | Valid JSON |
| `{contains: "text"}` | Contains substring |
| `{matches: "regex"}` | Matches regex pattern |

### Side-effect verifiers (Layer 2)

| Verifier | What it checks |
|----------|---------------|
| `file_exists: "path"` | File exists in Gitea repo |
| `file_not_empty: "path"` | File has content |
| `file_contains: {path, content}` | File contains substring |
| `file_matches: {path, pattern}` | File matches regex |
| `mermaid_valid: "path"` | All mermaid blocks parse correctly |
| `git_branch_exists: "branch"` | Branch exists |
| `gitea_repo_exists: true` | Project repo exists |

## Creating a Session (World State)

Sessions define pre-existing state for tests:

```yaml
metadata:
  id: weather-dashboard-completed      # Unique ID (referenced by tests)
  title: "Build a weather dashboard"
  status: completed
  user: admin                          # Test user (admin, developer, etc.)
  intent: create_project
  project_name: weather-dashboard
  hours_ago: 3                         # How old the session appears

agents:
  - id: router
    status: completed
    tool_calls:
      - tool: "builtin:set_intent"
        arguments: {intent: create_project, project_name: weather-dashboard}
        status: completed
        result: "Intent set to create_project"
        execute: false                 # Skip in replay mode (use result)

messages:
  - role: user
    content: "Build me a weather dashboard"
  - role: assistant
    content: "Creating weather dashboard project"
    agent_id: router
```

### Tool call options

```yaml
tool_calls:
  - tool: "coding:make_design"
    arguments: {path: "design.md", content: "..."}
    execute: true                      # Force execute even if blocklisted
    status: completed

  - tool: "coding:execute_coding_task"
    arguments: {task: "Build the app"}
    execute: false                     # Force mock (use result below)
    result: "Built successfully"
    status: completed
    outcome:                           # Create files in Gitea
      target: gitea
      files:
        - path: "src/app.py"
          content: "print('hello')"
```

## Expected Value Matching

Three matching modes in `expected`:

```yaml
evals:
  - eval: router-correct-intent
    expected:
      intent: create_project           # Exact match
      project_name: "*"                # Wildcard: just check key exists
      intent: ["create_project", "update_project"]  # Any-of list
      project_id: "@project:weather-dashboard"       # Dynamic reference → UUID
```

## HITL Profiles

Define how the simulator answers agent questions:

```yaml
# testing/profiles/hitl.yaml
profiles:
  non-technical-pm:
    model: glm-5
    provider: zai
    prompt: "You are a non-technical project manager..."
  dutch-water-authority:
    model: glm-5
    provider: zai
    prompt: "You are a Dutch water authority employee..."
```

## Judge Profiles

Define the LLM model for judge evaluations:

```yaml
# testing/profiles/judges.yaml
profiles:
  default:
    model: glm-5
    provider: zai
  strict:
    model: glm-5
    provider: zai
```

## Replay Config

Control which tools are mocked in replay mode:

```yaml
# testing/profiles/replay_config.yaml
replay:
  blocklist:
    - coding:execute_coding_task      # Too slow
    - docker:build_image              # Side-effects
    - docker:deploy_container

  default_results:
    "coding:execute_coding_task": "Task completed successfully."

  timeout: 30                         # Seconds per tool call
  on_error: mock                      # mock | fail | skip
```

## Analytics Dashboard

View test results and trends:

- **Test History**: `/admin/evaluations` — run tests, see past batches
- **Analytics**: `/admin/tests/analytics` — graphs, trends, pass rates by agent/eval/tool
- **Batch Detail**: `/admin/tests/batch/:id` — drill into a specific run with charts

## Tips

1. **Start with `record_only`** — fastest feedback loop for writing new evals
2. **Use `tier:fast` tag** for tests that should run in every PR
3. **Keep sessions small** — only include the agents/tools needed for the test
4. **Use wildcards** — `"*"` is your friend when you don't care about exact values
5. **Combine evals + inline** — reference reusable evals AND add test-specific checks
6. **Check the analytics** — the pass-rate-by-agent chart quickly shows which agents need work
