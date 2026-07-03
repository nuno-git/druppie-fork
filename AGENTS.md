# CLAUDE.md

Guidance for AI coding assistants working in this repository.

## Repos & Responsibilities

| Repo | Gitea URL | Purpose |
|------|----------|---------|
| `ai/druppie` | `aigit.waterschap.org/ai/druppie` | Application code + Helm chart (`helm/druppie/`) + CI workflow (`.gitea/workflows/build.yaml`) |
| `ai/k8s` | `aigit.waterschap.org/ai/k8s` | GitOps: HelmReleases, infra (Harbor, Gitea Runner, GPU), ExternalSecrets, FluxCD kustomizations |
| `systeembeheer/rancher-gitops` | `aigit.waterschap.org/systeembeheer/rancher-gitops` | Base infra: RKE2, Cilium, Traefik, cert-manager, Longhorn, FluxCD itself. Read-only context (can view online); **never change** — Infra team owns this. If changes are needed, tell me. |

### How they connect

```
ai/druppie push → Gitea Actions CI → builds images → pushes to Harbor
                                     → updates imageTag in ai/k8s HelmRelease
ai/k8s push     → FluxCD detects change → Helm upgrade → pods restart
```

FluxCD watches `ai/k8s` main branch every 5 min, applies everything under `clusters/ka-k8s-ai/`, and prunes removed objects. The chart source for HelmReleases comes from `ai/druppie` (FluxCD GitRepository `ai-druppie`).

## Infrastructure as Code (IaC)

**Everything must be defined in git.** Both `ai/k8s` and `ai/druppie` are the source of truth. FluxCD will revert manual `kubectl apply` changes on the next reconciliation cycle (5 min).

### To make permanent changes:
1. Edit YAML in `ai/k8s` (infra) or `ai/druppie` (app/chart)
2. Commit and push to `main` (ai/k8s) or `colab-dev`/`main` (ai/druppie)
3. Wait for FluxCD to sync (or force: `kubectl annotate kustomization/ai-k8s -n flux-system fluxcd.io/request reconcile="$(date +%s)" --overwrite`)

### Temporary changes for testing (will be reverted by FluxCD):
```bash
# OK for quick testing — FluxCD will undo these within 5 min
kubectl -n druppie scale deployment druppie-backend --replicas=0
kubectl -n druppie edit configmap ...
kubectl -n druppie apply -f /tmp/test-pod.yaml
```

### NEVER do without committing to git:
- Change HelmRelease values (FluxCD will revert and cause rollbacks)
- Add/update volumes, mounts, env vars in deployments
- Create PVCs, secrets, or configmaps

## CI/CD Pipeline

### How it works
1. Push to `main` or `colab-dev` on `ai/druppie`
2. Gitea Actions runner (DinD pod in `gitea-runner` namespace) builds all Docker images
3. Images tagged `{branch}-{timestamp}-{sha}` and pushed to Harbor (`harbor.rijnland.dev/druppie/`)
4. CI clones `ai/k8s`, updates `imageTag` in the appropriate HelmRelease, pushes
5. FluxCD detects the tag change → Helm upgrade → pods restart

### Layer caching
Docker layer cache persists on a 50Gi Longhorn PVC (`dind-storage`) in the DinD sidecar. Cold build ~23 min, cached build ~30 sec. The `CACHEBUST` ARG in Dockerfiles ensures code layers are rebuilt on new commits (dependencies stay cached).

### Branch → Namespace mapping
| Branch | HelmRelease | Namespace | Domain |
|--------|-------------|-----------|--------|
| `main` | `druppie/helmrelease.yaml` | `druppie` | `druppie.rijnland.dev` |
| `colab-dev` | `druppie-colab-dev/helmrelease.yaml` | `druppie-colab-dev` | `colab-dev-druppie.rijnland.dev` |

### Triggering a build manually
```bash
curl -sk -X POST -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ref":"main"}' \
  "https://aigit.waterschap.org/api/v1/repos/ai/druppie/actions/workflows/build.yaml/dispatches"
```

## Database Migrations (IMPORTANT)

**There is no automatic migration system yet.** The CI/CD pipeline deploys new code with schema changes, but the PostgreSQL database persists across deployments. When SQLAlchemy models add columns, you must manually apply the schema change to both databases:

```bash
# Prod
kubectl exec -n druppie pod/druppie-druppie-db-0 -- psql -U druppie -d druppie \
  -c "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN DEFAULT FALSE;"

# Dev
kubectl exec -n druppie-colab-dev pod/druppie-colab-dev-druppie-db-0 -- psql -U druppie -d druppie \
  -c "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN DEFAULT FALSE;"
```

After applying schema changes, restart the backend:
```bash
kubectl rollout restart -n druppie deploy/druppie-backend
kubectl rollout restart -n druppie-colab-dev deploy/druppie-colab-dev-backend
```

**TODO:** Migration files (Alembic) will be added later to automate this.

## Branch Policy

- **Default branch**: `colab-dev`
- **Always branch from**: `colab-dev`
- **PRs target**: `colab-dev`
- `main` tracks production deployments — only merge via PR when ready to deploy

## Local Development

### Docker Compose (primary local workflow)
```bash
docker compose --profile dev --profile init up -d      # Start full dev environment
docker compose --profile dev down                       # Stop everything
docker compose logs -f druppie-backend-dev              # View logs
docker compose --profile reset-db run --rm reset-db     # Reset DB
docker compose --profile dev up -d --build              # Rebuild after code changes
```

### Backend (Python/FastAPI)
```bash
cd druppie && pytest        # Tests
cd druppie && ruff check .  # Lint
cd druppie && black .       # Format
```

### Frontend (React/Vite)
```bash
cd frontend
npm install
npm run dev      # Dev server (port 5273)
npm run lint
npm test
```

## Project Architecture

```
druppie/
├── api/           # FastAPI routes — thin layer, delegates to services
├── services/      # Business logic, orchestrates repositories
├── repositories/  # Data access, returns domain models
├── domain/        # Pydantic models (Summary/Detail pattern)
├── db/models/     # SQLAlchemy ORM models
├── execution/     # Agent orchestrator, LangGraph loop
├── agents/        # YAML agent definitions
├── core/          # MCP client, config loading
└── mcp-servers/   # MCP tool servers (coding, docker, web, etc.)

helm/druppie/      # THE Helm chart — single source of truth for K8s deployment
frontend/           # React/Vite frontend
```

### Data Flow
Repository → Domain Model → Service → API Route

## Cluster Access

```bash
export KUBECONFIG=~/.kube/config  # RKE2 cluster ka-k8s-ai
kubectl get pods -n druppie           # Prod
kubectl get pods -n druppie-colab-dev # Dev
kubectl get pods -n gitea-runner      # CI runner
kubectl get hr -A                     # All HelmReleases
kubectl get kustomization -n flux-system  # FluxCD sync status
```

### Useful endpoints
| URL | Service |
|-----|---------|
| `druppie.rijnland.dev` | Druppie prod |
| `colab-dev-druppie.rijnland.dev` | Druppie dev |
| `harbor.rijnland.dev` | Harbor registry |
| `aigit.waterschap.org` | Gitea (shared, external) |

## Test Users (Keycloak)

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

## Critical Rules

1. **IaC only** — All permanent changes must be in git. `kubectl` is for testing only.
2. **NO automatic DB migrations** — Apply schema changes manually to both prod and dev databases.
3. **NO JSON/JSONB columns** — Normalize into proper relational tables.
4. **NO legacy/fallback code** — Clean architecture only.
5. **Config in YAML** — Agent definitions in `agents/definitions/*.yaml`.
6. **Always commit and push** — Uncommitted changes don't exist in GitOps.
