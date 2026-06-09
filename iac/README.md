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
- Hetzner Cloud Firewall, Network, and Load Balancer
- CCM, CSI driver, Cluster Autoscaler, System Upgrade Controller

### 3. Access the cluster

hetzner-k3s writes a kubeconfig to the path specified in `kubeconfig_path`:

```bash
export KUBECONFIG=./kubeconfig
kubectl get nodes
```

Expected output (5+ nodes):

```
NAME              STATUS   ROLES                       AGE   VERSION
druppie-server-1  Ready    control-plane,etcd,master   2m    v1.32.3+k3s1
druppie-server-2  Ready    control-plane,etcd,master   2m    v1.32.3+k3s1
druppie-server-3  Ready    control-plane,etcd,master   2m    v1.32.3+k3s1
druppie-infra-1   Ready    <none>                      1m    v1.32.3+k3s1
druppie-app-1     Ready    <none>                      1m    v1.32.3+k3s1
```

### 4. Verify

```bash
# Check all nodes are ready
kubectl get nodes -o wide

# Check system pods
kubectl get pods -A

# Check Cluster Autoscaler is running
kubectl get deployment cluster-autoscaler -n kube-system
```

## Teardown

```bash
hetzner-k3s delete cluster --config iac/cluster.yaml
```

This destroys all VMs, networks, firewalls, and load balancers created by the tool.

## Node Architecture

| Pool | Nodes | Type | Scaling | Workloads |
|------|-------|------|---------|-----------|
| masters | 3 (fixed) | CPX31 | None | Control plane only (etcd + API server) |
| infra | 1-2 (fixed) | CPX31 | Manual | Keycloak, Gitea, MCP, CNPG, monitoring |
| app | 1-10 (auto) | CPX31 | Cluster Autoscaler | Backend, Frontend |

## Cost Estimate

Based on Hetzner pricing (June 2026):

| Component | Count | Cost/mo |
|-----------|-------|---------|
| K3s servers (CPX31) | 3 | ~€39 |
| Infra agents (CPX31) | 1 | ~€13 |
| App agents (CPX31) | 1 (idle) | ~€13 |
| Load balancer | 1 | ~€6 |
| Block storage | 200GB | ~€10 |
| **Base total** | | **~€86/mo** |

## References

- [ADR-001: Kubernetes Migration Architecture](../docs/ADR-KUBERNETES.md)
- [Kubernetes Strategy (spike research)](../docs/KUBERNETES-STRATEGY.md)
- [hetzner-k3s documentation](https://github.com/vitobotta/hetzner-k3s)
- [K3s documentation](https://docs.k3s.io/)
