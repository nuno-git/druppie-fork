# builder_planner

File: `druppie/agents/definitions/builder_planner.yaml` (187 lines).

## Role

Writes `builder_plan.md` — a detailed, implementation-ready plan the `builder` (and `test_builder`) can follow step by step.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.1 |
| max_tokens | 16384 |
| max_iterations | 30 |
| MCPs | `coding` (read_file, write_file, list_dir, run_git) |

## `builder_plan.md` structure

5 sections:

1. **Code Standards** — language, framework, naming conventions, directory structure, error handling, style.
2. **Test Framework** — framework name (pytest / vitest / jest), config file, dependencies, run command, coverage command.
3. **Test Strategy** — what to test, coverage goals, test types (unit / integration / e2e), mocking strategy, edge cases, file structure.
4. **Solution Strategy** — architecture pattern, libraries, data flow, state management, API design, config/env.
5. **Change Approach** — files to create/modify, order, git strategy (branching, commit cadence), Dockerfile changes, new dependencies.

## Critical constraints

- `/health` endpoint must be preserved — deployment requires it.
- Git workflow: pull → write → add → commit → push. Sandbox builder clones from git, so workspace files must be committed before sandbox runs.

## Flow

1. Pull latest from git.
2. Read `functional_design.md` + `technical_design.md`.
3. Author `builder_plan.md`.
4. `coding:run_git(command="add docs/builder_plan.md")`.
5. Commit + push.
6. `done()`.

## Output (summary relay)

Typical:
```
Agent builder_planner: wrote /workspace/docs/builder_plan.md — pytest framework,
8 unit tests planned for /tasks endpoints, SQLAlchemy ORM with Alembic,
docker-compose with postgres, /health endpoint preserved.
```

## Why separate from builder

The builder runs in an isolated sandbox with narrow context. A pre-built plan in the workspace lets the sandbox skip the "what should I build" phase and focus on code production. It also gives the test_builder a ready reference.
