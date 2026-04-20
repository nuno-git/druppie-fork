# reviewer

File: `druppie/agents/definitions/reviewer.yaml` (62 lines).

## Role

Code quality review. Produces `REVIEW.md` in the workspace with findings by severity.

## Config

| Field | Value |
|-------|-------|
| category | quality |
| llm_profile | standard |
| temperature | 0.1 |
| max_tokens | 100000 |
| max_iterations | 50 |
| MCPs | `coding` (read_file, list_dir, write_file, run_git) |
| skills | code-review |

## Output: `REVIEW.md`

Structure:
1. **Summary** — executive overview.
2. **Issues by severity** — Critical / High / Medium / Low, each with file:line references.
3. **Recommendations** — concrete fixes.
4. **Positive observations** — what the team did well.

## Flow

1. Pull latest.
2. Read changed files and relevant config.
3. `invoke_skill("code-review")` for the review checklist.
4. Author `REVIEW.md`.
5. Commit + push.
6. `done()`.

## Placement in pipeline

Optional — the planner can include it before or after test_executor depending on the session. In practice it's invoked by the user via `general_chat` intent ("review this project") more often than automatically.
