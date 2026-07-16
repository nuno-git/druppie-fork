> **⚠️ STALE** — This guide describes the old kind-based local deployment.
> The production deployment has migrated to Hetzner K3s.
> - **`iac/README.md`** — current Hetzner K3s setup
> - **`docs/research/008-kubernetes-as-built-analysis.md`** — as-built analysis (when it exists)
> - **`docs/reference/as-built-architecture.md`** — as-built architecture reference
> See `iac/README.md` for current setup.

# Kubernetes Deployment Guide

This guide covers everything you need to deploy Druppie on Kubernetes using a local `kind` cluster. It starts with the basics, walks through the full setup, and ends with troubleshooting and production tips.

---

## 1. Kubernetes Basics

Kubernetes is a container orchestrator. It manages many containers across many machines, keeping your applications running even when individual containers crash or machines go down.

### Key Concepts

**Pod**
The smallest unit in Kubernetes. A pod runs one or more containers that share the same network and storage. In practice, most pods contain a single container.

**Deployment**
Manages a set of pods. You tell it "keep 3 replicas of this container running" and it handles the rest: starting new pods when they crash, rolling out updates, and rolling back if something breaks.

**StatefulSet**
Like a Deployment, but designed for databases and other stateful workloads. Each pod gets a stable network identity (like `druppie-db-0`, `druppie-db-1`) and its own persistent storage that survives pod restarts.

**Service**
An internal load balancer. Pods come and go, but a Service gives them a stable IP address and DNS name so other components can reach them reliably.

**Ingress**
An HTTP router that maps URLs to Services. Think of it as an nginx reverse proxy that sits at the edge of your cluster and routes `localhost:9080/api/*` to the backend, `localhost:9080/git/*` to Gitea, and so on.

**ConfigMap / Secret**
Configuration files and passwords that get injected into containers as environment variables or mounted files. ConfigMaps store non-sensitive data; Secrets store passwords and API keys.

**PVC (PersistentVolumeClaim)**
A request for disk storage. When a pod writes data to a PVC, that data survives even if the pod gets deleted and recreated.

**Namespace**
An isolated workspace within a cluster. All Druppie resources live in a namespace called `druppie`, keeping them separate from anything else running on the same cluster.

**Job**
A run-once task. Druppie uses a Job to run the Keycloak setup script on first install.

**NetworkPolicy**
Firewall rules for pods. Controls which pods can talk to each other and what traffic can leave the cluster. Druppie uses these to lock down database access and control egress.

---

## 2. Architecture Overview

```
                        localhost:9080
                              |
                    [nginx Ingress Controller]
                              |
         +--------------------+--------------------+
         |          |          |          |         |
    / -> frontend  /api -> backend  /realms -> keycloak  /git -> gitea
                                    /resources
                                    /admin
                                    /js
                                    /welcome
```

### Components

| Component | Resource Type | Purpose |
|-----------|---------------|---------|
| PostgreSQL (druppie-db) | StatefulSet | Druppie application database |
| PostgreSQL (keycloak-db) | StatefulSet | Keycloak identity database |
| PostgreSQL (gitea-db) | StatefulSet | Gitea metadata database |
| Keycloak | Deployment | OAuth2/OIDC identity provider |
| Gitea | Deployment | Git repository server |
| Backend | Deployment | Python/FastAPI REST API |
| Frontend | Deployment | React SPA served by serve |
| Module: coding | Deployment | MCP coding tools |
| Module: docker | Deployment | MCP Docker tools |
| Module: filesearch | Deployment | MCP file search tools |
| Module: llm | Deployment | MCP LLM proxy |
| Module: registry | Deployment | MCP registry tools |
| Module: vision | Deployment | MCP vision tools |
| Module: web | Deployment | MCP web tools |
| Module: archimate | Deployment | MCP architecture tools |
| Init Job | Job | Runs `setup_keycloak.py` on first install |

### Resource Count

3 StatefulSets + 12 Deployments + 15 Services + 5 NetworkPolicies + 1 Ingress + 1 ConfigMap + 1 Secret + 4 PVCs + 2 Jobs = roughly 43 Kubernetes resources.

---

## 3. Path-Based Routing

The nginx Ingress Controller sits at `localhost:9080` and routes requests based on the URL path:

| Path | Service | Description |
|------|---------|-------------|
| `/` | frontend | React SPA. This is the catch-all route, so any path not matched below goes to the frontend. |
| `/api/*` | backend | REST API. The backend already expects the `/api` prefix, so it passes through as-is. |
| `/realms/*` | keycloak | Keycloak authentication endpoints (OIDC discovery, token exchange). |
| `/resources/*` | keycloak | Keycloak static assets (CSS, JS, images). |
| `/admin/*` | keycloak | Keycloak admin console. |
| `/js/*` | keycloak | Keycloak JavaScript adapter. |
| `/welcome/*` | keycloak | Keycloak welcome page. |
| `/git/*` | gitea | Git web UI. The ingress rewrites the path, stripping the `/git` prefix before forwarding to Gitea. |

---

## 4. Helm Chart Structure

```
helm/druppie/
├── Chart.yaml                         # Chart metadata (name, version, appVersion)
├── values.yaml                        # All configurable values
└── templates/
    ├── _helpers.tpl                    # Reusable template helpers
    ├── secrets.yaml                    # API keys, DB passwords
    ├── configmap.yaml                  # Environment variables
    ├── services.yaml                   # 15 ClusterIP services
    ├── ingress.yaml                    # Path-based routing rules
    ├── networkpolicy.yaml              # 5 network policies
    ├── persistentvolumeclaims.yaml     # 4 PVCs (workspace, dataset, gitea, sandbox-bundles)
    ├── *-statefulset.yaml              # 3 PostgreSQL databases
    ├── *-deployment.yaml               # 12 deployments (keycloak, gitea, backend, frontend, 8 modules)
    ├── init-job.yaml                   # Post-install Keycloak setup
    ├── sandbox-image-builder-job.yaml  # Placeholder for sandbox image
    └── NOTES.txt                       # Post-install instructions
```

---

## 5. Setup Guide

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| Docker | Runs containers and the kind cluster | [docker.com](https://docker.com) (50GB+ free disk recommended) |
| Docker Buildx | BuildKit backend for fast cached builds | See below |
| kind | Kubernetes cluster inside Docker | `go install sigs.k8s.io/kind@latest` or download from [GitHub releases](https://github.com/kubernetes-sigs/kind/releases) |
| helm | Kubernetes package manager | `snap install helm --classic` or download from [GitHub releases](https://github.com/helm/helm/releases) |
| kubectl | Kubernetes command line | `snap install kubectl --classic` |

#### Docker Buildx (required)

The backend Dockerfile uses `--mount=type=cache` for pip, which requires BuildKit via buildx.

```bash
mkdir -p ~/.docker/cli-plugins
BUILDX_VERSION=$(curl -sL https://api.github.com/repos/docker/buildx/releases/latest | jq -r '.tag_name')
curl -L -o ~/.docker/cli-plugins/docker-buildx \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
chmod +x ~/.docker/cli-plugins/docker-buildx
docker buildx version  # verify
```

### Step 1: Clone the repo

```bash
git clone --branch feature/kubernetes-migration https://github.com/nuno-git/druppie-fork.git druppie-k8s
cd druppie-k8s
```

### Step 2: Build Docker images

```bash
# Backend
docker buildx build --load -t druppie-backend:latest .

# Frontend (VITE vars are baked at build time)
docker buildx build --load \
  --build-arg VITE_API_URL=http://localhost:9080 \
  --build-arg VITE_KEYCLOAK_URL=http://localhost:9080 \
  --build-arg VITE_KEYCLOAK_REALM=druppie \
  --build-arg VITE_KEYCLOAK_CLIENT_ID=druppie-frontend \
  --build-arg VITE_GITEA_URL=http://localhost:9080/git \
  -t druppie-frontend:latest ./frontend/

# Init
docker buildx build --load -t druppie-init:latest -f Dockerfile.init .

# MCP Modules (build context must be druppie/mcp-servers/)
for mod in coding docker filesearch llm registry vision web archimate; do
  docker buildx build --load -t druppie-module-$mod:latest \
    -f druppie/mcp-servers/module-$mod/Dockerfile \
    druppie/mcp-servers/
done
```

### Step 3: Create the kind cluster

```bash
kind create cluster --name druppie --config kind/cluster-dev.yaml
```

### Step 4: Install the nginx Ingress Controller

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

### Step 5: Load images into kind

`kind` runs its own internal Docker daemon, so images built on your host are not visible inside the cluster. You need to load them explicitly.

```bash
# The backend image is large (~4GB). If /tmp is too small for the transfer,
# save it to a different path:
# docker save druppie-backend:latest -o /path/to/backend.tar
# kind load image-archive /path/to/backend.tar --name druppie
# rm /path/to/backend.tar

for img in druppie-backend druppie-frontend druppie-init \
  druppie-module-coding druppie-module-docker druppie-module-filesearch \
  druppie-module-llm druppie-module-registry druppie-module-vision \
  druppie-module-web druppie-module-archimate; do
  kind load docker-image ${img}:latest --name druppie
done
```

### Step 6: Install the Helm chart

```bash
# With an LLM API key
helm install druppie helm/druppie/ \
  --namespace druppie --create-namespace --wait --timeout 300s \
  --set secrets.zaiApiKey="YOUR_ZAI_API_KEY"

# Without an API key (mock LLM mode)
helm install druppie helm/druppie/ \
  --namespace druppie --create-namespace --wait --timeout 300s
```

### Step 7: Initialize Keycloak

The init Job creates the Druppie realm, client, roles, and test users in Keycloak. It is defined as a Helm hook, so it runs automatically during `helm install`. If you need to run it manually:

```bash
kubectl create configmap druppie-init-scripts \
  --from-file=setup_keycloak.py=scripts/setup_keycloak.py \
  --from-file=users.yaml=iac/users.yaml \
  -n druppie

helm template druppie helm/druppie/ --show-only templates/init-job.yaml -n druppie \
  | sed '/helm.sh\/hook/d' | kubectl apply -n druppie -f -

kubectl wait --for=condition=complete job/druppie-init -n druppie --timeout=180s
```

### Step 8: Access the platform

Open http://localhost:9080 in your browser.

Test users:

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect |
| developer | Developer123! | developer |

---

## 6. Configuration Reference

Key values in `helm/druppie/values.yaml`:

| Value | Default | Description |
|-------|---------|-------------|
| `global.domain` | `localhost` | Domain name for the platform. Change this for production deployments. |
| `global.ingress.port` | `9080` | External port the ingress listens on. |
| `secrets.zaiApiKey` | (empty) | LLM provider API key. If empty, the backend runs in mock LLM mode. |
| `backend.llm.forceProvider` | (empty) | Force a specific LLM provider (options: `zai`, `deepinfra`, etc.). Leave empty for auto-detection. |
| `keycloak.adminUser` | `admin` | Keycloak master admin username. |
| `keycloak.adminPassword` | `admin` | Keycloak master admin password. Change this for any non-local deployment. |

---

## 7. Troubleshooting

### ImagePullBackOff on pods

The image was not loaded into the kind cluster. Load it:

```bash
kind load docker-image <image-name>:latest --name druppie
```

Then delete the pod so Kubernetes recreates it:

```bash
kubectl delete pod <pod-name> -n druppie
```

### 504 Gateway Timeout from the ingress

A NetworkPolicy is likely blocking the ingress controller from reaching the target service. Check the policies:

```bash
kubectl get networkpolicy -n druppie
```

Make sure the policy for the affected service allows ingress from the `ingress-nginx` namespace.

### LLM errors (connection refused to external API)

The backend pod needs egress access to reach external LLM APIs. Check that the backend NetworkPolicy includes an egress rule for port 443:

```bash
kubectl describe networkpolicy -n druppie
```

### Double `/api` prefix in requests

The Vite build variable `VITE_API_URL` should be set to `http://localhost:9080`, not `http://localhost:9080/api`. The frontend code already appends `/api` to the base URL. If you include it in the build variable, requests go to `/api/api/...`.

### Disk space during image loading

The backend image is roughly 4GB. `kind load docker-image` saves the image to a temporary file in `/tmp` before loading it into the cluster. If `/tmp` is on a small partition, use the archive approach instead:

```bash
docker save druppie-backend:latest -o /mnt/large-disk/backend.tar
kind load image-archive /mnt/large-disk/backend.tar --name druppie
rm /mnt/large-disk/backend.tar
```

### Pods stuck in CrashLoopBackOff

Check the logs:

```bash
kubectl logs <pod-name> -n druppie
```

Common causes: missing environment variables, database not ready yet (wait a minute and check again), or wrong image tag.

---

## 8. Teardown

To delete the entire cluster and all resources:

```bash
kind delete cluster --name druppie
```

This removes the kind Docker container, all containers inside it, and all stored data. There is no undo.

To uninstall the Helm release without deleting the cluster:

```bash
helm uninstall druppie -n druppie
```

---

## 9. Production Notes

This setup uses `kind` for local development. For a production deployment, you need to change several things:

**Cluster**
Replace `kind` with a real Kubernetes cluster: AWS EKS, Google GKE, Azure AKS, or an on-prem cluster.

**Databases**
The StatefulSets running PostgreSQL containers work for development. In production, use a managed database service (RDS, Cloud SQL, Azure Database) or a dedicated PostgreSQL operator. The container-based setup does not handle backups, replication, or failover.

**TLS**
Add TLS termination using cert-manager. The current ingress only handles plain HTTP on port 9080.

**Secrets**
Replace the Helm chart secrets with an external secrets manager: HashiCorp Vault, AWS Secrets Manager, or GCP Secret Manager. Helm values are stored in etcd and are visible to anyone with cluster access.

**Domain**
Set `global.domain` to your actual domain name and configure DNS to point to your cluster's ingress controller.

**Auto-scaling**
Add HorizontalPodAutoscaler (HPA) resources for the backend and MCP modules. These scale the number of pod replicas based on CPU or memory usage.

**Availability**
Add PodDisruptionBudgets (PDB) to ensure enough replicas stay available during rolling updates and node maintenance.

**Container registry**
Push images to a container registry (Docker Hub, ECR, GCR) instead of loading them into the cluster. Update the image references in `values.yaml` to point to the registry URLs.
