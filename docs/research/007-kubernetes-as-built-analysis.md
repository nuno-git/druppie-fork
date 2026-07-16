---
id: "007"
title: "Kubernetes As-Built Architecture Analysis"
status: complete
author: Druppie team
date: 2026-07-16
outcome: null
linked_adrs:
  - docs/adrs/002-kubernetes-migration.md
  - docs/adrs/005-dev-prod-infrastructure.md
---

# Research: Kubernetes As-Built Architecture Analysis

> **Where this fits:** This is an *analysis* document, not an option-selection
> spike. It records what was **actually deployed** (as-built, verified against a
> live cluster + Helm chart + IaC manifests) and compares it against what
> [ADR 002](../adrs/002-kubernetes-migration.md) originally planned. The
> discrepancy table in §Findings is the core value: it is the authoritative list
> of plan-vs-reality gaps that drove (and continue to drive) tech debt. The
> current production-stack decision is captured in
> [ADR 005](../adrs/005-dev-prod-infrastructure.md); this research is the
> evidence base behind it.

> **Source:** Formalized from `docs/reference/as-built-architecture.md`
> (verified against live cluster state on 2026-06-16, branch `pr-222` / PR #237).

## Question

_How does the actually-deployed Druppie Kubernetes cluster differ from the
[ADR 002](../adrs/002-kubernetes-migration.md) plan, and which of those gaps
represent tech debt that must be addressed before the cluster is considered
production-grade?_

## Background

[ADR 002](../adrs/002-kubernetes-migration.md) defined the target Kubernetes
architecture (registry, secrets, HA, autoscaling). [ADR 005](../adrs/005-dev-prod-infrastructure.md)
later locked in the dual-layer model (Docker Compose for dev, K3s on Hetzner for
prod). The production cluster was built out in PR #237, and when verified
against the live state it diverged from the plan in 15 material ways — some
intentional (cost, simplicity), some accidental (drift), and one of them a
security exposure.

This analysis matters because:

- Several gaps are **blocking for production** (Keycloak `start-dev`, plaintext
  Hetzner token in git, `:latest` tagging, no DB HA).
- The gaps are otherwise only documented in a Dutch reference file; codifying
  them as Research makes them queryable, linkable from ADRs, and tracked.
- It is the evidence base that justifies the ADR-002 decisions flagged for
  supersession in ADR 005 (pending the local-Rancher migration).

Stakeholders: platform engineering (cluster ops), security (token + RBAC), and
anyone consuming the cluster for dev/prod parity work.

## Approach

- Verified the live cluster state directly (`kubectl` against the Hetzner K3s
  cluster, K3s `v1.35.5+k3s1`).
- Read the Helm chart (`helm/druppie/`) and the IaC manifests under `iac/`
  (`cluster.yaml`, `registry/registry.yaml`, `arc-runners/`, `coredns-custom`,
  `metrics-server.yaml`).
- Read the CI/CD workflow `.github/workflows/build-and-deploy.yml` (252 lines).
- Cross-referenced each finding against the relevant section of
  [ADR 002](../adrs/002-kubernetes-migration.md) to classify it as *match*,
  *intentional divergence*, or *tech debt*.
- Source of truth: `docs/reference/as-built-architecture.md` (as-built
  documentation, verified 2026-06-16).

## Findings

### Summary

Druppie runs on a **K3s cluster on Hetzner Cloud** with 5 nodes (3 masters +
1 infra worker + 1 app worker). The full application — backend, frontend, 8 MCP
modules, layout-service, Keycloak, Gitea, 3 PostgreSQL databases — is deployed
via a single Helm chart. A **self-hosted GitHub Actions runner** (ARC with DinD)
inside the cluster builds 13 Docker images and deploys them automatically on
merge to `colab-dev`.

The deployment diverges significantly from the original ADR-002 plan at several
points. The headline differences:

| Aspect | ADR Plan | As-Built |
|--------|----------|----------|
| Container registry | Gitea Container Registry | Standalone `registry:2` with dual-path (HTTP push / HTTPS pull) |
| Secrets | Sealed Secrets | Gitignored `values-hetzner.secrets.yaml` overlay |
| Image tagging | Commit SHA (`$SHA`) | Hardcoded `:latest` |
| CNPG instances | 3 per database (HA) | 1 per database (no HA) |
| PDB + anti-affinity | Enabled | Disabled |
| CI/CD runner | Not specified | ARC self-hosted runner with cluster-admin RBAC |

### ADR-002 Plan vs As-Built: Discrepancy Table (core analytical value)

The table below is the authoritative list of plan-vs-reality gaps. "ADR Plan (§)"
refers to the section of ADR 002 where the plan was stated.

| # | Aspect | ADR Plan (§) | As-Built | Impact |
|---|--------|--------------|----------|--------|
| 1 | **Container Registry** | Gitea Container Registry (§4.8) | Standalone `registry:2` with dual-path push/pull | Gitea registry unused; extra component added |
| 2 | **Secrets Management** | Sealed Secrets (§4.6) | Gitignored `values-hetzner.secrets.yaml` | Simpler, no operator needed; secrets not in git |
| 3 | **Image Tagging** | Commit SHA (`$SHA`) | Hardcoded `:latest` | No rollback-by-tag, no audit trail of which commit is live |
| 4 | **CNPG Instances** | 3 per database (HA) (§4.3) | 1 per database | No database HA, no auto-failover; cost saving |
| 5 | **PDB + Anti-affinity** | Enabled (§4.11) | Both disabled | No protection on node drain; acceptable with 1 infra node |
| 6 | **CI/CD Runner** | Not specified (§4.9) | ARC self-hosted runner (DinD) in cluster | Runner shares resources with workloads |
| 7 | **Runner RBAC** | N/A | `cluster-admin` | Security risk — must be scoped down |
| 8 | **VM Types** | CPX31 for everything (§4.1) | CPX32 (masters+app), CPX42 (infra) | CPX31 unavailable; infra node heavier for more workloads |
| 9 | **Registry Push Path** | Not specified | Direct ClusterIP (HTTP), bypasses Traefik | Traefik 504 timeout on large blobs solved |
| 10 | **CoreDNS Rewrites** | Not specified | 2 rewrite rules for git + registry domains | Prevents DNS hairpinning in-cluster |
| 11 | **Docker Builds** | Standard `docker build` | `docker build --network=host` | Required for DinD network isolation (Microsoft packages) |
| 12 | **NFS RWX Storage** | Shared PVC via local-path (§4.10) | In-cluster NFS server pod on hcloud volume | True RWX for multi-node backend scaling |
| 13 | **Keycloak Mode** | Not specified | `start-dev` (not production `start`) | Development mode — must change for production |
| 14 | **Sync Workflow** | Not specified | `sync-main-to-colab-dev.yml` reverse-sync | `main` is "deprecated" but still has a sync mechanism |
| 15 | **Values File** | `values-prod.yaml` | `values-hetzner.yaml` | Environment-specific naming |

### Actual Cluster Topology

**K3s version:** `v1.35.5+k3s1`
**Datastore:** Embedded etcd (HA, 3 masters = quorum)
**CNI:** Flannel (K3s default)
**Provisioning:** [hetzner-k3s](https://github.com/vitobotta/hetzner-k3s) CLI, config in `iac/cluster.yaml`

| Node | Role | VM Type | vCPU | RAM | Disk | Public IP | Internal IP | Labels | Taints |
|------|------|---------|------|-----|------|-----------|-------------|--------|--------|
| `druppie-master1` | control-plane, etcd | CPX32 | 4 | 8 GB | 160 GB | 91.99.159.236 | 10.0.0.4 | — | — |
| `druppie-master2` | control-plane, etcd | CPX32 | 4 | 8 GB | 160 GB | 188.245.168.235 | 10.0.0.2 | — | — |
| `druppie-master3` | control-plane, etcd | CPX32 | 4 | 8 GB | 160 GB | 91.99.82.226 | 10.0.0.3 | — | — |
| `druppie-pool-infra-worker1` | worker (infra) | CPX42 | 8 | 16 GB | 320 GB | **167.233.67.11** | 10.0.0.5 | `pool=infra` | — |
| `druppie-app-77cb29c542f82130` | worker (app) | CPX32 | 4 | 8 GB | 160 GB | 49.13.222.218 | 10.0.0.6 | `pool=app` | — |

Key topology facts:

- **DNS:** All `*.druppie.rijnland.dev` records point to `167.233.67.11` (infra
  worker). Traefik runs on this node and routes traffic to the right services.
- **Masters run no workloads:** `schedule_workloads_on_masters: false` in
  `cluster.yaml`. The control plane is isolated.
- **App pool is autoscaled:** Cluster Autoscaler manages this pool (min 1, max
  10). CPX32 VMs are auto-provisioned for Pending pods (~60s).
- App nodes install `nfs-common` (NFS RWX) and `docker.io` (compose_up sandbox /
  module-docker) via cloud-init `additional_packages`.

### Namespace Overview

| Namespace | Purpose | Pod count |
|-----------|---------|-----------|
| `druppie` | Main app (backend, frontend, modules, DBs, Keycloak, Gitea) | 19 |
| `arc-system` | GitHub Actions self-hosted runner (ARC) | 2 |
| `registry` | Standalone Docker registry | 1 |
| `kube-system` | K3s system (CoreDNS, CSI, CCM, autoscaler, metrics-server, NFS) | 10 |
| `traefik` | Ingress controller | 1 |
| `cert-manager` | TLS certificate management | 3 |
| `cnpg-system` | CloudNativePG operator | 1 |
| `keda` | KEDA autoscaling operator | 3 |
| `monitoring` | Prometheus, Grafana, Alertmanager | 6 |
| `local-path-storage` | local-path provisioner | 1 |
| `system-upgrade` | K3s automated upgrades | 1 |

### Container Registry: Dual-Path Architecture

The registry is a **standalone `registry:2` deployment** (not Gitea, as the ADR
planned). It is reachable via **two paths** to work around Traefik timeouts on
large blob uploads:

```
PUSH PATH (runner -> registry):
  Runner DinD
    -> docker push 10.43.60.14:5000/druppie/<image>:latest
    -> HTTP (direct ClusterIP, bypasses Traefik)
    -> registry:2 pod

PULL PATH (containerd -> registry):
  Kubelet/containerd
    -> pull registry.druppie.rijnland.dev/druppie/<image>:latest
    -> HTTPS (via Traefik ingress + TLS)
    -> CoreDNS rewrite -> Traefik ClusterIP
    -> Traefik -> registry:2 pod

SYNC STEP (bridge between push and pull):
  After all builds:
    docker tag 10.43.60.14:5000/druppie/<img>:latest \
               registry.druppie.rijnland.dev/druppie/<img>:latest
    docker push registry.druppie.rijnland.dev/druppie/<img>:latest
```

**Why two paths?** Traefik returns **504 Gateway Timeout** on large blob uploads
(~4GB backend image) via the Ingress. Pushing directly to the ClusterIP (HTTP,
no Traefik) avoids timeouts. Containerd can pull via Traefik/TLS — downloads
work without issue. The runner's Docker daemon trusts the HTTP registry via a
`daemon.json` `insecure-registries: ["10.43.60.14:5000"]` entry.

Registry specs: `registry:2` in the `registry` namespace, static ClusterIP
`10.43.60.14:5000`, 50 Gi PVC on `hcloud-volumes`, no auth (internal only),
`Recreate` strategy (RWO PVC), delete enabled, ingress
`registry.druppie.rijnland.dev` (TLS via cert-manager). Catalog holds 13
repositories (backend, frontend, init, layout-service, 8 modules).

### Autoscaling (three-tier)

**Tier 1 — Backend pod scaling (KEDA).** KEDA replaces the standard CPU HPA for
the backend with two triggers:

| Trigger | Type | Threshold | Goal |
|---------|------|-----------|------|
| PostgreSQL query | `postgresql` | `targetQueryValue: 10` | Scale at >10 running `agent_runs` |
| CPU | `cpu` | `55%` utilization | Scale at high CPU load |

Live ScaledObject: `minReplicaCount: 3`, `maxReplicaCount: 8`,
`pollingInterval: 5` (poll DB every 5s), `cooldownPeriod: 120`. Scale-up is
immediate (`stabilizationWindowSeconds: 0`, +4 pods or +200% per 30s); scale-down
stabilizes over 180s at -1 pod per 120s.

> **Why two triggers:** LLM calls are I/O-bound (low CPU, high wait). The
> PostgreSQL trigger scales on the count of active agent runs; the CPU trigger
> catches read-heavy GET load.

**Tier 2 — Frontend pod scaling (HPA).** `minReplicas: 1`, `maxReplicas: 8`,
`targetCPUUtilizationPercentage: 70`. Frontend is pure static file serving, so
CPU is a reliable metric.

**Tier 3 — Node scaling (Cluster Autoscaler).** Pool `app` (CPX32), min 1 / max
10, scan interval 10s, scale-down delay 2m, max node provision time 15m. New
Hetzner VMs are provisioned via the Cloud API when pods go Pending from
capacity shortage; nodes join via cloud-init (~60s).

### Databases — CloudNativePG (backup & HA posture)

All three CNPG clusters run with **instances=1** (no HA — divergence from the
ADR plan). PostgreSQL image
`ghcr.io/cloudnative-pg/postgresql:15-standard-bookworm`.

| Cluster | Purpose | Instances | Storage | StorageClass | PG Tuning |
|---------|---------|-----------|---------|--------------|-----------|
| `druppie-druppie-db` | Main database | 1 | 20 Gi | local-path | shared_buffers=512MB, work_mem=16MB |
| `druppie-keycloak-db` | Keycloak | 1 | 5 Gi | local-path | shared_buffers=128MB |
| `druppie-gitea-db` | Gitea | 1 | 5 Gi | local-path | shared_buffers=128MB |

PgBouncer pooler (only on `druppie-db`): 2 instances, `rw`, transaction mode,
`max_client_conn: 200`, `default_pool_size: 10`,
`ghcr.io/cloudnative-pg/pgbouncer:1.25.1`.

> **Why PgBouncer:** Load testing proved that `pool_size=20` per worker × 4
> workers × 5 pods = 1000 connections vs PostgreSQL max 100 = crash. PgBouncer
> multiplexes connections in transaction mode.

Connection flow:
`Backend -> druppie-druppie-db-pooler-rw:5432 (PgBouncer) -> druppie-druppie-db-1:5432 (PostgreSQL)`.
The backend `DATABASE_URL` points at the pooler service, not directly at
PostgreSQL.

> **Backup posture:** CNPG's built-in backup/restore (barman-cloud) is **not
> configured** in the as-built. With `instances=1` and no WAL archiving, there
> is no point-in-time recovery and no automated backup; data durability rests
> entirely on the single PVC. This is a production gap (see Open Items).

### Additional Notes

- **CI/CD pipeline.** `.github/workflows/build-and-deploy.yml` (252 lines). On
  push to `colab-dev` -> `build-and-push` (full build + deploy); on PR ->
  `build-pr` (preview, backend + frontend only, tag `pr-{number}`, no deploy);
  `workflow_dispatch` supported. Build phase produces 13 images, each via
  `DOCKER_BUILDKIT=1 docker build --network=host`. A sync phase re-tags to
  `registry.druppie.rijnland.dev/...`. Deploy phase runs
  `helm upgrade druppie ./helm/druppie -n druppie --create-namespace -f
  values-hetzner.yaml -f values-hetzner.secrets.yaml --wait --timeout 10m`.
  Required GitHub secrets: `ZAI_API_KEY`, `DEEPINFRA_API_KEY`,
  `INTERNAL_API_KEY`, `GITEA_TOKEN`, `MODULE_API_TOKEN`.
- **Networking.** Four domains (all A-records to `167.233.67.11`):
  `druppie.rijnland.dev` (frontend + `/api`), `auth.druppie.rijnland.dev`
  (Keycloak), `git.druppie.rijnland.dev` (Gitea),
  `registry.druppie.rijnland.dev` (registry). TLS via cert-manager
  `letsencrypt-prod` (all certs Ready). CoreDNS custom rewrites map the git +
  registry domains to the Traefik ClusterIP to avoid DNS hairpinning. Traefik
  v3.7.4, 1 replica, `nodeSelector: pool: infra`; its `LoadBalancer` service
  shows `<pending>` EXTERNAL-IP but works via K3s ServiceLB daemonset port
  mapping on the node.
- **Storage.** Three StorageClasses: `hcloud-volumes` (default, RWO, Delete —
  registry data + NFS backing), `local-path` (RWO, Delete — CNPG DBs, Gitea,
  dataset), `nfs-workspace` (RWX, Retain — backend workspace + sandbox
  bundles). RWX is implemented as an **in-cluster NFS server pod**
  (`erichough/nfs-server:2.2.1`, privileged) backed by a 30 Gi Hetzner Cloud
  volume, exporting `/workspace` and `/sandbox-bundles` via NFSv4 to static PVs.
- **Runner RBAC.** ARC runner SA has `cluster-admin` cluster-wide — needed for
  cross-namespace `helm upgrade`, but a security risk that must be scoped to the
  `druppie` namespace.
- **Monitoring.** kube-prometheus-stack (separate Helm release). Prometheus (2
  Gi PVC), Grafana (admin via NodePort 30050), Alertmanager, Node Exporter
  DaemonSet, kube-state-metrics. Scrapes all annotated pods, CNPG (PodMonitor),
  KEDA metrics, Traefik metrics, kubelet/cAdvisor.
- **Resource usage.** Infra worker (CPX42) is the busiest node: ~6.2 Gi / 39%
  memory, running all MCP modules, Keycloak, Gitea, NFS server, 3 DBs, PgBouncer,
  Traefik, cert-manager, and the ARC runner. CPU requests 2510m (62%), limits
  12050m (301% — overcommitted). Total ~47 pods across all namespaces.
- **PR footprint.** PR #237: 102 files changed, 42,385 insertions(+),
  473 deletions(-). Key additions: `helm/druppie/values-hetzner.yaml` (198),
  `values-prod.yaml` (102), `values-local.yaml` (125), `iac/registry/registry.yaml`
  (116), `iac/arc-runners/` (3 files), `iac/coredns-custom.override` (2),
  `iac/cluster.yaml` (129), `iac/metrics-server.yaml` (203),
  `.github/workflows/build-and-deploy.yml` (252), `testing/autoscaling/` (load
  test scripts + results).

## Trade-off Analysis

Most as-built divergences are *forced* by real operational constraints rather
than chosen freely, so a weighted option comparison is less useful than a
gap-by-gap risk/effort matrix. The matrix below scores each tech-debt gap from
the discrepancy table on **severity to production** (weight: blocking > high >
medium > low) and **remediation effort** (S/M/L).

| # | Gap | Production severity | Remediation effort | Notes |
|---|-----|---------------------|--------------------|-------|
| TD-6 | `cluster.secrets.yaml` plaintext Hetzner token in git | **Blocking (High)** | M | Rotate token, purge from git history |
| TD-3 | Keycloak `start-dev` mode | **Blocking (High)** | S | Switch to `start` with proper DB init |
| TD-1 | `:latest` image tagging | High (Medium) | M | SHA-pinned tags + rollback support |
| TD-2 | Runner `cluster-admin` RBAC | High (Medium) | S | Scope SA to `druppie` namespace |
| TD-4 | CNPG instances=1 (no HA) | Medium (Low) | M | Set `instances: 3` for prod; cost ↑ |
| — | CNPG backup/PITR not configured | **Blocking (High)** | M | Enable barman-cloud WAL archiving |
| TD-5 | PDB disabled | Low | S | Re-enable; acceptable while 1 infra node |
| TD-7 | Docker daemon install timing on scaled app nodes | Low | M | Race between node join and Docker install (`Init:0/3`) |
| TD-10 | `values-hetzner.secrets.yaml` in working tree | Low | S | Confirm `.gitignore` + never committed |
| TD-9 | Traefik EXTERNAL-IP `<pending>` | Low | — | Cosmetic; works via K3s ServiceLB |
| TD-8 | Stray `node-debugger` pods in Error state | Low | S | Pre-existing; delete |

(Parenthetical severity = the level recorded in the source reference doc where
it differs from this analysis's production-readiness read.)

## Recommendation

_Treat the as-built as the current source of truth and close the
production-blocking gaps before declaring the cluster production-grade._ In
priority order:

1. **Rotate + purge the Hetzner API token** (TD-6) — the only *High*-severity
   secret exposure; do this first regardless of other work.
2. **Move Keycloak to `start` (production mode)** (TD-3) and **configure CNPG
   backup/WAL archiving** — both are data/auth durability requirements for any
   non-dev environment.
3. **Adopt SHA-pinned image tags** (TD-1) and **scope the ARC runner SA to the
   `druppie` namespace** (TD-2) — enables rollback and removes a cluster-wide
   privilege escalation path.
4. **Promote CNPG to `instances: 3`** (TD-4) and **re-enable PDBs** (TD-5) when
   the infra-tier is expanded beyond a single node.

The intentional divergences (standalone `registry:2` dual-path, gitignored
secrets overlay instead of Sealed Secrets, NFS-server-backed RWX, CoreDNS
rewrites, `--network=host` builds) should be **accepted and documented into
[ADR 005](../adrs/005-dev-prod-infrastructure.md)** rather than reverted — they
each solve a concrete operational problem the ADR did not anticipate.

## Open Items

- Confirm `values-hetzner.secrets.yaml` is in `.gitignore` and has never been
  committed (git history scan).
- Rotate the Hetzner API token and scrub it from git history.
- Define and enable a CNPG backup schedule (barman-cloud to S3-compatible
  storage) and verify a restore drill.
- Plan the Keycloak production-mode switch (`start` + proper DB init) and its
  impact on the `init` container's realm/user bootstrap.
- Decide SHA-pinned tagging format and update `build-and-deploy.yml` +
  `helm/druppie/values-hetzner.yaml` accordingly.
- Scope down the ARC runner ServiceAccount; verify `helm upgrade` still works
  with namespace-scoped RBAC (may need a Role per consumed namespace).
- Reconcile the legacy `sync-main-to-colab-dev.yml` workflow with the
  "deprecated `main`" policy (gap #14) — either remove or document why it stays.
- Track the three ADR-002 decisions flagged for supersession in ADR 005 against
  the planned local-Rancher migration.

## Resulting ADR

_This research is the analysis/evidence base behind
[ADR 005](../adrs/005-dev-prod-infrastructure.md) (current infra decision) and
informs the pending supersession of the relevant
[ADR 002](../adrs/002-kubernetes-migration.md) decisions. No new ADR was
produced directly from this document, so `outcome` remains `null`._
