---
id: "006"
title: "Scalable Kubernetes Strategy for Druppie"
status: complete
author: Druppie team
date: 2026-06-02
outcome: "adr-002"
---

# ADR: Scalable Kubernetes Strategy for Druppie

> **Status:** Proposal  
> **Date:** 2026-06-02  
> **Last updated:** 2026-06-09  
> **Type:** Spike / Architecture Decision Record  
> **Story:** Story 2 — Spike: scalable Kubernetes strategy (3 SP)  
> **Principle:** Everything open source, no vendor lock-in

> **Status: Historical spike (2026-06-02).** Superseded by `docs/adrs/002-kubernetes-migration.md` (decisions) and `docs/research/007-kubernetes-as-built-analysis.md` (current state). The Hetzner-specific provisioning/cost sections are kept for reference but no longer reflect the planned local-Rancher target.

---

## Strategy Overview

This document explores **13 strategy areas** for migrating from Docker Compose to production-ready Kubernetes. Each strategy addresses a specific bottleneck or risk in the current architecture.

| # | Strategy | Why | Current state | Decision |
|---|-----------|--------|---------------|------------|
| 2.1 | **Kubernetes Platform** | Which distribution for dev, staging, production | Kind (dev only) | Kind (dev) → K3s (staging/prod) |
| 2.2 | **Hosting Model** | Where the cluster runs, without vendor lock-in | Local (Docker Desktop) | Cloud VMs (commodity provider) |
| 2.3 | **Scalability** | Backend is single-replica, no autoscaling | 1 replica, hardcoded, no HPA | HPA + KEDA per service |
| 2.4 | **Database** | 3× container PostgreSQL without HA, backup, or failover | StatefulSets, no replication | CloudNativePG operator |
| 2.5 | **High Availability** | Single point of failure at every layer | No PDB, no anti-affinity | PDB + anti-affinity + graceful shutdown |
| 2.6 | **Sandbox** | Docker socket dependency does not work in K8s | `docker_manager.py` via Docker CLI | Agent Sandbox (SIG Apps) / K8s Jobs fallback |
| 2.7 | **Shared Volumes (RWX)** | Workspace PVC is ReadWriteOnce — blocks multi-node | RWO, 4 services share 1 volume | Longhorn RWX → per-session elimination |
| 2.8 | **Deployment** | No GitOps, no drift detection | Manual `helm upgrade` | Helm + CI/CD → ArgoCD |
| 2.9 | **Container Registry** | Images have to go somewhere (not `kind load`) | No registry | Gitea registry → Harbor |
| 2.10 | **Networking/Ingress** | TLS, routing, rate limiting for production | NGINX on Kind (port 9080) | Traefik (K3s default) + cert-manager |
| 2.11 | **Secrets Management** | API keys and passwords are in plaintext values | Helm values (unencrypted) | Sealed Secrets |
| 2.12 | **Monitoring** | No observability, flying blind in production | Nothing | kube-prometheus-stack |
| 2.13 | **Infrastructure Provisioning & Node Autoscaling** | HPA/KEDA scale pods, but if nodes are full = no scheduling | No node-level autoscaling | hetzner-k3s CLI + Cluster Autoscaler (upstream) |

**Section 3** describes **architecture suggestions** that go deeper than tooling choices — these are the changes needed to make Druppie truly horizontally scalable:

| # | Suggestion | Core problem |
|---|-----------|-------------|
| 3.1 | Event-driven backend | In-memory session tracking (`_active_session_tasks` dict) prevents multi-replica |
| 3.2 | MCP module mesh | 9 MCP modules as separate services + shared volume = NFS bottleneck |
| 3.3 | Database partitioning | `tool_calls`/`llm_calls` tables grow unbounded |
| 3.4 | Sandbox pool pre-warming | Cold start of 3-10s is too slow for interactive sessions |
| 3.5 | Multi-tenant scalability | No tenant isolation at the K8s level |
| 3.6 | Control plane scalability | SQLite in sandbox-control-plane = single replica |

### Future extensions (not yet covered)

The following topics are out of scope for this spike but become relevant as we grow:

| Topic | Why relevant | When |
|-----------|----------------|---------|
| **Service mesh** (Istio/Linkerd) | mTLS between services, traffic shaping, circuit breaking | Multi-tenant or compliance requirements |
| **Distributed caching** (Redis/Valkey) | Sharing session state between replicas, MCP response caching | Backend multi-replica (phase 2) |
| **Blue/green & canary deployments** | Zero-downtime releases with rollback on metrics | Production with SLA |
| **API rate limiting per tenant** | Fair use, abuse prevention | Multi-tenant |
| **Distributed tracing** (Jaeger/Tempo) | Debugging request flow across 20+ services | Production debugging |
| **Log aggregation** (Loki/ELK) | Centralized logging, correlation between services | Production operation |
| **Webhook retry & dead-letter queue** | Sandbox webhooks can fail, no retry mechanism currently | Backend reliability |
| **FinOps / cost management** | Resource right-sizing, idle detection, burst billing | Cloud production |
| **Disaster recovery automation** | Cluster rebuild, cross-region failover | Enterprise / SLA 99.9%+ |
| **Feature flags** | Gradual rollout of new agent capabilities | Team growth |

---

## 1. Context

Druppie is a governance platform for AI agents with 20+ services: a FastAPI backend, React frontend, 9 MCP microservices, Keycloak, Gitea, 3 PostgreSQL databases, and a sandbox infrastructure that dynamically spawns Docker containers. The platform currently runs on Docker Compose and has a working Helm chart for Kind (local). This spike explores how we become production-ready and scalable on Kubernetes.

### Starting points

- **100% open source** — no proprietary components, no managed cloud services as a dependency
- **No vendor lock-in** — runnable on any cloud, on-premises, or bare metal
- **Portable Helm chart** — the same chart works on Kind, K3s, Rancher, OpenShift, vanilla K8s

### Current state

| What | Status |
|-----|--------|
| Helm chart | Working for Kind, 43 K8s resources, sandbox still a placeholder |
| Kind cluster config | Single-node dev + multi-node config present |
| Docker socket dependency | 3 services (sandbox-manager, module-docker, backend) |
| Shared volumes (RWX) | `workspace` volume shared by 4 services |
| Database migrations | None — SQLAlchemy `create_all()`, reset = drop + recreate |

---

## 2. Decisions

### 2.1 Kubernetes Platform

#### Comparison matrix

| Criterion | Kind | K3s | Rancher (RKE2) | OpenShift (OKD) | Vanilla K8s (kubeadm) |
|-----------|------|-----|-----------------|-----------------|----------------------|
| **License** | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 (OKD) | Apache 2.0 |
| **Use case** | Dev/CI | Dev/Edge/Prod | Prod multi-cluster | Enterprise prod | Prod (bare metal) |
| **Installation** | 1 command | 1 command | UI or CLI | Installer (30+ min) | Manual (complex) |
| **Resource overhead** | ~300MB (in Docker) | ~512MB RAM | ~2GB RAM | ~8GB RAM minimum | ~2GB RAM |
| **Multi-node** | Yes (in Docker containers) | Yes (agent join) | Yes (UI-managed) | Yes | Yes |
| **Built-in storage** | No | Local-path provisioner | Longhorn (optional) | OpenShift Data Foundation | No |
| **Built-in ingress** | No (add NGINX) | Traefik (default) | NGINX (default) | HAProxy (Routes) | No |
| **Built-in monitoring** | No | No | Prometheus/Grafana via UI | Built-in (Prometheus) | No |
| **Helm support** | Yes | Yes | Yes | Yes (with limitations) | Yes |
| **NetworkPolicy** | Via CNI plugin | Via Flannel/Calico | Via Calico/Cilium | Via OVN-Kubernetes | Via CNI plugin |
| **Cert management** | Manual | Manual | Via Rancher UI | Built-in | Manual |
| **RBAC** | Kubernetes native | Kubernetes native | Rancher RBAC + K8s | OpenShift RBAC (stricter) | Kubernetes native |
| **Updates** | Recreate cluster | `k3s upgrade` | Rancher UI | `oc adm upgrade` | `kubeadm upgrade` |
| **Community** | Kubernetes SIG | CNCF Sandbox (Rancher Labs) | SUSE/Rancher | Red Hat + community | Kubernetes upstream |
| **Production-ready** | No | Yes (CNCF certified) | Yes | Yes | Yes (but a lot of work) |
| **Learning curve** | Low | Low | Medium | High | High |

#### Notes per platform

**Kind (Kubernetes in Docker)**

Kind runs a full Kubernetes cluster as Docker containers on your local machine. It is designed for testing Kubernetes itself and is therefore perfect for CI/CD and local development. Kind is not a production solution: it has no persistent storage, no HA, and no cluster lifecycle management. We already use it (`kind/cluster-dev.yaml`) and it works well.

- **Strength:** Fastest setup (~30 sec), zero configuration, perfect CI match
- **Weakness:** No persistent storage classes, no multi-node HA, not for production
- **When:** Development, CI pipelines, Helm chart validation

**K3s**

K3s is a lightweight, CNCF-certified Kubernetes distribution built by Rancher Labs (now SUSE). It is a single binary of ~70MB that contains everything: API server, scheduler, controller, etcd (replaced by SQLite for single-node or embedded etcd for HA), containerd, and Flannel CNI. K3s runs on anything: bare metal, VMs, Raspberry Pis, edge devices, cloud VMs.

K3s is **not** a stripped-down Kubernetes — it is full Kubernetes with the same API, the same conformance tests, and the same Helm charts. The difference is in the packaging: everything in one binary, automatic TLS bootstrapping, and out-of-the-box Traefik ingress + CoreDNS + local-path storage.

- **Strength:** Lightweight, fast, CNCF certified, runs everywhere, easy HA (3 server nodes)
- **Weakness:** Less ecosystem tooling than RKE2/kubeadm, Traefik instead of NGINX (configurable)
- **When:** Production for small/medium teams, edge deployments, budget-conscious

**Rancher / RKE2**

Rancher is an open source multi-cluster management platform. RKE2 is the underlying Kubernetes distribution (successor to RKE1), also called "RKE Government" because of its focus on security and FIPS compliance. Rancher offers a web UI for cluster lifecycle management, monitoring, logging, and RBAC.

The difference from K3s: Rancher/RKE2 is intended for teams that manage multiple clusters, need enterprise-grade security, or want a graphical management interface. RKE2 uses containerd (not Docker), has CIS hardening out-of-the-box, and runs with NGINX ingress by default.

Rancher can also manage external clusters (EKS, AKS, GKE, or existing K3s/kubeadm clusters).

- **Strength:** Multi-cluster UI, built-in monitoring/alerting, CIS hardened, Longhorn integration
- **Weakness:** More resources, more complex than K3s, SUSE commercial support ≠ community
- **When:** Multiple clusters, team of >5 people, enterprise compliance requirements

**OKD (OpenShift Community)**

OKD is the open source upstream of Red Hat OpenShift. It builds on Kubernetes but adds significant functionality: built-in CI/CD (Tekton), image registry, developer console, source-to-image builds, a stricter security model (SecurityContextConstraints instead of PodSecurityPolicies), and operator lifecycle management.

OpenShift/OKD deviates from standard Kubernetes on important points:
- Uses Routes instead of Ingress (Ingress is translated to Routes)
- Runs containers as non-root with a random UID by default
- Has its own CLI (`oc` alongside `kubectl`)
- Requires modifications to Dockerfiles (no `USER root`)

This means our Helm chart and Dockerfiles need modifications for OKD compatibility. Specifically: the backend Dockerfile installs packages as root and the sandbox containers run with specific UIDs.

- **Strength:** Most complete enterprise platform, everything built in, strict security
- **Weakness:** Heavy resource footprint (~8GB+), divergent standards, Dockerfile modifications needed, steep learning curve
- **When:** Enterprise environments with a Red Hat ecosystem, strict compliance

**Vanilla Kubernetes (kubeadm)**

Upstream Kubernetes installed via `kubeadm`. You get exactly what the Kubernetes project delivers, nothing more. You have to add everything yourself: CNI plugin (Calico/Cilium/Flannel), ingress controller, storage provisioner, monitoring, cert management.

- **Strength:** Maximum control, always up-to-date with upstream, no vendor-specifics
- **Weakness:** Most operational work, configure everything yourself, cluster upgrades are complex
- **When:** Teams with deep K8s expertise who want maximum control

#### Decision

| Environment | Platform | Reason |
|----------|----------|-------|
| **Development** | Kind | Already set up, fastest feedback loop, free |
| **CI/CD** | Kind | Ephemeral clusters in the pipeline, no state needed |
| **Staging** | K3s (single-node or 3-node HA) | Lightweight, production-equivalent, cheap |
| **Production** | K3s (3-node HA) or RKE2 | Open source, CNCF certified, runs everywhere |

K3s is the primary choice for staging and production because of the combination of lightweight, CNCF conformance, and operational simplicity. As we grow toward multiple clusters or enterprise requirements: upgrade to Rancher/RKE2 (same foundation, more management tooling).

OpenShift/OKD is an option if the team lives in a Red Hat ecosystem, but the Dockerfile modifications and divergent standards make it a bigger investment.

---

### 2.2 Hosting Model

#### Comparison matrix

| Criterion | Bare metal | Cloud VMs (self-managed K3s) | On-premises VMs | Hybrid |
|-----------|------------|------------------------------|-----------------|--------|
| **Vendor lock-in** | None | Minimal (VM = commodity) | None | Minimal |
| **Cost** | Hardware CAPEX | ~€100-300/mo (3 VMs) | Hardware CAPEX | Variable |
| **Scalability** | Physically bounded | Minutes (add a VM) | Physically bounded | Flexible |
| **Control** | Maximum | High | Maximum | Medium |
| **Operational** | Everything yourself | OS + K3s yourself, hardware managed | Everything yourself | Shared |
| **Data residency** | Full | Cloud provider dependent | Full | Shared |
| **Open source** | Yes | Yes (K3s on any VM) | Yes | Yes |

#### Notes

The hosting model is independent of the Kubernetes distribution. K3s runs on any Linux machine — whether that is a €5/month Hetzner VPS, a dedicated server, an on-premises VM, or a Raspberry Pi.

**Cloud VMs (recommended start):**
- Rent 3 VMs from a commodity provider (Hetzner, OVH, Scaleway, DigitalOcean, or yes, also Azure/AWS/GCP as VMs)
- Install K3s: `curl -sfL https://get.k3s.io | sh -` on the first node, join the rest
- No cloud-specific services needed — everything runs in K3s
- Moving to another provider = new VMs + K3s install + `helm install`

**On-premises:**
- Relevant if there are data-residency requirements or existing hardware is available
- Exactly the same K3s setup, only on your own machines

**Decision: Start with cloud VMs (commodity provider), K3s installation. Movable to any provider or on-prem without lock-in.**

---

### 2.3 Scalability

#### 2.3.1 Service classification

| Service | Type | Replicas (min) | Scaling strategy | Notes |
|---------|------|----------------|-------------------|-------------|
| Frontend | Stateless | 2 | HPA on CPU (target 70%) | Pure SPA, only serves static files. Scales trivially. |
| Backend | Semi-stateless* | 2 | HPA on CPU + custom metric | Heaviest service. Request handling is stateless, but async webhook callbacks make multi-replica complex. |
| MCP modules (9x) | Stateless | 1-2 | HPA on CPU per module | Each module independently scalable. Coding and Docker are heavier than registry/llm. |
| Keycloak | Stateless (state in DB) | 2 | HPA, min 2 for HA | Java app, 768MB per replica. Active JWT sessions survive downtime. |
| Gitea | Stateful | 1 | No HPA (single writer) | Git bare repos on disk. Multi-replica requires distributed storage (not trivial). |
| PostgreSQL (3x) | Stateful | 3 (via CNPG) | CloudNativePG operator | 1 primary + 2 read replicas. Operator manages failover. |
| Sandbox Control Plane | Stateful (SQLite) | 1 | None — single replica | SQLite cannot be shared. Migration to PostgreSQL needed for multi-replica. |
| Sandbox Manager | Stateless | 1 | None — K8s API is the bottleneck | Thin orchestrator that creates K8s Jobs. |

*Backend semi-stateless: `asyncio.create_task()` for fire-and-forget webhook callbacks. With multiple replicas, a webhook can land on a different replica than where the agent session is active. Solution in §2.5.

#### 2.3.2 HPA (Horizontal Pod Autoscaler)

HPA scales the number of pods horizontally based on metrics. Each stateless service gets its own HPA.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: druppie-backend
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: druppie-backend
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60    # Wait 60s before further scale-up
      policies:
        - type: Pods
          value: 2                       # Add at most 2 pods at a time
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300    # Wait 5 min before scale-down (prevent oscillation)
```

The `behavior` section is crucial for AI workloads: without a stabilization window, HPA responds to every short spike, causing pods to constantly scale up and down (oscillation).

#### 2.3.3 VPA (Vertical Pod Autoscaler)

VPA adjusts resource requests/limits per pod (more CPU/RAM per pod instead of more pods). We use VPA **only in recommendation mode** — it gives advice but adjusts nothing automatically. Reason: VPA in auto-mode restarts pods to apply new limits, which is unacceptable for long-running agent sessions.

Workflow: VPA runs alongside, we periodically read out the recommendations, and adjust `values.yaml` manually.

```bash
kubectl get vpa druppie-backend -o jsonpath='{.status.recommendation}'
```

#### 2.3.4 KEDA for bursty LLM workloads

Druppie's LLM calls are I/O-bound (waiting for an external API response), not CPU-bound. CPU-based HPA therefore responds too late to load spikes — the pods are waiting on the network, not on CPU.

**KEDA** (Kubernetes Event-Driven Autoscaling, CNCF Graduated, open source) solves this by scaling on application-specific metrics instead of only CPU/memory.

| Approach | Metric | Reactivity | Complexity |
|--------|--------|-------------|--------------|
| HPA on CPU | `cpu.utilization` | Slow (I/O-bound = low CPU) | Low |
| HPA on custom metric | `druppie_active_sessions` | Medium | Medium |
| **KEDA on queue depth** | `druppie_pending_agent_runs` (DB query via Prometheus) | **Fast** | Medium |
| KEDA scale-to-zero | Same + `minReplicaCount: 0` | Fast | Medium |

KEDA is open source (Apache 2.0), runs as an operator in the cluster, and works with any Kubernetes distribution. It supports 60+ event sources including Prometheus, PostgreSQL, Redis, and HTTP endpoints.

Concrete application for Druppie:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: druppie-backend
spec:
  scaleTargetRef:
    name: druppie-backend
  minReplicaCount: 2
  maxReplicaCount: 10
  cooldownPeriod: 360            # Only for scale-to-zero
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: druppie_pending_agent_runs
        query: sum(druppie_pending_agent_runs)
        threshold: "5"           # Scale up when >5 pending runs
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
            - type: Percent
              value: 50          # Scale down at most 50% at a time
              periodSeconds: 60
```

Important detail: KEDA's `cooldownPeriod` applies **only** to scale-to-zero (from 0 to 1 replica). For 1-to-N scaling, KEDA uses the Kubernetes HPA directly, including the `behavior` settings above. [[source](https://docs.vllm.ai/projects/production-stack/en/latest/use_cases/autoscaling-keda.html)]

**Phasing:** Phase 1 starts with HPA on CPU (simple, works). Phase 2 adds KEDA for more precise scaling based on actual workload.

---

### 2.4 Database Strategy

#### Comparison matrix

| Criterion | Container PG (current) | CloudNativePG | CrunchyData PGO | Zalando PG Operator | Managed DB (cloud) |
|-----------|----------------------|---------------|------------------|---------------------|-------------------|
| **License** | PostgreSQL License | Apache 2.0 | Apache 2.0 | MIT | Proprietary |
| **CNCF status** | n/a | Sandbox | None | None | n/a |
| **HA (auto-failover)** | No | Yes (<30s) | Yes | Yes | Yes |
| **Streaming replication** | No | Yes (sync + async) | Yes (pgBouncer) | Yes (Patroni) | Yes |
| **Continuous backup** | No | Barman (S3/MinIO/GCS) | pgBackRest (S3/MinIO) | WAL-G (S3/MinIO) | Automatic |
| **Point-in-time recovery** | No | Yes | Yes | Yes | Yes |
| **Rolling updates** | No (downtime) | Yes (zero-downtime) | Yes | Yes | Automatic |
| **Monitoring** | Manual | PodMonitor + Grafana | pgMonitor | None standard | Cloud dashboard |
| **Connection pooling** | No | PgBouncer (built-in) | PgBouncer (built-in) | None standard | Depends |
| **Operational effort** | Low (dev only) | Medium | High | Medium | Low |
| **CRD count** | 0 | 6 | 19 | 9 | 0 |
| **Vendor lock-in** | No | No | No | No | **Yes** |
| **Maturity** | n/a | GA (v1.29+) | GA (v5.7+) | GA (v1.12+) | n/a |
| **Maintainer** | n/a | EnterpriseDB + community | Crunchy Data | Zalando | Cloud provider |

#### Notes per option

**CloudNativePG (recommended)**

CloudNativePG is the most Kubernetes-native PostgreSQL operator. "Kubernetes-native" here means: it is designed to manage PostgreSQL as a Kubernetes-native resource via CRDs, not as a wrapper around existing tools. It is the only PostgreSQL project with CNCF Sandbox status.

What it does:
- Manages the full PostgreSQL lifecycle: provisioning, replication, failover, backup, restore, upgrades
- 1 primary + N read replicas with streaming replication
- Automatic failover on primary failure (<30s)
- Continuous backup to S3-compatible object storage (MinIO, Ceph, or cloud S3)
- Point-in-time recovery: restore the database to any moment in time
- Zero-downtime rolling updates for minor PostgreSQL versions
- Built-in PgBouncer connection pooling
- Prometheus metrics export with PodMonitor

A single CloudNativePG operator manages all 3 Druppie databases (app, keycloak, gitea) as separate Cluster CRDs.

**Important: Security advisory (May 2026):**
CloudNativePG v1.29.1 (8 May 2026) fixes **CVE-2026-44477** (CVSS v4: 9.4, Critical) — superuser privilege escalation + arbitrary OS command execution via the metrics exporter. The same release also fixes three independent HA failover bugs. **Always use v1.29.1+.** [[source](https://cloudnative-pg.io/releases/cloudnative-pg-1-29.1-released/)]

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: druppie-db
spec:
  instances: 3
  postgresql:
    parameters:
      shared_buffers: "256MB"
      max_connections: "200"
  storage:
    size: 20Gi
    storageClass: longhorn        # or local-path, or any CSI driver
  backup:
    barmanObjectStore:
      destinationPath: "s3://druppie-backups/db"
      endpointURL: "http://minio:9000"   # MinIO for on-prem S3
      s3Credentials:
        accessKeyId:
          name: minio-creds
          key: access-key
        secretAccessKey:
          name: minio-creds
          key: secret-key
    retentionPolicy: "30d"
  monitoring:
    enablePodMonitor: true
```

**CrunchyData PGO**

Crunchy Postgres Operator is older and more feature-rich than CloudNativePG, but also more complex. It uses 19 CRDs (vs 6 for CNPG) and has pgBackRest as its backup tool (powerful but more complex to configure). PGO has no CNCF status but is well maintained by Crunchy Data.

When to consider PGO: if you already have experience with pgBackRest, or need specific features that CNPG does not (yet) offer (e.g., pgBouncer connection pooling tuning, multi-cluster replication).

**Zalando PostgreSQL Operator**

The Zalando operator (Patroni-based) was one of the first PG operators and is used internally at Zalando for 1000+ databases. It is less actively maintained than CNPG and PGO, and has no built-in backup solution (WAL-G must be configured separately).

**Decision: CloudNativePG for all environments.**

Reason: CNCF status, lowest operational effort of the operators, active community, complete feature set for Druppie's needs. Container PostgreSQL remains available in the Helm chart for development.

---

### 2.5 High Availability

#### What does HA concretely mean for Druppie?

| Component | What happens during downtime? | Impact | Minimum HA |
|-----------|------------------------------|--------|-------------|
| **PostgreSQL** | All API calls fail, agents stop, UI shows errors | **Critical** | 3 replicas (CNPG auto-failover) |
| **Backend** | No chat, no agent execution, webhooks fail | **High** | 2+ replicas + PDB |
| **Keycloak** | New logins fail. Existing sessions keep working (JWT is self-contained) | Medium | 2 replicas |
| **Frontend** | Users see 502/503 | Medium | 2 replicas |
| **Gitea** | Git operations fail, agent code pushes halted | Medium | 1 replica + PVC + backup |
| **MCP modules** | Specific agent tools unavailable (e.g., no file ops without module-coding) | Low-Medium | 1-2 replicas per module |
| **Sandbox control plane** | New sandbox tasks fail, running sandboxes keep going | Medium | 1 replica (SQLite limitation) |

#### HA instruments

**PodDisruptionBudget (PDB):** Guarantees that Kubernetes never removes all pods at once during maintenance (node drain, rolling update).

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: druppie-backend-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: druppie-backend
```

**Pod Anti-Affinity:** Spreads pods across different nodes so that a node failure does not affect all replicas.

```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app: druppie-backend
          topologyKey: kubernetes.io/hostname
```

**Graceful shutdown:** Backend pods must finish running LLM calls before they stop. Configure `terminationGracePeriodSeconds: 60` and implement SIGTERM handling in the FastAPI app that refuses new requests but finishes active ones.

#### Backend multi-replica challenge

The backend uses `asyncio.create_task()` for fire-and-forget webhook callbacks from sandboxes. With multiple replicas, a webhook can land on a different replica than where the agent session is active in memory.

| Solution | Complexity | Robustness | Extra infra |
|-----------|------------|-------------|-------------|
| Sticky sessions (Ingress) | Low | Fragile (pod restart = session lost) | None |
| Redis task queue | Medium | Robust | Redis |
| **Database-driven resume** | Medium | **Very robust** | None |

**Recommendation: Database-driven resume.** The current `reconstruct_from_db()` function in `druppie/agents/message_history.py` already rebuilds agent state from the database. The webhook handler only needs to update the ToolCall record in the DB — any backend replica can then pick up the agent and continue. This fits the existing pattern and requires no new infrastructure.

---

### 2.6 Sandbox Strategy in Kubernetes

This is the **most complex challenge**. The sandbox-manager spawns Docker containers via the Docker socket, which does not work natively in Kubernetes.

#### Comparison matrix

| Criterion | Docker socket mount | DinD sidecar | K8s Jobs (manual) | agent-sandbox (SIG Apps) | Kata Containers | gVisor | Sysbox |
|-----------|--------------------|--------------|--------------------|--------------------------|-----------------|--------|--------|
| **License** | n/a | Apache 2.0 | n/a (K8s native) | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **Security** | Poor (root on host) | Fair | Good | Good-Very good | Very good (VM isolation) | Good (user-space kernel) | Good (user namespaces) |
| **Isolation level** | None (host Docker) | Container-in-container | Pod-level | Pod + runtime | **VM-level (guest kernel)** | Kernel-level (syscall filter) | Kernel-level (user NS) |
| **Cold start** | ~1-2s | ~3-5s | ~3-5s (pod scheduling) | <1s (WarmPool) | ~150-600ms | ~50-100ms | ~1-2s |
| **Memory overhead** | 0 | ~100MB | 0 | ~20-50MB (WarmPool) | ~60-120MB per pod | ~20-50MB per pod | ~50MB |
| **K8s native** | No | No | Yes | **Yes (CRD-based)** | Yes (RuntimeClass) | Yes (RuntimeClass) | No (CRI-O only) |
| **Warm pool support** | No | No | Build it yourself | **Yes (SandboxWarmPool CRD)** | No | No | No |
| **Python SDK** | Docker SDK | Docker SDK | kubernetes client | **Yes** | No | No | No |
| **Maturity** | n/a | Stable | Stable | **v1alpha1 (v0.4.6)** | Stable (3.x) | Stable | Community-maintained |
| **Production proven** | Everywhere | A lot | A lot | Early stage | Northflank (2M+ microVMs/mo) | Google (GKE Sandbox) | Limited |
| **Operational pages** | n/a | Unknown | Low | Unknown | 3.4x vs standard | Low | Unknown |

#### Agent Sandbox (kubernetes-sigs/agent-sandbox) — primary choice

The Kubernetes SIG Apps project **Agent Sandbox** was launched in November 2025 by Google at KubeCon Atlanta. It offers exactly what Druppie needs: a CRD-based operator for spawning isolated sandbox environments for AI agents. [[source](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)]

The official Kubernetes blog describes the problem: *"While you could theoretically approximate this by stringing together a StatefulSet of size 1, a headless Service, and a PersistentVolumeClaim for every single agent, managing this at scale becomes an operational nightmare."*

What Agent Sandbox offers:
- **Sandbox CRD:** Creates an isolated pod with a configurable runtime (gVisor, Kata, or standard)
- **SandboxTemplate:** Reusable sandbox definitions (resources, security context, volumes)
- **SandboxClaim:** Request-based model — agents claim a sandbox from a pool
- **SandboxWarmPool:** Pre-warmed pods that stand ready, making cold start < 1 second
- **Python SDK:** Direct integration with our Python sandbox-manager
- **Lifecycle management:** Automatic cleanup, TTL, resource tracking

```yaml
apiVersion: sandbox.k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: druppie-coding-sandbox
spec:
  runtimeClassName: gvisor
  resources:
    limits:
      memory: "4Gi"
      cpu: "2"
  securityContext:
    runAsUser: 1000
    runAsNonRoot: true
    allowPrivilegeEscalation: false
---
apiVersion: sandbox.k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: druppie-warm-sandboxes
spec:
  templateRef: druppie-coding-sandbox
  minReady: 2
  maxSize: 10
```

**Risk:** The v1alpha1 API may change before GA. Mitigation: fall back on K8s Jobs (see below).

#### Fallback: Kubernetes Jobs

If Agent Sandbox proves too immature, the fallback is to replace `docker_manager.py` with a `k8s_manager.py` that creates Kubernetes Jobs via the `kubernetes` Python client:

| Docker flag (current) | Kubernetes equivalent |
|---------------------|----------------------|
| `--memory=4g` | `resources.limits.memory: 4Gi` |
| `--cpus=2` | `resources.limits.cpu: "2"` |
| `--cap-drop=ALL --cap-add=NET_RAW` | `securityContext.capabilities` |
| `--security-opt=no-new-privileges` | `securityContext.allowPrivilegeEscalation: false` |
| `--network=sandbox-network` | NetworkPolicy (dedicated namespace) |
| `--pids-limit=4096` | RuntimeClass or cgroup configuration |

#### Runtime isolation: gVisor vs Kata Containers

Both are open source runtimes that run as a `RuntimeClass` in Kubernetes. Agent Sandbox supports both.

| Criterion | gVisor (runsc) | Kata Containers (3.x) |
|-----------|----------------|----------------------|
| **How it works** | User-space kernel that filters and translates syscalls. The container shares no kernel with the host. | Each container runs in its own lightweight VM with a dedicated guest kernel. |
| **Isolation** | Strong — 370+ syscalls implemented in Go, unknown syscalls blocked | Very strong — hardware virtualization (AMD-V/VT-x), full kernel isolation |
| **Cold start** | ~50-100ms | ~150-600ms |
| **Memory overhead** | ~20-50MB per pod | ~60-120MB per pod |
| **Performance impact** | Low for I/O, higher for syscall-heavy workloads | 8-12% steady-state overhead |
| **Compatibility** | Most Linux programs work, some syscalls missing | Nearly 100% Linux compatibility (full kernel) |
| **Operational** | Simpler (no VM management) | More complex, 3.4x more on-call pages than standard containers |
| **Production** | Google GKE Sandbox (millions of containers) | Northflank (2M+ microVMs/month) |
| **Suitable for Druppie** | **Yes** — code execution + git push = I/O bound, not syscall-heavy | Yes, but overkill for the current use case |

**Recommendation: Start with gVisor.** Lower overhead, simpler operationally, sufficient isolation for code execution sandboxes. Upgrade to Kata if multi-tenant isolation requirements arise (e.g., sandboxes from different organizations on the same nodes).

**Sysbox — not recommended:**
- Officially only CRI-O support; containerd integration "still evolving" (nestybox/sysbox#997)
- Community-maintained on a best-effort basis after Nestybox's acquisition by Docker
- Shares the host kernel — weaker isolation than gVisor and Kata

#### Codebase changes

1. `sandbox-manager`: Replace `docker_manager.py` with `k8s_manager.py` (Kubernetes Python client or Agent Sandbox SDK)
2. NetworkPolicy: dedicated `druppie-sandboxes` namespace, only communication with the control-plane
3. Container registry: sandbox image via registry (Harbor, see §2.9) instead of `kind load`
4. Resource limits: Configurable via Helm values (already prepared in `values.yaml` as `sandbox.memoryLimit`/`sandbox.cpuLimit`)

---

### 2.7 Shared Volume Strategy (RWX)

The `workspace` volume is shared by 4 services: backend, module-coding, module-docker, module-data-access. This requires ReadWriteMany (RWX) — multiple pods writing to the same volume.

#### Comparison matrix

| Criterion | NFS server (manual) | Longhorn | Rook-Ceph | OpenEBS (Mayastor) | SeaweedFS |
|-----------|----------------------|----------|-----------|-------------------|-----------|
| **License** | GPL (NFS kernel) | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **CNCF status** | n/a | CNCF Sandbox | CNCF Graduated | CNCF Sandbox | None |
| **RWX support** | Yes (native) | Yes (via NFS export) | Yes (CephFS) | No (RWO only) | Yes (FUSE mount) |
| **Performance** | Medium (network I/O) | Medium | Good | Very good (NVMe) | Medium |
| **Replication** | No (single point of failure) | Yes (2-3 replicas) | Yes (configurable) | Yes (sync) | Yes |
| **Operational effort** | Low | **Low** (Rancher UI) | High | Medium | Medium |
| **Disk overhead** | 0% | 2-3x (replica factor) | 2-3x (replica factor) | 2-3x | 1-3x |
| **Minimum nodes** | 1 | 3 (for replication) | 3 | 3 | 3 |
| **Suitable for Druppie** | Yes (dev/staging) | **Yes** | Yes (but overkill) | No (no RWX) | Yes |

#### Notes

**Longhorn (recommended)**

Longhorn is a CNCF Sandbox distributed block storage system, built by Rancher Labs. It offers replicated block storage with snapshots, backups, and disaster recovery. RWX support works via a built-in NFS server per volume.

Why Longhorn for Druppie:
- Lightweight: designed for edge and small clusters (fits with K3s)
- RWX via NFS: each RWX PVC automatically gets an NFS share-manager pod
- Simple installation: `helm install longhorn longhorn/longhorn`
- UI dashboard for volume management
- Backup to S3-compatible storage (MinIO)
- Integrates seamlessly with K3s and Rancher

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: druppie-workspace
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: longhorn
  resources:
    requests:
      storage: 50Gi
```

**Rook-Ceph** is more powerful (object + block + file storage) but requires more resources (3+ dedicated storage nodes, more RAM) and is more complex to manage. Overkill for Druppie's workspace volume.

**NFS server** (a simple pod with an NFS export) works for dev/staging but is a single point of failure without replication.

**Phase 2 goal — per-session workspace elimination:**

The architecturally better solution is to eliminate the shared workspace volume entirely:
- Each agent session gets its own `emptyDir` or ephemeral PVC
- MCP modules communicate via the backend as a proxy (no direct volume access)
- This eliminates the RWX dependency entirely and improves isolation

---

### 2.8 Deployment Strategy

#### Comparison matrix

| Criterion | Helm + CI/CD | ArgoCD | FluxCD |
|-----------|-------------|--------|--------|
| **License** | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **CNCF status** | CNCF Graduated (Helm) | CNCF Graduated | CNCF Graduated |
| **Model** | Push-based (CI pushes to cluster) | Pull-based (cluster pulls from git) | Pull-based |
| **GitOps** | No (git = source, not state) | **Yes** (git = desired state) | **Yes** |
| **Drift detection** | No | **Yes** (auto-detect config drift) | **Yes** |
| **Rollback** | `helm rollback` (manual) | Git revert = auto rollback | Git revert = auto rollback |
| **Multi-env** | Helm values per env | ApplicationSet | Kustomize overlays |
| **UI** | None | **Web dashboard** | None (CLI only) |
| **Helm support** | Native | Yes (Helm chart rendering) | Yes (HelmRelease CRD) |
| **Learning curve** | Low | Medium | Medium |
| **Extra infra** | None | ArgoCD server in cluster | Flux controllers in cluster |
| **Notifications** | Via CI (GitHub Actions) | Slack/webhook integration | Slack/webhook integration |

#### Notes

**Phase 1: Helm + CI/CD (GitHub Actions)**

The Helm chart already exists and works on Kind. The fastest path to production is a CI/CD pipeline that:
1. Builds Docker images and pushes them to a container registry
2. Runs `helm upgrade` on the K3s cluster

```yaml
# .github/workflows/deploy.yml
- name: Deploy to K3s
  run: |
    helm upgrade druppie helm/druppie/ \
      --namespace druppie \
      --values helm/druppie/values-prod.yaml \
      --set global.imageRegistry=$REGISTRY/ \
      --set secrets.zaiApiKey=${{ secrets.ZAI_API_KEY }} \
      --wait --timeout 600s
```

Push-based deployment is simple and works, but has drawbacks: if someone manually changes something in the cluster (kubectl edit), no one detects that drift.

**Phase 2: ArgoCD**

ArgoCD makes the cluster declarative: the git repository is the single source of truth. ArgoCD continuously compares the desired state (git) with the actual state (cluster) and reconciles automatically.

Add ArgoCD when:
- There are multiple environments (dev/staging/prod) — ApplicationSet makes this trivial
- The team grows and there is a need for an audit trail (who deployed what when)
- Drift detection is needed (preventing manual cluster changes from going unnoticed)

ArgoCD vs FluxCD: ArgoCD has a web dashboard (handy for teams), FluxCD is more CLI-driven. Both are CNCF Graduated. ArgoCD is more popular (16k+ GitHub stars) and has better Helm support.

---

### 2.9 Container Registry

#### Comparison matrix

| Criterion | Harbor | Gitea Container Registry | Docker Distribution | Zot | GitHub GHCR |
|-----------|--------|--------------------------|--------------------|----|-------------|
| **License** | Apache 2.0 | MIT | Apache 2.0 | Apache 2.0 | Proprietary |
| **CNCF status** | CNCF Graduated | None | None | None | n/a |
| **Vulnerability scanning** | Yes (Trivy built-in) | No | No | Yes (Trivy) | Yes |
| **Image signing** | Yes (Cosign/Notary) | No | No | Yes (Cosign) | Yes |
| **RBAC** | Yes (project-based) | Via Gitea users | No | Yes | Via GitHub |
| **Replication** | Yes (multi-registry) | No | No | No | n/a |
| **Garbage collection** | Yes | Yes | Yes | Yes | Automatic |
| **Self-hosted** | Yes | Yes (already in Druppie!) | Yes | Yes | No |
| **Helm chart storage** | Yes (OCI) | Yes (OCI) | No | Yes (OCI) | Yes |
| **Operational effort** | Medium | **Low (already running)** | Low | Low | None |

**Decision: Gitea Container Registry for phase 1, Harbor for phase 2.**

Gitea (which already runs in Druppie) has a built-in OCI-compatible container registry. This means zero extra infrastructure — we push images to the same Gitea instance that already hosts our git repos.

Add Harbor when vulnerability scanning, image signing, or multi-registry replication is needed.

---

### 2.10 Networking / Ingress

#### Comparison matrix

| Criterion | NGINX Ingress | Traefik | HAProxy Ingress | Cilium Ingress |
|-----------|--------------|---------|-----------------|----------------|
| **License** | Apache 2.0 | MIT | Apache 2.0 | Apache 2.0 |
| **CNCF status** | None (K8s SIG) | None | None | CNCF Graduated |
| **Protocol** | HTTP/HTTPS/gRPC/WebSocket | HTTP/HTTPS/gRPC/TCP/UDP | HTTP/HTTPS/TCP | HTTP/HTTPS/gRPC |
| **Auto-discovery** | Via Ingress resources | Via Ingress + IngressRoute CRD | Via Ingress | Via Ingress + Gateway API |
| **TLS termination** | Yes (cert-manager) | Yes (built-in ACME + cert-manager) | Yes | Yes |
| **Rate limiting** | Via annotations | Via middleware CRD | Via config | Via CiliumNetworkPolicy |
| **WAF** | ModSecurity plugin | No (separate) | No | No |
| **Observability** | Prometheus metrics | Prometheus + Datadog + Jaeger | Prometheus | Hubble (eBPF) |
| **K3s default** | No | **Yes** | No | No |
| **Performance** | Good | Good | Very good | Very good (eBPF) |
| **Configuration** | Annotations (can get messy) | Middleware CRDs (structured) | Config file | Gateway API (standard K8s) |
| **Learning curve** | Low | Low-Medium | Medium | Medium-High |

**Decision: Traefik (K3s default), with NGINX as an alternative.**

K3s installs Traefik as the default ingress controller. Our Helm chart currently uses NGINX (for Kind), but Traefik offers advantages:
- Built-in ACME/Let's Encrypt support (no separate cert-manager needed, though cert-manager also works)
- Middleware CRDs for rate limiting, headers, auth — cleaner than NGINX annotations
- Dashboard for real-time traffic monitoring
- IngressRoute CRD for more complex routing rules

The Helm chart must support both via `global.ingress.className: traefik | nginx`.

```yaml
# Traefik IngressRoute (alternative to a standard Ingress)
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: druppie
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`druppie.example.com`) && PathPrefix(`/api`)
      kind: Rule
      services:
        - name: druppie-backend
          port: 8000
    - match: Host(`druppie.example.com`)
      kind: Rule
      services:
        - name: druppie-frontend
          port: 5173
  tls:
    certResolver: letsencrypt
```

TLS for production via **cert-manager** (open source, CNCF project) + Let's Encrypt:

```bash
helm install cert-manager jetstack/cert-manager --set installCRDs=true
```

---

### 2.11 Secrets Management

#### Comparison matrix

| Criterion | Helm values (current) | Sealed Secrets | External Secrets Operator | HashiCorp Vault | SOPS + age |
|-----------|---------------------|----------------|---------------------------|-----------------|------------|
| **License** | Apache 2.0 (Helm) | Apache 2.0 | Apache 2.0 | BSL 1.1 (not open source!) | Apache 2.0 / MIT |
| **Encrypted in git** | No (plaintext) | **Yes** (asymmetric) | No (secrets in external system) | No | **Yes** (symmetric/asymmetric) |
| **Automatic rotation** | No | No | **Yes** (sync interval) | **Yes** | No |
| **Audit trail** | No | Via git history | Via external store | **Yes (extensive)** | Via git history |
| **Extra infra needed** | None | Controller in cluster | Controller + external store | **Vault cluster (3+ nodes)** | None |
| **Complexity** | Low | **Low** | Medium | **High** | **Low** |
| **Multi-cluster** | No | No (per-cluster keys) | Yes | Yes | Yes (same key) |
| **Backup/recovery** | n/a | Cluster key backup! | Via external store | Vault HA + unsealing | Key file backup |
| **Druppie secrets** | API keys, DB passwords, HMAC secrets | Same, encrypted | Same, externally managed | Same, Vault managed | Same, encrypted |

**Note: HashiCorp Vault has NOT been open source since 2023** (BSL 1.1 license). This conflicts with our open source principle. OpenBao is the open source fork (MPL 2.0), but is less mature.

**Decision: Sealed Secrets for phase 1, SOPS + age as an alternative.**

**Sealed Secrets** (Bitnami, v0.27+) works as follows:
1. A controller in the cluster generates an asymmetric key pair
2. You encrypt Kubernetes Secrets locally with the public key: `kubeseal < secret.yaml > sealed-secret.yaml`
3. The encrypted SealedSecret can safely go into git
4. The controller in the cluster decrypts it into a regular Kubernetes Secret

```bash
# Create and encrypt the secret
kubectl create secret generic druppie-secrets \
  --from-literal=zai-api-key=sk-xxx \
  --from-literal=db-password=xxx \
  --dry-run=client -o yaml | kubeseal > sealed-secrets.yaml

# Commit to git (safe — encrypted)
git add sealed-secrets.yaml && git commit -m "Add sealed secrets"
```

**Important:** Make a backup of the Sealed Secrets controller private key! Without this key you cannot decrypt existing sealed secrets after a cluster rebuild.

**SOPS + age** is a lighter alternative: encrypt YAML files directly with `sops` and an `age` key. No controller needed, works with Helm via the `helm-secrets` plugin. Drawback: no automatic sync — you have to deploy after every change.

---

### 2.12 Monitoring & Observability

#### Comparison matrix

| Criterion | kube-prometheus-stack | Victoria Metrics | Grafana Loki (logging) | Jaeger (tracing) |
|-----------|----------------------|------------------|----------------------|------------------|
| **License** | Apache 2.0 | Apache 2.0 | AGPL 3.0 | Apache 2.0 |
| **Function** | Metrics + alerting | Metrics (Prometheus-compatible) | Log aggregation | Distributed tracing |
| **Resource usage** | Medium-High | **Low** (2-5x more efficient) | Medium | Low |
| **Prometheus-compatible** | Native | Yes (drop-in replacement) | n/a | n/a |
| **Grafana dashboards** | Built-in | Yes | Built-in | Via Grafana |
| **Operational** | Medium | Low | Medium | Low |

**Decision: kube-prometheus-stack (Prometheus + Grafana + Alertmanager).**

This is the de-facto standard for Kubernetes monitoring. A single `helm install` gives you:
- Prometheus for metrics (CPU, memory, custom app metrics)
- Grafana for dashboards
- Alertmanager for notifications (Slack, email)
- Node-exporter for host metrics
- kube-state-metrics for Kubernetes object metrics

CloudNativePG automatically exports PostgreSQL metrics via PodMonitor. KEDA, Traefik, and Keycloak also have Prometheus endpoints.

---

### 2.13 Infrastructure Provisioning & Node Autoscaling

#### Problem statement

HPA and KEDA scale pods, but when all 3 nodes are full, Kubernetes has no place to schedule new pods. We need automatic node-level autoscaling: provision new Hetzner VMs when capacity is needed, and remove them when they are idle.

#### Comparison matrix

| Criterion | hetzner-k3s (CLI) | kube-hetzner (Terraform) | Custom Terraform | Manual |
|-----------|-------------------|--------------------------|------------------|-----------|
| **License** | MIT | MIT | n/a | n/a |
| **Type** | CLI tool (1 YAML config) | Terraform module | Own Terraform | SSH + scripts |
| **OS** | Ubuntu (default), Debian, others | MicroOS (openSUSE) | Choose yourself | Choose yourself |
| **Cluster setup** | 2-3 minutes | ~5 minutes | Variable | 30+ min |
| **Autoscaling built-in** | Yes (Cluster Autoscaler + CCM + CSI) | Yes (Cluster Autoscaler + CCM + CSI) | No (configure yourself) | No |
| **Auto-upgrades K3s** | Yes (System Upgrade Controller) | Yes (System Upgrade Controller) | No | No |
| **IaC in git** | Yes (YAML config) | Yes (Terraform state) | Yes | No |
| **Learning curve** | Low | Medium (Terraform knowledge needed) | High | Low |
| **Flexibility** | Medium | High (190+ variables) | Maximum | None |
| **Community** | ⭐ 3.5k+ GitHub stars | ⭐ 3.8k+ GitHub stars | n/a | n/a |
| **Multi-cluster** | No | Yes (Terraform workspaces) | Yes | No |
| **Production ready** | Yes | Yes | Depends on implementation | No |

#### Notes: Two-tier autoscaling architecture

Pod scaling and node scaling are two separate layers that work together:

**Tier 1 — Pod Autoscaling (HPA + KEDA):**
- Monitors CPU/memory/custom metrics per pod
- Adds or removes pod replicas within existing nodes
- Fast (seconds): a new pod starts on an existing node
- Bounded by available node capacity

**Tier 2 — Node Autoscaling (Cluster Autoscaler):**
- Monitors pods that cannot be scheduled (Pending state)
- Creates new Hetzner VMs via the Hetzner Cloud API
- Cloud-init script automatically installs the K3s agent and adds it to the cluster
- Removes idle nodes after a configurable timeout
- Slower (30-60s): VM provisioning + K3s join

Flow:
```
Load spike → HPA creates pods → Nodes full? → Pending pods
                                                  ↓
                              Cluster Autoscaler detects Pending pods
                                                  ↓
                              Hetzner API: create new VM
                                                  ↓
                              Cloud-init: install K3s agent, join cluster
                                                  ↓
                              Node ready → Pending pods scheduled
```

#### Notes per option

**hetzner-k3s (recommended for Druppie)**

CLI tool by Vito Botta. A single YAML config file defines the entire cluster: masters, workers, autoscaling pools, networking. No Terraform needed. Automatically installs: Hetzner CCM, CSI driver, System Upgrade Controller, and Cluster Autoscaler.

```yaml
# cluster.yaml
hetzner_token: <token>
cluster_name: druppie
kubeconfig_path: "./kubeconfig"
k3s_version: v1.32.3+k3s1

networking:
  mode: flannel

masters_pool:
  instance_type: cpx31
  instance_count: 3
  location: fsn1

worker_node_pools:
- name: workers
  instance_type: cpx31
  instance_count: 1
  location: fsn1
  autoscaling:
    enabled: true
    min_instances: 1
    max_instances: 10
```

Strengths: Ubuntu support, simplest setup, batteries included, active community.
Weaknesses: Single maintainer, less flexible than Terraform modules.

**kube-hetzner (Terraform module)**

The most popular Terraform module for K3s on Hetzner. Uses MicroOS (openSUSE), an immutable, transactional OS designed for containers. Deep integration with auto-upgrades, Longhorn, and multiple CNI options.

Strengths: Most complete, IaC standard, multi-cluster, MicroOS security benefits.
Weaknesses: Requires Terraform knowledge, MicroOS learning curve, no Ubuntu.

**Kubernetes Cluster Autoscaler (upstream Hetzner provider)**

Independent of the provisioning tool: the actual autoscaling is performed by the official Kubernetes Cluster Autoscaler with a built-in Hetzner Cloud provider (`--cloud-provider=hetzner`). This is upstream Kubernetes, actively maintained (commits from May 2026).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.32.0
          command:
            - ./cluster-autoscaler
            - --cloud-provider=hetzner
            - --nodes=1:10:cpx31:fsn1:workers    # min:max:type:region:pool
            - --scale-down-delay-after-add=10m
            - --scale-down-unneeded-time=10m
            - --scan-interval=10s
          env:
            - name: HCLOUD_TOKEN
              valueFrom:
                secretKeyRef:
                  name: hcloud-autoscaler
                  key: token
            - name: HCLOUD_CLUSTER_CONFIG
              valueFrom:
                secretKeyRef:
                  name: hcloud-autoscaler
                  key: clusterConfig
            - name: HCLOUD_NETWORK
              value: "druppie-network"
```

**Hetzner Cloud Controller Manager (CCM)** — Mandatory dependency. Integrates Kubernetes with Hetzner APIs for node lifecycle, load balancer provisioning, and network routes. The CCM does not handle autoscaling itself; it is the bridge between K8s and Hetzner that the Cluster Autoscaler needs.

**Karpenter** — NOT available for Hetzner. There is no provider and it is not on the roadmap. Karpenter supports only AWS, Azure, GCP, and a few others. Not an option.

#### Decision: hetzner-k3s (CLI) + Cluster Autoscaler (upstream)

| Part | Choice | Reason |
|-----------|-------|-------|
| **Cluster provisioning** | hetzner-k3s CLI | Ubuntu, simplest setup, everything built in, 2-3 min cluster |
| **Node autoscaling** | Kubernetes Cluster Autoscaler (Hetzner provider) | Upstream, production-ready, actively maintained |
| **Cloud integration** | Hetzner CCM | Mandatory — node lifecycle, LB provisioning |
| **Storage integration** | Hetzner CSI driver | Persistent volumes via Hetzner block storage |
| **Auto-upgrades** | System Upgrade Controller | K3s and OS updates with rollback |

---

## 3. Scalability Vision — Architecture Suggestions

The current Druppie architecture is designed for single-instance Docker Compose. To become truly scalable on Kubernetes, architecture changes are needed. This section describes suggestions — none of these takes the current codebase as a constraint.

> **Current state summarized:** Backend runs on 1 hardcoded replica (`backend-deployment.yaml:9`). Session tracking is in-memory via the `_active_session_tasks` dict in `core/background_tasks.py` — this prevents multi-replica without race conditions. The workspace PVC is `ReadWriteOnce` — blocking scheduling to other nodes. The sandbox-manager spawns containers via `docker run` subprocess calls. No HPA, no PDB, no autoscaling configured in the Helm chart.

### 3.1 Event-Driven Backend (eliminate the current bottleneck)

**Problem:** The backend processes agent sessions via `create_session_task()` (`core/background_tasks.py`), which keeps an in-memory `dict[UUID, asyncio.Task]` per session_id. This prevents duplicate runs within one replica, but with multiple replicas there is **no cross-replica coordination** — two replicas can run the same session simultaneously. The sandbox webhook (`api/routes/sandbox.py`) lands on a random replica via the Service load balancer, not necessarily on the replica that hosts the agent session.

**Suggestion: Message queue as the backbone**

Introduce a message broker (Redis Streams, NATS, or RabbitMQ — all open source) as a decoupling layer:

```
                    ┌─────────────────┐
   User request ──► │  API Gateway    │ ──► Queue: "agent.start"
                    │  (FastAPI)      │
                    └─────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Agent Workers    │ ◄── Queue: "agent.start"
                    │  (N replicas)     │ ──► Queue: "tool.execute"
                    └───────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Tool Workers     │ ◄── Queue: "tool.execute"
                    │  (N replicas)     │ ──► Queue: "agent.resume"
                    └───────────────────┘
```

| Broker | License | Persistence | Throughput | Complexity | Recommendation |
|--------|----------|-------------|-----------|--------------|-------------|
| **Redis Streams** | BSD 3-Clause | Yes (AOF/RDB) | Very high | Low | **Phase 2** |
| **NATS JetStream** | Apache 2.0 | Yes | Very high | Low | Alternative |
| RabbitMQ | MPL 2.0 | Yes | High | Medium | Alternative |

Benefits:
- Each backend replica can pick up any task (no sticky sessions)
- Webhook → queue → a random worker picks it up
- Scale workers independently of API pods
- Failed workers → message back in the queue → automatic retry
- Backpressure: if workers are full, the queues grow, HPA/KEDA scales workers up

### 3.2 MCP Module Mesh — Sidecar vs Centralized

**Problem:** MCP modules are currently standalone HTTP services with a shared workspace volume (RWX). This creates an NFS/storage bottleneck and makes scaling complex.

**Suggestion A: Sidecar pattern**

Run MCP modules as sidecars alongside the backend pod. Each backend replica has its own set of MCP modules:

```
┌─────────────────────────────────┐
│  Pod: druppie-backend-xyz       │
│  ┌──────────┐ ┌──────────────┐  │
│  │ backend  │ │ module-coding │  │
│  │          │ │ module-llm    │  │
│  │          │ │ module-web    │  │
│  └──────────┘ └──────────────┘  │
│         (localhost:9001-9011)    │
│  emptyDir: /workspace           │
└─────────────────────────────────┘
```

Benefits:
- No network latency to MCP modules (localhost)
- No shared volume needed (each pod has its own emptyDir)
- Scales automatically along with backend replicas
- Simpler NetworkPolicy (everything in one pod)

Drawbacks:
- More resources per pod (each replica runs all modules)
- Modules not independently scalable
- Larger pod = slower scheduling

**Suggestion B: Per-session microservices (advanced)**

Spawn MCP modules on-demand per agent session as temporary pods:

```
Session start → spawn module-coding pod (session-123)
             → spawn module-docker pod (session-123)
Session end  → cleanup pods
```

This is what Agent Sandbox offers conceptually — but for MCP modules instead of sandboxes. Benefits: perfect isolation, no shared state, scale = more session pods.

### 3.3 Database Partitioning

**Problem:** One PostgreSQL database for everything. As we grow, the `tool_calls` and `llm_calls` tables become huge (each agent session generates dozens of records).

**Suggestions:**

| Strategy | What | When |
|-----------|-----|---------|
| **Read replicas** | CNPG read-only endpoints for UI queries | >1000 sessions |
| **Table partitioning** | Partition `tool_calls` and `llm_calls` on `created_at` (monthly) | >100k records |
| **Archive strategy** | Move old sessions to cold storage (S3/MinIO as Parquet) | >6 months of data |
| **Separate DB per concern** | Own CNPG cluster for audit/logging vs operational data | Enterprise scale |

```sql
-- Example: table partitioning by date
CREATE TABLE tool_calls (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL,
    ...
) PARTITION BY RANGE (created_at);

CREATE TABLE tool_calls_2026_06 PARTITION OF tool_calls
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

### 3.4 Sandbox Pool Pre-warming

**Problem:** Cold start for sandboxes (pod scheduling + container pull + init) takes 3-10 seconds. This feels slow for interactive sessions.

**Suggestions:**

| Strategy | Latency | Cost | Complexity |
|-----------|---------|------|--------------|
| **Agent Sandbox WarmPool** | <1s | Idle pods cost resources | Low (CRD config) |
| **Pre-pulled images** | ~2-3s (skip pull) | Disk space on nodes | Low (DaemonSet) |
| **Snapshot/restore** | ~1-2s | Snapshot storage | Medium |
| **Dedicated sandbox nodes** | ~3s (no scheduling contention) | Dedicated hardware | Low (node taint) |

Agent Sandbox WarmPool is the most elegant:

```yaml
apiVersion: sandbox.k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: coding-sandboxes
spec:
  templateRef: druppie-coding-sandbox
  minReady: 3       # Always 3 warm sandboxes available
  maxSize: 20       # Max 20 total
  ttlSecondsAfterIdle: 600  # Cleanup after 10 min idle
```

### 3.5 Multi-Tenant Scalability

If Druppie has to serve multiple organizations:

| Isolation level | How | Overhead | Security |
|----------------|-----|----------|----------|
| **Namespace per tenant** | Separate K8s namespace with ResourceQuota and NetworkPolicy | Low | Medium |
| **Node pool per tenant** | Dedicated nodes via taints/tolerations | High | High |
| **Cluster per tenant** | Separate K3s clusters via Rancher | Very high | Very high |
| **Virtual clusters** | vCluster (open source) — virtual K8s clusters in namespaces | Medium | High |

For Druppie, **namespace per tenant + vCluster** is the sweet spot: full Kubernetes API isolation without the overhead of separate clusters. vCluster (open source, Loft Labs) creates virtual Kubernetes clusters in existing namespaces — each tenant thinks it has its own cluster.

### 3.6 Control Plane Scalability

**Problem:** The sandbox-control-plane uses SQLite — cannot span multiple replicas.

**Suggestion:** Migrate control plane storage to PostgreSQL (can use the same CNPG cluster). This enables multi-replica deployment and eliminates the last single-point-of-failure in the architecture.

Alternative: if the control plane mainly does caching and session state, consider Redis as a backing store (faster than PostgreSQL for key-value lookups, but less durable).

### 3.7 Concrete codebase changes for scalability

The changes below are needed to go from single-replica to horizontally scalable. Ordered by priority:

| Priority | Change | File(s) | What |
|------------|-----------|-------------|-----|
| **P0** | Replica count configurable | `helm/druppie/templates/backend-deployment.yaml` | Hardcoded `replicas: 1` → `{{ .Values.backend.replicas }}` |
| **P0** | Workspace PVC to RWX | `helm/druppie/templates/persistentvolumeclaims.yaml` | `ReadWriteOnce` → `ReadWriteMany` + storageClass |
| **P0** | Add HPA | `helm/druppie/templates/` (new) | HPA resources for backend, frontend, MCP modules |
| **P1** | Session locking to database | `druppie/core/background_tasks.py` | `_active_session_tasks` dict → PostgreSQL advisory lock or `FOR UPDATE SKIP LOCKED` |
| **P1** | Sandbox manager to K8s API | `background-agents/.../docker_manager.py` | `docker run` subprocess → `kubernetes` Python client |
| **P2** | Add PDBs | `helm/druppie/templates/` (new) | PodDisruptionBudget per critical service |
| **P2** | Configure anti-affinity | `helm/druppie/templates/*-deployment.yaml` | Pod anti-affinity on hostname |
| **P2** | Graceful shutdown | `druppie/api/main.py` | Extend `terminationGracePeriodSeconds` + SIGTERM handler |
| **P3** | Control plane SQLite → PG | `background-agents/` | Replace SQLite with a PostgreSQL client |
| **P3** | Replica counts in values.yaml | `helm/druppie/values.yaml` | Expose `replicas` per service in values |

---

## 4. Phasing

### Phase 1 — Minimally Production-Ready (4-6 weeks)

| Item | Work | Tooling |
|------|------|---------|
| K3s cluster setup | 3-node HA cluster on cloud VMs | K3s, Terraform (optional) |
| Container registry | Configure Gitea container registry | Gitea (already present) |
| CloudNativePG | Operator v1.29.1+, 3 database clusters | CloudNativePG operator |
| Longhorn storage | Installation, RWX PVC for workspace | Longhorn |
| Helm chart updates | `values-k3s.yaml` overlay, Traefik config | Helm |
| TLS certificates | cert-manager + Let's Encrypt | cert-manager |
| Sealed Secrets | API keys, DB passwords encrypted in git | Sealed Secrets |
| CI/CD pipeline | GitHub Actions: build → push → helm upgrade | GitHub Actions |
| Monitoring | kube-prometheus-stack installation | Prometheus, Grafana |
| Sandbox as K8s Jobs | Refactor sandbox-manager (fallback for Agent Sandbox) | Kubernetes Python client |

### Phase 2 — Scalable & Operational (6-10 weeks)

| Item | Work | Tooling |
|------|------|---------|
| Agent Sandbox | Evaluate and adopt kubernetes-sigs/agent-sandbox | Agent Sandbox operator |
| HPA for stateless services | CPU + custom metrics per service | HPA, Prometheus |
| KEDA | Event-driven autoscaling on queue depth | KEDA |
| ArgoCD | GitOps deployment pipeline | ArgoCD |
| Backend multi-replica | Implement database-driven resume pattern | Application code |
| Per-session workspace | Eliminate the shared RWX volume | Architecture refactor |
| gVisor runtime | RuntimeClass configuration for sandboxes | gVisor |
| Network Policies | Per-namespace isolation | Kubernetes NetworkPolicy |
| Harbor registry | Vulnerability scanning, image signing | Harbor |

### Phase 3 — Enterprise-Ready (optional)

| Item | Work | Tooling |
|------|------|---------|
| Rancher management | Multi-cluster management via UI | Rancher |
| Kata Containers | VM-level isolation for multi-tenant | Kata Containers |
| Database read replicas | CloudNativePG read-only endpoints for reporting | CloudNativePG |
| Distributed tracing | Request tracing across all services | Jaeger |
| Chaos engineering | Failure testing | Litmus (CNCF) |
| Backup/DR | Cluster-level backup and disaster recovery | Velero (open source) |

---

## 5. Risks

| Risk | Impact | Likelihood | Mitigation |
|--------|--------|------|-----------|
| Agent Sandbox too immature (v1alpha1) | Sandbox refactor delayed | Medium | Start with K8s Jobs as a fallback; evaluate Agent Sandbox in parallel |
| Longhorn RWX performance insufficient | Slow workspace file operations | Low | Benchmark early; fallback = NFS server pod |
| CloudNativePG operational knowledge lacking | Database issues in production | Medium | Training + write runbooks; test failover scenarios on staging |
| Backend multi-replica race conditions | Data inconsistency on webhooks | Medium | Phase 1 runs single replica; phase 2 implements DB-driven resume |
| K3s cluster management overhead | More ops work than expected | Low | K3s is minimal; upgrade to Rancher as we grow |
| Sealed Secrets key lost | All secrets inaccessible after cluster rebuild | Medium | Document and test key backup procedure |

---

## 6. Assumptions

1. The team has basic Kubernetes knowledge or is willing to build it up.
2. There is no strict data-residency requirement that forces a specific hosting location.
3. The current load fits on a 3-node cluster (4 vCPU, 16GB RAM per node).
4. Sandboxes do not need to run Docker-in-Docker (only code execution + git).
5. There is no 99.99% uptime SLA required in phase 1.
6. All tooling must be open source (Apache 2.0, MIT, GPL, MPL — no BSL or proprietary).

---

## 7. Cost Estimate

### Option A: Cloud VMs (e.g. Hetzner)

| Component | Specification | Estimated cost/month |
|-----------|-------------|----------------------|
| Server nodes (3x) | CPX31 (4 vCPU, 8GB RAM, 160GB NVMe) | 3 × €13 = ~€39 |
| Extra storage | 200GB block storage for Longhorn | ~€10 |
| Load balancer | Hetzner LB | ~€6 |
| Backup storage | 100GB (DB backups via MinIO/S3) | ~€5 |
| **Total** | | **~€60/month** |

### Option B: Dedicated servers (higher performance)

| Component | Specification | Estimated cost/month |
|-----------|-------------|----------------------|
| Server nodes (3x) | AX42 (8 vCPU, 64GB RAM, 2x512GB NVMe) | 3 × €49 = ~€147 |
| **Total** | | **~€147/month** |

### Option C: On-premises (existing hardware)

| Component | Specification | Cost |
|-----------|-------------|--------|
| Hardware | 3 servers (existing) | €0 (already available) |
| Power + cooling | Depends on location | Variable |
| **Total** | | **€0 + power** |

Note: Sandbox workloads are bursty. Consider a separate worker node that is switched on/off for sandboxes (K3s agent join/leave is trivial).

---

## 8. Next Steps

1. **Spike: Agent Sandbox evaluation** — Install the operator on Kind, test the Python SDK as a replacement for `docker_manager.py`. Fallback: K8s Jobs. This is the biggest technical risk.
2. **K3s staging cluster** — Set up a 3-node K3s HA cluster (cloud VMs or on-prem). Test the full Helm chart.
3. **CloudNativePG test** — Deploy operator v1.29.1+ on Kind, test HA failover and backup/restore to MinIO.
4. **Longhorn benchmark** — Measure RWX performance for the workspace volume (git clone, file write throughput).
5. **CI/CD pipeline** — GitHub Actions: build → push to Gitea registry → helm upgrade on K3s.
6. **Helm chart updates** — `values-k3s.yaml`, Traefik/NGINX toggle, Longhorn StorageClass.

---

## 9. Caveats for this research

- **Agent Sandbox is v1alpha1** (pre-stable) — the API may change significantly before GA. A fallback on K8s Jobs must be ready.
- **CloudNativePG CVE-2026-44477** requires immediate patching on every production deployment.
- **Sysbox risk:** Containerd integration is "still evolving" with best-effort community support — not recommended.
- **HashiCorp Vault** is no longer open source (BSL 1.1 since 2023). OpenBao (MPL 2.0 fork) is an alternative but less mature.
- **Cost estimates** are indicative and based on public prices (June 2026). Actual costs vary per provider and usage.

---

## 10. References

### Verified via deep research (adversarial verification, 23/25 claims confirmed)

- [Agent Sandbox — Kubernetes blog](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)
- [Agent Sandbox — Google Open Source blog](https://opensource.googleblog.com/2025/11/unleashing-autonomous-ai-agents-why-kubernetes-needs-a-new-standard-for-agent-execution.html)
- [Kata Containers + Agent Sandbox integration](https://katacontainers.io/blog/kata-containers-agent-sandbox-integration/)
- [CloudNativePG v1.29.1 release notes](https://cloudnative-pg.io/releases/cloudnative-pg-1-29.1-released/)
- [GKE autoscaling best practices for LLM inference](https://docs.cloud.google.com/kubernetes-engine/docs/best-practices/machine-learning/inference/autoscaling)
- [KEDA GPU autoscaling — CNCF blog](https://www.cncf.io/blog/2026/05/27/gpu-autoscaling-on-kubernetes-with-keda-building-an-external-scaler/)
- [vLLM Production Stack — KEDA autoscaling](https://docs.vllm.ai/projects/production-stack/en/latest/use_cases/autoscaling-keda.html)
- [Sysbox + K3s integration](https://docs.k3s.io/blog/2025/09/27/k3s-sysbox)

### Platform documentation

- [K3s documentation](https://docs.k3s.io/)
- [Rancher documentation](https://ranchermanager.docs.rancher.com/)
- [OKD documentation](https://docs.okd.io/)
- [CloudNativePG documentation](https://cloudnative-pg.io/documentation/)
- [Longhorn documentation](https://longhorn.io/docs/)
- [KEDA documentation](https://keda.sh/docs/)
- [ArgoCD documentation](https://argo-cd.readthedocs.io/)
- [Sealed Secrets](https://sealed-secrets.netlify.app/)
- [Traefik documentation](https://doc.traefik.io/traefik/)
- [cert-manager documentation](https://cert-manager.io/docs/)
- [Harbor documentation](https://goharbor.io/docs/)
- [gVisor documentation](https://gvisor.dev/docs/)

### Existing Druppie resources

- Helm chart: `helm/druppie/`
- K8s setup guide: `docs/guides/kubernetes-deployment.md`
- Kind cluster config: `kind/cluster-dev.yaml`
</content>
</invoke>
