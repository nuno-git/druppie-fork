# Monitoring Setup — kube-prometheus-stack

> **Decision reference:** [ADR-001 §4.7](ADR-KUBERNETES.md#47-monitoring-kube-prometheus-stack) — kube-prometheus-stack chosen as the de-facto standard for Kubernetes monitoring.

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
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin \
  --set prometheus.prometheusSpec.retention=15d \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=local-path \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=20Gi
```

This configures:
- **15-day** metric retention
- **20Gi** persistent volume via K3s `local-path` provisioner
- Grafana admin password set to `admin` (change for production)

Verify all pods are running:

```bash
kubectl get pods -n monitoring
```

## Access

Use port-forwarding for local access:

```bash
# Grafana (http://localhost:3000)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Prometheus (http://localhost:9090)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

# Alertmanager (http://localhost:9093)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
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
