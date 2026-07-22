# Branch Environment Developer Guide

> Your personal, isolated development environment inside the cluster.
> Create one per feature branch, develop with hot-reload, tear down when done.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [How It Works](#2-how-it-works)
3. [Your URLs](#3-your-urls)
4. [Developing: Hot-Reload (No Push Needed)](#4-developing-hot-reload-no-push-needed)
5. [When to Push (and What Happens)](#5-when-to-push-and-what-happens)
6. [Egress IP (Firewall Rules)](#6-egress-ip-firewall-rules)
7. [Known Limitations](#7-known-limitations)
8. [Troubleshooting](#8-troubleshooting)
9. [FAQ](#9-faq)

---

## 1. Quick Start

### Step 1: Create a feature branch

```bash
# From the colab-dev branch
git checkout colab-dev
git pull origin colab-dev
git checkout -b feature/my-awesome-feature
```

### Step 2: Deploy a branch environment

Open the **colab-dev** Druppie instance and go to the **Branch Environments** page:

```
https://colab-dev-druppie.rijnland.dev
```

[Screenshot: Druppie UI - Branch Environments page showing the list of branches and the "Deploy" button]

1. Select your feature branch from the dropdown
2. Click **"Deploy"**
3. Wait ~2-5 minutes for the environment to become ready

[Screenshot: Deployment status indicator showing "Deploying..." → green success with URL]

### Step 3: Access your workspace

You get **two URLs**:

| What | URL |
|------|-----|
| **App (hot-reload)** | `https://druppie-feature-my-awesome-feature.rijnland.dev` |
| **code-server IDE** | `https://druppie-feature-my-awesome-feature-dev.rijnland.dev` |

[Screenshot: code-server IDE showing the workspace with the Druppie project files]

Open the code-server URL, log in with your Keycloak credentials, and start editing code. Changes reload **instantly** — no push, no rebuild, no restart.

---

## 2. How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    YOUR BRANCH ENVIRONMENT                       │
│         Namespace: druppie-feature-my-awesome-feature            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Non-hot-reload services (baked images) ──────────────────┐  │
│  │  Keycloak  ·  Postgres  ·  Gitea  ·  MCP modules         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Dev Workspace Pod (hot-reload) ──────────────────────────┐  │
│  │  code-server (:8080)  ← your IDE                          │  │
│  │  uvicorn --reload (:8000)  ← backend                      │  │
│  │  Vite HMR (:5173)  ← frontend                             │  │
│  │  Desktop (:6080)  ← optional XFCE/noVNC                   │  │
│  │  PVC /workspace (20Gi, persists across restarts)          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  App URL → frontend + backend (hot-reload)                      │
│  -dev URL → code-server (behind oauth2-proxy)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Key concept:** The branch namespace **is** your workspace. There's exactly one backend and one frontend, and they hot-reload live. The database, Keycloak, and MCP modules run as normal services that your workspace connects to.

---

## 3. Your URLs

Every branch environment gets unique URLs based on your branch name (slashes and special characters become dashes):

| Branch name | App URL | IDE URL |
|-------------|---------|---------|
| `feature/my-feature` | `druppie-feature-my-feature.rijnland.dev` | `druppie-feature-my-feature-dev.rijnland.dev` |
| `feature/pr-review-agent-cron` | `druppie-feature-pr-review-agent-cron.rijnland.dev` | `druppie-feature-pr-review-agent-cron-dev.rijnland.dev` |

[Screenshot: Browser showing the app URL with the Druppie interface]

[Screenshot: Browser showing the -dev URL with code-server IDE]

### What each URL gives you

**App URL** (`druppie-<slug>.rijnland.dev`):
- The full Druppie application
- Backend API with hot-reload (Python changes reflect instantly)
- Frontend with Vite HMR (React changes reflect instantly)
- Authenticated via Keycloak (same test users as colab-dev)

**IDE URL** (`druppie-<slug>-dev.rijnland.dev`):
- VS Code in your browser (code-server)
- Full terminal access
- The project is checked out at `/workspace/druppie`
- Optional desktop environment at `/proxy/6080/`

[Screenshot: code-server terminal showing kubectl or git commands]

---

## 4. Developing: Hot-Reload (No Push Needed)

### The normal workflow

1. **Edit code** in code-server at your `-dev` URL
2. **Save** — the changes reload automatically
3. **Test** in the app at your main URL
4. Repeat

**You do NOT need to push, rebuild, or restart anything for code changes.**

### What hot-reloads

| Component | How | Speed |
|-----------|-----|-------|
| **Backend** (Python/FastAPI) | `uvicorn --reload` watches `/workspace/druppie` | ~1-2 sec |
| **Frontend** (React/Vite) | Vite HMR via websocket | ~instant |
| **MCP modules** | Baked images (no hot-reload) | Requires push |

[Screenshot: Split screen showing code edit in code-server and the app updating live]

### Test users

Same users available as in colab-dev:

| User | Password |
|------|----------|
| admin | Admin123! |
| developer | Developer123! |
| normal_user | User123! |

---

## 5. When to Push (and What Happens)

### When to push

**ONLY push when you need something that can't hot-reload:**

- Adding a new Python/Node.js **package** (new `requirements.txt` or `package.json` dependency)
- Changing a **Dockerfile**
- Adding a new **MCP module** (new Dockerfile)
- Changing the **dev-workspace image** itself (new tools, desktop packages)
- Updating the **Helm chart** templates

**Do NOT push just to see your code changes** — that's what hot-reload is for.

### What happens when you push

```
You push to feature/my-feature
        │
        ▼
Gitea Actions CI builds ALL images (~30 sec cached, ~23 min cold)
        │
        ▼
Images pushed to Harbor (tagged feature-my-feature-YYYYMMDDHHMMSS-sha)
        │
        ▼
CI updates imageTag in your branch-env's HelmRelease in ai/k8s
        │
        ▼
FluxCD detects change (~1 min) → Helm upgrade → pods restart
        │
        ▼
Your environment runs with new images
```

[Screenshot: Gitea Actions showing the build workflow running for a feature branch]

### What gets reset after a push

| What | Persists? | Why |
|------|-----------|-----|
| **PVC data** (`/workspace` contents) | ✅ Yes | Longhorn volume survives pod restart |
| **Database** | ✅ Yes | Postgres has its own PVC |
| **Keycloak users/realm** | ✅ Yes | Re-imported from ConfigMap on start |
| **In-memory caches** | ❌ No | Pod restart clears them |
| **Running processes** | ❌ No | New pod = fresh start |
| **Claude Code login** | ❌ No | Must re-authenticate in code-server |
| **Workspace pod** | ⚠️ Only if workspace files changed | CI is smart: code-only pushes skip workspace rebuild |

### Important: Push deliberately

Every push triggers a **full rebuild of all images** (backend, frontend, 14 MCP modules, etc.). With Docker layer caching, cached builds take ~30 seconds. Cold builds (first push after a while) take ~23 minutes.

**Tip:** Make your code changes in the workspace first (hot-reload), verify everything works, then push once when you're ready to commit the changes.

---

## 6. Egress IP (Firewall Rules)

Your branch environment's outbound traffic (egress) goes through a specific IP address. If your feature needs to call external APIs or services, you may need to whitelist this IP in the target's firewall.

### Egress IP

| Traffic | Source IP |
|---------|-----------|
| **Normal egress** | `159.100.71.81` |
| Secondary egress | TBD (will be added here when identified) |

> **Note:** If you notice traffic coming from a different IP, let the team know so we can document it here.

### Common use cases

- **External API calls:** Whitelist `159.100.71.81` on the API provider's firewall
- **Webhook receivers:** Allow inbound from `159.100.71.81`
- **Database connections:** If connecting to an external database, whitelist the IP

[Screenshot: Example firewall configuration showing the IP whitelist rule]

---

## 7. Known Limitations

### No GPU access

Branch environments **cannot use GPUs**. The GPU node (with 2× RTX PRO 6000) is reserved for the LLM inference workloads. If you need GPU access for development:

- Use the **colab-dev** environment (has `tolerateGpu: true`)
- Or request temporary GPU access from the infra team

### Limited concurrent environments

Due to storage constraints (Longhorn RWX not yet available), you can have **~3 concurrent branch environments** at a time. When you're done with an environment, stop it to free resources.

### No auto-teardown

Branch environments don't automatically expire. **Remember to stop your environment** when you're done:

[Screenshot: Druppie UI - Branch Environments page showing the "Stop" button]

1. Go to the Branch Environments page in colab-dev
2. Click **Stop** on your environment
3. This deletes the namespace and all associated resources (PVCs, pods, etc.)

### MCP modules don't hot-reload

MCP modules run as baked Docker images. To test MCP module changes:

1. Make your code changes in the workspace
2. **Push** to trigger a rebuild
3. Wait for the new image to deploy

### No automatic database migrations

If you add columns to SQLAlchemy models, you must manually apply the migration:

```bash
# Inside your workspace terminal
kubectl exec -n druppie-feature-my-feature pod/druppie-feature-my-feature-druppie-db-0 \
  -- psql -U druppie -d druppie \
  -c "ALTER TABLE my_table ADD COLUMN IF NOT EXISTS new_column BOOLEAN DEFAULT FALSE;"
```

Then restart the backend (or wait for hot-reload to pick it up).

---

## 8. Troubleshooting

### App shows "No available server"

The backend isn't ready yet. Check if it's still starting:

```bash
# In code-server terminal
curl -s localhost:8000/health
```

Wait ~30 seconds and refresh. If it persists, check the workspace pod logs.

### code-server login loop

The oauth2-proxy can't authenticate. Check:

```bash
# In code-server terminal
kubectl logs deploy/workspace -c oauth2-proxy --tail=20
```

Common cause: The Keycloak `workspace` client is missing for your environment. Ask the team to create it.

### Git push fails from workspace

Inside the workspace pod, git should work directly (no proxy needed). If it fails:

```bash
# Test connectivity
curl -sk https://aigit.waterschap.org/api/v1/version
```

If this fails, the workspace network policy may be blocking it. Check with the team.

### Pods stuck in Pending

Not enough cluster resources. Check:

```bash
kubectl top nodes
kubectl get pods -n druppie-feature-my-feature
```

May need to stop other branch environments to free resources.

### ImagePullBackOff

The image doesn't exist in Harbor. This happens after a Harbor reset. The `harbor-ci-trigger` job should rebuild it automatically. If not:

```bash
# Ask the team to re-run
kubectl -n harbor create job ci-trigger-rerun --from=job/harbor-ci-trigger
```

---

## 9. FAQ

**Q: Can I use my own API keys?**
A: Branch environments inherit API keys from the colab-dev Vault path (`druppie/colab-dev/app`). For personal keys, ask the team to set up a per-developer Vault path.

**Q: Can I install packages in the workspace?**
A: You can install packages temporarily (they'll be gone after pod restart). For permanent changes, update the `Dockerfile.dev-workspace` and push.

**Q: How do I connect to the database?**
A: The Postgres server is at `<instance>-druppie-db:5432` inside the namespace. Use the credentials from the workspace environment variables (`DATABASE_URL`).

**Q: Can I run multiple branch environments at once?**
A: Yes, but limited to ~3 concurrent due to storage constraints. Stop environments you're not actively using.

**Q: What happens to my data when I stop the environment?**
A: **Everything is deleted** — pods, PVCs, database, everything. The `longhorn-branch-env` StorageClass has `reclaimPolicy: Delete`. Save any important data before stopping.

**Q: Can I access the GPU node?**
A: No. GPU access is not available in branch environments. Use colab-dev if you need GPU resources.

**Q: Why does my push take so long?**
A: First pushes are cold builds (~23 min). Subsequent pushes use Docker layer cache (~30 sec). If it's been a while since your last push, expect a longer build.

**Q: Can I access other namespaces from my workspace?**
A: You have a read-only kubeconfig. You can `kubectl get` resources but can't modify production namespaces.

---

## Appendix: Architecture Overview

For the technically curious, here's how everything connects:

```
Developer (code-server)
    │
    ├── Edits code → uvicorn --reload + Vite HMR (instant, no push)
    │
    └── Pushes to feature branch
            │
            ├── Gitea Actions CI
            │   ├── Builds all Docker images (DinD, layer-cached)
            │   ├── Pushes to Harbor (harbor.rijnland.dev)
            │   └── Updates imageTag in ai/k8s HelmRelease
            │
            ├── FluxCD (1m interval)
            │   └── Detects HelmRelease change → Helm upgrade
            │
            └── Pods restart with new images
                    │
                    ├── Backend, Frontend, MCP modules (always restart)
                    └── Workspace pod (only if Dockerfile.dev-workspace changed)
```

**Three repositories:**

| Repo | Purpose | Your access |
|------|---------|-------------|
| `ai/druppie` | App code, Helm chart, CI | ✅ Push |
| `ai/k8s` | GitOps, HelmReleases, infra | ✅ Push (auto-updated by CI) |
| `systeembeheer/rancher-gitops` | Base cluster infra | ❌ Read-only (infra team) |