# Druppie Specifications

This folder contains the comprehensive current-state specification of the Druppie platform. It is organised hierarchically: each numbered folder is a topic; files inside drill down into increasing detail.

All content reflects the `colab-dev` branch as of 2026-04-20.

## Navigation

| # | Folder | Scope |
|---|--------|-------|
| 00 | [overview.md](00-overview.md) | One-page system overview, value proposition, top-level components |
| 01 | [architecture/](01-architecture/README.md) | Layered architecture, data flow, deployment topology |
| 02 | [backend/](02-backend/README.md) | FastAPI app: routes, services, repositories, domain, DB models, auth |
| 03 | [frontend/](03-frontend/README.md) | React/Vite SPA: pages, components, services, routing, testing |
| 04 | [mcp-servers/](04-mcp-servers/README.md) | Every MCP module, conventions, config, approval model |
| 05 | [agents/](05-agents/README.md) | Every agent definition, orchestrator, tool executor, skills, templates |
| 06 | [sandbox/](06-sandbox/README.md) | `background-agents/` packages: control plane, sandbox manager, LLM proxy |
| 07 | [testing/](07-testing/README.md) | Evaluation framework, tool/agent tests, judge, HITL simulator, e2e |
| 08 | [infrastructure/](08-infrastructure/README.md) | docker-compose, Dockerfiles, Keycloak, Gitea, scripts, Terraform |
| 09 | [data-model/](09-data-model/README.md) | Every entity, lifecycle state machines, relationships |
| 10 | [operations/](10-operations/README.md) | Dev workflow, reset procedures, deployment, troubleshooting |

## How the layers relate

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│                  src/pages, src/components                   │
└───────────────────────┬─────────────────────────────────────┘
                        │ REST + WebSocket (polling)
┌───────────────────────▼─────────────────────────────────────┐
│              Backend API (FastAPI) — port 8100               │
│      api/routes → services → repositories → db/models        │
└───────────────────────┬─────────────────────────────────────┘
                        │
    ┌───────────────────┼─────────────────────┐
    │                   │                     │
┌───▼──────────┐ ┌──────▼────────┐ ┌─────────▼──────────┐
│  Orchestrator│ │  Tool Registry│ │  Auth (Keycloak)   │
│  (custom     │ │  + MCP Config │ │  Gitea integration │
│   tool-call  │ │               │ │                    │
│   loop)      │ │               │ │                    │
└───┬──────────┘ └──────┬────────┘ └────────────────────┘
    │                   │
    │         ┌─────────┼─────────┬─────────┬──────────┐
    │         │         │         │         │          │
┌───▼───┐ ┌──▼───┐ ┌───▼───┐ ┌──▼────┐ ┌──▼────┐ ┌───▼──────┐
│coding │ │docker│ │  web  │ │search │ │archi- │ │ registry │
│ 9001  │ │ 9002 │ │ 9005  │ │ 9004  │ │mate   │ │   9007   │
│       │ │      │ │       │ │       │ │ 9006  │ │          │
└───────┘ └──┬───┘ └───────┘ └───────┘ └───────┘ └──────────┘
             │
   ┌─────────▼─────────────┐        ┌───────────────────────┐
   │ Sandbox Control Plane │◄───────┤ Sandbox Manager       │
   │ (TS/Express, 8787)    │        │ (Python/FastAPI,8000) │
   │ LLM proxy + sessions  │        │ Docker/Kata lifecycle │
   └───────────────────────┘        └───────┬───────────────┘
                                            │
                                      ┌─────▼──────┐
                                      │  Sandbox   │
                                      │ containers │
                                      │(open-insp) │
                                      └────────────┘
```

## Conventions used in these specs

- **File:line citations** are given where they aid navigation — e.g. `druppie/api/main.py:88` points to the lifespan handler.
- **Code identifiers** (class names, functions, env vars) are in `backticks`.
- **Mermaid diagrams** in `.md` files render natively on GitHub/Gitea and in the in-app Mermaid renderer.
- **Authoritative source**: the code wins. If a spec and the code disagree, fix whichever is wrong in the next PR.
