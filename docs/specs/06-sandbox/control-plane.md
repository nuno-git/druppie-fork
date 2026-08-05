# Production Control Plane

Path: `background-agents/packages/control-plane/`. Stack: TypeScript, Cloudflare Workers, D1 (serverless SQLite), Durable Objects, KV. Not used by Druppie today but scaffolded for future production deployment.

## Differences from local control plane

| Concern | Local (dev) | Production |
|---------|-------------|------------|
| Runtime | Express on Node.js | CF Workers (serverless) |
| Session state | In-memory + SQLite | Durable Objects (hibernating WebSocket) |
| Persistence | SQLite file | D1 (serverless SQLite) |
| Repo cache | In-memory | KV namespace, 5-min TTL |
| Secrets | In-memory only | AES-256-GCM encrypted in D1 |
| Auth | Internal API key | OAuth + GitHub App |
| Provider health | Per-process | Shared via KV |

## Key files

```
src/
├── index.ts                  worker entry (fetch handler)
├── router.ts                 HTTP routing
├── types.ts                  shared TS types
├── logger.ts                 structured logs
├── sandbox/
│   ├── provider.ts           abstract SandboxProvider
│   ├── providers/
│   │   └── modal-provider.ts Wraps modal-infra via HTTP
│   ├── client.ts             modal-infra HTTP client
│   └── lifecycle/
│       ├── manager.ts        state machine
│       └── decisions.ts      when to warm/snapshot/restore
├── realtime/
│   └── index.ts              WS event routing
├── db/
│   ├── session-index.ts      D1 sessions table
│   ├── repo-metadata.ts      D1 repo metadata table
│   └── repo-secrets.ts       encrypted secrets
├── session/                  Durable Object for per-session state
├── source-control/           GitHub provider, PR creation
└── routes/                   API endpoints
```

## D1 schema

Three tables (migrations in `terraform/d1/migrations/*.sql`):

### `sessions`
- `id`, `status`, `repo_owner`, `repo_name`, `user_id`, `started_at`, `completed_at`, `archived_at`
- Indexes: `(user_id, status)`, `(repo_owner, repo_name)`

### `repo_metadata`
- `repo_owner`, `repo_name` (composite PK)
- `description`, `alias`, `channel_id` (slack), `enabled`
- Indexes: `(user_id)`

### `repo_secrets`
- `repo_owner`, `repo_name`, `key` (composite PK)
- `value_encrypted` (AES-256-GCM with `REPO_SECRETS_ENCRYPTION_KEY`)
- `created_at`, `updated_at`

Secrets are decrypted at spawn time and passed to the sandbox via env vars.

## Durable Objects

One DO instance per session. Responsibilities:
- Hold the live WebSocket for event streaming.
- Survive hibernation — on reconnect, `ctx.getWebSockets()` restores the connection list.
- Serialize access to session state (no concurrent writes).

## Circuit breaker

Similar to local control plane's error tracking, but shared across Workers via KV:

```ts
enum ErrorType {
  TRANSIENT,   // don't count toward circuit breaker (network, 502-504)
  PERMANENT,   // count (400, 401, 403, 422, config errors)
}
```

When a provider hits N consecutive permanent errors for a tenant, the provider is "opened" for that tenant — future calls skip straight to fallback.

## Repo listing

`GET /repos` lists GitHub repositories the user has installed the Druppie GitHub App on, enriched with D1 `repo_metadata`. KV caches the GitHub response for 5 min to avoid rate limits.

## OAuth + GitHub App

- **OAuth**: users log in via GitHub OAuth; session cookie identifies them to the control plane.
- **GitHub App**: installation tokens scoped per-repo for git operations (clone, push, PR). Tokens are short-lived (1 hour) and regenerated as needed.

## Status vs Druppie

Druppie currently uses the LOCAL control plane. Migrating to the production version would require:
1. Routing Druppie's sandbox webhook calls to the CF Workers URL.
2. Providing OAuth credentials (or switching to a service-auth model).
3. Encrypted repo secrets for projects that need API keys at sandbox spawn time.

Terraform in `background-agents/terraform/environments/production/` provisions everything. See `08-infrastructure/terraform.md`.
