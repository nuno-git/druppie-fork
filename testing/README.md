# Testing & Evaluation Framework

Declarative session seeding, LLM-as-judge evaluation, and end-to-end test execution for Druppie agents.

## Directory Structure

```
testing/
  sessions/       <- Session definitions (used for both demo seeding AND test worlds)
  evals/           <- Evaluation checks (what to verify, reusable across tests)
  tests/           <- Test definitions (combine sessions + run + evals)
  profiles/        <- HITL and judge model configurations
    hitl.yaml
    judges.yaml
  reports/         <- Generated test reports (gitignored)

druppie/testing/                      <- Python code (one package)
  seed_schema.py, seed_loader.py,     <- Seeding: schema, loader, UUID generation
    seed_ids.py
  v2_schema.py, v2_runner.py,         <- Test runner: schema, runner, assertions
    v2_assertions.py
  eval_schema.py, eval_judge.py,      <- Evaluation: judge engine, context extraction,
    eval_context.py, eval_config.py,      config, live eval hook
    eval_live.py

scripts/                              <- CLI entry points
  seed.py                             <- Seed the database
  test_runner.py                      <- Run tests

evaluation_config.yaml                <- Live evaluation config (project root)
```

## Quick Start

### 1. Seed the Database

Populates the DB with realistic session fixtures. Use after `reset-db` to get a working demo environment.

```bash
# Reset DB, then seed with real Gitea repos
docker compose --profile reset-db run --rm reset-db
DATABASE_URL=postgresql://druppie:druppie_secret@localhost:5634/druppie \
    python scripts/seed.py --gitea-url=http://localhost:3200

# Or without Gitea (record-only mode, placeholder URLs)
python scripts/seed.py
```

Each seed file is a self-contained session. Tool calls are the source of truth -- there is no separate `project:` block. The project exists because `set_intent` was called; files exist because `execute_coding_task` ran.

```yaml
# testing/sessions/02-calculator-architect-paused.yaml
metadata:
  id: calculator-architect-paused
  title: "create a scientific calculator"
  status: paused_approval
  user: admin
  intent: create_project
  project_name: calculator

agents:
  - id: router
    status: completed
    tool_calls:
      - tool: builtin:set_intent
        arguments: { intent: create_project, project_name: calculator }
        status: completed
        result: "Intent set to create_project"
      - tool: builtin:done
        arguments: { summary: "Classified intent as create_project" }
        status: completed
        result: "Agent completed"
```

The `outcome:` block on `execute_coding_task` creates real files in Gitea when `--gitea-url` is provided:

```yaml
      - tool: builtin:execute_coding_task
        arguments: { task: "Implement weather dashboard", agent: druppie-builder }
        status: completed
        result: "Sandbox completed successfully"
        outcome:
          target: gitea
          files:
            - path: "src/App.jsx"
              content: |
                import React from 'react';
                // ...
```

### 2. Run V2 Tests

The v2 test runner creates isolated users per test, seeds world state, runs real agents with LLM calls, handles HITL simulation, and evaluates with assertions and LLM judge checks.

```bash
# List all tests
python scripts/test_runner.py --list

# Run a specific test
python scripts/test_runner.py --test=router-create-recipe

# Run tests by tag
python scripts/test_runner.py --tag=router

# Run all tests
python scripts/test_runner.py --all

# Dry run (validate without executing)
python scripts/test_runner.py --all --dry-run
```

### 3. Admin UI

Navigate to `/admin/evaluations` in the frontend. Shows test runs, evaluation scores, and per-session results.

### 4. Docker Compose Test Profiles

```bash
# Integration tests (isolated test DB)
docker compose --profile test-integration up --abort-on-container-exit

# V2 tests (run inside backend container)
docker exec druppie-new-backend python scripts/test_runner.py --all
```

## Key Concepts

- **Sessions** -- Declarative session state as YAML. Tool calls are the source of truth. The `outcome:` block on `execute_coding_task` creates real files in Gitea/GitHub so seeded sessions have browsable repos. Used for both demo seeding (admin sidebar) and test world state.

- **Evals** -- Reusable evaluation checks. Each eval defines assertions (deterministic checks) and optional judge checks (LLM-as-judge). Referenced by tests via name.

- **Tests** -- Test definitions that combine sessions (world state) + a run (message + agents) + evals (assertions + judge checks). Support HITL and judge profile matrix execution.

- **Profiles** -- HITL profiles (model + prompt for simulating users) and judge profiles (model + config for LLM-as-judge).
