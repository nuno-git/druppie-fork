# Druppie Governance Platform

AI agent governance platform with MCP tool permissions and approval workflows.

## Quick Start

### Prerequisites (k3s)
k3s + Docker + Helm required.

### Quick Start
```bash
# 1. Clone
git clone --recursive <repo-url> && cd druppie-fork

# 2. Configure
cp .env.example .env

# 3. Deploy on k3s (see docs/K3S-DEV-SETUP.md for full guide)
sudo ./scripts/setup-harbor-k8s.sh
helm upgrade --install druppie ./helm/druppie -n druppie --create-namespace
kubectl apply -f k8s/guacamole.yaml

# 4. Open the app
open http://localhost:30001
```

> **Already cloned without `--recursive`?** Run: `git submodule update --init`

> Docker-compose has been **removed**. All development runs in Kubernetes dev
> workspaces (a branch namespace that *is* the hot-reloading environment). See
> `dev-workspace-hotreload-plan.md`.

## Commands

### Development — Kubernetes dev workspace (hot reload)

A dev workspace is a branch namespace whose backend (`uvicorn --reload`) and
frontend (Vite HMR) **are** the running app — edits in code-server reload it
live. Bring one up for a branch:

```bash
# Deploy an isolated branch env (full stack + hot-reload workspace)
./scripts/deploy-branch-env.sh feature/my-thing

# App:   https://druppie-feature-my-thing.rijnland.dev
# IDE:   https://druppie-feature-my-thing-dev.rijnland.dev   (code-server, oauth2-proxy)
```

The workspace pod consumes the namespace's real Postgres/Keycloak/MCP
(`devWorkspace.stackMode=real`). For an isolated SQLite/mock workspace, set
`devWorkspace.stackMode=degraded`.

### Logs / status

```bash
kubectl -n druppie-feature-my-thing get pods
kubectl -n druppie-feature-my-thing logs -f deploy/druppie-feature-my-thing-workspace -c workspace
# Backend/frontend/code-server logs also live on the PVC at /workspace/.logs/
```

### Reset

```bash
# Tear down the whole branch env (Flux prunes when the manifest dir is removed)
kubectl -n druppie-feature-my-thing delete deploy/druppie-feature-my-thing-workspace
# Wipe the workspace source PVC to force a fresh seed on next start
kubectl -n druppie-feature-my-thing delete pvc/druppie-feature-my-thing-workspace-dev
```

DB schema changes are applied manually (no migrations yet):
```bash
kubectl -n druppie-feature-my-thing exec pod/druppie-feature-my-thing-druppie-db-0 -- \
  psql -U druppie -d druppie -c "ALTER TABLE ... ;"
```

## What is the init job?

The init container configures Keycloak and Gitea on first run:
- Creates the `druppie` realm in Keycloak
- Creates test users (admin, architect, developer, etc.)
- Sets up Gitea admin account and OAuth integration
- Creates the sample repository

**It only runs once** (tracked by a marker). Re-run by deleting the init job /
marker after changing `iac/users.yaml` or `iac/realm.yaml`.

## URLs

| Service | URL | Login |
|---------|-----|-------|
| Frontend | http://localhost:30001 | Test users below |
| API Docs | http://localhost:30000/docs | - |
| Keycloak Admin | http://localhost:30002 | admin / admin |
| Gitea | http://localhost:30003 | gitea_admin / GiteaAdmin123 |

## Test Users

| User | Password | Role |
|------|----------|------|
| admin | Admin123! | admin (full access) |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

## Environment Variables

Copy `.env.example` to `.env`. Required: an LLM API key.

```bash
# Option 1: Z.AI (default)
LLM_PROVIDER=zai
ZAI_API_KEY=your_key_here

# Option 2: DeepInfra
LLM_PROVIDER=deepinfra
DEEPINFRA_API_KEY=your_key_here
```

Both providers use LiteLLM internally for standardized tool calling.

After editing `.env` (or a Vault/ExternalSecret), apply changes by restarting the
workspace pod so it picks up the new env:
```bash
kubectl -n druppie-feature-my-thing rollout restart deploy/druppie-feature-my-thing-workspace
```

## GitHub App Setup (for `update_core`)

The `update_core` flow lets Druppie modify its own codebase via PRs on GitHub. It requires a GitHub App for authentication. **This is optional** — all other flows work without it.

### Steps

1. **Create a GitHub App** at [github.com/settings/apps/new](https://github.com/settings/apps/new):
   - Permissions: **Contents** (R/W), **Pull requests** (R/W), **Metadata** (Read)
   - Webhook: disabled

2. **Generate a private key** on the App settings page → save as `secrets/github-app-private-key.pem`

3. **Install the App** on the target repository (e.g., your Druppie fork)

4. **Add to `.env`:**
   ```bash
   GITHUB_APP_ID=<from app settings page>
   GITHUB_APP_PRIVATE_KEY_PATH=/app/secrets/github-app-private-key.pem
   GITHUB_APP_INSTALLATION_ID=<from install URL>
   ```

5. **Restart the workspace:** `kubectl -n druppie-feature-my-thing rollout restart deploy/druppie-feature-my-thing-workspace`

> See [docs/SANDBOX.md](docs/SANDBOX.md#github-app-setup) for detailed setup instructions.

## Custom Ports

Edit `.env` if default NodePorts conflict:

```bash
BACKEND_PORT=30000
FRONTEND_PORT=30001
KEYCLOAK_PORT=30002
GITEA_PORT=30003
```

## Documentation

| Document | Description |
|----------|-------------|
| [docs/FEATURES.md](docs/FEATURES.md) | Functional features: agents, workflows, approvals, HITL, sandbox coding |
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Technical architecture: backend, database, agent runtime, security |
| [docs/SANDBOX.md](docs/SANDBOX.md) | Sandbox infrastructure: OpenCode integration, provider resilience, Kata Containers |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Bugs, technical debt, and improvement ideas |

## Troubleshooting

**Check logs:**
```bash
kubectl -n druppie-feature-my-thing logs -f deploy/druppie-feature-my-thing-workspace -c workspace
```

**Fresh workspace (re-seed source PVC):**
```bash
kubectl -n druppie-feature-my-thing delete pvc/druppie-feature-my-thing-workspace-dev
kubectl -n druppie-feature-my-thing rollout restart deploy/druppie-feature-my-thing-workspace
```

**Workspace pod won't start:**
```bash
kubectl -n druppie-feature-my-thing describe pod -l app.kubernetes.io/component=dev-workspace
# Rebuild the dev-workspace image (CI builds it on colab-dev/main pushes):
#   .gitea/workflows/build.yaml → "Build and push dev-workspace image"
```
