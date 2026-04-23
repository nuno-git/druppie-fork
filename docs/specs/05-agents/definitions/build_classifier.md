# build_classifier

File: `druppie/agents/definitions/build_classifier.yaml` (76 lines).

## Role

Deterministic routing between two build paths:
- **CORE_UPDATE** — the user's intent implies modifying Druppie itself (new MCP module, tweak to an agent, change to backend code). Routes to `update_core_builder`.
- **STANDALONE** — the user's intent is a new project. Routes to `builder_planner`.

## Config

| Field | Value |
|-------|-------|
| category | system |
| llm_profile | cheap |
| temperature | 0.0 |
| max_tokens | 4096 |
| max_iterations | 5 |
| builtin tools | `done` |
| MCPs | `coding` (read_file, list_dir only) |
| system prompts | tool_only_communication, summary_relay, done_tool_format, workspace_state |

Zero temperature + low iteration count — this is a pure deterministic classifier.

## Decision rules

### CORE_UPDATE triggers
- Intent mentions "new module" / "new MCP server" / "new tool".
- Intent mentions modifying an existing agent (architect.yaml, builder.yaml, etc.).
- Intent mentions changing Druppie's backend routes, services, UI.
- Intent cites a specific file under `druppie/` or `frontend/`.

### STANDALONE triggers
- Intent is a user-facing app (todo, portfolio, dashboard, chat client).
- Intent can stand alone in its own repo.
- Technical design implies a new FastAPI + React + Postgres app.

## Output

Single call: `done(summary="BUILD_PATH=CORE_UPDATE reason=<one line>", next_agent="update_core_builder")` or `done(summary="BUILD_PATH=STANDALONE reason=<one line>", next_agent="builder_planner")`.

The `next_agent` field bypasses the planner entirely.

## Why a dedicated agent

Without the classifier, either the planner would have to carry this logic (bloating its already-long prompt) or each of builder_planner / update_core_builder would have to short-circuit if called wrongly. Keeping the decision in a narrow, cheap agent:
- Keeps the planner stable.
- Uses a cheap LLM for a binary decision.
- Logs the reasoning explicitly in the summary relay.
