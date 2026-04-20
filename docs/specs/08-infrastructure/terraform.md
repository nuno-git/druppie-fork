# Terraform

Production infrastructure for the sandbox system. Path: `background-agents/terraform/`.

Scope: deploys the production-grade `control-plane` (Cloudflare Workers), `web` (Vercel), `modal-infra` (Modal Labs), and the three bot workers (GitHub, Slack, Linear). Druppie itself doesn't have production Terraform — that's on the roadmap.

## Structure

```
terraform/
├── d1/migrations/                D1 SQL migration files
├── modules/
│   ├── cloudflare-kv/            KV namespace provisioning
│   ├── cloudflare-worker/        Worker + routes + bindings
│   ├── vercel-project/           Vercel project + env vars
│   └── modal-app/                Modal deploy via null_resource + local-exec
├── environments/
│   └── production/
│       ├── main.tf               resource instantiation
│       ├── variables.tf          inputs
│       ├── outputs.tf            URLs, IDs
│       ├── backend.tf            R2 state backend
│       ├── versions.tf           provider versions
│       └── terraform.tfvars.example
├── scripts/
│   ├── d1-migrate.sh             applies migrations to D1
│   ├── create-secrets.sh         Modal secret creation
│   └── deploy.sh                 Modal deployment wrapper
└── README.md                     setup guide (~421 lines)
```

## Providers

- **Cloudflare** — Workers, D1, KV, Durable Objects.
- **Vercel** — Next.js web app (the dashboard in `packages/web`).
- **Modal** — wrapped via `null_resource + local-exec` (no native Terraform provider today).

## What gets provisioned

### Cloudflare
- **D1 database**: `open-inspect-${deployment_name}`, `read_replication=disabled`. Schema from `d1/migrations/*.sql`.
- **KV namespaces**: `session_index_kv`, `slack_kv`, optional `linear_kv`.
- **Workers**:
  - `control-plane-worker` — Durable Objects for sessions, WebSocket support. Built from `packages/control-plane` (deterministic bundle output).
  - `slack-bot-worker` — from `packages/slack-bot`.
  - `linear-bot-worker` — optional (`var.enable_linear_bot`).
  - `github-bot-worker` — from `packages/github-bot`.

### Vercel
- `open-inspect-${deployment_name}` project. Built from `packages/web`. Env vars populated from Terraform outputs.

### Modal
- `null_resource.modal_secrets` — creates secrets via Modal CLI.
- `null_resource.modal_volume` — optional persistent volume.
- `null_resource.modal_deploy` — runs `modal deploy` with triggers on source hash.

## Required GitHub secrets (CI)

```
CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
VERCEL_API_TOKEN, VERCEL_TEAM_ID
MODAL_TOKEN_ID, MODAL_TOKEN_SECRET
GH_OAUTH_CLIENT_ID, GH_OAUTH_CLIENT_SECRET
GH_APP_ID, GH_APP_PRIVATE_KEY, GH_APP_INSTALLATION_ID
SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
ANTHROPIC_API_KEY
TOKEN_ENCRYPTION_KEY, REPO_SECRETS_ENCRYPTION_KEY
INTERNAL_CALLBACK_SECRET, NEXTAUTH_SECRET
```

State backend: **Cloudflare R2** (S3-compatible) with lockfile support.

## `cloudflare-worker` module

Three-step pattern per Cloudflare's 2024 API:
1. `cloudflare_worker` — script resource.
2. `cloudflare_worker_version` — version tracking.
3. `cloudflare_workers_deployment` — routes + bindings.

Handles D1 binding, KV binding, Durable Object binding, secret binding declaratively.

## `modal-app` module

Modal doesn't have a native Terraform provider. The module uses `null_resource + local-exec`:

```hcl
resource "null_resource" "modal_deploy" {
  triggers = {
    source_hash     = filesha256("${var.deploy_path}/${var.deploy_module}")
    app_name        = var.app_name
    secrets_created = null_resource.modal_secrets.id
    volume_created  = null_resource.modal_volume.id
  }
  provisioner "local-exec" {
    command = "${path.module}/../../scripts/deploy.sh ${var.app_name} ${var.deploy_path} ${var.deploy_module}"
  }
}
```

On source change, triggers change, provisioner re-runs, `modal deploy` executes.

## Output URLs

After apply:
```
control_plane_url = "https://open-inspect-control-plane-${deployment_name}.<subdomain>.workers.dev"
web_app_url      = "https://open-inspect-${deployment_name}.vercel.app"
ws_url           = "wss://<control_plane_host>"
```

These become env vars for the bot workers and the sandboxes spawned via Modal.

## D1 migrations

Migrations in `terraform/d1/migrations/*.sql` follow a simple numeric prefix convention (`0001_initial.sql`, `0002_add_secrets.sql`, …).

Applied via `scripts/d1-migrate.sh`:
- Enumerates SQL files in order.
- For each, runs `wrangler d1 execute --file=<sql>`.
- Skip if already applied (tracked via a migration metadata table).

## Druppie's relationship

Today Druppie runs only the local sandbox path via `docker compose`. To switch to the production path:
1. Apply this Terraform stack.
2. Route Druppie's `SANDBOX_CONTROL_PLANE_URL` to the CF Workers URL.
3. Switch LLM proxying to the CF version (similar API surface).
4. Ensure GitHub App installation is configured for Druppie's fork.

Nothing in Druppie code prevents this — the endpoint shapes were designed to match. But the transition hasn't been exercised end-to-end yet.

## Limitations

- Cloudflare limits: Workers max 30s CPU, D1 size caps. For very high sandbox throughput, would need to shard.
- Modal costs scale with usage — long-running sandboxes are more expensive than Docker-on-VM for steady workloads.
- Durable Objects have region affinity — users in distant regions see higher WS latency.

For most teams, the local `docker compose` path is sufficient; Terraform is the answer when sandbox usage outgrows a single host.
