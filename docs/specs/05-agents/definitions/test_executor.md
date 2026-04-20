# test_executor

File: `druppie/agents/definitions/test_executor.yaml` (186 lines).

## Role

Run tests, analyse results, report PASS/FAIL. Explicitly does NOT fix code — analysis and reporting only.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.2 |
| max_tokens | 16384 |
| max_iterations | 25 |
| builtin tools | `test_report` + default |
| MCPs | `coding` (get_test_framework, run_tests, get_coverage_report, install_test_dependencies, run_git) |

## Flow

1. `coding:run_git(command="pull")`.
2. `coding:get_test_framework()` — confirm framework.
3. If deps missing → `coding:install_test_dependencies()` (1200 s timeout).
4. `coding:run_tests()` (1200 s timeout).
5. `coding:get_coverage_report()` (optional if coverage unavailable).
6. `test_report(iteration, tests_passed, summary, failed_count, passed_count, error_classification)`.
7. `done(summary="...")`.

## Pass / fail criteria

Pass:
- All tests pass (0 failed).
- Coverage > 80% (OR unavailable — don't block on missing coverage).
- No critical env errors.

Fail:
- ≥1 test failing, OR
- Critical errors (import errors, compile errors), OR
- Environment issues preventing test execution.

## `test_report` output

Structured:
```
test_report(
  iteration=1,
  tests_passed=false,
  summary="3 of 8 tests failing in test_tasks.py: create returns 400 instead of 201, ...",
  test_command="pytest -v",
  failed_count=3,
  passed_count=5,
  error_classification="code_bug"  # code_bug|test_bug|env_bug|flaky
)
```

Error classification helps the planner decide which retry strategy to use:
- `code_bug` — builder fixes.
- `test_bug` — test_builder updates the tests.
- `env_bug` — install_test_dependencies or other setup.
- `flaky` — retry once, then investigate.

## `done()` format

Summary line includes the result prominently:
```
Agent test_executor: ## TEST RESULT: PASS (8/8 tests, coverage 87%). All assertions OK.
```

or

```
Agent test_executor: ## TEST RESULT: FAIL (5/8 tests, 3 failures in test_tasks.py).
code_bug classification; see test_report for details.
```

The `## TEST RESULT: PASS` / `## TEST RESULT: FAIL` tag is the planner's parser-friendly signal.
