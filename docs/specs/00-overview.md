# 00 — System Overview

## What Druppie is

Druppie is a **governance platform for AI agents**. It takes a user intent expressed in natural language and drives it through a pipeline of specialised LLM agents that produce real artifacts (functional designs, technical designs, code, tests, deployments) with **approval gates** enforced against role-based permissions.

The platform is the anti-"one monolithic agent": every phase of the SDLC has a dedicated agent with a narrow system prompt, a restricted toolset, and explicit handoff semantics. Agents never output free-form text directly — every effect must go through a tool. Two categories exist: **built-in tools** run in-process inside the Druppie backend (`done`, `make_plan`, `set_intent`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`, `create_message`, `invoke_skill`, `execute_coding_task`, `test_report`), and **MCP tools** run in separate FastMCP servers (coding, docker, web, filesearch, archimate, registry). A mandatory `done()` call ends each agent run and relays a summary to the next agent.

## Top-level value propositions

1. **Auditable autonomy.** Every LLM call, tool invocation, approval decision, and HITL question is persisted. The UI reconstructs a chronological timeline.
2. **Governance by construction.** Agents cannot write to disk, push code, merge PRs, or deploy containers without an approval record that matches the required role (`architect`, `developer`, `session_owner`, etc.).
3. **Reusable modules.** MCP servers are versioned, containerised, and self-describing. New capabilities are added by creating a new module, not by patching the core.
4. **Dual-mode: projects and core.** The same orchestrator can build a new user project (`create_project`, `update_project`) or modify Druppie itself (`CORE_UPDATE` path through `build_classifier` → `update_core_builder`).
5. **Full evaluation harness.** `druppie/testing/` + `testing/*.yaml` supports tool-level replay tests (real MCP, no LLM), agent-level tests (real LLMs + HITL simulator personas), and LLM-judge checks.

## Component map

| Layer | Implementation | Key entry points |
|-------|----------------|------------------|
| **Frontend SPA** | React 18 + Vite 5 + Tailwind + React Query + Keycloak JS | `frontend/src/main.jsx`, `frontend/src/App.jsx` |
| **Backend API** | FastAPI on Python 3.11, SQLAlchemy, Pydantic | `druppie/api/main.py` |
| **Orchestrator** | Custom tool-calling loop (OpenAI function-calling format), per-agent iteration limits | `druppie/execution/orchestrator.py`, `druppie/agents/loop.py` |
| **Agent definitions** | 14 agent YAML files + 4 system-prompt snippets + `llm_profiles.yaml` (3 profiles) | `druppie/agents/definitions/` |
| **MCP servers** | FastMCP over HTTP, one container per module | `druppie/mcp-servers/module-*/` |
| **Skills** | Markdown prompt modules agents load on demand | `druppie/skills/*/SKILL.md` |
| **Project templates** | Stub React+FastAPI app with `/health` endpoint | `druppie/templates/project/` |
| **Sandbox infra** | Vendored `background-agents/` — Express control plane, FastAPI sandbox manager, Modal (prod) | `background-agents/packages/` |
| **Testing harness** | Replay executor, bounded orchestrator, HITL simulator, LLM judge | `druppie/testing/` + `testing/*.yaml` |
| **Infra & init** | Docker Compose with profiles, Keycloak/Gitea init scripts | `docker-compose.yml`, `scripts/` |
| **IAC config** | Keycloak realm and users as YAML | `iac/realm.yaml`, `iac/users.yaml` |
| **Prod deploy (sandbox)** | Terraform → Cloudflare Workers + D1 + Vercel + Modal | `background-agents/terraform/` |

## The five request shapes

1. **User chat → agent pipeline.** `POST /api/chat` creates or resumes a `Session`, spawns a background task that runs the orchestrator, returns immediately. Client polls `GET /api/sessions/{id}` every few seconds.
2. **Approval resolution.** `POST /api/approvals/{id}/approve|reject` — two-phase: DB update commits synchronously, then a background task resumes the orchestrator from the paused tool call.
3. **HITL answer.** `POST /api/questions/{id}/answer` — same two-phase pattern, resumes the agent with the answer in context.
4. **Sandbox webhook.** Control plane → Druppie `POST /api/sandbox-sessions/{id}/complete` with HMAC signature. Druppie fetches events, extracts files/git/PRs/output, marks the sandbox tool call COMPLETED/FAILED, resumes the agent run.
5. **Evaluation run.** `POST /api/evaluations/run-tests` — batches YAML test definitions, executes via `TestRunner`, writes to `test_runs` + `test_assertion_results` tables; UI polls via `batch_id`.

## Canonical agent pipeline (create_project)

```
router → planner → business_analyst → architect → build_classifier
                                         │
                    STANDALONE ──────────┴──────── CORE_UPDATE
                         │                             │
                 builder_planner                update_core_builder
                         │                             │
                  test_builder                   architect(run 2)
                         │                             │
                     builder                      (normal flow)
                         │
                 test_executor
                         │
       ┌─────────────────┼─────────────────┐
     PASS            FAIL (retries<3)   FAIL (>=3 retries)
       │                 │                   │
    deployer           builder         business_analyst
       │             (with feedback)   (HITL escalation)
     summarizer
```

Each transition is governed by the **planner** (re-evaluates after each agent finishes) except for deterministic handoffs via `done(next_agent=…)` (used by `architect` → `build_classifier` and `build_classifier` → `builder_planner` / `update_core_builder`).

## Canonical status state machine (session)

```
ACTIVE ──┬──► PAUSED_APPROVAL ──(approve)──► ACTIVE
         ├──► PAUSED_HITL ─────(answer) ───► ACTIVE
         ├──► PAUSED_SANDBOX ──(webhook) ──► ACTIVE
         ├──► PAUSED ──────────(user stop, then resume) ──► ACTIVE
         ├──► PAUSED_CRASHED ──(resume) ───► ACTIVE
         ├──► COMPLETED (terminal)
         └──► FAILED (terminal, but retry-from is allowed)
```

Crash recovery happens on FastAPI startup via `_recover_zombie_sessions()` in `druppie/api/main.py`. Active sessions are marked `PAUSED_CRASHED` if they have agent runs stuck `RUNNING`, otherwise `PAUSED`; failed sessions with orphaned `RUNNING` runs are also rescued to `PAUSED_CRASHED` (see `druppie/repositories/execution_repository.py:889`).

## Key architectural invariants

- **No database migrations.** SQLAlchemy ORM `Base.metadata.create_all()` runs at startup. Schema changes ship with a reset: `docker compose --profile reset-db run --rm reset-db`.
- **No JSON/JSONB blobs for queryable data.** Use normalised tables. JSON is only used for opaque payloads (tool `arguments`, LLM messages, choices arrays).
- **Agents communicate via tools only.** Agents never emit free-text to the user. All user-facing text is either the `summarizer`'s `create_message` or a HITL question (`hitl_ask_question` / `hitl_ask_multiple_choice_question`). These live alongside MCP tools in the same OpenAI-format tool list handed to the LLM; the ToolExecutor routes each call to either an in-process builtin handler or an HTTP MCP server.
- **Config as YAML, not DB.** Agent definitions, LLM profiles, MCP config live in the repo and reload at startup.
- **MCP servers are independent.** Each has its own Dockerfile, versioned `vN/` directory, and can be deployed separately.
- **Row-level locking for retries.** `SELECT … FOR UPDATE` in `SessionService.lock_for_retry/resume()` prevents double-spawn.
- **Sandbox work is ephemeral.** Containers die after the task completes. Anything not committed+pushed via the git MCP is lost.

## Non-goals

- Druppie does not run agents itself in-process for long-running tasks — heavy coding is delegated to the sandbox (`execute_coding_task` builtin tool → control plane → Modal/Docker sandbox).
- Druppie does not host user apps long-term — the `docker` MCP deploys preview/production containers on the same Docker daemon, but there is no autoscaling, load balancing, or managed runtime layer.
- Druppie does not maintain backward compatibility for in-dev APIs. The CLAUDE.md rule "no legacy/fallback code" is enforced: removed features are deleted, not deprecated.
