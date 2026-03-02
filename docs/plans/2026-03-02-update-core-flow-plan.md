# Update Core Flow & GitHub App Integration — Implementation Plan

Date: 2026-03-02
Design: [2026-03-02-update-core-flow-design.md](./2026-03-02-update-core-flow-design.md)

> **Note:** `execute_coding_task` (builtin tool in `builtin_tools.py`) is still
> being developed on `feature/execute-coding-task`. This plan stays high-level
> on opencode internals — details will be filled in once that branch lands.

---

## Story 1: GitHub App Integration

### Task 1.1 — Create GitHub App (manual, one-time)

- Create `druppie-core-bot` at `github.com/settings/apps/new`
- Permissions: Contents R/W, Pull Requests R/W, Metadata R
- Install on `nuno-git/druppie-fork` only
- Download private key, store path + app ID + installation ID in `.env`

### Task 1.2 — GitHub App Token Service

- New file: `druppie/services/github_app_service.py`
- Reads `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_APP_INSTALLATION_ID` from env
- Generates RS256 JWT, exchanges for installation access token
- Caches token until near-expiry (~55 min)
- Single public method: `get_installation_token() -> str`
- Gracefully disabled when env vars missing (no error, returns None)
- Add `PyJWT[crypto]` to requirements

### Task 1.3 — Token injection in execute_coding_task

> Depends on `feature/execute-coding-task` being merged first.

- In `builtin_tools.py`, when `execute_coding_task` is called:
  - Check session intent
  - If `update_core`: use GitHub App token + druppie-fork URL + `colab-dev` as base branch
  - Otherwise: use Gitea token + project repo URL + `main` as base branch
- Opencode stays generic — receives URL + token, doesn't know GitHub vs Gitea

### Task 1.4 — PR creation on GitHub

> Depends on opencode's current PR creation logic being finalized.

- Opencode already creates PRs on Gitea
- Add GitHub PR creation: detect host from repo URL, call GitHub API with token
- `POST https://api.github.com/repos/{owner}/{repo}/pulls`
- Return PR number + URL (same interface as Gitea)

---

## Story 2: Update Core Flow

### Task 2.1 — Router: add `update_core` intent

- Edit `druppie/agents/definitions/router.yaml`
- Add fourth intent with keywords:
  - "change how you work", "update your prompt", "modify the agent",
    "improve yourself", "fix the router", "add a new skill", "change the planner"
- Router calls `set_intent(intent="update_core")` — no `project_name` parameter

### Task 2.2 — `set_intent`: handle `update_core`

- Edit `druppie/agents/builtin_tools.py` — `set_intent` function
- New branch for `intent == "update_core"`:
  - Do NOT create a project in DB
  - Do NOT create a Gitea repo
  - Set `session.intent = "update_core"`
  - Store repo context on session: repo URL, owner, name, base branch (`colab-dev`)
- Session model may need new fields for repo context (or reuse existing project fields)
- Call `_update_planner_prompt` with `update_core` intent

### Task 2.3 — Planner: add `UPDATE_CORE` workflow

- Edit `druppie/agents/definitions/planner.yaml`
- Add `UPDATE_CORE` section with two pipeline options:

  **Simple** (prompt tweaks, YAML, single-file, docs):
  1. Developer → Planner
  2. Summarizer

  **Complex** (new features, multi-file, architecture):
  1. BA → Planner
  2. Architect → Planner
  3. Developer → Planner
  4. Summarizer

- Decision criteria in prompt: specific/small → simple; vague/large/multi-component → complex
- Key differences from `update_project`: no deploy, no merge, branch naming `core/{desc}-{hash}`, PR targets `colab-dev`

### Task 2.4 — Update docs

- `docs/FEATURES.md` — document update_core flow
- `docs/TECHNICAL.md` — document GitHub App service, token injection
- `docs/BACKLOG.md` — remove/update relevant items if any

---

## Ordering

```
1.1  GitHub App (manual)         — do first, unblocks 1.2
1.2  Token service               — no code deps, can start immediately
2.1  Router update_core          — no code deps, can start immediately
2.2  set_intent update_core      — depends on 2.1 (for testing)
2.3  Planner UPDATE_CORE         — depends on 2.2 (for testing)
1.3  Token injection             — depends on 1.2 + feature/execute-coding-task merge
1.4  GitHub PR creation          — depends on 1.3 + opencode PR logic
2.4  Docs                        — do last, after everything works
```

Tasks 1.2, 2.1, 2.2, 2.3 can be built and tested independently.
Tasks 1.3 and 1.4 are blocked until `feature/execute-coding-task` merges.

---

## What stays unchanged

- `create_project` flow
- `update_project` flow
- `general_chat` flow
- Existing Gitea integration
- Frontend (sessions render normally regardless of intent)
- Approval workflow and HITL questions
