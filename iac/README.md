# Hetzner K3s Cluster Setup

Provisions a production K3s cluster on Hetzner Cloud using [hetzner-k3s](https://github.com/vitobotta/hetzner-k3s).

See [ADR-001](../docs/ADR-KUBERNETES.md) for the full architecture decisions.

## Prerequisites

1. **Hetzner Cloud account** with a project and API token ([create one here](https://console.hetzner.cloud/))
2. **SSH key pair** (ed25519 recommended) — upload the public key to Hetzner Cloud Console
3. **hetzner-k3s CLI** — download the latest binary from [releases](https://github.com/vitobotta/hetzner-k3s/releases):

```bash
# Example (Linux amd64 — check releases page for your platform)
curl -sL https://github.com/vitobotta/hetzner-k3s/releases/latest/download/hetzner-k3s-linux-amd64 -o hetzner-k3s
chmod +x hetzner-k3s
sudo mv hetzner-k3s /usr/local/bin/
```

4. **kubectl** — for interacting with the cluster

## Setup

### 1. Configure the cluster

Edit `cluster.yaml` and set your Hetzner token:

```yaml
hetzner_token: "your_hcloud_api_token_here"
```

Alternatively, use the `HCLOUD_TOKEN` environment variable and leave the config value empty.

Review and adjust if needed:
- **SSH key paths** in `networking.ssh` — must match your local key pair
- **Allowed networks** — restrict `ssh` and `api` CIDRs for production
- **Worker pool sizes** — defaults match ADR-001 (1 infra, 1-10 app)

### 2. Create the cluster

```bash
hetzner-k3s create cluster --config iac/cluster.yaml
```

This takes 2-3 minutes. The tool provisions:
- 3 K3s server nodes (control plane + etcd HA)
- 1+ K3s agent nodes (worker pools)
- Hetzner Cloud Firewall, Network
- CCM, CSI driver, Cluster Autoscaler, System Upgrade Controller

### 3. Access the cluster

hetzner-k3s writes a kubeconfig to the path specified in `kubeconfig_path`:

```bash
export KUBECONFIG=./kubeconfig
kubectl get nodes
```

Expected output (5+ nodes):

```
NAME                          STATUS   ROLES                       AGE   VERSION
druppie-master1               Ready    control-plane,etcd          2m    v1.35.5+k3s1
druppie-master2               Ready    control-plane,etcd          2m    v1.35.5+k3s1
druppie-master3               Ready    control-plane,etcd          2m    v1.35.5+k3s1
druppie-pool-infra-worker1    Ready    <none>                      1m    v1.35.5+k3s1
druppie-app-*                 Ready    <none>                      1m    v1.35.5+k3s1
```

### 4. Install metrics-server

Required for HPA (Horizontal Pod Autoscaler) to read CPU/memory metrics. K3s does not include it by default when provisioned with hetzner-k3s.

```bash
export KUBECONFIG=./kubeconfig
kubectl apply -f iac/metrics-server.yaml
```

Verify:
```bash
kubectl top nodes
```

### 5. Verify

```bash
# Check all nodes are ready
kubectl get nodes -o wide

# Check system pods
kubectl get pods -A

# Check Cluster Autoscaler is running
kubectl get deployment cluster-autoscaler -n kube-system

# Check metrics-server is running
kubectl get deployment metrics-server -n kube-system
```

### 6. Pin Traefik to the infra node + Configure DNS

Traefik must run on the infra node so that DNS → infra node IP → Traefik routing always works. By default, K3s schedules Traefik on any node.

```bash
# Pin Traefik to the infra node (1 replica is enough — only 1 infra node)
kubectl patch deployment traefik -n traefik --type=json -p='[
  {"op":"add","path":"/spec/template/spec/nodeSelector","value":{"pool":"infra"}}
]'
kubectl scale deployment traefik -n traefik --replicas=1
```

Then point DNS records to the infra node's public IP:

```bash
# Get the infra node public IP
kubectl get nodes -l pool=infra -o wide
```

Create these DNS A records:

| Record | Target |
|--------|--------|
| `druppie.example.com` | Infra node public IP |
| `auth.druppie.example.com` | Infra node public IP |
| `git.druppie.example.com` | Infra node public IP |

Traefik reads the Kubernetes Ingress resources and routes traffic to the correct services based on hostname.

### 7. NFS server (required for autoscaling)

An in-cluster NFS server provides `ReadWriteMany` (RWX) storage, allowing backend pods to mount the same workspace across multiple nodes. This is required for KEDA/HPA to schedule pods beyond a single node.

The NFS server is deployed automatically by the Helm chart when `nfs.enabled: true` (set in `values-hetzner.yaml`). It:
- Runs as a `Recreate` Deployment pinned to the infra node (`pool: infra`)
- Backs data onto a Hetzner Cloud Volume (`hcloud-volumes` StorageClass)
- Exports via NFSv4 (single port 2049 — works through Kubernetes ClusterIP Service)
- Creates static PVs for workspace and sandbox-bundles with `ReadWriteMany` access

A DaemonSet (`nfs-client-installer`) runs on all `pool=app` nodes to ensure `nfs-common` is installed before pods mount NFS volumes.

To verify after deployment:
```bash
kubectl get pods -n druppie -l app=nfs-server
kubectl get pv | grep nfs
kubectl get pvc -n druppie druppie-workspace druppie-sandbox-bundles
```

All PVCs should show `Bound` with access mode `RWX`.

### 8. Docker on app nodes (required for sandbox)

Backend's compose_up sandbox requires `/var/run/docker.sock`. The Helm chart includes a DaemonSet (`druppie-docker-installer`) that installs Docker on all `pool=app` nodes via `nsenter` + `get.docker.com`.

**Note:** When the Cluster Autoscaler provisions new nodes, the Docker installer runs but there may be a timing gap — pods scheduled before Docker is ready will be stuck in `Init:0/3`. The `additional_packages: [nfs-common]` in `cluster.yaml` handles NFS at cloud-init time. Docker installation via cloud-init is being evaluated.

### 9. KEDA autoscaling (backend)

KEDA scales the backend based on running agent runs, not CPU usage (LLM calls are I/O-bound). It queries PostgreSQL directly every 15 seconds:

```sql
SELECT COUNT(*) FROM agent_runs WHERE status = 'running'
```

The KEDA operator is installed separately in the `keda` namespace. The Helm chart creates:
- `ScaledObject` — defines the scaling trigger and replica bounds
- `TriggerAuthentication` — references existing `druppie-secrets` for DB credentials
- `NetworkPolicy` — allows `keda` namespace → DB pod on port 5432

```bash
# Verify KEDA
kubectl get scaledobject -n druppie
kubectl get hpa -n druppie
```

## Storage

| StorageClass | Access Mode | Use Case |
|---|---|---|
| `hcloud-volumes` | ReadWriteOnce | Databases (PostgreSQL StatefulSets), NFS backing volume |
| `nfs-workspace` | ReadWriteMany | Backend workspace, sandbox bundles — shared across all app nodes |
| `local-path` | ReadWriteOnce | Node-local scratch storage |

The NFS server sits on top of a Hetzner Cloud Volume and re-exports it as NFSv4 with `ReadWriteMany`. This is the recommended pattern for multi-node workloads on Hetzner — the same approach works on EKS (EFS) and GKE (Filestore) since both speak NFS.

## Autoscaling

Three-tier autoscaling is configured in `values-hetzner.yaml`:

| Tier | What | Tool | Trigger |
|------|------|------|---------|
| **1. Pod scaling (backend)** | 1→10 replicas | KEDA | PostgreSQL: `agent_runs WHERE status = 'running'` > 5 |
| **2. Pod scaling (frontend)** | 1→8 replicas | HPA | CPU > 70% |
| **3. Node scaling** | 1→10 VMs | Cluster Autoscaler | Pending pods (no capacity) |

- **Backend**: KEDA replaces CPU HPA when `keda.enabled: true`. Queries DB every 15s.
- **Frontend**: Standard CPU-based HPA.
- **Nodes**: Cluster Autoscaler provisions CPX32 VMs via Hetzner API (~60s). Scale-down tuned to 2m (vs default 10m).
- **Scale up**: +2 pods per 60s, new node per ~60s
- **Scale down**: -50% pods per 60s (300s stabilization), nodes after 2m unneeded

```bash
# Current approach (helm upgrade is broken — use helm template | kubectl apply)
helm template druppie helm/druppie/ -n druppie \
  -f helm/druppie/values-hetzner.yaml \
  -f helm/druppie/values-hetzner.secrets.yaml | kubectl apply -f - --namespace druppie
```

See [testing/autoscaling/](../testing/autoscaling/) for load test scripts.

## Teardown

```bash
hetzner-k3s delete cluster --config iac/cluster.yaml
```

This destroys all VMs, networks, firewalls, and load balancers created by the tool.

## Node Architecture

| Pool | Nodes | Type | Scaling | Workloads |
|------|-------|------|---------|-----------|
| masters | 3 (fixed) | CPX32 | None | Control plane only (etcd + API server) |
| infra | 1-2 (fixed) | CPX42 | Manual | Keycloak, Gitea, NFS server, MCP modules, monitoring |
| app | 1-10 (auto) | CPX32 | Cluster Autoscaler | Backend (KEDA), Frontend (HPA) |

## Cost Estimate

Based on Hetzner pricing (June 2026):

| Component | Count | Cost/mo |
|-----------|-------|---------|
| K3s servers (CPX32) | 3 | ~€39 |
| Infra agent (CPX42) | 1 | ~€24 |
| App agents (CPX32) | 1 (idle) | ~€13 |
| Block storage | 200GB | ~€10 |
| **Base total** | | **~€86/mo** |

## References

- [ADR-001: Kubernetes Migration Architecture](../docs/ADR-KUBERNETES.md)
- [Kubernetes Strategy (spike research)](../docs/KUBERNETES-STRATEGY.md)
- [hetzner-k3s documentation](https://github.com/vitobotta/hetzner-k3s)
- [K3s documentation](https://docs.k3s.io/)
