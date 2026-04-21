# TDD Workflow Documentation

## Overview

The Test-Driven Development (TDD) workflow is now owned end-to-end by the
**builder agent**, which delegates all code and test work to three OpenCode
sandbox agents via `execute_coding_task`. The Druppie side of the flow holds
planning, orchestration, and HITL escalation — not file operations.

This replaces the earlier 4-agent pipeline (`builder_planner → test_builder →
builder → test_executor`). `test_builder` and `test_executor` have been removed.

## Architecture

### Druppie-side agents (execution)

| Agent | Role | Tools |
|-------|------|-------|
| **builder_planner** | Reads design docs (FD/TD), writes `builder_plan.md` (test framework, test strategy, solution approach). | coding MCP (read_file, write_file, list_dir, run_git) |
| **builder** | The sole execution agent. Four modes — TDD CYCLE (signals `TDD_PASSED`/`TDD_FAILED`), BRANCH SETUP (`BRANCH_CREATED`), IMPROVEMENT (`IMPROVEMENT_DONE`), MERGE (`MERGED`). All modes delegate to OpenCode via `execute_coding_task`. | `execute_coding_task` only |

### OpenCode sandbox agents (execution)

Defined in `druppie/opencode/config/agents/*.md`:

| Agent | Phase | Role |
|-------|-------|------|
| **druppie-test-writer** | Red | Reads FD/TD/builder_plan, sets up test framework, writes comprehensive tests. Commits + pushes. Does **not** run tests. |
| **druppie-implementer** | Green | Reads tests (source of truth) and design docs, implements production code to pass tests. Runs tests locally to self-verify. Commits + pushes. Never modifies tests. |
| **druppie-test-runner** | Verify | Runs the full test suite with coverage, emits a structured `---VERDICT---` block (`RESULT: PASS` or `FAIL`). Does not modify anything. Does not push. |

## Flow

```
builder_planner (Druppie, writes builder_plan.md)
     ↓
builder (Druppie, drives loop)
     ├─► execute_coding_task(agent="druppie-test-writer")   [Red]
     ├─► execute_coding_task(agent="druppie-implementer")   [Green — initial]
     ├─► execute_coding_task(agent="druppie-test-runner")   [Verify]
     │
     │   if RESULT: PASS   → done("Agent builder: TDD_PASSED ...")
     │   if RESULT: FAIL   → retry (see below)
     │
     ├─► retry 1: druppie-implementer (STRATEGY: TARGETED_FIXES) → test-runner
     ├─► retry 2: druppie-implementer (STRATEGY: REWRITE)        → test-runner
     └─► retry 3: druppie-implementer (STRATEGY: SIMPLIFY)       → test-runner

     if any retry PASS  → done("Agent builder: TDD_PASSED ...")
     if all 3 retries FAIL → done("Agent builder: TDD_FAILED ...")
     ↓
planner re-evaluates:
     TDD_PASSED → deployer
     TDD_FAILED → BA (HITL escalation) → user picks:
                   • continue with guidance → builder (fresh TDD cycle)
                   • deploy with warning    → deployer
                   • abort                  → summarizer
```

Retry count and strategy rotation live inside the **builder** agent's system
prompt — not inside the planner. The planner only branches on the final
`TDD_PASSED` / `TDD_FAILED` verdict.

## Signals the planner reads

| Source | Signal | Meaning |
|--------|--------|---------|
| builder `done()` (TDD mode) | `TDD_PASSED` | All tests pass. Route to deployer. |
| builder `done()` (TDD mode) | `TDD_FAILED` | All 3 retry strategies exhausted. Escalate to user via HITL. |
| builder `done()` (branch mode) | `BRANCH_CREATED` | Feature branch ready. Route to BA. |
| builder `done()` (improve mode) | `IMPROVEMENT_DONE` | User feedback applied. Route to deployer. |
| builder `done()` (merge mode) | `MERGED` | PR merged. Route to deployer for final deploy. |
| BA `done()` | `HITL_ESCALATION_RESULT: <choice>` | User's decision after TDD_FAILED. |

## Verdict block contract

The `druppie-test-runner` agent emits either:

```
---VERDICT---
RESULT: PASS
Framework: pytest
Tests: 12/12 passed
Coverage: 87%
---END VERDICT---
```

or on failure:

```
---VERDICT---
RESULT: FAIL
Framework: pytest
Tests: 9/12 passed
Coverage: 62%

### Failing tests
- test_upload_recipe in tests/test_routes.py:42
  AssertionError: expected 200, got 404

### Raw output
```
<stdout + stderr from the test framework>
```
---END VERDICT---
```

The builder parses this block and either commits success or formulates a
retry prompt that pastes the full VERDICT for context.

## Why this design

- **One source of truth for the retry loop.** Previously the planner counted
  `"TDD RETRY"` substrings in accumulated summaries — fragile and hard to
  reason about. Now retries live inside the builder's prompt.
- **Sandbox isolation.** All mutating operations (write tests, implement,
  run tests) happen in throwaway containers. The Druppie workspace never
  holds dirty state; everything syncs via git push/pull.
- **Clear separation of planning vs. execution.** `builder_planner` owns
  planning (runs in Druppie workspace with direct MCP tools). `builder`
  owns execution (runs in Druppie but only dispatches to sandboxes).

## Files

- Druppie-side agent definitions: `druppie/agents/definitions/{builder_planner,builder,planner}.yaml`
- OpenCode sandbox agents: `druppie/opencode/config/agents/druppie-{test-writer,implementer,test-runner}.md` (TDD mode) and `druppie-builder.md` (non-TDD modes)
- `execute_coding_task` builtin: `druppie/agents/builtin_tools.py`
