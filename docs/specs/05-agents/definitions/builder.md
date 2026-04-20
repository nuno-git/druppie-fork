# builder

File: `druppie/agents/definitions/builder.yaml` (225 lines).

## Role

TDD Green phase. Implements code to make the test_builder's tests pass. Delegates the actual writing to a sandbox via `execute_coding_task`.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.2 |
| max_tokens | 16384 |
| max_iterations | 100 |
| builtin tools | `execute_coding_task` + default |
| MCPs | `coding` (read_file, list_dir, get_git_status, run_git) — read-only ops in Druppie; writes happen in sandbox |

## Flow (initial)

1. `coding:run_git(command="pull")` — get latest tests.
2. `coding:read_file(path="tests/…")` — inspect what to satisfy.
3. `coding:read_file(path="docs/builder_plan.md")` / `functional_design.md` / `technical_design.md` — context.
4. `execute_coding_task(task="<detailed, self-contained prompt>", agent="implement", repo_target="project")` — sandbox writes code, commits, pushes.
5. After sandbox completes (webhook): `coding:run_git(command="pull")` — sync sandbox commits.
6. `done(summary="...")`.

## TDD retry strategies

If the planner loops the builder due to test_executor FAIL:

### Attempt 1 — Targeted Fixes
Read test failures → make minimal fixes → re-test.

### Attempt 2 — Rethink & Rewrite
Discard partial work → reread the plan → rebuild the affected module.

### Attempt 3 — Simplify
Strip the solution to the bare minimum to make tests pass. Better a simple passing app than a complex failing one.

Each attempt is labeled in the summary (`attempt 1/3: targeted fixes`).

After 3 attempts planner escalates to business_analyst HITL.

## Critical post-sandbox step

After `execute_coding_task` completes, the builder MUST run `coding:run_git(command="pull")`. The sandbox commits push to git; the Druppie workspace needs to fetch them so subsequent agents (test_executor) see the updated files.

Agents frequently forget this — the prompt emphasises it in bold.

## Sandbox task prompt

The `task` argument passed to `execute_coding_task` must be **fully self-contained**. The sandbox agent doesn't see the summary relay or prior messages — it sees only the task string and the cloned repo.

Prompts include:
- The tests to pass (copy the test bodies into the prompt if small).
- Relevant design context (paste the builder_plan.md sections).
- Git directives (which branch, commit messages).
- Explicit completion criteria.
