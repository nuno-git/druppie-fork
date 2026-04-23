# Tool Tests

Path: `testing/tools/*.yaml`. Each file is a sequence of tool calls to replay through real MCP servers. No LLM is invoked.

Fast. Deterministic. Good for regression tests on:
- The router + planner correctly seeding the right agent pipeline.
- MCP tools producing expected results.
- Approval gates firing correctly.
- Session status transitions.

## YAML shape

```yaml
tool-test:
  name: create-todo-app
  description: Router → planner → BA flow produces a project with FD
  tags: [type:tool, create_project, happy-path]

  # Optional: extend another test's chain
  extends: setup-create-project-pipeline

  # Optional: seed fixtures
  setup:
    - fixture: user-fixture-1

  # Test actions
  chain:
    - agent: router
      tool: set_intent
      arguments:
        intent: create_project
        project_name: "@project:todo-app"
      execute: true
    - agent: planner
      tool: make_plan
      arguments:
        steps:
          - agent_id: business_analyst
            prompt: "Elicit requirements for todo app"
          - agent_id: planner
            prompt: "Re-evaluate"
      execute: true
    - agent: business_analyst
      tool: coding:make_design
      arguments:
        path: /workspace/docs/functional_design.md
        content: "# Functioneel Ontwerp..."
      mock: true                  # don't hit MCP; just record
      approval: approve           # if approval gate, approve it
      mock_result:
        success: true
      assert:
        - type: no_error
        - type: contains
          pattern: "Functioneel Ontwerp"

  # After chain completes, verify state
  session_status: active
  pending_agents: [business_analyst]

  # Top-level assertions
  assert:
    - name: BA completed
      ref: ba-completes-happy-path
    - name: FD tool called
      agent: business_analyst
      tool: coding:make_design

  # Side-effect checks on Gitea
  verify:
    - type: gitea_repo_exists
      repo: todo-app
    - type: file_exists
      path: docs/functional_design.md

  # LLM judge checks
  judge:
    profile: default
    context:
      - all_tool_calls: {agent: business_analyst}
    checks:
      - name: FD is comprehensive
        check: "Does the FD cover all 13 required sections?"
```

## ChainStep fields

| Field | Type | Purpose |
|-------|------|---------|
| `agent` | string | Which agent issued the tool call |
| `tool` | string | Tool name (e.g. `coding:make_design` or `done`) |
| `arguments` | dict | Tool arguments |
| `execute` | bool (default true) | Run for real or skip to mock_result |
| `mock` | bool (default false) | Explicit mock flag |
| `mock_result` | dict | Result returned if mocked |
| `approval` | `approve|reject` | Simulated approval decision for gated tools |
| `outcome` | dict | Side effects to apply when mocked (e.g. create files in Gitea) |
| `assert` | list | Per-step inline assertions |
| `planned_prompt` | string | Override the run's planned_prompt (for deterministic BA runs) |

## Dynamic references

`@project:name` in YAML resolves at runtime to the project's UUID for the current session. Enables testing the "create_project" path without hardcoding IDs.

## `extends`

Merges the `chain` from the named setup test before this test's own chain runs. Used to avoid duplicating the router+planner preamble in every test.

Setup tests live in the same directory: `setup-create-project-pipeline.yaml`, `setup-project-with-fd.yaml`, `setup-todo-app-pipeline.yaml`, etc.

## Assertions

### Inline (per step)

```yaml
assert:
  - type: not_empty
  - type: no_error
  - type: contains
    pattern: "DESIGN_APPROVED"
  - type: matches
    regex: "^Agent \\w+: .+$"
```

### Top-level

```yaml
assert:
  - agent: planner
    completed: true
  - agent: business_analyst
    tool: coding:make_design
    status: completed
  - ref: architect-produces-td         # reference to testing/checks/*.yaml
```

### Status check

```yaml
session_status: paused_approval
pending_agents: [business_analyst]
```

## Verify

Side-effect checks on Gitea after the chain runs:

```yaml
verify:
  - type: file_exists
    path: docs/functional_design.md
  - type: file_not_empty
    path: docs/functional_design.md
  - type: file_contains
    path: docs/functional_design.md
    pattern: "Functionele eisen"
  - type: file_matches
    path: docs/technical_design.md
    regex: "NORA-\\d+"
  - type: mermaid_valid
    path: docs/functional_design.md
  - type: git_branch_exists
    branch: feature/xxx
  - type: gitea_repo_exists
    repo: todo-app
```

## Judge checks

```yaml
judge:
  profile: default   # from testing/profiles/judges.yaml
  context:
    - agent_definition: {agent: business_analyst, fields: [system_prompt]}
    - all_tool_calls: {agent: business_analyst}
  checks:
    - name: FD in Dutch
      check: "Is the functional_design.md written in Dutch?"
    - name: No solution bias
      check: "Does the FD avoid prescribing a technical solution?"
```

## Tag system

`tags: [type:tool, happy-path, create_project]` — used by the UI to filter runnable tests, and by `POST /api/evaluations/run-tests {tag: "…"}` to run categories.

## Files shipped

Representative tests in `testing/tools/`:
- `general-chat.yaml`
- `create-todo-app.yaml`, `create-portfolio-site.yaml`, `create-expense-tracker.yaml`, `create-weather-dashboard.yaml`, `create-sdk-recipe-app.yaml`
- `setup-*.yaml` — extendable setup chains
- `architect-paused-mid-run.yaml` — tests UI resume behaviour
- `agent-without-done-fails.yaml` — negative case
- `git-commit-empty-fails.yaml` — negative case
- `read-nonexistent-file.yaml` — negative case
