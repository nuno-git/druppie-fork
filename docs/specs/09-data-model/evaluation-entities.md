# Evaluation Entities

Separate aggregate from sessions. Built around batches of test runs.

## Entities

### `benchmark_runs`
One row per batch. Columns:
- `name`, `run_type` (`batch` | `live` | `manual`).
- `git_commit`, `git_branch` — captured at start.
- `judge_model`, `config_summary`.
- `started_at`, `completed_at`.

### `evaluation_results` (v1, legacy)
Judge scoring outputs from the v1 evaluation engine.
- `benchmark_run_id`, `session_id`, `agent_run_id`, `agent_id`.
- `evaluation_name`, `rubric_name`.
- `score_type` (`binary` | `graded`), `score_binary`, `score_graded`, `max_score`.
- `judge_model`, `judge_prompt`, `judge_response`, `judge_reasoning`.
- `llm_model`, `llm_provider`, `judge_duration_ms`, `judge_tokens_used`.

### `test_runs` (v2, current)
One per test execution.
- `benchmark_run_id`, `test_name`, `test_description`.
- `test_user` — which Keycloak user impersonated.
- `hitl_profile`, `judge_profile` — names from testing/profiles.
- `sessions_seeded` — count of fixture sessions.
- `assertions_total / assertions_passed`.
- `judge_checks_total / judge_checks_passed`.
- `session_id` — the session the test produced.
- `status` (`passed` | `failed` | `error`), `duration_ms`.
- `batch_id` — groups tests from one "Run" click.
- `agent_id` — the primary agent under test.
- `mode` (`tool` | `agent`).

### `test_batch_runs`
Batch-level status (UI polling target).
- `id` (batch_id) — string.
- `status` (`running` | `completed` | `failed`).
- `message` — latest human-readable status line.
- `current_test`, `total_tests`.
- `started_at`, `completed_at`.

### `test_assertion_results`
Per-assertion result within a test run.
- `test_run_id`.
- `assertion_type`:
  - `completed` — did agent complete.
  - `tool_called` — specific tool was invoked.
  - `status_check` — session status matched expected.
  - `result_valid` — inline validator (not_empty, contains, matches).
  - `verify` — Gitea side-effect check.
  - `judge_check` — LLM judge PASS/FAIL.
  - `judge_eval` — judge meta-eval.
- `agent_id`, `tool_name`, `eval_name` — for filtering.
- `passed` bool.
- `message` — human-readable detail.
- `judge_reasoning`, `judge_raw_input`, `judge_raw_output` — for judge entries.

### `test_run_tags`
Many-to-many tags. `(test_run_id, tag)` composite.

## Flow

```
POST /api/evaluations/run-tests   (request with test_names + tag + options)
  │
  ▼
  create TestBatchRun(id=batch_uuid, status=running)
  enqueue N test threads on ThreadPoolExecutor
  return {batch_id}
  │
  ▼
per-thread:
  TestRunner.run_test(test_def, options)
    create BenchmarkRun (if v2 test)
    create test user (Keycloak + Gitea)
    execute chain / agents
    write TestRun
    write N TestAssertionResult rows
    write tag rows
    update TestBatchRun progress
  │
  ▼
after all tests: TestBatchRun.status = completed
  │
  ▼
UI polls GET /run-status/{batch_id} throughout
UI navigates to /admin/tests/batch/{batch_id} for drill-down
```

## Analytics views

All backed by `test_assertion_results` aggregations.

- **By Agent** — `GROUP BY agent_id`. Pass rates per agent over time or per batch.
- **By Eval** — `GROUP BY eval_name` (for judge checks). Which checks are strict, which are permissive.
- **By Tool** — `GROUP BY tool_name`. Which tools are unreliable.
- **By Test** — `GROUP BY test_run.test_name`. Which tests are flaky.

Batch scoping: optional `batch_id` narrows all views to a single run.

## Indexes

Performance-critical indexes:
- `test_assertion_results(test_run_id)`.
- `test_assertion_results(agent_id, created_at)`.
- `test_assertion_results(eval_name)`.
- `test_assertion_results(tool_name)`.
- `test_assertion_results(assertion_type)`.
- `test_runs(created_at)`, `test_runs(agent_id)`.
- `evaluation_results(agent_id, rubric_name, benchmark_run_id)`.

## Cleanup

- Deleting a BenchmarkRun cascades to its children (results / test_runs / assertion_results).
- Deleting a test user (via `/api/evaluations/test-users`) removes their Keycloak account and Gitea repos. Associated TestRun rows stay (session_id becomes dangling).
- `reset-hard` wipes everything.

## Why separate v1 and v2

`evaluation_results` predates the current testing framework. It stores flat judge scores without the fuller assertion taxonomy of v2. Both coexist:
- v1 populates `evaluation_results` (historical data).
- v2 populates `test_runs` + `test_assertion_results` (current).

Analytics views query both where appropriate. New tests should use v2. The v1 tables are retained for history and will likely be deprecated once all historical runs are migrated.
