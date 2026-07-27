# Branch Environment Developer Guide

> Your personal, isolated development environment inside the cluster.
> Create one from the Druppie UI, develop with hot-reload, tear down when done.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Your URLs](#2-your-urls)
3. [Developing: Hot-Reload (No Push Needed)](#3-developing-hot-reload-no-push-needed)
4. [AI Coding Assistants](#4-ai-coding-assistants)
5. [When to Push (and What Happens)](#5-when-to-push-and-what-happens)
6. [Egress IP (Firewall Rules)](#6-egress-ip-firewall-rules)
7. [Secrets and API Keys](#7-secrets-and-api-keys)
8. [Known Limitations](#8-known-limitations)
9. [Troubleshooting](#9-troubleshooting)
10. [FAQ](#10-faq)

---

## 1. Quick Start

### Step 1: Open the Branch Environments page

Go to the colab-dev Druppie instance:

```
https://colab-dev-druppie.rijnland.dev
```

Navigate to the **Branch Environments** page.

[Screenshot: Druppie UI - Branch Environments page]

### Step 2: Choose your deployment type

There are **two deployment options**:

| Option | What it deploys | URLs | Use case |
|--------|----------------|------|----------|
| **Full deployment** (default) | Complete Druppie stack: backend, frontend, database, Keycloak, Gitea, MCP modules + workspace | All 3 URLs below | Developing and testing code changes against the full application |
| **Workspace only** (recovery mode) | Just the workspace pod + Keycloak for auth | VS Code + Desktop only | Using Claude Code or OpenCode without deploying the full stack — saves cluster resources |

[Screenshot: Branch Environments UI showing the deployment type toggle/checkbox]

1. Type your feature branch name (e.g. `feature/my-awesome-feature`)
2. Select your deployment type
3. Click **"Deploy"**

The system **automatically creates the branch** from `colab-dev` if it doesn't exist yet. No manual git commands needed.

4. Wait ~2-5 minutes for the environment to become ready

[Screenshot: Deployment pipeline showing the stages: Flux sync → Chart source → Secrets → Helm install → Pods & images]

### Step 3: Start developing

Open your IDE URL (see [Your URLs](#2-your-urls) below), log in, and start editing. Changes reload **instantly** — no push, no rebuild, no restart.

---

## 2. Your URLs

Every branch environment gets URLs based on your branch name (slashes and special characters become dashes):

### Full deployment

| Access | URL Pattern | Example |
|--------|-------------|---------|
| **App** (frontend + backend) | `druppie-<slug>.rijnland.dev` | `druppie-feature-my-feature.rijnland.dev` |
| **VS Code** (code-server IDE) | `druppie-<slug>-dev.rijnland.dev` | `druppie-feature-my-feature-dev.rijnland.dev` |
| **Desktop** (XFCE/noVNC) | `druppie-<slug>-dev.rijnland.dev/proxy/6080/` | `druppie-feature-my-feature-dev.rijnland.dev/proxy/6080/` |

[Screenshot: The app URL showing the Druppie application]

[Screenshot: The code-server IDE showing the workspace with project files]

[Screenshot: The desktop environment showing XFCE with terminal]

**App URL** — The full Druppie application with hot-reloading backend and frontend. Log in with Keycloak.

**VS Code URL** — Full VS Code in your browser with:
- Terminal access
- Project checked out at `/workspace/druppie`
- All repos cloned (`ai/druppie`, `ai/k8s`, `systeembeheer/rancher-gitops`)
- Claude Code and OpenCode pre-installed
- Read-only `kubectl` access to the cluster

**Desktop URL** — Full XFCE desktop environment with VS Code desktop, Chromium, and Terminator terminal.

### Workspace only (recovery mode)

| Access | URL Pattern | Example |
|--------|-------------|---------|
| **VS Code** (code-server IDE) | `druppie-<slug>-dev.rijnland.dev` | `druppie-feature-my-feature-dev.rijnland.dev` |
| **Desktop** (XFCE/noVNC) | `druppie-<slug>-dev.rijnland.dev/proxy/6080/` | `druppie-feature-my-feature-dev.rijnland.dev/proxy/6080/` |

No app URL — just the workspace for coding with Claude Code or OpenCode. Use this when you don't need the full Druppie stack and want to save cluster resources.

---

## 3. Developing: Hot-Reload (No Push Needed)

### The normal workflow

1. **Edit code** in code-server or the desktop
2. **Save** — changes reload automatically
3. **Test** in the app at your main URL
4. Repeat

**You do NOT need to push, rebuild, or restart anything for code changes.**

### What hot-reloads

**Everything hot-reloads.** The workspace pod runs the backend, frontend, and all MCP modules under `uvicorn --reload` — edits in code-server reflect instantly.

| Component | How | Speed |
|-----------|-----|-------|
| **Backend** (Python/FastAPI) | `uvicorn --reload` watches `/workspace/druppie` | ~1-2 sec |
| **Frontend** (React/Vite) | Vite HMR via websocket | ~instant |
| **MCP modules** (all 11) | `uvicorn --reload` per module | ~1-2 sec |

[Screenshot: Split screen showing code edit in code-server and the app updating live]

### How it works (full deployment)

Your branch environment has **one workspace pod** that runs everything with hot-reload, plus **separate pods** for the supporting infrastructure:

```
┌─────────────────────────────────────────────────────────────┐
│  Workspace Pod (everything hot-reloads)                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  code-server (:8080)     ← VS Code IDE                │  │
│  │  uvicorn --reload (:8000) ← Backend (hot-reload)      │  │
│  │  Vite HMR (:5173)       ← Frontend (hot-reload)       │  │
│  │  MCP modules (:9001-15) ← All modules (hot-reload)    │  │
│  │  Desktop (:6080)        ← XFCE/noVNC                  │  │
│  │  PVC /workspace (20Gi)  ← Persists across restarts    │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Separate Pods (infrastructure, no hot-reload needed):      │
│  Keycloak · Postgres · Gitea                                │
└─────────────────────────────────────────────────────────────┘
```

The workspace pod connects to the infrastructure services (database, Keycloak, Gitea) over in-cluster DNS.

### How it works (workspace only)

```
┌─────────────────────────────────────────────────────────────┐
│  Workspace Pod                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  code-server (:8080)     ← VS Code IDE                │  │
│  │  Desktop (:6080)        ← XFCE/noVNC                  │  │
│  │  PVC /workspace (20Gi)  ← Persists across restarts    │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Keycloak (for authentication only)                         │
└─────────────────────────────────────────────────────────────┘
```

No backend, frontend, database, Gitea, or MCP modules — just the workspace and Keycloak for auth.

### Test users

Same users available as in colab-dev:

| User | Password | Role |
|------|----------|------|
| admin | Admin123! | admin |
| developer | Developer123! | developer |
| normal_user | User123! | user |
| architect | Architect123! | architect |
| analyst | Analyst123! | business_analyst |

---

## 4. AI Coding Assistants

Your workspace comes with AI coding assistants pre-installed and ready to use:

### Claude Code

- **CLI**: `claude` command available in the terminal
- **VS Code extension**: Installed and ready in code-server
- Login state persists on the PVC (survives pod restarts)

[Screenshot: Claude Code running in the code-server terminal]

### OpenCode

- **CLI**: `opencode` command available in the terminal
- All providers configured and ready to use

[Screenshot: OpenCode running in the code-server terminal]

Use these directly from the terminal or from within VS Code to get AI-assisted coding help.

---

## 5. When to Push (and What Happens)

### When to push

**ONLY push when you need something that can't hot-reload:**

- Adding a new Python/Node.js **package** (dependency in `requirements.txt` or `package.json`)
- Changing a **Dockerfile**
- Changing the **dev-workspace image** (new tools, desktop packages)
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

[Screenshot: Gitea Actions showing the build workflow running]

### What persists after a push

| What | Persists? |
|------|-----------|
| **PVC data** (`/workspace` contents) | ✅ Yes |
| **Database** | ✅ Yes |
| **Keycloak users/realm** | ✅ Yes |
| **In-memory caches** | ❌ No (pod restart) |
| **Running processes** | ❌ No (new pod) |
| **Claude Code login** | ⚠️ On PVC (persists if workspace pod doesn't restart) |
| **Workspace pod restart** | ⚠️ Only if `Dockerfile.dev-workspace` changed |

**Important:** CI is smart — code-only pushes (no Dockerfile changes) skip the workspace rebuild, so your workspace pod keeps running with your in-memory state intact.

**Tip:** Develop with hot-reload first, verify everything works, then push once when you're ready to commit.

---

## 6. Egress IP (Firewall Rules)

Your branch environment's outbound traffic goes through a specific IP. If your feature needs to call external APIs or services, you may need to whitelist this IP.

### Egress IP

| Traffic | Source IP |
|---------|-----------|
| **Normal egress** | `159.100.71.81` |
| Secondary egress | TBD (will be added when identified) |

> **Note:** If you see traffic from a different IP, let the team know.

### Common use cases

- **External API calls:** Whitelist `159.100.71.81`
- **Webhook receivers:** Allow inbound from `159.100.71.81`
- **External database connections:** Whitelist the IP

[Screenshot: Example firewall configuration]

---

## 7. Secrets and API Keys

### How secrets flow into your environment

Secrets flow through three layers — you only touch the first one:

```
Vault (you edit here) ──(ESO polls every 1 min)──▶ ExternalSecret ──▶ K8s Secret ──(envFrom)──▶ Pod
```

| Layer | What it is | Who manages it |
|-------|-----------|----------------|
| **Vault** | Source of truth — all secret values | You (via Vault UI or CLI) |
| **ExternalSecret** | Bridge — tells ESO which Vault keys to sync | Helm chart (automatic) |
| **K8s Secret** | What pods actually mount | ESO (automatic) |
| **Pod env vars** | `envFrom: secretRef` dumps all keys as env vars | Helm chart (automatic) |

**You only ever edit Vault.** The rest is automatic.

### Vault paths

Your environment reads secrets from one of two Vault paths, controlled by the `secrets_source` setting:

| `secrets_source` | Vault path | Use case |
|-----------------|------------|----------|
| `colab-dev` (default) | `druppie/colab-dev/*` | Shared dev secrets (LLM keys, DB creds, etc.) |
| `nuno` (example) | `druppie/developers/nuno/*` | Your own isolated secrets |

Plus shared paths (same for all environments):
- `ci/gitea` — Gitea token (GitOps operations)
- `ci/harbor` — Harbor registry credentials

### Vault structure

```
ai-team-k8s/
├── ci/gitea          {token}
├── ci/harbor         {username, password, registry}
└── druppie/
    ├── colab-dev/
    │   ├── app       {internal-api-key, zai-api-key, deepseek-api-key, ...}
    │   ├── database  {password}
    │   ├── gitea     {admin-password, token, ...}
    │   └── keycloak  {admin-user, admin-password, ...}
    └── developers/
        └── <your-name>/
            ├── app   {same keys as colab-dev/app}
            ├── database
            ├── gitea
            └── keycloak
```

### Updating an existing secret (automatic, no redeploy)

```
1. Edit a value in Vault UI (e.g. druppie/colab-dev/app#zai-api-key)
2. ExternalSecret polls Vault every 1 minute → updates K8s Secret
3. Stakater Reloader detects Secret change → restarts the pod
4. Pod comes up with new env vars → hot-reload picks up the change
```

**No push, no ai/k8s changes, no CI pipeline.** Just edit Vault and wait ~1 minute.

### Adding a new secret (requires code change)

If you need a **new** env var that doesn't exist yet (e.g. `MY_NEW_API_KEY`):

```
1. Add the key in Vault (e.g. druppie/colab-dev/app#my-new-api-key)
2. Add a remoteRef mapping in dev-workspace-secrets.yaml (Helm chart)
3. Push to your branch
4. Flux picks up the chart change (~1 min) → re-renders → ESO syncs → pod restarts
```

The pod uses `envFrom: secretRef`, which dumps **all keys** in the Secret as env vars. So you only need to update the ExternalSecret template — no pod template changes needed.

**Important:** This requires a push and a redeploy cycle. Unlike updating existing values, adding new keys can't be done mid-work without a restart.

### Setting up your own secrets

To use your own isolated secrets:

1. Create the keys in Vault at `ai-team-k8s/druppie/developers/<your-name>/` (matching the structure of `druppie/colab-dev/`)
2. When creating your branch environment, set `secrets_source` to your name
3. Your environment will read from `druppie/developers/<your-name>/*` instead of `druppie/colab-dev/*`

This lets you use your own API keys and quotas, keeping your development costs separate.

### What secrets are available

The following env vars are synced from Vault into your pods:

| Env var | Vault path | Purpose |
|---------|-----------|---------|
| `INTERNAL_API_KEY` | `app#internal-api-key` | Internal API authentication |
| `ZAI_API_KEY` | `app#zai-api-key` | ZAI LLM provider |
| `DEEPSEEK_API_KEY` | `app#deepseek-api-key` | DeepSeek LLM provider |
| `DEEPINFRA_API_KEY` | `app#deepinfra-api-key` | DeepInfra LLM provider |
| `FOUNDRY_API_KEY` | `app#foundry-api-key` | Foundry LLM provider |
| `OPENROUTER_API_KEY` | `app#openrouter-api-key` | OpenRouter LLM provider |
| `DRUPPIE_MODULE_API_TOKEN` | `app#module-api-token` | MCP module authentication |
| `SANDBOX_API_SECRET` | `app#sandbox-api-secret` | Sandbox runtime authentication |
| `DRUPPIE_DB_PASSWORD` | `database#password` | Database password |
| `KEYCLOAK_ADMIN` | `keycloak#admin-user` | Keycloak admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `keycloak#admin-password` | Keycloak admin password |
| `GITEA_ADMIN_PASSWORD` | `gitea#admin-password` | Gitea admin password |
| `GITEA_TOKEN` | `gitea#token` | Internal Gitea token |
| `EXTERNAL_GITEA_TOKEN` | `ci/gitea#token` | External Gitea token (GitOps) |

Plus infrastructure secrets (managed by separate ExternalSecrets, not Vault):
- `druppie-tls` — TLS certificate for ingress
- `druppie-branch-env-pull-secret` — Harbor image pull credentials
- `druppie-branch-env-git` — GitOps Gitea token (for backend + module-deploy)

---

## 8. Known Limitations

### No GPU access

Branch environments **cannot use GPUs**. The GPU node (2× RTX PRO 6000) is reserved for LLM inference. Need GPU access? Use the **colab-dev** environment.

### Remember to stop your environment

Branch environments don't auto-expire. When you're done, stop it from the Branch Environments page to free resources:

[Screenshot: Branch Environments page with the Stop button]

**Warning:** Stopping deletes **everything** — pods, PVCs, database, all data. The `longhorn-local` StorageClass has `reclaimPolicy: Delete`. Save important data first.

---

## 9. Troubleshooting

### App shows "No available server"

Backend still starting. Check:

```bash
curl -s localhost:8000/health
```

Wait ~30 seconds and refresh.

### code-server login loop

oauth2-proxy can't authenticate. Check:

```bash
kubectl logs deploy/workspace -c oauth2-proxy --tail=20
```

Common cause: Keycloak `workspace` client missing for your environment.

### Pods stuck in Pending

Not enough cluster resources:

```bash
kubectl top nodes
kubectl get pods -n druppie-feature-my-feature
```

### ImagePullBackOff

Image missing from Harbor (after a reset). The `harbor-ci-trigger` job rebuilds automatically. If not:

```bash
kubectl -n harbor create job ci-trigger-rerun --from=job/harbor-ci-trigger
```

### Nothing works — just recreate it

If you're stuck and can't figure out what's wrong, the fastest fix is often to **stop and recreate** the environment:

1. Go to the **Branch Environments** page in the Druppie UI
2. Click **Stop** on your environment (this deletes everything — pods, PVCs, database)
3. Wait a minute for cleanup
4. Click **Deploy** again with the same branch name

This gives you a clean slate. Your code is still in the Git branch, so nothing is lost. The PVC data is the only thing that gets wiped — if you have important data, save it first.

**This is the nuclear option** — use it when debugging takes longer than a fresh deploy (~2-5 minutes).

---

## 10. FAQ

**Q: How do I connect to the database?**
A: Postgres is at `<instance>-druppie-db:5432` inside the namespace. Check `DATABASE_URL` in the workspace environment variables.

**Q: Can I run multiple branch environments at once?**
A: Yes. Stop environments you're not actively using to free resources.

**Q: Can I access other namespaces?**
A: You have a read-only kubeconfig. You can `kubectl get` resources but can't modify other namespaces.

**Q: Why does my push take so long?**
A: First pushes are cold builds (~23 min). Subsequent pushes use Docker layer cache (~30 sec).

**Q: Can I install packages temporarily?**
A: Yes, but they're gone after pod restart. For permanent changes, update `Dockerfile.dev-workspace` and push.

**Q: What repos are available in the workspace?**
A: All three repos are cloned: `ai/druppie` (at `/workspace/druppie`), `ai/k8s`, and `systeembeheer/rancher-gitops` (read-only).