# Internal Gitea CI/CD Architecture for User Apps

> **Status**: Draft for review (v3)
> **Date**: 2026-07-28
> **Author**: Druppie AI

## 1. Problem Statement

User apps created by Druppie (`create_project` intent) have their Gitea repos on the
**internal Gitea** (`http://druppie-gitea:3000`, in-cluster), but the `module-deploy` GitOps
client is configured to dispatch CI workflows on the **external Gitea**
(`https://aigit.waterschap.org`). This causes a 404 error:

```
workflow dispatch failed: GitOps dispatching workflow build.yaml
on ai/vergunningzoeker-555750bf@main failed: HTTP 404: not found
```

Additionally, the internal Gitea has **no Gitea Actions runner**, so even if the
dispatch succeeded, no runner would execute the workflow.

## 2. Kubernetes Infrastructure Overview

### 2.1 Namespace Architecture

The cluster runs multiple isolated Druppie instances, each in its own namespace.
Every namespace contains a full Druppie stack including its **own internal Gitea**:

```
Cluster (RKE2 on rijnland.dev)
│
├── druppie                          # Production / main instance
│   ├── Backend, Frontend, Keycloak
│   ├── Internal Gitea (druppie-gitea:3000)
│   ├── Internal Gitea Runner (NEW — for user app CI)
│   ├── PostgreSQL (3-node CNPG HA)
│   ├── 11 MCP Modules (module-deploy, coding, etc.)
│   └── druppie-sandbox              # Sandbox runtime namespace
│
├── druppie-colab-dev                # Shared development instance
│   ├── Backend, Frontend, Keycloak
│   ├── Internal Gitea (druppie-colab-dev-gitea:3000)
│   ├── Internal Gitea Runner (NEW — for user app CI)
│   ├── PostgreSQL (1-node CNPG)
│   ├── 11 MCP Modules
│   └── druppie-colab-dev-sandbox
│
├── druppie-feature-foo              # Per-branch environment (ephemeral)
│   ├── Backend, Frontend, Keycloak
│   ├── Internal Gitea (druppie-feature-foo-gitea:3000)
│   ├── Internal Gitea Runner (NEW — for user app CI)
│   ├── PostgreSQL (standalone)
│   ├── 11 MCP Modules (hot-reload from workspace)
│   ├── Dev workspace pod
│   └── druppie-feature-foo-sandbox
│
├── gitea-runner                     # Shared external runner namespace
│   ├── External Gitea Runner (5x, DinD, privileged)
│   └── Connects to aigit.waterschap.org (external Gitea)
│
├── harbor                          # Container registry (in-cluster)
│   └── druppie/ project            # All images (Druppie + user apps)
│
├── flux-system, cert-manager, traefik, longhorn, ...  # System namespaces
│
└── External (outside cluster)
    └── aigit.waterschap.org         # External Gitea (shared, Infra-managed)
        ├── ai/druppie               # Druppie's own source code
        ├── ai/k8s                   # GitOps repo (Flux source of truth)
        └── systeembeheer/rancher-gitops  # Base infra (read-only)
```

### 2.2 Two Runner Types

| Aspect | External Runner | Internal Runner |
|--------|----------------|-----------------|
| **Purpose** | Builds Druppie itself (ai/druppie CI) | Builds user apps (druppie-apps/* CI) |
| **Gitea** | External `aigit.waterschap.org` | Internal per-namespace Gitea |
| **Deployment** | Single StatefulSet in `gitea-runner` ns | One StatefulSet PER Druppie namespace |
| **Part of Helm chart?** | No (managed in ai/k8s infra) | Yes (part of druppie Helm chart) |
| **Build engine** | DinD (privileged) | Kaniko (non-privileged, daemonless) |
| **Replicas** | 5 | 2 per namespace |
| **Namespace** | `gitea-runner` | Same as the Druppie instance (e.g. `druppie`, `druppie-colab-dev`, `druppie-feature-foo`) |

The internal runner is deployed **as part of the Druppie Helm chart** (`helm/druppie/templates/internal-runner-statefulset.yaml`).
This means every Druppie instance (main, colab-dev, each branch env) gets its own
runner that talks to its own in-cluster Gitea. The runner is gated by a Helm value
(e.g. `internalRunner.enabled`) so branch environments can opt out if desired.

### 2.3 Shared Infrastructure (External to All Namespaces)

These are shared across all Druppie instances and are NOT deployed per namespace:

| Component | Location | Purpose |
|-----------|----------|---------|
| **External Gitea** | `aigit.waterschap.org` (outside cluster) | Hosts `ai/druppie`, `ai/k8s`, `systeembeheer/*` |
| **External Runner** | `gitea-runner` namespace | Builds Druppie's own CI (ai/druppie) |
| **Harbor** | `harbor` namespace (in-cluster) | Stores all container images at `harbor.rijnland.dev/druppie/` |
| **ai/k8s repo** | On external Gitea | GitOps source of truth for FluxCD |
| **FluxCD** | `flux-system` namespace | Watches ai/k8s, reconciles cluster state |

### 2.4 Current Problem (per-namespace view)

Taking the `druppie` namespace as an example — the same problem exists in every
namespace:

```
┌──────────────────────────────────────────────────────────┐
│                    druppie namespace                      │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────────────┐    │
│  │ module-deploy     │    │ Internal Gitea            │    │
│  │ (k8s_deploy.py)   │    │ druppie-gitea:3000        │    │
│  │                   │    │                          │    │
│  │ USERAPPS_GITOPS_URL│   │  org: druppie             │    │
│  │ = aigit.waterschap│    │  user repos:             │    │
│  │ .org              │    │  <user>/<project>-<id>   │    │
│  │                   │    │                          │    │
│  │ ❌ Dispatches     │    │  ⚠ No Actions runner     │    │
│  │    workflows on   │    │  ⚠ No Harbor secrets     │    │
│  │    external Gitea │    └──────────────────────────┘    │
│  │    → 404          │                                    │
│  └──────────────────┘                                    │
└──────────────────────────────────────────────────────────┘

External Gitea (aigit.waterschap.org):
  ai/k8s ← module-deploy commits Flux manifests here (correct)
  ai/druppie, systeembeheer/*
  ✗ user app repos don't exist here → 404
```

### 2.5 Current Data Flow

1. **Project creation** (`builtin_tools.py`): Creates repo on **internal Gitea**
   under the user's Gitea username (e.g., `john_doe/vergunningzoeker-a1b2c3d4`).
2. **Deploy** (`k8s_deploy.py`): `GitopsClient` uses `USERAPPS_GITOPS_URL`
   (`https://aigit.waterschap.org`) for ALL Gitea API calls:
   - Committing Flux manifests to `ai/k8s` → **correct** (ai/k8s is on external Gitea)
   - Dispatching workflows on user app repos → **wrong** (repos are on internal Gitea)
3. **Workflow dispatch** fails with 404 because the repo doesn't exist on the
   external Gitea.

## 3. Target Architecture (per-namespace view)

Taking the `druppie` namespace as an example — every namespace gets the same setup:

```
┌──────────────────────────────────────────────────────────┐
│                    druppie namespace                      │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────────────┐    │
│  │ module-deploy     │    │ Internal Gitea            │    │
│  │ (k8s_deploy.py)   │    │ druppie-gitea:3000        │    │
│  │                   │    │                          │    │
│  │ USERAPPS_GITOPS_URL│   │  org: druppie-apps        │    │
│  │ = aigit.waterschap│    │  user repos:             │    │
│  │ .org              │    │  druppie-apps/<project>  │    │
│  │ (for ai/k8s)      │    │  -<id>                   │    │
│  │                   │    │                          │    │
│  │ USERAPPS_APP_REPO │    │  ✅ Actions runner (new) │    │
│  │ _URL = http://    │    │  ✅ Harbor secrets       │    │
│  │ druppie-gitea:3000│    │  ✅ Gitea token secret   │    │
│  │ (for dispatch)    │    └───────────┬──────────────┘    │
│  │                   │                │                    │
│  │ ✅ Dispatches     │    ┌───────────┴──────────────┐    │
│  │    workflows on   │    │ Internal Runner            │    │
│  │    internal Gitea │    │ (StatefulSet, 2 replicas)  │    │
│  │ ✅ Commits to     │    │                            │    │
│  │    ai/k8s on      │    │  ┌──────────────┐         │    │
│  │    external Gitea │    │  │  act_runner   │         │    │
│  └──────────────────┘    │  │ (kaniko for   │         │    │
│                          │  │  builds)      │         │    │
│  ┌──────────────────┐    │  └──────────────┘         │    │
│  │ Harbor            │    └──────────────────────────┘    │
│  │ (harbor namespace)│                                    │
│  │ ← runner pushes   │                                    │
│  │    images here    │                                    │
│  └──────────────────┘                                    │
└──────────────────────────────────────────────────────────┘

External Gitea (aigit.waterschap.org):
  ai/k8s ← module-deploy commits Flux manifests here
         ← runner pushes image tag bumps here
  ai/druppie, systeembeheer/*
```

The same pattern repeats in every namespace:
- `druppie` namespace → runner connects to `druppie-gitea:3000`
- `druppie-colab-dev` namespace → runner connects to `druppie-colab-dev-gitea:3000`
- `druppie-feature-foo` namespace → runner connects to `druppie-feature-foo-gitea:3000`

All runners push images to the same shared Harbor and all commit tag bumps to
the same shared `ai/k8s` repo on the external Gitea.

## 4. End-to-End Lifecycle

This section explains the full lifecycle of a user app, from creation to teardown,
and what each component (agent, CI/CD, Flux) is responsible for.

### 4.1 Lifecycle Overview

```
User request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ AGENT LAYER (Druppie backend, MCP servers)                   │
│                                                              │
│  1. Router agent detects intent → "create_project"           │
│  2. set_intent() creates Project record + Gitea repo         │
│     + pushes template code (.gitea/workflows/build.yaml,     │
│     Dockerfile, chart/, app/, frontend/)                     │
│  3. Planner routes to: architect → developer → deployer      │
│  4. Developer agent codes the app (via sandbox)              │
│  5. Deployer agent calls deploy() MCP tool                   │
│     → commits Flux manifests to ai/k8s                       │
│     → dispatches CI workflow on internal Gitea               │
│     → waits for build + Flux rollout + health check          │
│                                                              │
│  Available MCP tools: build, deploy, teardown, stop,         │
│  logs, list_apps, inspect                                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ CI/CD LAYER (Gitea Actions, internal runner)                 │
│                                                              │
│  1. Workflow dispatched on internal Gitea                    │
│  2. Internal runner picks up the job                         │
│  3. Kaniko builds image + pushes to Harbor                   │
│  4. Workflow bumps image.tag in ai/k8s HelmRelease           │
│     (clusters/user-apps/<slug>/helmrelease.yaml)             │
│  5. Git push to external Gitea (ai/k8s)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ GITOPS LAYER (FluxCD on cluster)                             │
│                                                              │
│  1. Flux detects new/changed files in ai/k8s                 │
│  2. Flux creates/updates the HelmRelease                     │
│  3. HelmRelease deploys the app (Deployment, Service,        │
│     Ingress, etc.)                                           │
│  4. App becomes available at <slug>-apps.rijnland.dev        │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Step-by-Step: Creating and Deploying an App

#### Phase A: Project Creation (Agent Layer)

1. User says "create a project called vergunningzoeker"
2. **Router agent** calls `set_intent("create_project", project_name="vergunningzoeker")`
3. `set_intent()` in `builtin_tools.py`:
   - Creates a `Project` record in the Druppie database
   - Calls `GiteaClient.create_repo()` on the **internal Gitea**
     → repo created at `druppie-apps/vergunningzoeker-a1b2c3d4`
   - Calls `GiteaClient.push_template()` to push the project template
     → files pushed: `Dockerfile`, `chart/`, `app/`, `frontend/`,
       `.gitea/workflows/build.yaml`, etc.
4. **Planner** creates a plan: `architect → developer → deployer → summarizer`
5. **Architect agent** designs the app (reads template, plans changes)
6. **Developer agent** implements the app via `execute_coding_task()` (sandbox):
   - Clones the repo, writes code, commits, pushes
   - All changes go to the internal Gitea repo
7. **Deployer agent** calls the `deploy()` MCP tool

#### Phase B: Deploy (Agent → CI/CD handoff)

The `deploy()` MCP tool (`tools.py`) calls `k8s_deploy()` in `k8s_deploy.py`:

**Step 1 — Commit GitOps manifests to ai/k8s** (external Gitea):
```
ai/k8s repo (on aigit.waterschap.org):
  clusters/user-apps/
    vergunningzoeker-a1b2c3d4/
      namespace.yaml        # K8s Namespace for the app
      gitrepository.yaml    # Flux GitRepository → points to internal Gitea repo
      helmrelease.yaml      # Flux HelmRelease → deploys the app chart
```

These three files are the **entire deployment footprint** in ai/k8s. They are
committed atomically via the Gitea batch contents API.

**Step 2 — Dispatch CI workflow** on the **internal** Gitea:
```
POST /api/v1/repos/druppie-apps/vergunningzoeker-a1b2c3d4/actions/workflows/build.yaml/dispatches
```

**Step 3 — Poll for build completion** (up to 20 minutes):
- Polls `GET /api/v1/repos/druppie-apps/.../actions/runs` every 5 seconds
- Waits for status="completed"

#### Phase C: CI Build (CI/CD Layer)

The internal runner executes `build.yaml`:

1. **Checkout** the app repo from internal Gitea
2. **Derive names**: image tag = `<branch>-<timestamp>-<sha>`
3. **Install kaniko** (daemonless image builder)
4. **Build and push** with kaniko:
   ```
   kaniko --context . --dockerfile Dockerfile \
     --destination harbor.rijnland.dev/druppie/vergunningzoeker-a1b2c3d4:<tag> \
     --cache --cache-repo harbor.rijnland.dev/druppie/vergunningzoeker-a1b2c3d4/cache
   ```
5. **Clone ai/k8s**, bump the image tag in the HelmRelease:
   ```yaml
   # clusters/user-apps/vergunningzoeker-a1b2c3d4/helmrelease.yaml
   spec.values.image.tag: <new-tag>
   ```
6. **Push** the tag bump to `ai/k8s` on external Gitea
   (with retry+rebase loop for concurrent push handling)

#### Phase D: GitOps Rollout (FluxCD Layer)

1. FluxCD detects the new commit in `ai/k8s` (within ~1 minute)
2. Flux reconciles the `GitRepository` + `HelmRelease`:
   - Creates the namespace `vergunningzoeker-a1b2c3d4`
   - Deploys the app (Deployment, Service, Ingress, etc.)
   - Uses the new image tag from the HelmRelease
3. `k8s_deploy()` waits for HelmRelease Ready=True (up to 10 minutes)
4. `k8s_deploy()` health-gates the public URL (up to 5 minutes):
   ```
   https://vergunningzoeker-a1b2c3d4-apps.rijnland.dev/health
   ```
5. Returns success/failure to the deployer agent

### 4.3 What Lives Where

| Resource | Location | Created By | Removed By |
|----------|----------|------------|------------|
| App source code | Internal Gitea: `druppie-apps/<project>-<id>` | `set_intent()` | Manual or reset |
| CI workflow | `.gitea/workflows/build.yaml` in app repo | Template push | Manual |
| Docker image | Harbor: `harbor.rijnland.dev/druppie/<repo>:<tag>` | CI workflow | Harbor retention policy |
| Flux GitRepository | `ai/k8s: clusters/user-apps/<slug>/gitrepository.yaml` | `k8s_deploy()` | `k8s_teardown()` |
| Flux HelmRelease | `ai/k8s: clusters/user-apps/<slug>/helmrelease.yaml` | `k8s_deploy()` | `k8s_teardown()` |
| K8s Namespace | Cluster: `<slug>` | Flux (via HelmRelease) | Flux prune (after teardown) |
| App pods | Cluster: `<slug>` namespace | Flux (via HelmRelease) | Flux prune or `k8s_stop()` |

### 4.4 Teardown (How Apps Are Removed)

The `teardown()` MCP tool calls `k8s_teardown()`:

1. Lists files in `ai/k8s/clusters/user-apps/<slug>/`
2. Deletes all files via the Gitea batch contents API (single commit)
3. FluxCD detects the directory is gone → prunes all resources:
   - Deletes the HelmRelease
   - Deletes the GitRepository
   - Deletes the namespace (and all pods/services inside)
4. Returns success

The app repo on the internal Gitea is **not** deleted by teardown — only the
deployment footprint in ai/k8s is removed. The source code remains.

### 4.5 Stop (Scale to Zero)

The `stop()` MCP tool can either:
- **Pause** (`remove=false`): Scales the app Deployment to 0 replicas.
  The HelmRelease, namespace, and ai/k8s manifests remain. The app can be
  resumed by scaling back up.
- **Full teardown** (`remove=true`, default): Same as teardown above.

### 4.6 Other Agent Tools

| Tool | What It Does | How |
|------|-------------|-----|
| `build()` | Dispatch CI + poll for completion | Calls internal Gitea Actions API |
| `logs()` | Read app pod logs | Reads via K8s API (in-cluster SA token) |
| `list_apps()` | List deployed apps | Scans `ai/k8s/clusters/user-apps/` dir |
| `inspect()` | App status, URL, pod info | Reads HelmRelease + pods via K8s API |

## 5. Component Details

### 5.1 Code Fix: `dispatch_workflow` and `latest_run`

**File**: `druppie/mcp-servers/module-deploy/v1/k8s_deploy.py`

**Current** (broken):
```python
class GitopsClient:
    def __init__(self):
        base = GITOPS_URL.rstrip("/")
        self._api = f"{base}/api/v1/repos/{GITOPS_REPO}"
        self._runs_api = f"{base}/api/v1/repos/{APP_REPO_ORG}"
        # _runs_api is always https://aigit.waterschap.org/api/v1/repos/ai

    async def dispatch_workflow(self, repo, workflow, ref):
        resp = await c.post(
            f"{self._runs_api}/{repo}/actions/workflows/{workflow}/dispatches",
            # Always uses APP_REPO_ORG — ignores actual repo_owner
        )
```

**Fixed**:
```python
class GitopsClient:
    def __init__(self):
        base = GITOPS_URL.rstrip("/")
        app_base = APP_REPO_URL.rstrip("/")  # internal Gitea URL
        self._api = f"{base}/api/v1/repos/{GITOPS_REPO}"
        self._runs_api_base = f"{app_base}/api/v1/repos"  # no hardcoded org

    async def dispatch_workflow(self, repo, workflow, ref, repo_owner=None):
        owner = repo_owner or APP_REPO_ORG
        resp = await c.post(
            f"{self._runs_api_base}/{owner}/{repo}/actions/workflows/{workflow}/dispatches",
            json={"ref": ref},
        )
```

**New env var**:
```python
APP_REPO_URL = os.getenv("USERAPPS_APP_REPO_URL", "http://druppie-gitea:3000")
```

**Updated org default**:
```python
APP_REPO_ORG = os.getenv("USERAPPS_APP_REPO_ORG", "druppie-apps")
```

### 5.2 Internal Gitea Runner

A new StatefulSet in the Druppie namespace. Unlike the external runner (which
uses a privileged DinD sidecar), the internal runner uses **kaniko** for image
building — kaniko runs entirely in userspace as a workflow step, no sidecar
container or privileged mode needed.

| Aspect | External Runner | Internal Runner |
|--------|----------------|-----------------|
| **Gitea instance** | `https://aigit.waterschap.org` | `http://druppie-gitea:3000` |
| **Registration** | Org-level (`ai` org) | Org-level (`druppie-apps` org) |
| **Registration token** | From Vault `ci/gitea-runner` | From Vault `ci/gitea-runner-internal` |
| **Replicas** | 5 | 2 (fewer user apps) |
| **Build engine** | DinD sidecar (privileged) | Kaniko (daemonless, workflow step) |
| **Build cache** | 30Gi Longhorn PVC (`dind-storage`) | Registry cache in Harbor (no PVC) |
| **Runner data** | 1Gi PVC (`runner-data`) | 1Gi PVC (`runner-data`) |
| **Harbor access** | `--insecure-registry harbor.rijnland.dev` | Kaniko `--skip-tls-verify` flags |
| **External Gitea access** | N/A (runs external workflows) | Needed (to push to `ai/k8s`) |
| **CA bundle** | Waterschap private CA | Same (for external Gitea TLS) |
| **Security context** | `privileged: true` | Default (no privileged escalation) |
| **Namespace** | `gitea-runner` (separate) | `druppie` (same as other components) |

**Why kaniko?** Kaniko builds container images without requiring a Docker daemon.
It executes each Dockerfile command in userspace, needs no privileged mode, and
pushes directly to registries. It runs as a regular CLI tool in the workflow —
no sidecar, no persistent daemon, no special security context.

**Runner ConfigMap** (`configmap-internal-runner-config.yaml`):
```yaml
log:
  level: info
runner:
  capacity: 1
  timeout: 1h
  fetch_timeout: 10s
  labels:
    ubuntu-latest: "docker://node:20-bookworm"
container:
  network: host
  options: "-e GIT_SSL_NO_VERIFY=1"
  valid_volumes:
    - '*'
```

**StatefulSet template** (`internal-runner-statefulset.yaml`):
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {instance}-internal-runner
  namespace: {namespace}
spec:
  serviceName: {instance}-internal-runner
  replicas: 2
  podManagementPolicy: Parallel
  selector:
    matchLabels:
      app.kubernetes.io/component: internal-runner
  template:
    metadata:
      labels:
        app.kubernetes.io/component: internal-runner
    spec:
      initContainers:
        - name: ca-setup
          image: gitea/act_runner:latest
          command:
            - sh
            - -c
            - cat /etc/ssl/certs/ca-certificates.crt /etc/aigit-ca/chain.pem
                > /castore/ca-bundle.pem && echo CA bundle built
          volumeMounts:
            - { name: aigit-ca, mountPath: /etc/aigit-ca }
            - { name: castore, mountPath: /castore }
        - name: register-runner
          image: curlimages/curl:latest
          command:
            - sh
            - -c
            - |
              TOKEN=$(curl -sf -X POST \
                -H "Authorization: token $(cat /etc/gitea-admin/token)" \
                http://druppie-gitea:3000/api/v1/orgs/druppie-apps/actions/runners/registration-token \
                | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
              if [ -n "$TOKEN" ]; then
                mkdir -p /etc/runner-token
                echo -n "$TOKEN" > /etc/runner-token/token
              else
                echo "Failed to fetch registration token"
                exit 1
              fi
          volumeMounts:
            - { name: runner-token-dir, mountPath: /etc/runner-token }
            - { name: gitea-admin-token, mountPath: /etc/gitea-admin }
      containers:
        - name: runner
          image: gitea/act_runner:latest
          env:
            - name: GITEA_INSTANCE_URL
              value: "http://druppie-gitea:3000"
            - name: GITEA_RUNNER_REGISTRATION_TOKEN
              valueFrom:
                secretKeyRef:
                  name: {instance}-internal-runner-token
                  key: token
            - name: GITEA_RUNNER_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: GITEA_RUNNER_LABELS
              value: "ubuntu-latest:docker://node:20-bookworm"
            - name: SSL_CERT_FILE
              value: "/castore/ca-bundle.pem"
            - name: CONFIG_FILE
              value: "/etc/act_runner/config.yaml"
          volumeMounts:
            - { name: runner-data, mountPath: /data }
            - { name: castore, mountPath: /castore }
            - { name: act-runner-config, mountPath: /etc/act_runner }
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 512Mi
              cpu: 1000m
      volumes:
        - { name: castore, emptyDir: {} }
        - { name: runner-token-dir, emptyDir: {} }
        - name: aigit-ca
          configMap:
            name: {instance}-aigit-ca
        - name: act-runner-config
          configMap:
            name: {instance}-internal-runner-config
        - name: gitea-admin-token
          secret:
            secretName: {instance}-gitea-admin-token
            items:
              - key: token
                path: token
  volumeClaimTemplates:
    - metadata:
        name: runner-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: longhorn-distributed
        resources:
          requests:
            storage: 1Gi
```

**Registration token flow**:
1. Init container `register-runner` calls `POST /api/v1/orgs/druppie-apps/actions/runners/registration-token`
   on the internal Gitea (authenticated as `gitea_admin`).
2. Writes the token to a shared emptyDir volume.
3. A seed job (or the Helm chart's post-install hook) also stores the token in
   a K8s Secret (`{instance}-internal-runner-token`) for pod restarts.
4. The StatefulSet references this secret for `GITEA_RUNNER_REGISTRATION_TOKEN`.
5. **Token renewal**: The init container runs on every pod start, ensuring the
   token is always fresh.

### 5.3 Org-Level Secrets on Internal Gitea

The template `build.yaml` workflow references these secrets:
- `HARBOR_REGISTRY` → `harbor.rijnland.dev`
- `HARBOR_USERNAME` → Harbor robot account
- `HARBOR_PASSWORD` → Harbor robot token
- `CI_GIT_TOKEN` → Gitea token with write access to `ai/k8s`

These must be set on the `druppie-apps` org of the internal Gitea via the Gitea API:
```
PUT /api/v1/orgs/druppie-apps/actions/secrets/{secret_name}
```

The init job (`setup_gitea.py`) or a dedicated seed job sets these during
deployment, sourcing the values from the same Vault paths used by the external
Gitea bootstrap.

### 5.4 CI_GIT_TOKEN Scoping

The `CI_GIT_TOKEN` used by user app workflows to push image tag bumps to
`ai/k8s` should be restricted to only modify files under `clusters/user-apps/`.

**Server-side enforcement** (ideal, but external Gitea is managed by Infra team):
A pre-receive hook on `ai/k8s` that rejects pushes modifying files outside
`clusters/user-apps/`. This requires Infra team action on `aigit.waterschap.org`.

**Client-side enforcement** (implemented in the workflow template):
A validation step in `build.yaml` that checks the files being committed:

```yaml
      - name: Validate changed paths
        run: |
          git diff --cached --name-only | while read file; do
            case "$file" in
              clusters/user-apps/${SLUG}/*) ;;
              *)
                echo "ERROR: Attempting to modify '$file' which is outside"
                echo "       clusters/user-apps/${SLUG}/ — rejected."
                exit 1
                ;;
            esac
          done
```

This step runs immediately before `git commit` in the HelmRelease bump section.
Combined with a dedicated Gitea machine user `druppie-apps-ci` whose token is
only authorized for the `ai/k8s` repo, this provides defense in depth.

**Additional measures**:
- The `CI_GIT_TOKEN` is stored as an org-level secret on the internal Gitea
  `druppie-apps` org, not shared across orgs.
- The token is sourced from Vault `ci/gitea-apps-ci` (a dedicated Vault path),
  separate from the admin token used by the Druppie backend.

### 5.5 Repo Creation Under Org

**File**: `druppie/agents/builtin_tools.py`

**Current**: Creates repos under the user's Gitea username:
```python
repo_result = await gitea.create_repo(
    name=repo_name,
    owner=gitea_username,  # user-owned repo
)
```

**Changed**: Create repos under the `druppie-apps` org:
```python
repo_result = await gitea.create_repo(
    name=repo_name,
    # owner=None → creates under org (GITEA_ORG = "druppie-apps")
)
```

This requires:
1. The `druppie-apps` org to exist on the internal Gitea (created by `setup_gitea.py`)
2. The `GITEA_ORG` env var on the backend to be set to `druppie-apps` (or the
   `GiteaClient` to be configured with the correct org)

### 5.6 CiliumNetworkPolicy

The internal Gitea runner needs egress to:
1. **Internal Gitea** (same namespace) → already allowed by app-net policy
2. **Harbor** (`harbor.rijnland.dev`, port 443) → needs a CNP
3. **External Gitea** (`aigit.waterschap.org`, port 443) → needs a CNP (for
   pushing `ai/k8s` image tag bumps)
4. **DNS** (CoreDNS/kube-dns, port 53 UDP) → needs explicit egress if the
   default app-net policy blocks DNS

New CNP template: `cnp-internal-runner-egress.yaml`:
```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: {instance}-internal-runner-egress
spec:
  endpointSelector:
    matchLabels:
      app.kubernetes.io/component: internal-runner
  egress:
    - toEndpoints:
        - matchLabels:
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
          rules:
            dns:
              - matchPattern: "*"
    - toFQDNs:
        - matchPattern: "aigit.waterschap.org"
        - matchPattern: "harbor.rijnland.dev"
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
    - toCIDR:
        - 10.23.0.101/32  # external Gitea IP fallback
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
```

## 6. Workflow Template Changes

The existing template `build.yaml` (at `druppie/templates/project/.gitea/workflows/build.yaml`)
needs modifications to use **kaniko** instead of Docker commands:

**Changed steps** (only the build and push steps differ):

```yaml
      - name: Install kaniko
        run: |
          curl -fsSL -o /usr/local/bin/kaniko \
            https://github.com/GoogleContainerTools/kaniko/releases/download/v1.23.2/kaniko-linux-amd64
          chmod +x /usr/local/bin/kaniko

      - name: Build and push image
        env:
          IMAGE: ${{ steps.names.outputs.image_name }}
          TAG: ${{ steps.names.outputs.tag }}
          HARBOR_PASS: ${{ secrets.HARBOR_PASSWORD }}
        run: |
          # Configure Docker credentials for kaniko
          USER="${HARBOR_USER:-robot$druppie+druppie-ci}"
          AUTH="$(printf '%s:%s' "$USER" "$HARBOR_PASS" | base64 -w0)"
          mkdir -p /kaniko/.docker
          printf '{"auths":{"%s":{"auth":"%s"}}}\n' "$REGISTRY" "$AUTH" \
            > /kaniko/.docker/config.json

          # Build and push in one shot (kaniko caches layers in Harbor)
          /usr/local/bin/kaniko \
            --context "$(pwd)" \
            --dockerfile Dockerfile \
            --destination "$REGISTRY/druppie/$IMAGE:$TAG" \
            --cache=true \
            --cache-repo "$REGISTRY/druppie/$IMAGE/cache" \
            --build-arg CACHEBUST=${{ github.sha }} \
            --skip-tls-verify-pull \
            --skip-tls-verify-push
```

The rest of the workflow (checkout, name derivation, yq install, HelmRelease
bump with path validation) remains unchanged.

**Key differences from the Docker-based approach**:
- No DinD sidecar needed — kaniko runs as a regular process.
- No privileged mode — kaniko executes Dockerfile commands in userspace.
- Layer caching uses Harbor as a cache repo (`--cache-repo`), not local storage.
- No periodic cleanup needed — cache lives in Harbor, not on a PVC.
- The `--skip-tls-verify-*` flags are needed because Harbor uses a private CA;
  these can be removed once the CA is properly configured in the kaniko image.

## 7. Implementation Plan

### Phase 1: Code Fix (minimal, unblocks the 404 error)

| Step | File | Change |
|------|------|--------|
| 1.1 | `k8s_deploy.py` | Add `APP_REPO_URL` env var (default `http://druppie-gitea:3000`) |
| 1.2 | `k8s_deploy.py` | Fix `dispatch_workflow` to accept `repo_owner` param |
| 1.3 | `k8s_deploy.py` | Fix `latest_run` to accept `repo_owner` param |
| 1.4 | `k8s_deploy.py` | Fix `k8s_build` to pass `repo_owner` to both methods |
| 1.5 | `k8s_deploy.py` | Fix `_poll_build` to pass `repo_owner` to `latest_run` |
| 1.6 | `k8s_deploy.py` | Change `APP_REPO_ORG` default to `druppie-apps` |
| 1.7 | `module-deploy-deployment.yaml` | Add `USERAPPS_APP_REPO_URL` env var |
| 1.8 | `values.yaml` | Add `userApps.gitops.appRepoUrl` config |
| 1.9 | `values.yaml` | Change `userApps.gitops.appRepoOrg` default to `druppie-apps` |

### Phase 2: Internal Gitea Runner (enables CI for user apps)

| Step | File | Change |
|------|------|--------|
| 2.1 | New: `templates/internal-runner-statefulset.yaml` | StatefulSet for internal runner (2 replicas, no sidecar) |
| 2.2 | New: `templates/internal-runner-configmap.yaml` | Runner config (capacity 1, labels) |
| 2.3 | New: `templates/internal-runner-rbac.yaml` | RBAC for runner pod (if needed) |
| 2.4 | New: `templates/cnp-internal-runner-egress.yaml` | CNP for runner egress (Harbor, external Gitea, DNS) |
| 2.5 | `values.yaml` | Add `internalRunner` config section |
| 2.6 | `setup_gitea.py` | Create `druppie-apps` org, set Actions secrets |
| 2.7 | `build.yaml` template | Replace Docker build/push with kaniko |

### Phase 3: Repo Creation Under Org (cleaner secret management)

| Step | File | Change |
|------|------|--------|
| 3.1 | `builtin_tools.py` | Change `create_repo` to not pass `owner` (creates under org) |
| 3.2 | `gitea.py` | Update `GITEA_ORG` default to `druppie-apps` |
| 3.3 | `setup_gitea.py` | Ensure `druppie-apps` org exists |

### Phase 4: CI_GIT_TOKEN Scoping (security hardening)

| Step | File | Change |
|------|------|--------|
| 4.1 | External Gitea admin | Create `druppie-apps-ci` machine user + access token |
| 4.2 | Vault | Store scoped token as `ci/gitea-apps-ci` |
| 4.3 | `setup_gitea.py` | Source `CI_GIT_TOKEN` from `ci/gitea-apps-ci` instead of `ci/gitea` |
| 4.4 | `build.yaml` template | Add pre-commit path validation step |

## 8. Secret Management

### Secrets needed on the internal Gitea `druppie-apps` org:

| Secret Name | Source | Description |
|-------------|--------|-------------|
| `HARBOR_REGISTRY` | Vault `ci/harbor` → `registry` | Harbor registry URL |
| `HARBOR_USERNAME` | Vault `ci/harbor` → `username` | Harbor robot account |
| `HARBOR_PASSWORD` | Vault `ci/harbor` → `password` | Harbor robot token |
| `CI_GIT_TOKEN` | Vault `ci/gitea-apps-ci` → `token` | Scoped Gitea token (write to `ai/k8s` only) |

These are sourced from the same Vault paths used by the external Gitea's `ai`
org. The init job or a dedicated seed job copies them to the internal Gitea.

### Runner registration token:

| Secret | Source | Description |
|--------|--------|-------------|
| `GITEA_RUNNER_REGISTRATION_TOKEN` | Generated via Gitea API init container, stored in K8s Secret | Runner registration with internal Gitea |

### K8s Secrets for the runner pod:

| Secret | Source | Description |
|--------|--------|-------------|
| `{instance}-gitea-admin-token` | Vault `ci/gitea` → `token` | Admin token for registration token fetch |
| `{instance}-internal-runner-token` | Init container output | Runner registration token (refreshed on pod start) |

## 9. Workflow Queue Behavior

- Each runner replica has `capacity: 1` (one concurrent job).
- With 2 replicas, max 2 concurrent builds.
- Gitea natively queues additional workflow runs when all runners are busy.
- Queued runs are picked up as soon as a runner becomes idle.
- No explicit queue depth monitoring in MVP (relies on Gitea's built-in queue).
- Build timeout: runner `timeout: 1h`; code-side `BUILD_POLL_TIMEOUT: 1200s` (20m).
  The code gives up after 20m even if the runner continues — align if needed.

## 10. Rollout Strategy

1. **Phase 1 first** (code fix): Deploy independently. After this phase, the
   404 error is resolved. Workflow dispatch targets the internal Gitea, but
   there's no runner yet, so builds will time out instead of 404-ing.

2. **Phase 2** (runner + workflow template): Deploy after Phase 1. User app CI
   workflows start executing. Builds push to Harbor and bump `ai/k8s` image tags.

3. **Phase 3** (org-based repos): Deploy last. New projects are created under
   the `druppie-apps` org. Existing repos under user accounts continue to work
   (no migration needed — dev phase, cluster resets are expected).

4. **Phase 4** (token scoping): Deploy after Phase 3. Hardens the CI_GIT_TOKEN
   to prevent out-of-path modifications to `ai/k8s`.

## 11. Testing Plan

### Phase 1 validation:
1. Deploy a test user app via `create_project`.
2. Trigger `k8s_build` — verify workflow dispatch returns HTTP 200 (not 404).
3. Verify `latest_run` returns the workflow run (status: "waiting" since no runner).

### Phase 2 validation:
1. Verify runner pods start and register in Gitea (check Gitea UI → Org → Runners).
2. Trigger a build — verify workflow transitions: waiting → running → completed.
3. Verify image appears in Harbor (`harbor.rijnland.dev/druppie/<repo>`).
4. Verify `ai/k8s` HelmRelease image tag is bumped.
5. Verify Flux rolls out the new image (HelmRelease Ready=True).

### Phase 3 validation:
1. Create a new project — verify repo is under `druppie-apps` org, not user account.
2. Verify org-level secrets are accessible to the workflow.

### Phase 4 validation:
1. Modify the workflow to attempt a push outside `clusters/user-apps/` — verify
   the pre-commit validation step rejects it.
2. Normal push inside `clusters/user-apps/` — verify acceptance.

## 12. Out of Scope (MVP)

The following are explicitly out of scope for the initial MVP:
- **Monitoring & alerting** (runner health, workflow success rates, queue depth)
- **Backup & disaster recovery** for internal Gitea data
- **Upgrade strategy** for act_runner, kaniko, or Gitea versions
- **Migration of existing user repos** from user accounts to `druppie-apps` org
  (dev phase — cluster resets are expected)
- **Server-side pre-receive hook** on external Gitea (Infra team ownership)
