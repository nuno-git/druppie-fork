# Druppie k3s Dev Setup Guide

This guide walks you from an empty machine to a fully running Druppie platform on a
single-node k3s cluster. Every service (backend, frontend, Keycloak, Gitea, Harbor,
Guacamole, and the nine MCP modules) runs inside the cluster, and you can spin up
isolated dev VMs from the UI or the API.

The docker-compose stack in the repo root is kept for reference, but k3s is now the
primary local development environment.

---

## Prerequisites

You need the following on the host before you start.

- **k3s** installed (single node). If it is not present yet, step 3 of Quick Start
  installs it.
- **Docker daemon** running. The backend talks to `/var/run/docker.sock` to launch
  dev VM containers, so Docker must be up on the host.
- **sysbox-runc** (optional). Gives you better isolation for dev VMs. Without it the
  platform still works using the default Docker runtime.
- **Helm 3+** for deploying the Druppie chart.
- **kubectl** for talking to the cluster.

Quick check:

```bash
docker info >/dev/null 2>&1 && echo "docker OK"     || echo "docker MISSING"
helm version --short >/dev/null 2>&1 && echo "helm OK" || echo "helm MISSING"
kubectl version --client --short >/dev/null 2>&1 && echo "kubectl OK" || echo "kubectl MISSING"
```

---

## Quick Start

Follow these steps in order. Steps that only need to run once are marked **(once)**.

### 1. Clone the repo and init submodules

```bash
git clone --recursive <repo-url>
cd druppie-fork

# If you already cloned without --recursive:
git submodule update --init
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in at least one LLM key (`ZAI_API_KEY` or `DEEPINFRA_API_KEY`).
The k3s NodePorts override the docker-compose defaults, so the values in
`.env.example` are fine to keep. The ports this guide uses are listed in the
[Service Ports](#service-ports-k3s-nodeports) table below.

### 3. Install k3s (only if not already installed)

```bash
curl -sfL https://get.k3s.io | sh -
```

This installs a single-node cluster with the embedded containerd and Traefik disabled
for ingress routing (Traefik ships with k3s but is not used for per-dev-VM routing in
this dev setup).

### 4. Set KUBECONFIG

k3s writes its kubeconfig to `/etc/rancher/k3s/k3s.yaml`. Point kubectl at it:

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

### 5. Install Harbor **(once)**

```bash
sudo ./scripts/setup-harbor-k8s.sh
```

This installs Harbor into the `harbor` namespace and exposes it on NodePort 30010.
Wait for the seven Harbor pods to be ready:

```bash
kubectl get pods -n harbor -w
```

### 6. Deploy Druppie via Helm **(once)**

```bash
helm upgrade --install druppie ./helm/druppie \
  -n druppie --create-namespace \
  -f helm/druppie/values.yaml
```

### 7. Wait for pods

The Druppie pods will go into `ImagePullBackOff` until you push the images in the
next step. That is expected. Watch them anyway so you can see the cluster come alive
once images are available:

```bash
kubectl get pods -n druppie -w
```

### 8. Build and push images to Harbor

Harbor expects the project `druppie` to exist. Create it first (once) from the Harbor
UI at http://localhost:30010 (login `admin` / `Harbor12345`), then build and push:

```bash
# Backend
docker build -t localhost:30010/druppie/druppie-backend:latest -f Dockerfile .
docker push localhost:30010/druppie/druppie-backend:latest

# Frontend
docker build -t localhost:30010/druppie/druppie-frontend:latest -f frontend/Dockerfile frontend/
docker push localhost:30010/druppie/druppie-frontend:latest

# Dev VM base image
docker build -t localhost:30010/druppie/dev-vm-base:latest \
  -f druppie/mcp-servers/module-coding/Dockerfile.dev-vm ./druppie/mcp-servers/
docker push localhost:30010/druppie/dev-vm-base:latest
```

After the push, the pods from step 7 start pulling and become `Running`.

### 9. Deploy Guacamole **(once)**

```bash
kubectl apply -f k8s/guacamole.yaml
```

This creates the `remote-access` namespace with guacd, the Guacamole web app, and a
PostgreSQL instance for Guacamole's own schema.

### 10. Initialize the Guacamole DB schema **(once)**

```bash
kubectl exec -n remote-access deploy/guacamole -- \
  /opt/guacamole/bin/initdb.sh --postgresql \
  | kubectl exec -i -n remote-access deploy/guac-postgres -- \
    psql -U guacamole_user -d guacamole_db
```

### 11. Run the Keycloak setup **(once)**

This creates the `druppie` realm, the test users, and the Gitea OAuth client.

```bash
KEYCLOAK_URL=http://localhost:30002 \
KEYCLOAK_ADMIN=admin \
KEYCLOAK_ADMIN_PASSWORD=admin \
FRONTEND_PORT=30001 \
BACKEND_PORT=30000 \
KEYCLOAK_PORT=30002 \
GITEA_PORT=30003 \
python3 scripts/setup_keycloak.py
```

### 12. Configure k3s insecure registry for Harbor **(once)**

k3s needs to know that Harbor on NodePort 30010 is an insecure (HTTP) registry.
Create `/etc/rancher/k3s/registries.yaml`:

```bash
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  localhost:30010:
    endpoint:
      - "http://localhost:30010"
configs:
  "localhost:30010":
    tls:
      insecure_skip_verify: true
EOF

sudo systemctl restart k3s
```

Without this, k3s pulls from `localhost:30010` fail with TLS errors.

### 13. Patch the NetworkPolicy for Guacamole access

The Druppie namespace ships a default-deny `NetworkPolicy` that blocks egress to the
`remote-access` namespace, so the backend cannot reach Guacamole until you allow it.
See the [Troubleshooting](#backend-cant-reach-guacamole) section for the exact patch.

### 14. Open the app

Point your browser at http://localhost:30001 and log in with `admin` / `Admin123!`.

---

## Service Ports (k3s NodePorts)

All services are exposed as NodePorts, so you reach them on `localhost:<port>`.

| Service | Port | URL |
|---------|------|-----|
| Frontend | 30001 | http://localhost:30001 |
| Backend API | 30000 | http://localhost:30000 |
| Keycloak | 30002 | http://localhost:30002 |
| Gitea | 30003 | http://localhost:30003 |
| Harbor | 30010 | http://localhost:30010 |
| Guacamole | 30020 | http://localhost:30020/guacamole/ |
| Grafana | 30050 | http://localhost:30050 |

---

## Architecture Overview

Everything described below runs on the single k3s node.

**Namespace `druppie`** holds the core platform:

- Backend (FastAPI) and Frontend (Vite/React), both pulling images from Harbor.
- Keycloak and Gitea.
- The nine MCP modules (coding, docker, plus the rest), each its own Deployment.
- `layout-service` for UI layout.
- Three PostgreSQL instances: one for the Druppie app, one for Keycloak, one for Gitea.

**Namespace `harbor`** runs the Harbor registry as seven pods (core, jobservice,
registry, portal, database, redis, trivy).

**Namespace `remote-access`** runs Guacamole: `guacd` (the protocol gateway), the
`guacamole` web app, and a dedicated `guac-postgres`.

**On the host**, outside the cluster:

- The Docker daemon, used by the backend to start dev VM containers via the mounted
  `/var/run/docker.sock`.
- The Gitea `act-runner`, the CI/CD executor that builds and deploys on push.

---

## Creating a Dev VM

Dev VMs are Docker containers (optionally on the sysbox runtime) that give each
developer an isolated coding environment with its own branch checked out.

**Via API:**

```bash
TOKEN=$(curl -s -X POST "http://localhost:30000/realms/druppie/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=druppie-frontend&username=admin&password=Admin123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:30000/api/dev-vms \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-vm","branch":"colab-dev"}'
```

**Via UI:** Open http://localhost:30001, log in, and go to the **Dev Environments**
tab. Click to create a new VM and pick a branch.

**Access the VM through Guacamole:**

1. Open http://localhost:30020/guacamole/
2. Log in with `guacadmin` / `guacadmin` (change this in any non-throwaway setup).
3. The connection created for your VM appears in the list.
4. RDP credentials inside the session: `developer` / `developer`.

---

## CI/CD Pipeline

Druppie uses Gitea Actions for continuous delivery.

- The workflow lives at `.gitea/workflows/build-and-deploy.yaml`.
- An `act-runner` runs on the host with the Docker socket and kubeconfig mounted, so
  it can both build images and talk to the cluster.
- Pushing to the `colab-dev` branch triggers: build the backend and frontend images,
  push them to Harbor, then `kubectl rollout restart` the two deployments.

Trigger it with a normal push:

```bash
git push origin colab-dev
```

Watch the run in Gitea at http://localhost:30003 under the repo's **Actions** tab.

---

## Troubleshooting

### Keycloak login fails

Symptom: the frontend shows "Invalid username or password" even with the right
credentials, or redirects loop.

Re-run the setup script and make sure the port environment variables match the
NodePorts in the [Service Ports](#service-ports-k3s-nodeports) table:

```bash
KEYCLOAK_URL=http://localhost:30002 \
KEYCLOAK_ADMIN=admin KEYCLOAK_ADMIN_PASSWORD=admin \
FRONTEND_PORT=30001 BACKEND_PORT=30000 \
KEYCLOAK_PORT=30002 GITEA_PORT=30003 \
python3 scripts/setup_keycloak.py
```

### Backend can't reach Guacamole

Symptom: dev VM creation fails, backend logs show timeouts to `guacd` or the
Guacamole API.

The Druppie namespace uses a restrictive `NetworkPolicy` named `druppie-app-net`.
By default it denies egress to the `remote-access` namespace. You need to **add**
an egress rule for `remote-access` without removing the existing ones.

A strategic merge patch would *replace* the whole `egress` array and silently drop
the rules the app already needs. Use a JSON Patch instead so the new rule is appended
to the list:

```bash
kubectl patch networkpolicy druppie-app-net -n druppie --type=json -p='[
  {
    "op": "add",
    "path": "/spec/egress/-",
    "value": {
      "to": [
        { "namespaceSelector": { "matchLabels": { "kubernetes.io/metadata.name": "remote-access" } } }
      ],
      "ports": [
        { "protocol": "TCP", "port": 4822 },
        { "protocol": "TCP", "port": 8080 }
      ]
    }
  }
]'
```

The `/spec/egress/-` path means "append to the end of the egress array", so every
existing rule stays in place. Port 4822 is guacd, port 8080 is the Guacamole web app.

Verify the rule landed:

```bash
kubectl get networkpolicy druppie-app-net -n druppie -o jsonpath='{.spec.egress}' | python3 -m json.tool
```

### Backend can't launch dev VMs

The backend launches dev VMs through Docker, so it needs the host socket. Check that
the socket is mounted and reachable inside the pod:

```bash
kubectl exec -n druppie deploy/druppie-backend -- docker ps
```

If that fails with "permission denied" or "cannot connect to the Docker daemon", the
socket mount in `helm/druppie/values.yaml` is wrong or the container user is not in
the right group. Confirm `/var/run/docker.sock` is mounted and the backend runs as a
user that can access it.

### Image pull errors

Symptom: pods stuck in `ImagePullBackOff` or `ErrImagePull`.

```bash
kubectl describe pod <pod> -n druppie | grep -A5 "Failed:"
```

Common causes:

- The images were never pushed. Re-run step 8 of Quick Start.
- k3s does not know Harbor is insecure. Re-run step 12 and `sudo systemctl restart k3s`.
- The Harbor project `druppie` does not exist. Create it in the Harbor UI.

### Port conflicts

Something else on the host already holds a NodePort:

```bash
ss -tlnp | grep -E '3000[0-3]|30010|30020|30050'
```

Kill the conflicting process, or remap the NodePort in `helm/druppie/values.yaml`
and the matching manifest.

---

## Deploying to the rijnland.dev RKE2 cluster (kubectl/helm)

The remote RKE2 cluster differs from the local k3s flow above: it uses Traefik
ingress (in `kube-system`), Longhorn storage, a publicly-resolvable in-cluster
registry, and no Harbor / `docker.sock`. The local-only steps below do **not**
apply to RKE2: `localhost:30010`, `/etc/rancher/k3s/registries.yaml`, the insecure
registry config, and the Docker-socket dev-VM steps.

1. **Registry + TLS secrets.** Deploy the in-cluster registry and create the two
   wildcard-backed TLS secrets in their namespaces (copies of the cluster
   `*.rijnland.dev` cert):

   ```bash
   kubectl apply -f k8s/registry.yaml
   # registry-tls in namespace registry, druppie-tls in namespace druppie
   kubectl create secret tls registry-tls -n registry --cert=wildcard.crt --key=wildcard.key
   kubectl create secret tls druppie-tls  -n druppie  --cert=wildcard.crt --key=wildcard.key
   ```

2. **Build & push images** to `druppie-registry.rijnland.dev/druppie/`:

   ```bash
   docker build -t druppie-registry.rijnland.dev/druppie/druppie-backend:latest -f Dockerfile .
   docker push  druppie-registry.rijnland.dev/druppie/druppie-backend:latest
   docker build -t druppie-registry.rijnland.dev/druppie/druppie-frontend:latest -f frontend/Dockerfile frontend/
   docker push  druppie-registry.rijnland.dev/druppie/druppie-frontend:latest
   # ...repeat for each module image
   ```

3. **Deploy via Helm** with the rijnland override on top of the base values:

   ```bash
   helm upgrade --install druppie ./helm/druppie -n druppie --create-namespace \
     -f helm/druppie/values.yaml \
     -f helm/druppie/values-rijnland.yaml
   ```

The app is then reachable at https://druppie.rijnland.dev. The domain stays a
single label so it matches the `*.rijnland.dev` wildcard cert.

### Per-branch full-stack environments

Stand up a complete, isolated Druppie instance for any branch in its own
namespace, alongside the live `druppie` deployment:

```bash
# From the repo root, with kubectl pointed at the rijnland RKE2 cluster:
./scripts/deploy-branch-env.sh colab-dev
```

This creates namespace `druppie-colab-dev`, copies the `*.rijnland.dev` wildcard
TLS secret into it, and runs `helm upgrade --install` layering branch overrides
(host `druppie-colab-dev.rijnland.dev`, a dedicated worker-node pin) on top of
`values.yaml` + `values-rijnland.yaml`. Preview the rendered release without
touching the cluster:

```bash
./scripts/deploy-branch-env.sh colab-dev --dry-run
```

Notes:
- The host stays a single label under `rijnland.dev` to match the wildcard cert.
- Shared PVCs are ReadWriteOnce here, so the instance is pinned to one worker
  node (default a different node than the live `druppie` instance — override with
  `BRANCH_ENV_NODE`). See `helm/druppie/values-branch.example.yaml` for the full
  set of override knobs (registry, image tag, node).
- Provide branch-specific images via `BRANCH_ENV_IMAGE_TAG` /
  `BRANCH_ENV_REGISTRY`, or an extra values file via `-f`.
- Tear down with `helm uninstall druppie -n druppie-colab-dev && kubectl delete ns druppie-colab-dev`.
