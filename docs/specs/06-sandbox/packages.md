# Packages

`background-agents/packages/` — 9 packages, TypeScript and Python mixed.

| Package | Language | Role |
|---------|----------|------|
| `shared` | TypeScript | Shared types, auth helpers, git utilities |
| `local-control-plane` | TypeScript | Local HTTP control plane (Express, SQLite) |
| `local-sandbox-manager` | Python | Local sandbox lifecycle (Docker or Kata) |
| `control-plane` | TypeScript (CF Workers) | Production control plane (D1 + Durable Objects) |
| `modal-infra` | Python | Modal Labs sandbox functions |
| `web` | TypeScript (Next.js) | Background-agents dashboard UI (not Druppie's UI) |
| `github-bot` | TypeScript (CF Workers) | GitHub App webhook handler |
| `slack-bot` | TypeScript (CF Workers) | Slack app handler |
| `linear-bot` | TypeScript | Linear issue tracker integration |

## Workspace layout

```
background-agents/
├── package.json             npm workspaces config
├── packages/
│   ├── shared/
│   ├── local-control-plane/
│   ├── local-sandbox-manager/
│   ├── control-plane/
│   ├── modal-infra/
│   ├── web/
│   ├── github-bot/
│   ├── slack-bot/
│   └── linear-bot/
├── terraform/              Infra-as-code for production
├── scripts/                Deployment helpers
└── docs/
    └── adr/                Architecture decisions
```

## Shared types (`packages/shared`)

Enums used across every package:

```ts
export type SessionStatus = "created" | "active" | "completed" | "archived";
export type SandboxStatus = "pending" | "warming" | "syncing" | "ready" |
                            "running" | "stopped" | "failed";
export type GitSyncStatus = "pending" | "in_progress" | "completed" | "failed";
export type MessageStatus = "pending" | "processing" | "completed" | "failed";
export type EventType = "tool_call" | "tool_result" | "token" | "error" |
                        "git_sync" | "cache_summary";
export type ArtifactType = "pr" | "screenshot" | "preview" | "branch";
```

Utilities:
- `generateInternalToken(secret, body)` — HMAC helper used by both control planes.
- Git parsing (commit SHA, branch name validation).

## Why separate packages

- Bots (slack/github/linear) run as CF Workers for 0-op ops scaling.
- Control plane is stateful + WebSocket-heavy — fits CF Durable Objects in production.
- Sandbox manager is host-local (needs Docker socket) — Python was simplest.
- Modal-infra is Python because Modal's SDK is Python-first.
- Web is Next.js — standard SPA stack for the dashboard.
