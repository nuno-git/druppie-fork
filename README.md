# Druppie Governance Platform

AI agent governance platform with MCP tool permissions and approval workflows.

## Quick Start

```bash
# 1. Clone (--recursive pulls in the sandbox submodule)
git clone --recursive <repo-url>
cd cleaner-druppie

# 2. Configure environment
cp .env.example .env
# Edit .env and add your LLM API key (ZAI_API_KEY or DEEPINFRA_API_KEY)

# 3. Start (first time includes --profile init)
docker compose --profile dev --profile init up -d --build

# 4. Open the app
open http://localhost:5273
```

First startup takes a few minutes to build images and initialize services.

> **Already cloned without `--recursive`?** Run: `git submodule update --init`

## Daily Usage

```bash
docker compose --profile dev up -d    # Start
docker compose --profile dev down     # Stop
```

## Commands

### Development Mode (hot reload)

```bash
# First time (or after reset)
docker compose --profile dev --profile init up -d

# Daily usage
docker compose --profile dev up -d
docker compose --profile dev down
docker compose --profile dev restart
docker compose --profile dev up -d --build   # Rebuild after Dockerfile changes
```

### Production Mode

```bash
# First time (or after reset)
docker compose --profile prod --profile init up -d

# Daily usage
docker compose --profile prod up -d
docker compose --profile prod down
```

### Switching Between Dev and Prod

Dev and prod use the same ports and container names, so stop one before starting the other:

```bash
# Switch from dev to prod
docker compose --profile dev down
docker compose --profile prod up -d --build

# Switch from prod to dev
docker compose --profile prod down
docker compose --profile dev up -d
```

### Infrastructure Only

Start only databases, Keycloak, Gitea, and MCP servers (no backend/frontend):

```bash
# First time (or after reset)
docker compose --profile infra --profile init up -d

# Daily usage
docker compose --profile infra up -d
docker compose --profile infra down
```

### Logs

```bash
docker compose logs -f                       # All services
docker compose logs -f druppie-backend-dev   # Backend only
docker compose logs -f druppie-frontend-dev  # Frontend only
docker compose logs -f keycloak              # Keycloak only
docker compose logs -f sandbox-control-plane # Sandbox control plane
docker compose logs -f sandbox-manager       # Sandbox manager
```

### Reset

```bash
# Soft reset - clears projects, sessions, chats (keeps user accounts, make sure to logout in the browser because tokens are kept there in cache.)
docker compose --profile reset-db run --rm reset-db

# Hard reset - wipes all data volumes and re-initializes Keycloak & Gitea
docker compose --profile reset-hard run --rm reset-hard
docker compose --profile dev up -d --build   # Rebuild + start (MCP servers need --build)

# Full nuke - destroys EVERYTHING (containers, volumes, images) and rebuilds from scratch
docker compose --profile nuke run --rm nuke

# Nuke without restarting (tear down only)
START_AFTER=false docker compose --profile nuke run --rm nuke

# Or run directly on the host (Linux/Mac/WSL)
./scripts/nuke.sh
```

**Soft reset keeps:** User accounts, Keycloak config, Gitea repos
**Soft reset clears:** Projects, sessions, agent runs, messages, approvals, questions

**Hard reset clears:** All data (databases, Keycloak, Gitea, workspace files). Keeps Docker images.

**Nuke clears:** Everything including Docker images. Rebuilds all images and starts fresh.

## What is `--profile init`?

The init container configures Keycloak and Gitea on first run:
- Creates the `druppie` realm in Keycloak
- Creates test users (admin, architect, developer, etc.)
- Sets up Gitea admin account and OAuth integration
- Creates the sample repository

**It only runs once.** A marker volume tracks completion. On subsequent runs, it exits immediately doing nothing.

**When to include `--profile init`:**
- First-time setup
- After changing `iac/users.yaml` or `iac/realm.yaml`
- After running `reset-hard`

**To force re-initialization:**
```bash
docker volume rm druppie_init_marker
docker compose --profile dev --profile init up -d
```

## URLs

| Service | URL | Login |
|---------|-----|-------|
| Frontend | http://localhost:5273 | Test users below |
| API Docs | http://localhost:8100/docs | - |
| Keycloak Admin | http://localhost:8180 | admin / admin |
| Gitea | http://localhost:3100 | gitea_admin / GiteaAdmin123 |
| Adminer (DB) | http://localhost:8081 | druppie / druppie_secret |

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

After editing `.env`, apply changes:
```bash
docker compose --profile dev up -d
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

5. **Restart:** `docker compose --profile dev up -d`

> See [docs/SANDBOX.md](docs/SANDBOX.md#github-app-setup) for detailed setup instructions.

## Custom Ports

Edit `.env` if default ports conflict:

```bash
BACKEND_PORT=8200
FRONTEND_PORT=5274
KEYCLOAK_PORT=8181
GITEA_PORT=3101
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
docker compose logs -f
```

**Fresh start (nuclear option):**
```bash
docker compose --profile nuke run --rm nuke
```

**Container won't start:**
```bash
docker compose --profile dev up -d --build  # Force rebuild
```
