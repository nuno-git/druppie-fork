# Testing & Benchmarking Framework

Declarative session seeding, LLM-as-judge evaluation, and end-to-end benchmarking for Druppie agents. Seed the database from YAML fixtures, score agent behavior with configurable judge rubrics, and run controlled benchmark scenarios to compare models, prompts, and configurations.

## Directory Structure

```
testing/                              <- All YAML data files
  seeds/                              <- Session fixtures for DB seeding (11 files)
  evaluations/
    architect/                        <- Rubrics for architect agent
      design_quality.yaml
    builder/                          <- Rubrics for builder agent
      tool_compliance.yaml
  scenarios/                          <- Benchmark test scenarios (3 files)

druppie/testing/                      <- Python code (one package)
  seed_schema.py, seed_loader.py,     <- Seeding: schema, loader, UUID generation
    seed_ids.py
  eval_schema.py, eval_judge.py,      <- Evaluation: judge engine, context extraction,
    eval_context.py, eval_config.py,      config, live eval hook
    eval_live.py
  bench_schema.py, bench_runner.py,   <- Benchmarks: scenario runner, assertions,
    bench_assertions.py,                  user simulator
    bench_simulator.py

scripts/                              <- CLI entry points
  seed.py                             <- Seed the database
  evaluate.py                         <- Run evaluations
  benchmark.py                        <- Run benchmark scenarios

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
# testing/seeds/02-calculator-architect-paused.yaml
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

### 2. Run Evaluations (LLM-as-Judge)

Scores a completed session against rubric definitions. Results are stored in a `benchmark_runs` DB table.

```bash
# List available evaluations
python scripts/evaluate.py --list

# Run a specific evaluation
python scripts/evaluate.py \
    --evaluation=architect_design_quality \
    --session-id=<uuid>

# Override judge model
python scripts/evaluate.py \
    --evaluation=architect_design_quality \
    --session-id=<uuid> \
    --judge-model=glm-5
```

Rubrics live in `testing/evaluations/<agent>/`. Each rubric defines context extraction (which tool calls, messages, or definitions to pull) and judge prompts with `graded` (1-5) or `binary` (pass/fail) scoring:

```yaml
rubrics:
  - name: requirement_coverage
    scoring: graded
    prompt: |
      Score 1-5: Does the technical design cover the user's requirements?
      ...
```

### 3. Run Benchmarks

Runs end-to-end scenarios with mocked agents, real agents under test, automated assertions, and optional LLM-as-judge evaluation.

```bash
# List scenarios
python scripts/benchmark.py --list

# Run one scenario
python scripts/benchmark.py --scenario=create-todo-app

# Run all, dry-run (validates YAML only)
python scripts/benchmark.py --all --dry-run

# Run all with a specific judge model
python scripts/benchmark.py --all --judge-model=glm-5
```

Scenarios define input, mocked agents, agents under test, assertions, evaluations, and an optional user simulator for HITL questions:

```yaml
scenario:
  name: create_todo_app
  input:
    user_message: "build me a simple todo app"
    user: admin
  mocked_agents:
    - agent_id: router
      # ... predetermined tool calls
  agents_under_test: [business_analyst, architect]
  evaluations: [architect_design_quality]
  assertions:
    - agent: architect
      assert: completed
  user_simulator:
    mode: scripted
    scripted_answers:
      - question_contains: "features"
        answer: "Add, delete, mark complete. No auth needed."
    default_answer: "Yes, that sounds good."
  timeout_minutes: 15
```

### 4. Live Evaluation

Scores production sessions in the background as agents complete. Edit `evaluation_config.yaml` at the project root:

```yaml
live_evaluation:
  enabled: true               # flip to true
  sample_rate: 1.0             # 0.0-1.0
  judge_model: glm-5
  agent_evaluations:
    architect:
      - architect_design_quality
    builder:
      - builder_tool_compliance
```

No restart required -- config is re-read on each agent completion.

### 5. Admin UI

Navigate to `/admin/evaluations` in the frontend. Shows benchmark runs, evaluation scores, and per-session results.

### 6. Docker Compose Test Profiles

```bash
# Integration tests (isolated test DB)
docker compose --profile test-integration up --abort-on-container-exit

# Benchmark tests (dry-run by default; set BENCHMARK_JUDGE_MODEL for real runs)
docker compose --profile test-benchmark up --abort-on-container-exit
```

## Key Concepts

- **Seeds** -- Declarative session state as YAML. Tool calls are the source of truth. The `outcome:` block on `execute_coding_task` creates real files in Gitea/GitHub so seeded sessions have browsable repos.

- **Evaluations** -- LLM-as-judge rubrics that score agent behavior. Each rubric extracts context (tool call results, agent definitions, session messages) and sends a judge prompt. Scoring is `binary` (pass/fail) or `graded` (1-5). Configurable per-agent.

- **Scenarios** -- End-to-end benchmark definitions. Mock early agents (router, planner), run later agents for real, assert on outcomes, and optionally run evaluations. A user simulator answers HITL questions automatically.

- **Live evaluation** -- Background scoring of production sessions. Controlled by `evaluation_config.yaml`. Results feed the admin UI dashboard for ongoing quality tracking.
