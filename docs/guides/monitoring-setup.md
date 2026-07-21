# Monitoring Setup — kube-prometheus-stack

> **Decision reference:** [ADR-001 §4.7](../adrs/002-kubernetes-migration.md#47-monitoring-kube-prometheus-stack) — kube-prometheus-stack chosen as the de-facto standard for Kubernetes monitoring.

## Overview

A single Helm chart that deploys the full Prometheus ecosystem:

| Component | Purpose |
|-----------|---------|
| **Prometheus** | Metrics collection and time-series storage |
| **Grafana** | Dashboards and visualization |
| **Alertmanager** | Alert routing and notifications |
| **Node Exporter** | Host-level metrics (CPU, memory, disk, network) |
| **kube-state-metrics** | Kubernetes object metrics (pods, deployments, nodes) |

CloudNativePG, KEDA, Traefik, and Keycloak all expose native Prometheus endpoints — everything centralizes in Grafana.

## Prerequisites

- K3s cluster running (see [cluster setup](../iac/README.md))
- `kubectl` configured with cluster access
- `helm` installed

## Installation

```bash
# Add the Helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin \
  --set grafana.service.type=NodePort \
  --set grafana.service.nodePort=30050 \
  --set prometheus.prometheusSpec.retention=7d \
  --set alertmanager.enabled=false \
  --set prometheus-node-exporter.enabled=false
```

> **K3s note:** Node exporter conflicts with K3s's embedded metrics server on port 9100.
> Disable it with `--set prometheus-node-exporter.enabled=false` — K3s already exposes node metrics via its own endpoint.

This configures:
- **7-day** metric retention
- Grafana on **NodePort 30050** (accessible at `http://<node-ip>:30050`)
- Node exporter **disabled** (K3s provides equivalent metrics)
- Grafana admin password set to `admin` (change for production)

Verify all pods are running:

```bash
kubectl get pods -n monitoring
```

## Access

For single-node VM deployments, services are accessible via NodePort:

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | `http://<node-ip>:30050` | admin / admin |
| Prometheus | Port-forward only | — |

Port-forwarding for Prometheus:

```bash
# Prometheus (http://localhost:9090)
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
```

For production, expose Grafana via Traefik Ingress with TLS (cert-manager + Let's Encrypt).

## CloudNativePG Integration

When CloudNativePG is installed, enable its PodMonitor to get PostgreSQL metrics in Prometheus:

```yaml
# In the CNPG Cluster CRD:
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: druppie-db
spec:
  instances: 3
  # ...
  monitoring:
    enablePodMonitor: true
```

CNPG automatically creates a `PodMonitor` resource that Prometheus picks up. No additional configuration needed — PostgreSQL metrics appear in Grafana.

Metrics include: replication lag, connection count, transaction rate, buffer cache hit ratio, dead tuples, and more.

## Key Dashboards

Grafana ships with built-in Kubernetes dashboards. Import these for Druppie-specific monitoring:

| Dashboard | Grafana ID | What it shows |
|-----------|-----------|---------------|
| **K3s / Node Exporter Full** | `1860` | Node CPU, memory, disk, network per host |
| **Kubernetes cluster overview** | `7249` | Cluster-wide pod status, resource usage |
| **Traefik** | `11462` | Request rate, latency, error rate per ingress route |
| **CloudNativePG** | `20441` | PostgreSQL replication, connections, transactions |

To import: Grafana → Dashboards → Import → paste the ID → Load.

## Alerting

Alertmanager is included and pre-configured with default Kubernetes alert rules (node down, pod crash looping, PVC almost full, etc.).

To configure notification receivers (Slack, email, PagerDuty), create an Alertmanager config:

```bash
kubectl edit alertmanager kube-prometheus-stack-alertmanager -n monitoring
```

Receiver configuration will be added when production alerting requirements are defined.

## Uninstall

```bash
helm uninstall kube-prometheus-stack -n monitoring
kubectl delete ns monitoring
```

This removes all monitoring resources. Persistent volume claims are deleted with the namespace.
