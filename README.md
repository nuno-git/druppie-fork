# Druppie Governance Platform

AI agent governance platform with MCP tool permissions and approval workflows.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Docker Compose v2)
- An LLM API key (Z.AI, DeepInfra, or local Ollama)

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env and set your LLM_PROVIDER and API key

# 2. Start everything (development mode with hot reload)
docker compose --profile dev --profile init up -d

# 3. Open the application
# Frontend:  http://localhost:5273
# Backend:   http://localhost:8100
# API Docs:  http://localhost:8100/docs
# Keycloak:  http://localhost:8180
# Gitea:     http://localhost:3100
# Adminer:   http://localhost:8081
```

## Docker Compose Profiles

| Profile | What it starts |
|---------|---------------|
| `infra` | Databases, Keycloak, Gitea, MCP servers, Adminer |
| `dev` | Everything in `infra` + backend (hot reload) + frontend (Vite HMR) |
| `prod` | Everything in `infra` + backend + frontend (production builds) |
| `init` | Initialization container (Keycloak & Gitea first-time setup) |
| `reset-db` | Database reset service |
| `reset-hard` | Full reset service |

## Common Commands

### Start Services

```bash
# Development mode (hot reload on backend + frontend)
docker compose --profile dev --profile init up -d

# Infrastructure only (databases, Keycloak, Gitea, MCP servers)
docker compose --profile infra --profile init up -d

# Production mode
docker compose --profile prod --profile init up -d
```

> **Note:** Include `--profile init` on first run to configure Keycloak and Gitea.
> On subsequent runs you can omit it - the init container checks a marker volume
> and skips if already initialized.

### Stop Services

```bash
# Stop all running services
docker compose --profile dev down

# Stop and remove volumes (destroys all data)
docker compose --profile dev down -v
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f druppie-backend-dev
docker compose logs -f druppie-frontend-dev
docker compose logs -f keycloak
docker compose logs -f gitea
```

### Restart Services

```bash
# Restart everything
docker compose --profile dev restart

# Restart specific service
docker compose restart druppie-backend-dev
```

### Check Status

```bash
docker compose --profile dev ps
```

## Reset Operations

### Reset Application Database Only

Clears the Druppie application database while preserving Keycloak users, Gitea repos, and all other data.

```bash
docker compose --profile reset-db run --rm reset-db
```

### Hard Reset (Full Wipe + Re-Initialize)

Destroys ALL data (databases, Keycloak config, Gitea repos, workspace) and re-initializes from scratch. Keycloak and Gitea will be reconfigured automatically.

```bash
# Stop application services first
docker compose --profile dev down

# Run hard reset
docker compose --profile infra --profile reset-hard run --rm reset-hard
```

After hard reset, start the application again:
```bash
docker compose --profile dev up -d
```

### Re-Run Initialization Only

If you need to re-run the Keycloak/Gitea setup scripts without losing data:

```bash
# Remove the init marker
docker volume rm druppie_init_marker

# Run init again
docker compose --profile infra --profile init up -d
```

## Development

### Hot Reload

In `dev` profile:
- **Backend**: Source code is mounted from `./druppie/`. Changes to Python files trigger automatic reload via uvicorn `--reload`.
- **Frontend**: Source code is mounted from `./frontend/`. Vite HMR provides instant updates in the browser.

### Building Images

```bash
# Rebuild all images
docker compose --profile dev build

# Rebuild specific service
docker compose build druppie-backend-dev
```

### Changing Environment Variables

Docker Compose reads `.env` only at startup. If you edit `.env` while containers are running (e.g. changing `LLM_PROVIDER` or API keys), re-run:

```bash
docker compose --profile dev up -d
```

Compose will detect the config change and recreate only the affected containers. Source code changes are picked up automatically via hot reload, but environment variable changes always require this step.

## Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:5273 | Keycloak login |
| Backend API | http://localhost:8100 | - |
| API Docs | http://localhost:8100/docs | - |
| Keycloak Admin | http://localhost:8180 | admin / admin |
| Gitea | http://localhost:3100 | gitea_admin / GiteaAdmin123 |
| Adminer | http://localhost:8081 | druppie / druppie_secret |
| MCP Coding | http://localhost:9001 | - |
| MCP Docker | http://localhost:9002 | - |
| MCP File Search | http://localhost:9004 | - |
| MCP Web | http://localhost:9005 | - |

## Test Users (Keycloak)

| User | Password | Role |
|------|----------|------|
| admin | Admin123! | admin |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

## Project Structure

```
.
├── docker-compose.yml     # Main compose file with all profiles
├── Dockerfile             # Backend container image
├── Dockerfile.init        # Init container (Keycloak + Gitea setup)
├── Dockerfile.reset       # Reset container (hard reset operations)
├── .env                   # Environment variables (create from .env.example)
├── .env.example           # Environment template with documentation
├── druppie/               # Backend source code (FastAPI)
│   ├── api/               # API routes
│   ├── services/          # Business logic
│   ├── repositories/      # Data access
│   ├── domain/            # Domain models
│   ├── db/                # SQLAlchemy models
│   ├── execution/         # Agent orchestrator
│   ├── agents/            # YAML agent definitions
│   ├── core/              # MCP client, config
│   ├── mcp-servers/       # MCP microservices
│   └── requirements.txt
├── frontend/              # Frontend source code (React/Vite)
│   ├── src/
│   ├── Dockerfile         # Production frontend image
│   └── Dockerfile.dev     # Development frontend image
├── scripts/               # Setup & utility scripts
│   ├── setup_keycloak.py  # Keycloak configuration
│   ├── setup_gitea.py     # Gitea configuration
│   ├── init-entrypoint.sh # Init container entrypoint
│   └── reset-hard.sh      # Hard reset script
└── iac/                   # Infrastructure as Code
    ├── realm.yaml         # Keycloak realm config
    └── users.yaml         # Users & roles config
```

## Migration from setup_dev.sh

| Old command | New command |
|-------------|-------------|
| `./setup_dev.sh` | `docker compose --profile dev --profile init up -d` |
| `./setup_dev.sh start` | `docker compose --profile dev --profile init up -d` |
| `./setup_dev.sh infra` | `docker compose --profile infra --profile init up -d` |
| `./setup_dev.sh stop` | `docker compose --profile dev down` |
| `./setup_dev.sh restart` | `docker compose --profile dev restart` |
| `./setup_dev.sh status` | `docker compose --profile dev ps` |
| `./setup_dev.sh logs` | `docker compose logs -f` |
| `./setup_dev.sh logs backend` | `docker compose logs -f druppie-backend-dev` |
| `./setup_dev.sh logs frontend` | `docker compose logs -f druppie-frontend-dev` |
| `./setup_dev.sh reset` | `docker compose --profile reset-db run --rm reset-db` |
| `./setup.sh clean && ./setup.sh all` | `docker compose --profile reset-hard run --rm reset-hard` |

## Troubleshooting

### First run: GITEA_TOKEN not set

On the very first run, the init container generates a Gitea access token and writes it to `.env`. However, services that were already started may not have picked it up. Fix:

```bash
docker compose --profile dev restart mcp-coding
```

### Keycloak not ready

Keycloak can take 30-60 seconds to start. If you see connection errors, wait and retry. The init container has built-in retry logic.

### Port conflicts

If ports are already in use, configure alternative ports in `.env`:

```env
BACKEND_PORT=8200
FRONTEND_PORT=5274
KEYCLOAK_PORT=8181
```

### Rebuild after code changes to Dockerfiles

```bash
docker compose --profile dev up -d --build
```
