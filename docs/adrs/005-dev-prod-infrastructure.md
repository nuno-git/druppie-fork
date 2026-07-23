---
id: "005"
title: Adopt dual-layer dev/prod infrastructure
status: accepted
date: 2026-06-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/005-dev-prod-infrastructure.md
linked_research: docs/research/006-kubernetes-strategy.md
---

# ADR 005: Adopt dual-layer dev/prod infrastructure

## Context

Druppie needs both a fast local development environment (hot reload, quick
feedback) and a production-grade deployment (high availability, monitoring,
TLS). The sandbox infrastructure (Docker-based, per-agent containers via
sysbox-runc) must work identically in both environments. Three Docker networks
isolate sandbox traffic:

- `sandbox-net` internal
- `sandbox-inet` internet-enabled
- `sandbox-modules` internal

Keeping the sandbox execution model the same across dev and prod is the core
constraint that drives the rest of this decision.

## Decision

Use Docker Compose as the primary development layer. Compose profiles
(`infra`, `dev`, `prod`, `init`) let developers start only what they need and
keep the local feedback loop fast.

Use K3s on Hetzner for production:

- 3 CPX32 master nodes for etcd HA
- 1 CPX42 infra node
- 1 to 10 autoscaled CPX32 app nodes

Deploy workloads via a comprehensive Helm chart. The chart ships 60+ templates
covering all modules, CNPG database clusters, PgBouncer, KEDA autoscaling, NFS
storage, Traefik ingress, and cert-manager TLS.

The sandbox uses the same Docker-socket pattern in both environments. On K8s
app nodes, a DaemonSet installs Docker so the per-agent container model behaves
exactly as it does locally.

Three ADR-002 decisions (Hetzner hosting, hetzner-k3s provisioning, Cluster
Autoscaler) are flagged for supersession pending a planned local-Rancher
migration.

## Consequences

Positive:

- dev/prod parity for sandbox execution
- fast local iteration via compose profiles
- production HA via K3s etcd quorum
- self-hosted CI via ARC runners

Negative:

- two deployment paths to maintain (compose and helm)
- helm upgrade is broken (must use `helm template | kubectl apply`)
- `:latest` image tagging instead of SHA-pinned tagging (tech debt)
- three ADR-002 decisions pending supersession for the local-Rancher migration
