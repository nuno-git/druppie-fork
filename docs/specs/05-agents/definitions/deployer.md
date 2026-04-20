# deployer

File: `druppie/agents/definitions/deployer.yaml` (183 lines).

## Role

Build images, deploy containers via docker-compose, ask user for feedback. Every docker operation requires `developer` approval (global default).

## Config

| Field | Value |
|-------|-------|
| category | deployment |
| llm_profile | standard |
| temperature | 0.1 |
| max_tokens | 100000 |
| max_iterations | 100 |
| MCPs | `docker` (compose_up, compose_down, list_containers, logs, inspect — all require developer approval), `coding` (read_file, write_file, list_dir, run_git) |

## Flow

### Step 0 — Discover
`docker:list_containers(project_id=<id>)` — find any existing containers for this project.

### Step 1 — Deploy
`docker:compose_up(repo_name=…, branch=…, compose_project_name=…, health_path="/health", health_timeout=60)` — **requires developer approval**.
- `compose_up` internally clones the repo, builds, starts, health-checks, and returns the URL.
- Branch is explicit (not auto-injected) — the agent must pass the correct feature branch for update_project sessions.

### Step 2 — Ask user
For non-final deploys:
```
hitl_ask_question(
  question="Deployment is live at https://…:9105/. Does this look good?",
  context="..."
)
```
Pauses until user answers.

### Step 3 — Report
Include the user's feedback in the done() summary:
```
Agent deployer: deployed project to http://localhost:9105 via compose project
todo-app-preview on branch feature/add-reminders. USER FEEDBACK: "looks good,
can we tweak the color?"
```

## Compose project naming

- **create_project** — use the project name directly: `compose_project_name="todo-app"`.
- **update_project PREVIEW** — append `-preview`: `compose_project_name="todo-app-preview"`.
- **update_project FINAL** (after PR merge) — use project name, but FIRST `docker:compose_down(compose_project_name="todo-app-preview")` AND stop-old-production.

## Three modes

1. **create_project deploy** — first and only deploy.
2. **update_project PREVIEW deploy** — deploy feature branch to `-preview` compose project.
3. **update_project FINAL deploy** — stop preview, stop old production, deploy new production from merged main.

## Resume check

When the deployer run resumes from an approval, it reads the context for:
- `deployment_complete` — already deployed, don't redo.
- `last_approved_tool` — was it `compose_up` (deploy done) or `compose_down` (teardown done)?
- `last_tool_result` — URL, container names.

This avoids duplicate deployments when the agent resumes after a crash mid-flow.

## Port allocation

Handled by `module-docker` — the deployer doesn't pick a port. The returned URL reflects whatever port `module-docker` allocated from the 9100-9199 pool.

## Health check

`compose_up` has built-in health check against `{project_name}-app-1:{container_port}{health_path}` on the internal Docker network. If it fails, the compose is torn down and the tool returns an error. The deployer then asks the user whether to retry or roll back.
