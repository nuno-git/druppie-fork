# developer

File: `druppie/agents/definitions/developer.yaml` (114 lines).

## Role

Three purposes, triggered by the planner:
1. **Branch setup** (update_project flow) — create a feature branch before business_analyst runs.
2. **Improvement** — implement user-feedback changes that emerged during deployer HITL.
3. **Merge** — create a PR from feature branch to main, merge it (requires `developer` approval), return final `done()`.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.1 |
| max_tokens | 4096 |
| max_iterations | 100 |
| builtin tools | `execute_coding_task` + `invoke_skill` + default |
| MCPs | `coding` (read_file, list_dir, get_git_status — read-only; writes via sandbox) |
| skills | code-review, git-workflow |

## Mode 1 — Branch setup

For update_project sessions, runs first:
1. Determine feature branch name from intent (e.g. `feature/add-reminders`).
2. `coding:run_git(command="checkout -b feature/add-reminders")`.
3. `done(summary="Agent developer: created feature branch feature/add-reminders from main")`.

## Mode 2 — Improvement

Triggered after deployer's HITL surfaces issues:
1. Read feedback from the summary relay.
2. `execute_coding_task` with specific change instructions.
3. After sandbox: `coding:run_git(command="pull")`.
4. `done(summary="...")` — planner re-runs test_executor + deployer.

## Mode 3 — Merge

After final deployer success:
1. `execute_coding_task(task="create pull request from <branch> to main")` — sandbox handles creation via coding MCP.
2. `coding:merge_pull_request(pr_number=N, delete_branch=true)` — **requires `developer` role approval** (global default).
3. Update session context with merged status.
4. `done()`.

## Approval

`coding:merge_pull_request` is the only high-stakes action this agent requires approval for. Global default: `developer` role.

## Skills

- `git-workflow` — branch naming, commit conventions.
- `code-review` — used when developer is reviewing deployer feedback to decide changes.
