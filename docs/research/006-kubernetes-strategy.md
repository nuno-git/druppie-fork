---
id: "006"
title: "Schaalbare Kubernetes Strategie voor Druppie"
status: complete
author: Druppie team
date: 2026-06-02
outcome: "adr-002"
---

# ADR: Schaalbare Kubernetes Strategie voor Druppie

> **Status:** Voorstel  
> **Datum:** 2026-06-02  
> **Laatst bijgewerkt:** 2026-06-09  
> **Type:** Spike / Architecture Decision Record  
> **Story:** Story 2 — Spike: schaalbare Kubernetes strategie (3 SP)  
> **Principe:** Alles open source, geen vendor lock-in

> **Status: Historische spike (2026-06-02).** Vervangen door `docs/adrs/002-kubernetes-migration.md` (beslissingen) en `docs/research/007-kubernetes-as-built-analysis.md` (huidige staat). De Hetzner-specifieke provisioning/kosten secties zijn behouden ter referentie maar reflecteren niet langer het geplande lokale-Rancher doel.

---

## Strategieoverzicht

Dit document onderzoekt **13 strategiegebieden** voor de migratie van Docker Compose naar productie-ready Kubernetes. Elke strategie adresseert een specifieke bottleneck of risico in de huidige architectuur.

| # | Strategie | Waarom | Huidige staat | Beslissing |
|---|-----------|--------|---------------|------------|
| 2.1 | **Kubernetes Platform** | Welke distributie voor dev, staging, productie | Kind (alleen dev) | Kind (dev) → K3s (staging/prod) |
| 2.2 | **Hosting Model** | Waar draait het cluster, zonder vendor lock-in | Lokaal (Docker Desktop) | Cloud VMs (commodity provider) |
| 2.3 | **Schaalbaarheid** | Backend is single-replica, geen autoscaling | 1 replica, hardcoded, geen HPA | HPA + KEDA per service |
| 2.4 | **Database** | 3× container PostgreSQL zonder HA, backup, of failover | StatefulSets, geen replicatie | CloudNativePG operator |
| 2.5 | **High Availability** | Single point of failure op elke laag | Geen PDB, geen anti-affinity | PDB + anti-affinity + graceful shutdown |
| 2.6 | **Sandbox** | Docker socket dependency werkt niet in K8s | `docker_manager.py` via Docker CLI | Agent Sandbox (SIG Apps) / K8s Jobs fallback |
| 2.7 | **Shared Volumes (RWX)** | Workspace PVC is ReadWriteOnce — blokkeert multi-node | RWO, 4 services delen 1 volume | Longhorn RWX → per-session eliminatie |
| 2.8 | **Deployment** | Geen GitOps, geen drift detection | Handmatig `helm upgrade` | Helm + CI/CD → ArgoCD |
| 2.9 | **Container Registry** | Images moeten ergens naartoe (niet `kind load`) | Geen registry | Gitea registry → Harbor |
| 2.10 | **Networking/Ingress** | TLS, routing, rate limiting voor productie | NGINX op Kind (port 9080) | Traefik (K3s standaard) + cert-manager |
| 2.11 | **Secrets Management** | API keys en wachtwoorden staan in plaintext values | Helm values (onversleuteld) | Sealed Secrets |
| 2.12 | **Monitoring** | Geen observability, blind vliegen in productie | Niets | kube-prometheus-stack |
| 2.13 | **Infrastructure Provisioning & Node Autoscaling** | HPA/KEDA schalen pods, maar nodes zijn vol = geen scheduling | Geen node-level autoscaling | hetzner-k3s CLI + Cluster Autoscaler (upstream) |

**Sectie 3** beschrijft **architectuursuggesties** die dieper ingrijpen dan tooling-keuzes — dit zijn de wijzigingen die nodig zijn om Druppie écht horizontaal schaalbaar te maken:

| # | Suggestie | Kernprobleem |
|---|-----------|-------------|
| 3.1 | Event-driven backend | In-memory session tracking (`_active_session_tasks` dict) voorkomt multi-replica |
| 3.2 | MCP module mesh | 9 MCP modules als losse services + shared volume = NFS bottleneck |
| 3.3 | Database partitioning | `tool_calls`/`llm_calls` tabellen groeien onbegrensd |
| 3.4 | Sandbox pool pre-warming | Cold start 3-10s is te traag voor interactieve sessies |
| 3.5 | Multi-tenant schaalbaarheid | Geen tenant isolatie op K8s niveau |
| 3.6 | Control plane schaalbaarheid | SQLite in sandbox-control-plane = single replica |

### Toekomstige uitbreidingen (nog niet behandeld)

De volgende onderwerpen vallen buiten scope van deze spike maar worden relevant bij groei:

| Onderwerp | Waarom relevant | Wanneer |
|-----------|----------------|---------|
| **Service mesh** (Istio/Linkerd) | mTLS tussen services, traffic shaping, circuit breaking | Multi-tenant of compliance-eisen |
| **Distributed caching** (Redis/Valkey) | Session state delen tussen replicas, MCP response caching | Backend multi-replica (fase 2) |
| **Blue/green & canary deployments** | Zero-downtime releases met rollback op metrics | Productie met SLA |
| **API rate limiting per tenant** | Fair use, abuse prevention | Multi-tenant |
| **Distributed tracing** (Jaeger/Tempo) | Request flow door 20+ services debuggen | Productie debugging |
| **Log aggregation** (Loki/ELK) | Gecentraliseerd loggen, correlatie tussen services | Productie operatie |
| **Webhook retry & dead-letter queue** | Sandbox webhooks kunnen falen, geen retry mechanisme nu | Backend reliability |
| **FinOps / cost management** | Resource right-sizing, idle detection, burst billing | Cloud productie |
| **Disaster recovery automatisering** | Cluster rebuild, cross-region failover | Enterprise / SLA 99.9%+ |
| **Feature flags** | Graduele rollout van nieuwe agent capabilities | Team groei |

---

## 1. Context

Druppie is een governance platform voor AI-agents met 20+ services: een FastAPI backend, React frontend, 9 MCP-microservices, Keycloak, Gitea, 3 PostgreSQL databases, en een sandbox-infrastructuur die dynamisch Docker-containers spawnt. Het platform draait nu op Docker Compose en heeft een werkend Helm chart voor Kind (lokaal). Deze spike onderzoekt hoe we productie-ready en schaalbaar worden in Kubernetes.

### Uitgangspunten

- **100% open source** — geen proprietary componenten, geen managed cloud services als dependency
- **Geen vendor lock-in** — draaibaar op elke cloud, on-premises, of bare metal
- **Portable Helm chart** — dezelfde chart werkt op Kind, K3s, Rancher, OpenShift, vanilla K8s

### Huidige staat

| Wat | Status |
|-----|--------|
| Helm chart | Werkend voor Kind, 43 K8s resources, sandbox nog placeholder |
| Kind cluster config | Single-node dev + multi-node config aanwezig |
| Docker socket dependency | 3 services (sandbox-manager, module-docker, backend) |
| Shared volumes (RWX) | `workspace` volume gedeeld door 4 services |
| Database migraties | Geen — SQLAlchemy `create_all()`, reset = drop + recreate |

---

## 2. Beslissingen

### 2.1 Kubernetes Platform

#### Vergelijkingsmatrix

| Criterium | Kind | K3s | Rancher (RKE2) | OpenShift (OKD) | Vanilla K8s (kubeadm) |
|-----------|------|-----|-----------------|-----------------|----------------------|
| **Licentie** | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 (OKD) | Apache 2.0 |
| **Use case** | Dev/CI | Dev/Edge/Prod | Prod multi-cluster | Enterprise prod | Prod (bare metal) |
| **Installatie** | 1 commando | 1 commando | UI of CLI | Installer (30+ min) | Handmatig (complex) |
| **Resource overhead** | ~300MB (in Docker) | ~512MB RAM | ~2GB RAM | ~8GB RAM minimum | ~2GB RAM |
| **Multi-node** | Ja (in Docker containers) | Ja (agent join) | Ja (UI-managed) | Ja | Ja |
| **Built-in storage** | Nee | Local-path provisioner | Longhorn (optioneel) | OpenShift Data Foundation | Nee |
| **Built-in ingress** | Nee (add NGINX) | Traefik (standaard) | NGINX (standaard) | HAProxy (Routes) | Nee |
| **Built-in monitoring** | Nee | Nee | Prometheus/Grafana via UI | Ingebouwd (Prometheus) | Nee |
| **Helm support** | Ja | Ja | Ja | Ja (met beperkingen) | Ja |
| **NetworkPolicy** | Via CNI plugin | Via Flannel/Calico | Via Calico/Cilium | Via OVN-Kubernetes | Via CNI plugin |
| **Cert management** | Handmatig | Handmatig | Via Rancher UI | Ingebouwd | Handmatig |
| **RBAC** | Kubernetes native | Kubernetes native | Rancher RBAC + K8s | OpenShift RBAC (strenger) | Kubernetes native |
| **Updates** | Recreate cluster | `k3s upgrade` | Rancher UI | `oc adm upgrade` | `kubeadm upgrade` |
| **Community** | Kubernetes SIG | CNCF Sandbox (Rancher Labs) | SUSE/Rancher | Red Hat + community | Kubernetes upstream |
| **Productie-ready** | Nee | Ja (CNCF certified) | Ja | Ja | Ja (maar veel werk) |
| **Leercurve** | Laag | Laag | Medium | Hoog | Hoog |

#### Toelichting per platform

**Kind (Kubernetes in Docker)**

Kind draait een volledige Kubernetes cluster als Docker containers op je lokale machine. Het is ontworpen voor het testen van Kubernetes zelf en is daarmee perfect voor CI/CD en lokale development. Kind is geen productie-oplossing: het heeft geen persistent storage, geen HA, en geen cluster lifecycle management. Wij gebruiken het al (`kind/cluster-dev.yaml`) en het werkt goed.

- **Sterkte:** Snelste setup (~30 sec), nul configuratie, perfecte CI match
- **Zwakte:** Geen persistent storage classes, geen multi-node HA, niet voor productie
- **Wanneer:** Development, CI pipelines, Helm chart validatie

**K3s**

K3s is een lichtgewicht, CNCF-gecertificeerde Kubernetes distributie gebouwd door Rancher Labs (nu SUSE). Het is een single binary van ~70MB die alles bevat: API server, scheduler, controller, etcd (vervangen door SQLite voor single-node of embedded etcd voor HA), containerd, en Flannel CNI. K3s draait op alles: bare metal, VMs, Raspberry Pi's, edge devices, cloud VMs.

K3s is **niet** een afgezwakte Kubernetes — het is volledige Kubernetes met dezelfde API, dezelfde conformance tests, en dezelfde Helm charts. Het verschil zit in de verpakking: alles in één binary, automatische TLS bootstrapping, en out-of-the-box Traefik ingress + CoreDNS + local-path storage.

- **Sterkte:** Lichtgewicht, snel, CNCF certified, draait overal, makkelijk HA (3 server nodes)
- **Zwakte:** Minder ecosystem tooling dan RKE2/kubeadm, Traefik ipv NGINX (configureerbaar)
- **Wanneer:** Productie voor kleine/medium teams, edge deployments, budget-bewust

**Rancher / RKE2**

Rancher is een open source multi-cluster management platform. RKE2 is de onderliggende Kubernetes distributie (opvolger van RKE1), ook wel "RKE Government" genoemd vanwege de focus op security en FIPS compliance. Rancher biedt een web UI voor cluster lifecycle management, monitoring, logging, en RBAC.

Het verschil met K3s: Rancher/RKE2 is bedoeld voor teams die meerdere clusters beheren, enterprise-grade security nodig hebben, of een grafische beheersinterface willen. RKE2 gebruikt containerd (geen Docker), heeft CIS hardening out-of-the-box, en draait standaard met NGINX ingress.

Rancher kan ook externe clusters beheren (EKS, AKS, GKE, of bestaande K3s/kubeadm clusters).

- **Sterkte:** Multi-cluster UI, ingebouwde monitoring/alerting, CIS hardened, Longhorn integratie
- **Zwakte:** Meer resources, complexer dan K3s, SUSE commerciële support ≠ community
- **Wanneer:** Meerdere clusters, team >5 personen, enterprise compliance eisen

**OKD (OpenShift Community)**

OKD is de open source upstream van Red Hat OpenShift. Het bouwt voort op Kubernetes maar voegt significant functionaliteit toe: ingebouwde CI/CD (Tekton), image registry, developer console, source-to-image builds, stricter security model (SecurityContextConstraints ipv PodSecurityPolicies), en operator lifecycle management.

OpenShift/OKD wijkt op belangrijke punten af van standaard Kubernetes:
- Gebruikt Routes ipv Ingress (Ingress wordt vertaald naar Routes)
- Draait containers standaard als non-root met random UID
- Heeft eigen CLI (`oc` naast `kubectl`)
- Vereist aanpassingen aan Dockerfiles (geen `USER root`)

Dit betekent dat onze Helm chart en Dockerfiles aanpassingen nodig hebben voor OKD compatibility. Specifiek: de backend Dockerfile installeert packages als root en de sandbox containers draaien met specifieke UIDs.

- **Sterkte:** Meest volledige enterprise platform, ingebouwd alles, strikte security
- **Zwakte:** Zware resource footprint (~8GB+), afwijkende standaarden, Dockerfile aanpassingen nodig, steile leercurve
- **Wanneer:** Enterprise omgevingen met Red Hat ecosysteem, strikte compliance

**Vanilla Kubernetes (kubeadm)**

Upstream Kubernetes geïnstalleerd via `kubeadm`. Je krijgt exact wat het Kubernetes project levert, niets meer. Alles moet je zelf toevoegen: CNI plugin (Calico/Cilium/Flannel), ingress controller, storage provisioner, monitoring, cert management.

- **Sterkte:** Maximale controle, altijd up-to-date met upstream, geen vendor-specifics
- **Zwakte:** Meeste operationeel werk, alles zelf configureren, cluster upgrades zijn complex
- **Wanneer:** Teams met diepgaande K8s expertise die maximale controle willen

#### Beslissing

| Omgeving | Platform | Reden |
|----------|----------|-------|
| **Development** | Kind | Al ingericht, snelste feedback loop, gratis |
| **CI/CD** | Kind | Ephemeral clusters in pipeline, geen state nodig |
| **Staging** | K3s (single-node of 3-node HA) | Lichtgewicht, productie-equivalent, goedkoop |
| **Productie** | K3s (3-node HA) of RKE2 | Open source, CNCF certified, draait overal |

K3s is de primaire keuze voor staging en productie vanwege de combinatie van lichtgewicht, CNCF conformance, en operationele eenvoud. Bij groei naar meerdere clusters of enterprise eisen: upgrade naar Rancher/RKE2 (dezelfde basis, meer management tooling).

OpenShift/OKD is een optie als het team in een Red Hat ecosysteem zit, maar de Dockerfile aanpassingen en afwijkende standaarden maken het een grotere investering.

---

### 2.2 Hosting Model

#### Vergelijkingsmatrix

| Criterium | Bare metal | Cloud VMs (self-managed K3s) | On-premises VMs | Hybrid |
|-----------|------------|------------------------------|-----------------|--------|
| **Vendor lock-in** | Geen | Minimaal (VM = commodity) | Geen | Minimaal |
| **Kosten** | Hardware CAPEX | ~€100-300/mo (3 VMs) | Hardware CAPEX | Variabel |
| **Schaalbaarheid** | Fysiek begrensd | Minuten (VM toevoegen) | Fysiek begrensd | Flexibel |
| **Controle** | Maximaal | Hoog | Maximaal | Medium |
| **Operationeel** | Alles zelf | OS + K3s zelf, hardware managed | Alles zelf | Gedeeld |
| **Data residency** | Volledig | Cloud provider afhankelijk | Volledig | Gedeeld |
| **Open source** | Ja | Ja (K3s op elke VM) | Ja | Ja |

#### Toelichting

Het hosting model is onafhankelijk van de Kubernetes distributie. K3s draait op elke Linux machine — of dat nu een Hetzner VPS van €5/maand is, een dedicated server, een on-premises VM, of een Raspberry Pi.

**Cloud VMs (aanbevolen start):**
- Huur 3 VMs bij een commodity provider (Hetzner, OVH, Scaleway, DigitalOcean, of ja, ook Azure/AWS/GCP als VMs)
- Installeer K3s: `curl -sfL https://get.k3s.io | sh -` op de eerste node, join de rest
- Geen cloud-specifieke services nodig — alles draait in K3s
- Verhuizen naar een andere provider = nieuwe VMs + K3s install + `helm install`

**On-premises:**
- Relevant als er data-residency eisen zijn of bestaande hardware beschikbaar is
- Exact dezelfde K3s setup, alleen op eigen machines

**Beslissing: Start met cloud VMs (commodity provider), K3s installatie. Verhuisbaar naar elke provider of on-prem zonder lock-in.**

---

### 2.3 Schaalbaarheid

#### 2.3.1 Service classificatie

| Service | Type | Replicas (min) | Scaling strategie | Toelichting |
|---------|------|----------------|-------------------|-------------|
| Frontend | Stateless | 2 | HPA op CPU (target 70%) | Pure SPA, alleen static files serveren. Schaalt triviaal. |
| Backend | Semi-stateless* | 2 | HPA op CPU + custom metric | Zwaarste service. Request handling is stateless, maar async webhook callbacks maken multi-replica complex. |
| MCP modules (9x) | Stateless | 1-2 | HPA op CPU per module | Elke module onafhankelijk schaalbaar. Coding en Docker zijn zwaarder dan registry/llm. |
| Keycloak | Stateless (state in DB) | 2 | HPA, min 2 voor HA | Java app, 768MB per replica. Actieve JWT sessies overleven downtime. |
| Gitea | Stateful | 1 | Geen HPA (single writer) | Git bare repos op disk. Multi-replica vereist distributed storage (niet triviaal). |
| PostgreSQL (3x) | Stateful | 3 (via CNPG) | CloudNativePG operator | 1 primary + 2 read replicas. Operator beheert failover. |
| Sandbox Control Plane | Stateful (SQLite) | 1 | Geen — single replica | SQLite kan niet gedeeld worden. Migratie naar PostgreSQL nodig voor multi-replica. |
| Sandbox Manager | Stateless | 1 | Geen — K8s API is bottleneck | Thin orchestrator die K8s Jobs aanmaakt. |

*Backend semi-stateless: `asyncio.create_task()` voor fire-and-forget webhook callbacks. Bij meerdere replicas kan een webhook op een andere replica landen dan waar de agent sessie actief is. Oplossing in §2.5.

#### 2.3.2 HPA (Horizontal Pod Autoscaler)

HPA schaalt het aantal pods horizontaal op basis van metrics. Elke stateless service krijgt een eigen HPA.

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
      stabilizationWindowSeconds: 60    # Wacht 60s voor verdere scale-up
      policies:
        - type: Pods
          value: 2                       # Max 2 pods per keer toevoegen
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300    # 5 min wachten voor scale-down (voorkom oscillatie)
```

De `behavior` sectie is cruciaal voor AI workloads: zonder stabilization window reageert HPA op elke korte spike, waardoor pods constant op- en afschalen (oscillatie).

#### 2.3.3 VPA (Vertical Pod Autoscaler)

VPA past resource requests/limits per pod aan (meer CPU/RAM per pod ipv meer pods). Wij gebruiken VPA **alleen in recommendation mode** — het geeft advies maar past niets automatisch aan. Reden: VPA in auto-mode herstart pods om nieuwe limits toe te passen, wat onacceptabel is voor langlopende agent sessies.

Workflow: VPA draait mee, we lezen periodiek de recommendations uit, en passen `values.yaml` handmatig aan.

```bash
kubectl get vpa druppie-backend -o jsonpath='{.status.recommendation}'
```

#### 2.3.4 KEDA voor bursty LLM workloads

Druppie's LLM calls zijn I/O-bound (wachten op externe API response), niet CPU-bound. CPU-based HPA reageert daardoor te laat op load spikes — de pods wachten op netwerk, niet op CPU.

**KEDA** (Kubernetes Event-Driven Autoscaling, CNCF Graduated, open source) lost dit op door te schalen op applicatie-specifieke metrics in plaats van alleen CPU/memory.

| Aanpak | Metric | Reactiviteit | Complexiteit |
|--------|--------|-------------|--------------|
| HPA op CPU | `cpu.utilization` | Traag (I/O-bound = lage CPU) | Laag |
| HPA op custom metric | `druppie_active_sessions` | Medium | Medium |
| **KEDA op queue depth** | `druppie_pending_agent_runs` (DB query via Prometheus) | **Snel** | Medium |
| KEDA scale-to-zero | Zelfde + `minReplicaCount: 0` | Snel | Medium |

KEDA is open source (Apache 2.0), draait als operator in het cluster, en werkt met elke Kubernetes distributie. Het ondersteunt 60+ event sources waaronder Prometheus, PostgreSQL, Redis, en HTTP endpoints.

Concrete toepassing voor Druppie:

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
  cooldownPeriod: 360            # Alleen voor scale-to-zero
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: druppie_pending_agent_runs
        query: sum(druppie_pending_agent_runs)
        threshold: "5"           # Scale up bij >5 pending runs
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
            - type: Percent
              value: 50          # Max 50% afschalen per keer
              periodSeconds: 60
```

Belangrijk detail: KEDA's `cooldownPeriod` geldt **alleen** bij scale-to-zero (van 0 naar 1 replica). Voor 1-to-N scaling gebruikt KEDA de Kubernetes HPA direct, inclusief de `behavior` settings hierboven. [[bron](https://docs.vllm.ai/projects/production-stack/en/latest/use_cases/autoscaling-keda.html)]

**Fasering:** Fase 1 start met HPA op CPU (simpel, werkt). Fase 2 voegt KEDA toe voor preciezere scaling op basis van daadwerkelijke workload.

---

### 2.4 Database Strategie

#### Vergelijkingsmatrix

| Criterium | Container PG (huidig) | CloudNativePG | CrunchyData PGO | Zalando PG Operator | Managed DB (cloud) |
|-----------|----------------------|---------------|------------------|---------------------|-------------------|
| **Licentie** | PostgreSQL License | Apache 2.0 | Apache 2.0 | MIT | Proprietary |
| **CNCF status** | n.v.t. | Sandbox | Geen | Geen | n.v.t. |
| **HA (auto-failover)** | Nee | Ja (<30s) | Ja | Ja | Ja |
| **Streaming replication** | Nee | Ja (sync + async) | Ja (pgBouncer) | Ja (Patroni) | Ja |
| **Continuous backup** | Nee | Barman (S3/MinIO/GCS) | pgBackRest (S3/MinIO) | WAL-G (S3/MinIO) | Automatisch |
| **Point-in-time recovery** | Nee | Ja | Ja | Ja | Ja |
| **Rolling updates** | Nee (downtime) | Ja (zero-downtime) | Ja | Ja | Automatisch |
| **Monitoring** | Handmatig | PodMonitor + Grafana | pgMonitor | Geen standaard | Cloud dashboard |
| **Connection pooling** | Nee | PgBouncer (ingebouwd) | PgBouncer (ingebouwd) | Geen standaard | Afhankelijk |
| **Operationeel effort** | Laag (dev only) | Medium | Hoog | Medium | Laag |
| **CRD count** | 0 | 6 | 19 | 9 | 0 |
| **Vendor lock-in** | Nee | Nee | Nee | Nee | **Ja** |
| **Maturity** | n.v.t. | GA (v1.29+) | GA (v5.7+) | GA (v1.12+) | n.v.t. |
| **Maintainer** | n.v.t. | EnterpriseDB + community | Crunchy Data | Zalando | Cloud provider |

#### Toelichting per optie

**CloudNativePG (aanbevolen)**

CloudNativePG is de meest Kubernetes-native PostgreSQL operator. "Kubernetes-native" betekent hier: het is ontworpen om PostgreSQL te beheren als een Kubernetes-native resource via CRDs, niet als een wrapper rond bestaande tools. Het is het enige PostgreSQL project met CNCF Sandbox status.

Wat het doet:
- Beheert de volledige PostgreSQL lifecycle: provisioning, replicatie, failover, backup, restore, upgrades
- 1 primary + N read replicas met streaming replication
- Automatische failover bij primary failure (<30s)
- Continuous backup naar S3-compatible object storage (MinIO, Ceph, of cloud S3)
- Point-in-time recovery: herstel de database naar elk moment in de tijd
- Zero-downtime rolling updates voor minor PostgreSQL versies
- Ingebouwde PgBouncer connection pooling
- Prometheus metrics export met PodMonitor

Eén CloudNativePG operator beheert alle 3 Druppie databases (app, keycloak, gitea) als aparte Cluster CRDs.

**Belangrijk: Security advisory (mei 2026):**
CloudNativePG v1.29.1 (8 mei 2026) fixt **CVE-2026-44477** (CVSS v4: 9.4, Critical) — superuser privilege escalation + arbitrary OS command execution via de metrics exporter. Dezelfde release fixt ook drie onafhankelijke HA failover bugs. **Altijd v1.29.1+ gebruiken.** [[bron](https://cloudnative-pg.io/releases/cloudnative-pg-1-29.1-released/)]

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
    storageClass: longhorn        # of local-path, of elke CSI driver
  backup:
    barmanObjectStore:
      destinationPath: "s3://druppie-backups/db"
      endpointURL: "http://minio:9000"   # MinIO voor on-prem S3
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

Crunchy Postgres Operator is ouder en feature-rijker dan CloudNativePG, maar ook complexer. Het gebruikt 19 CRDs (vs 6 voor CNPG) en heeft pgBackRest als backup tool (krachtig maar complexere configuratie). PGO heeft geen CNCF status maar is goed onderhouden door Crunchy Data.

Wanneer PGO overwegen: als je al ervaring hebt met pgBackRest, of specifieke features nodig hebt die CNPG (nog) niet biedt (bijv. pgBouncer connection pooling tuning, multi-cluster replication).

**Zalando PostgreSQL Operator**

De Zalando operator (Patroni-gebaseerd) was een van de eerste PG operators en wordt intern bij Zalando gebruikt voor 1000+ databases. Het is minder actief onderhouden dan CNPG en PGO, en heeft geen ingebouwde backup oplossing (WAL-G moet apart geconfigureerd worden).

**Beslissing: CloudNativePG voor alle omgevingen.**

Reden: CNCF status, laagste operationeel effort van de operators, actieve community, volledige feature set voor Druppie's behoeften. Container PostgreSQL blijft beschikbaar in het Helm chart voor development.

---

### 2.5 High Availability

#### Wat betekent HA concreet voor Druppie?

| Component | Wat gebeurt er bij downtime? | Impact | Minimale HA |
|-----------|------------------------------|--------|-------------|
| **PostgreSQL** | Alle API calls falen, agents stoppen, UI toont errors | **Kritiek** | 3 replicas (CNPG auto-failover) |
| **Backend** | Geen chat, geen agent execution, webhooks falen | **Hoog** | 2+ replicas + PDB |
| **Keycloak** | Nieuwe logins falen. Bestaande sessies werken door (JWT is self-contained) | Medium | 2 replicas |
| **Frontend** | Gebruikers zien 502/503 | Medium | 2 replicas |
| **Gitea** | Git operations falen, agent code pushes gestopt | Medium | 1 replica + PVC + backup |
| **MCP modules** | Specifieke agent tools onbeschikbaar (bijv. geen file ops zonder module-coding) | Laag-Medium | 1-2 replicas per module |
| **Sandbox control plane** | Nieuwe sandbox tasks falen, lopende sandboxes draaien door | Medium | 1 replica (SQLite beperking) |

#### HA instrumenten

**PodDisruptionBudget (PDB):** Garandeert dat Kubernetes nooit alle pods tegelijk weghaalt tijdens onderhoud (node drain, rolling update).

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

**Pod Anti-Affinity:** Spreidt pods over verschillende nodes zodat een node failure niet alle replicas raakt.

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

**Graceful shutdown:** Backend pods moeten lopende LLM calls afronden voor ze stoppen. Configureer `terminationGracePeriodSeconds: 60` en implementeer SIGTERM handling in de FastAPI app die nieuwe requests weigert maar actieve afrondt.

#### Backend multi-replica uitdaging

Het backend gebruikt `asyncio.create_task()` voor fire-and-forget webhook callbacks van sandboxes. Bij meerdere replicas kan een webhook op een andere replica landen dan waar de agent sessie actief is in memory.

| Oplossing | Complexity | Robuustheid | Extra infra |
|-----------|------------|-------------|-------------|
| Sticky sessions (Ingress) | Laag | Fragiel (pod restart = sessie kwijt) | Geen |
| Redis task queue | Medium | Robuust | Redis |
| **Database-driven resume** | Medium | **Zeer robuust** | Geen |

**Aanbeveling: Database-driven resume.** De huidige `reconstruct_from_db()` functie in `druppie/agents/message_history.py` rebuildt al agent state vanuit de database. De webhook handler hoeft alleen de ToolCall record in de DB bij te werken — elke backend replica kan de agent vervolgens oppakken en doorgaan. Dit sluit aan bij het bestaande patroon en vereist geen nieuwe infrastructuur.

---

### 2.6 Sandbox Strategie in Kubernetes

Dit is de **meest complexe uitdaging**. De sandbox-manager spawnt Docker containers via de Docker socket, wat in Kubernetes niet native werkt.

#### Vergelijkingsmatrix

| Criterium | Docker socket mount | DinD sidecar | K8s Jobs (handmatig) | agent-sandbox (SIG Apps) | Kata Containers | gVisor | Sysbox |
|-----------|--------------------|--------------|--------------------|--------------------------|-----------------|--------|--------|
| **Licentie** | n.v.t. | Apache 2.0 | n.v.t. (K8s native) | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **Security** | Slecht (root op host) | Matig | Goed | Goed-Zeer goed | Zeer goed (VM isolatie) | Goed (user-space kernel) | Goed (user namespaces) |
| **Isolatie level** | Geen (host Docker) | Container-in-container | Pod-level | Pod + runtime | **VM-level (guest kernel)** | Kernel-level (syscall filter) | Kernel-level (user NS) |
| **Cold start** | ~1-2s | ~3-5s | ~3-5s (pod scheduling) | <1s (WarmPool) | ~150-600ms | ~50-100ms | ~1-2s |
| **Memory overhead** | 0 | ~100MB | 0 | ~20-50MB (WarmPool) | ~60-120MB per pod | ~20-50MB per pod | ~50MB |
| **K8s native** | Nee | Nee | Ja | **Ja (CRD-based)** | Ja (RuntimeClass) | Ja (RuntimeClass) | Nee (CRI-O only) |
| **Warm pool support** | Nee | Nee | Zelf bouwen | **Ja (SandboxWarmPool CRD)** | Nee | Nee | Nee |
| **Python SDK** | Docker SDK | Docker SDK | kubernetes client | **Ja** | Nee | Nee | Nee |
| **Maturity** | n.v.t. | Stabiel | Stabiel | **v1alpha1 (v0.4.6)** | Stabiel (3.x) | Stabiel | Community-maintained |
| **Productie bewezen** | Overal | Veel | Veel | Vroeg stadium | Northflank (2M+ microVMs/mo) | Google (GKE Sandbox) | Beperkt |
| **Operationele pages** | n.v.t. | Onbekend | Laag | Onbekend | 3.4x vs standaard | Laag | Onbekend |

#### Agent Sandbox (kubernetes-sigs/agent-sandbox) — primaire keuze

Het Kubernetes SIG Apps project **Agent Sandbox** is in november 2025 gelanceerd door Google op KubeCon Atlanta. Het biedt precies wat Druppie nodig heeft: een CRD-gebaseerde operator voor het spawnen van geïsoleerde sandbox-omgevingen voor AI-agents. [[bron](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)]

Het officiële Kubernetes blog beschrijft het probleem: *"While you could theoretically approximate this by stringing together a StatefulSet of size 1, a headless Service, and a PersistentVolumeClaim for every single agent, managing this at scale becomes an operational nightmare."*

Wat Agent Sandbox biedt:
- **Sandbox CRD:** Creëert een geïsoleerde pod met configurable runtime (gVisor, Kata, of standaard)
- **SandboxTemplate:** Herbruikbare sandbox definities (resources, security context, volumes)
- **SandboxClaim:** Request-based model — agents claimen een sandbox uit een pool
- **SandboxWarmPool:** Pre-warmed pods die klaarstaan, waardoor cold start < 1 seconde
- **Python SDK:** Directe integratie met onze Python sandbox-manager
- **Lifecycle management:** Automatische cleanup, TTL, resource tracking

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

**Risico:** v1alpha1 API kan veranderen voor GA. Mitigatie: fallback op K8s Jobs (zie onder).

#### Fallback: Kubernetes Jobs

Als Agent Sandbox te onvolwassen blijkt, is de fallback om `docker_manager.py` te vervangen door een `k8s_manager.py` die Kubernetes Jobs aanmaakt via de `kubernetes` Python client:

| Docker flag (huidig) | Kubernetes equivalent |
|---------------------|----------------------|
| `--memory=4g` | `resources.limits.memory: 4Gi` |
| `--cpus=2` | `resources.limits.cpu: "2"` |
| `--cap-drop=ALL --cap-add=NET_RAW` | `securityContext.capabilities` |
| `--security-opt=no-new-privileges` | `securityContext.allowPrivilegeEscalation: false` |
| `--network=sandbox-network` | NetworkPolicy (dedicated namespace) |
| `--pids-limit=4096` | RuntimeClass of cgroup configuratie |

#### Runtime isolatie: gVisor vs Kata Containers

Beide zijn open source runtimes die als `RuntimeClass` in Kubernetes draaien. Agent Sandbox ondersteunt beide.

| Criterium | gVisor (runsc) | Kata Containers (3.x) |
|-----------|----------------|----------------------|
| **Hoe het werkt** | User-space kernel die syscalls filtert en vertaalt. Container deelt geen kernel met host. | Elke container draait in een eigen lightweight VM met dedicated guest kernel. |
| **Isolatie** | Sterk — 370+ syscalls geïmplementeerd in Go, onbekende syscalls geblokkeerd | Zeer sterk — hardware virtualisatie (AMD-V/VT-x), volledige kernel isolatie |
| **Cold start** | ~50-100ms | ~150-600ms |
| **Memory overhead** | ~20-50MB per pod | ~60-120MB per pod |
| **Performance impact** | Laag voor I/O, hoger voor syscall-heavy workloads | 8-12% steady-state overhead |
| **Compatibility** | Meeste Linux programma's werken, sommige syscalls ontbreken | Vrijwel 100% Linux compatibility (volledige kernel) |
| **Operationeel** | Simpeler (geen VM management) | Complexer, 3.4x meer on-call pages dan standaard containers |
| **Productie** | Google GKE Sandbox (miljoenen containers) | Northflank (2M+ microVMs/maand) |
| **Geschikt voor Druppie** | **Ja** — code execution + git push = I/O bound, niet syscall-heavy | Ja, maar overkill voor huidige use case |

**Aanbeveling: Start met gVisor.** Lagere overhead, simpeler operationeel, voldoende isolatie voor code execution sandboxes. Upgrade naar Kata als er multi-tenant isolatie-eisen komen (bijv. sandboxes van verschillende organisaties op dezelfde nodes).

**Sysbox — niet aanbevolen:**
- Officieel alleen CRI-O support; containerd integratie "still evolving" (nestybox/sysbox#997)
- Community-maintained op best-effort basis na Nestybox acquisitie door Docker
- Deelt host kernel — zwakkere isolatie dan gVisor en Kata

#### Codebase wijzigingen

1. `sandbox-manager`: Vervang `docker_manager.py` door `k8s_manager.py` (Kubernetes Python client of Agent Sandbox SDK)
2. NetworkPolicy: dedicated `druppie-sandboxes` namespace, alleen communicatie met control-plane
3. Container registry: sandbox image via registry (Harbor, zie §2.9) ipv `kind load`
4. Resource limits: Configureerbaar via Helm values (al voorbereid in `values.yaml` als `sandbox.memoryLimit`/`sandbox.cpuLimit`)

---

### 2.7 Shared Volume Strategie (RWX)

Het `workspace` volume wordt gedeeld door 4 services: backend, module-coding, module-docker, module-data-access. Dit vereist ReadWriteMany (RWX) — meerdere pods schrijven naar hetzelfde volume.

#### Vergelijkingsmatrix

| Criterium | NFS server (handmatig) | Longhorn | Rook-Ceph | OpenEBS (Mayastor) | SeaweedFS |
|-----------|----------------------|----------|-----------|-------------------|-----------|
| **Licentie** | GPL (NFS kernel) | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **CNCF status** | n.v.t. | CNCF Sandbox | CNCF Graduated | CNCF Sandbox | Geen |
| **RWX support** | Ja (native) | Ja (via NFS export) | Ja (CephFS) | Nee (alleen RWO) | Ja (FUSE mount) |
| **Performance** | Medium (network I/O) | Medium | Goed | Zeer goed (NVMe) | Medium |
| **Replicatie** | Nee (single point of failure) | Ja (2-3 replicas) | Ja (configurable) | Ja (sync) | Ja |
| **Operationeel effort** | Laag | **Laag** (Rancher UI) | Hoog | Medium | Medium |
| **Disk overhead** | 0% | 2-3x (replica factor) | 2-3x (replica factor) | 2-3x | 1-3x |
| **Minimale nodes** | 1 | 3 (voor replicatie) | 3 | 3 | 3 |
| **Geschikt voor Druppie** | Ja (dev/staging) | **Ja** | Ja (maar overkill) | Nee (geen RWX) | Ja |

#### Toelichting

**Longhorn (aanbevolen)**

Longhorn is een CNCF Sandbox distributed block storage system, gebouwd door Rancher Labs. Het biedt replicated block storage met snapshots, backups, en disaster recovery. RWX support werkt via een ingebouwde NFS server per volume.

Waarom Longhorn voor Druppie:
- Lichtgewicht: ontworpen voor edge en small clusters (past bij K3s)
- RWX via NFS: elke RWX PVC krijgt automatisch een NFS share-manager pod
- Eenvoudige installatie: `helm install longhorn longhorn/longhorn`
- UI dashboard voor volume management
- Backup naar S3-compatible storage (MinIO)
- Integreert naadloos met K3s en Rancher

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

**Rook-Ceph** is krachtiger (object + block + file storage) maar vereist meer resources (3+ dedicated storage nodes, meer RAM) en is complexer te beheren. Overkill voor Druppie's workspace volume.

**NFS server** (simple pod met NFS export) werkt voor dev/staging maar is een single point of failure zonder replicatie.

**Fase 2 doel — per-session workspace eliminatie:**

De architectureel betere oplossing is het shared workspace volume volledig te elimineren:
- Elke agent session krijgt een eigen `emptyDir` of ephemeral PVC
- MCP modules communiceren via de backend als proxy (geen directe volume access)
- Dit elimineert de RWX dependency volledig en verbetert de isolatie

---

### 2.8 Deployment Strategie

#### Vergelijkingsmatrix

| Criterium | Helm + CI/CD | ArgoCD | FluxCD |
|-----------|-------------|--------|--------|
| **Licentie** | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **CNCF status** | CNCF Graduated (Helm) | CNCF Graduated | CNCF Graduated |
| **Model** | Push-based (CI pusht naar cluster) | Pull-based (cluster pull van git) | Pull-based |
| **GitOps** | Nee (git = source, niet state) | **Ja** (git = desired state) | **Ja** |
| **Drift detection** | Nee | **Ja** (auto-detect config drift) | **Ja** |
| **Rollback** | `helm rollback` (handmatig) | Git revert = auto rollback | Git revert = auto rollback |
| **Multi-env** | Helm values per env | ApplicationSet | Kustomize overlays |
| **UI** | Geen | **Web dashboard** | Geen (CLI only) |
| **Helm support** | Native | Ja (Helm chart rendering) | Ja (HelmRelease CRD) |
| **Leercurve** | Laag | Medium | Medium |
| **Extra infra** | Geen | ArgoCD server in cluster | Flux controllers in cluster |
| **Notificaties** | Via CI (GitHub Actions) | Slack/webhook integratie | Slack/webhook integratie |

#### Toelichting

**Fase 1: Helm + CI/CD (GitHub Actions)**

Het Helm chart bestaat al en werkt op Kind. De snelste weg naar productie is een CI/CD pipeline die:
1. Docker images bouwt en pusht naar een container registry
2. `helm upgrade` uitvoert op het K3s cluster

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

Push-based deployment is simpel en werkt, maar heeft nadelen: als iemand handmatig iets wijzigt in het cluster (kubectl edit), detecteert niemand die drift.

**Fase 2: ArgoCD**

ArgoCD maakt het cluster declaratief: de git repository is de single source of truth. ArgoCD vergelijkt continu de gewenste state (git) met de actuele state (cluster) en reconcilieert automatisch.

Voeg ArgoCD toe wanneer:
- Er meerdere omgevingen zijn (dev/staging/prod) — ApplicationSet maakt dit trivial
- Het team groeit en er behoefte is aan audit trail (wie deployede wat wanneer)
- Er drift detection nodig is (voorkomen dat handmatige cluster wijzigingen onopgemerkt blijven)

ArgoCD vs FluxCD: ArgoCD heeft een web dashboard (handig voor teams), FluxCD is meer CLI-driven. Beide zijn CNCF Graduated. ArgoCD is populairder (16k+ GitHub stars) en heeft betere Helm support.

---

### 2.9 Container Registry

#### Vergelijkingsmatrix

| Criterium | Harbor | Gitea Container Registry | Docker Distribution | Zot | GitHub GHCR |
|-----------|--------|--------------------------|--------------------|----|-------------|
| **Licentie** | Apache 2.0 | MIT | Apache 2.0 | Apache 2.0 | Proprietary |
| **CNCF status** | CNCF Graduated | Geen | Geen | Geen | n.v.t. |
| **Vulnerability scanning** | Ja (Trivy ingebouwd) | Nee | Nee | Ja (Trivy) | Ja |
| **Image signing** | Ja (Cosign/Notary) | Nee | Nee | Ja (Cosign) | Ja |
| **RBAC** | Ja (project-based) | Via Gitea users | Nee | Ja | Via GitHub |
| **Replication** | Ja (multi-registry) | Nee | Nee | Nee | n.v.t. |
| **Garbage collection** | Ja | Ja | Ja | Ja | Automatisch |
| **Self-hosted** | Ja | Ja (al in Druppie!) | Ja | Ja | Nee |
| **Helm chart storage** | Ja (OCI) | Ja (OCI) | Nee | Ja (OCI) | Ja |
| **Operationeel effort** | Medium | **Laag (al draait)** | Laag | Laag | Geen |

**Beslissing: Gitea Container Registry voor fase 1, Harbor voor fase 2.**

Gitea (die al in Druppie draait) heeft een ingebouwde OCI-compatible container registry. Dit betekent nul extra infrastructuur — we pushen images naar dezelfde Gitea instance die al onze git repos host.

Harbor toevoegen als er vulnerability scanning, image signing, of multi-registry replication nodig is.

---

### 2.10 Networking / Ingress

#### Vergelijkingsmatrix

| Criterium | NGINX Ingress | Traefik | HAProxy Ingress | Cilium Ingress |
|-----------|--------------|---------|-----------------|----------------|
| **Licentie** | Apache 2.0 | MIT | Apache 2.0 | Apache 2.0 |
| **CNCF status** | Geen (K8s SIG) | Geen | Geen | CNCF Graduated |
| **Protocol** | HTTP/HTTPS/gRPC/WebSocket | HTTP/HTTPS/gRPC/TCP/UDP | HTTP/HTTPS/TCP | HTTP/HTTPS/gRPC |
| **Auto-discovery** | Via Ingress resources | Via Ingress + IngressRoute CRD | Via Ingress | Via Ingress + Gateway API |
| **TLS termination** | Ja (cert-manager) | Ja (ingebouwd ACME + cert-manager) | Ja | Ja |
| **Rate limiting** | Via annotations | Via middleware CRD | Via config | Via CiliumNetworkPolicy |
| **WAF** | ModSecurity plugin | Nee (apart) | Nee | Nee |
| **Observability** | Prometheus metrics | Prometheus + Datadog + Jaeger | Prometheus | Hubble (eBPF) |
| **K3s standaard** | Nee | **Ja** | Nee | Nee |
| **Performance** | Goed | Goed | Zeer goed | Zeer goed (eBPF) |
| **Configuratie** | Annotations (kan rommelig worden) | Middleware CRDs (gestructureerd) | Config file | Gateway API (standaard K8s) |
| **Leercurve** | Laag | Laag-Medium | Medium | Medium-Hoog |

**Beslissing: Traefik (K3s standaard), met NGINX als alternatief.**

K3s installeert Traefik standaard als ingress controller. Ons Helm chart gebruikt nu NGINX (voor Kind), maar Traefik biedt voordelen:
- Ingebouwde ACME/Let's Encrypt support (geen aparte cert-manager nodig, hoewel cert-manager ook werkt)
- Middleware CRDs voor rate limiting, headers, auth — schoner dan NGINX annotations
- Dashboard voor real-time traffic monitoring
- IngressRoute CRD voor complexere routing regels

Het Helm chart moet beide ondersteunen via `global.ingress.className: traefik | nginx`.

```yaml
# Traefik IngressRoute (alternatief voor standaard Ingress)
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

TLS voor productie via **cert-manager** (open source, CNCF project) + Let's Encrypt:

```bash
helm install cert-manager jetstack/cert-manager --set installCRDs=true
```

---

### 2.11 Secrets Management

#### Vergelijkingsmatrix

| Criterium | Helm values (huidig) | Sealed Secrets | External Secrets Operator | HashiCorp Vault | SOPS + age |
|-----------|---------------------|----------------|---------------------------|-----------------|------------|
| **Licentie** | Apache 2.0 (Helm) | Apache 2.0 | Apache 2.0 | BSL 1.1 (niet open source!) | Apache 2.0 / MIT |
| **Versleuteld in git** | Nee (plaintext) | **Ja** (asymmetrisch) | Nee (secrets in extern systeem) | Nee | **Ja** (symmetrisch/asymmetrisch) |
| **Automatische rotation** | Nee | Nee | **Ja** (sync interval) | **Ja** | Nee |
| **Audit trail** | Nee | Via git history | Via external store | **Ja (uitgebreid)** | Via git history |
| **Extra infra nodig** | Geen | Controller in cluster | Controller + external store | **Vault cluster (3+ nodes)** | Geen |
| **Complexiteit** | Laag | **Laag** | Medium | **Hoog** | **Laag** |
| **Multi-cluster** | Nee | Nee (per-cluster keys) | Ja | Ja | Ja (zelfde key) |
| **Backup/recovery** | n.v.t. | Cluster key backup! | Via external store | Vault HA + unsealing | Key file backup |
| **Druppie secrets** | API keys, DB passwords, HMAC secrets | Idem, versleuteld | Idem, extern beheerd | Idem, Vault managed | Idem, versleuteld |

**Let op: HashiCorp Vault is sinds 2023 NIET meer open source** (BSL 1.1 licentie). Dit conflicteert met ons open source uitgangspunt. OpenBao is de open source fork (MPL 2.0), maar is minder volwassen.

**Beslissing: Sealed Secrets voor fase 1, SOPS + age als alternatief.**

**Sealed Secrets** (Bitnami, v0.27+) werkt als volgt:
1. Een controller in het cluster genereert een asymmetrisch sleutelpaar
2. Je versleutelt Kubernetes Secrets lokaal met de publieke sleutel: `kubeseal < secret.yaml > sealed-secret.yaml`
3. De versleutelde SealedSecret kan veilig in git
4. De controller in het cluster ontsleutelt het naar een gewone Kubernetes Secret

```bash
# Secret aanmaken en versleutelen
kubectl create secret generic druppie-secrets \
  --from-literal=zai-api-key=sk-xxx \
  --from-literal=db-password=xxx \
  --dry-run=client -o yaml | kubeseal > sealed-secrets.yaml

# Commit naar git (veilig — versleuteld)
git add sealed-secrets.yaml && git commit -m "Add sealed secrets"
```

**Belangrijk:** Maak een backup van de Sealed Secrets controller private key! Zonder deze key kun je bestaande sealed secrets niet ontsleutelen na een cluster rebuild.

**SOPS + age** is een lichter alternatief: versleutel YAML files direct met `sops` en een `age` key. Geen controller nodig, werkt met Helm via `helm-secrets` plugin. Nadeel: geen automatische sync — je moet na elke wijziging deployen.

---

### 2.12 Monitoring & Observability

#### Vergelijkingsmatrix

| Criterium | kube-prometheus-stack | Victoria Metrics | Grafana Loki (logging) | Jaeger (tracing) |
|-----------|----------------------|------------------|----------------------|------------------|
| **Licentie** | Apache 2.0 | Apache 2.0 | AGPL 3.0 | Apache 2.0 |
| **Functie** | Metrics + alerting | Metrics (Prometheus-compatible) | Log aggregatie | Distributed tracing |
| **Resource usage** | Medium-Hoog | **Laag** (2-5x efficiënter) | Medium | Laag |
| **Prometheus-compatible** | Native | Ja (drop-in replacement) | n.v.t. | n.v.t. |
| **Grafana dashboards** | Ingebouwd | Ja | Ingebouwd | Via Grafana |
| **Operationeel** | Medium | Laag | Medium | Laag |

**Beslissing: kube-prometheus-stack (Prometheus + Grafana + Alertmanager).**

Dit is de de-facto standaard voor Kubernetes monitoring. Eén `helm install` geeft je:
- Prometheus voor metrics (CPU, memory, custom app metrics)
- Grafana voor dashboards
- Alertmanager voor notificaties (Slack, email)
- Node-exporter voor host metrics
- kube-state-metrics voor Kubernetes object metrics

CloudNativePG exporteert automatisch PostgreSQL metrics via PodMonitor. KEDA, Traefik, en Keycloak hebben ook Prometheus endpoints.

---

### 2.13 Infrastructure Provisioning & Node Autoscaling

#### Probleemstelling

HPA en KEDA schalen pods, maar wanneer alle 3 nodes vol zijn, heeft Kubernetes geen plek om nieuwe pods te schedulen. We hebben automatische node-level autoscaling nodig: nieuwe Hetzner VMs inrichten wanneer er capaciteit nodig is, en ze verwijderen wanneer ze idle zijn.

#### Vergelijkingsmatrix

| Criterium | hetzner-k3s (CLI) | kube-hetzner (Terraform) | Custom Terraform | Handmatig |
|-----------|-------------------|--------------------------|------------------|-----------|
| **Licentie** | MIT | MIT | N.v.t. | n.v.t. |
| **Type** | CLI tool (1 YAML config) | Terraform module | Eigen Terraform | SSH + scripts |
| **OS** | Ubuntu (default), Debian, others | MicroOS (openSUSE) | Kies zelf | Kies zelf |
| **Cluster setup** | 2-3 minuten | ~5 minuten | Variabel | 30+ min |
| **Autoscaling ingebouwd** | Ja (Cluster Autoscaler + CCM + CSI) | Ja (Cluster Autoscaler + CCM + CSI) | Nee (zelf configureren) | Nee |
| **Auto-upgrades K3s** | Ja (System Upgrade Controller) | Ja (System Upgrade Controller) | Nee | Nee |
| **IaC in git** | Ja (YAML config) | Ja (Terraform state) | Ja | Nee |
| **Leercurve** | Laag | Medium (Terraform kennis nodig) | Hoog | Laag |
| **Flexibiliteit** | Medium | Hoog (190+ variabelen) | Maximaal | Geen |
| **Community** | ⭐ 3.5k+ GitHub stars | ⭐ 3.8k+ GitHub stars | n.v.t. | n.v.t. |
| **Multi-cluster** | Nee | Ja (Terraform workspaces) | Ja | Nee |
| **Production ready** | Ja | Ja | Afhankelijk van implementatie | Nee |

#### Toelichting: Two-tier autoscaling architectuur

Pod scaling en node scaling zijn twee aparte lagen die samenwerken:

**Tier 1 — Pod Autoscaling (HPA + KEDA):**
- Bewaakt CPU/memory/custom metrics per pod
- Voegt pod replicas toe of verwijdert ze binnen bestaande nodes
- Snel (seconden): nieuwe pod start op bestaande node
- Begrensd door beschikbare node capaciteit

**Tier 2 — Node Autoscaling (Cluster Autoscaler):**
- Bewaakt pods die niet gescheduled kunnen worden (Pending state)
- Creëert nieuwe Hetzner VMs via Hetzner Cloud API
- Cloud-init script installeert automatisch K3s agent en voegt toe aan cluster
- Verwijdert idle nodes na een configureerbare timeout
- Trager (30-60s): VM provisioning + K3s join

Flow:
```
Load spike → HPA creates pods → Nodes full? → Pending pods
                                                  ↓
                              Cluster Autoscaler detecteert Pending pods
                                                  ↓
                              Hetzner API: maak nieuwe VM aan
                                                  ↓
                              Cloud-init: installeer K3s agent, join cluster
                                                  ↓
                              Node ready → Pending pods gescheduled
```

#### Toelichting per optie

**hetzner-k3s (aanbevolen voor Druppie)**

CLI tool door Vito Botta. Eén YAML config file definieert het hele cluster: masters, workers, autoscaling pools, networking. Geen Terraform nodig. Installeert automatisch: Hetzner CCM, CSI driver, System Upgrade Controller, en Cluster Autoscaler.

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

Sterktes: Ubuntu support, simpelste setup, batteries included, actieve community.
Zwaktes: Single maintainer, minder flexibel dan Terraform modules.

**kube-hetzner (Terraform module)**

Meest populaire Terraform module voor K3s op Hetzner. Gebruikt MicroOS (openSUSE), een immuut, transactioneel OS ontworpen voor containers. Diepe integratie met auto-upgrades, Longhorn, meerdere CNI opties.

Sterktes: Meest compleet, IaC standaard, multi-cluster, MicroOS security voordelen.
Zwaktes: Vereist Terraform kennis, MicroOS leercurve, geen Ubuntu.

**Kubernetes Cluster Autoscaler (upstream Hetzner provider)**

Onafhankelijk van provisioning tool: de daadwerkelijke autoscaling wordt uitgevoerd door de officiële Kubernetes Cluster Autoscaler met ingebouwde Hetzner Cloud provider (`--cloud-provider=hetzner`). Dit is upstream Kubernetes, actief onderhouden (commits van mei 2026).

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

**Hetzner Cloud Controller Manager (CCM)** — Verplichte dependency. Integreert Kubernetes met Hetzner APIs voor node lifecycle, load balancer provisioning, en netwerk routes. De CCM regelt geen autoscaling zelf, het is de brug tussen K8s en Hetzner die de Cluster Autoscaler nodig heeft.

**Karpenter** — NIET beschikbaar voor Hetzner. Er bestaat geen provider en het staat niet op de roadmap. Karpenter ondersteunt alleen AWS, Azure, GCP, en een paar anderen. Geen optie.

#### Beslissing: hetzner-k3s (CLI) + Cluster Autoscaler (upstream)

| Onderdeel | Keuze | Reden |
|-----------|-------|-------|
| **Cluster provisioning** | hetzner-k3s CLI | Ubuntu, simpelste setup, alles ingebouwd, 2-3 min cluster |
| **Node autoscaling** | Kubernetes Cluster Autoscaler (Hetzner provider) | Upstream, production-ready, actief onderhouden |
| **Cloud integration** | Hetzner CCM | Verplicht — node lifecycle, LB provisioning |
| **Storage integration** | Hetzner CSI driver | Persistent volumes via Hetzner block storage |
| **Auto-upgrades** | System Upgrade Controller | K3s en OS updates met rollback |

---

## 3. Schaalbaarheidsvisie — Architectuur Suggesties

De huidige Druppie-architectuur is ontworpen voor single-instance Docker Compose. Om echt schaalbaar te worden op Kubernetes zijn er architectuurwijzigingen nodig. Deze sectie beschrijft suggesties — geen van deze vereist de huidige codebase als beperking.

> **Huidige staat samengevat:** Backend draait op 1 hardcoded replica (`backend-deployment.yaml:9`). Session tracking is in-memory via `_active_session_tasks` dict in `core/background_tasks.py` — dit voorkomt multi-replica zonder race conditions. Workspace PVC is `ReadWriteOnce` — blokkeert scheduling naar andere nodes. Sandbox-manager spawnt containers via `docker run` subprocess calls. Geen HPA, geen PDB, geen autoscaling geconfigureerd in het Helm chart.

### 3.1 Event-Driven Backend (huidige bottleneck elimineren)

**Probleem:** Het backend verwerkt agent sessies via `create_session_task()` (`core/background_tasks.py`), dat een in-memory `dict[UUID, asyncio.Task]` bijhoudt per session_id. Dit voorkomt dubbele runs binnen één replica, maar bij meerdere replicas is er **geen cross-replica coördinatie** — twee replicas kunnen tegelijk dezelfde sessie draaien. De sandbox webhook (`api/routes/sandbox.py`) landt op een willekeurige replica via de Service load balancer, niet noodzakelijk op de replica die de agent sessie host.

**Suggestie: Message queue als backbone**

Introduceer een message broker (Redis Streams, NATS, of RabbitMQ — allen open source) als ontkoppelingslaag:

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

| Broker | Licentie | Persistence | Throughput | Complexiteit | Aanbeveling |
|--------|----------|-------------|-----------|--------------|-------------|
| **Redis Streams** | BSD 3-Clause | Ja (AOF/RDB) | Zeer hoog | Laag | **Fase 2** |
| **NATS JetStream** | Apache 2.0 | Ja | Zeer hoog | Laag | Alternatief |
| RabbitMQ | MPL 2.0 | Ja | Hoog | Medium | Alternatief |

Voordelen:
- Elke backend replica kan elke taak oppakken (geen sticky sessions)
- Webhook → queue → willekeurige worker pakt het op
- Scale workers onafhankelijk van API pods
- Failed workers → message terug in queue → automatic retry
- Backpressure: als workers vol zijn, groeien de queues, HPA/KEDA schaalt workers op

### 3.2 MCP Module Mesh — Sidecar vs Centralized

**Probleem:** MCP modules zijn nu standalone HTTP services met een shared workspace volume (RWX). Dit creëert een NFS/storage bottleneck en maakt scaling complex.

**Suggestie A: Sidecar pattern**

Draai MCP modules als sidecars naast de backend pod. Elke backend replica heeft zijn eigen set MCP modules:

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

Voordelen:
- Geen netwerk latency naar MCP modules (localhost)
- Geen shared volume nodig (elke pod heeft eigen emptyDir)
- Schaalt automatisch mee met backend replicas
- Simpelere NetworkPolicy (alles in één pod)

Nadelen:
- Meer resources per pod (elke replica draait alle modules)
- Modules niet onafhankelijk schaalbaar
- Grotere pod = langzamere scheduling

**Suggestie B: Per-session microservices (geavanceerd)**

Spawn MCP modules on-demand per agent sessie als tijdelijke pods:

```
Session start → spawn module-coding pod (session-123)
             → spawn module-docker pod (session-123)
Session end  → cleanup pods
```

Dit is wat Agent Sandbox conceptueel biedt — maar dan voor MCP modules ipv sandboxes. Voordelen: perfecte isolatie, geen shared state, schaal = meer sessie-pods.

### 3.3 Database Partitioning

**Probleem:** Eén PostgreSQL database voor alles. Bij groei worden de `tool_calls` en `llm_calls` tabellen enorm (elke agent sessie genereert tientallen records).

**Suggesties:**

| Strategie | Wat | Wanneer |
|-----------|-----|---------|
| **Read replicas** | CNPG read-only endpoints voor UI queries | >1000 sessies |
| **Table partitioning** | Partitioneer `tool_calls` en `llm_calls` op `created_at` (maandelijks) | >100k records |
| **Archive strategie** | Verplaats oude sessies naar cold storage (S3/MinIO als Parquet) | >6 maanden data |
| **Aparte DB per concern** | Eigen CNPG cluster voor audit/logging vs operational data | Enterprise scale |

```sql
-- Voorbeeld: table partitioning op datum
CREATE TABLE tool_calls (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL,
    ...
) PARTITION BY RANGE (created_at);

CREATE TABLE tool_calls_2026_06 PARTITION OF tool_calls
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

### 3.4 Sandbox Pool Pre-warming

**Probleem:** Cold start voor sandboxes (pod scheduling + container pull + init) kost 3-10 seconden. Dit voelt traag voor interactieve sessies.

**Suggesties:**

| Strategie | Latency | Cost | Complexiteit |
|-----------|---------|------|--------------|
| **Agent Sandbox WarmPool** | <1s | Idle pods kosten resources | Laag (CRD config) |
| **Pre-pulled images** | ~2-3s (skip pull) | Disk space op nodes | Laag (DaemonSet) |
| **Snapshot/restore** | ~1-2s | Snapshot storage | Medium |
| **Dedicated sandbox nodes** | ~3s (geen scheduling contention) | Dedicated hardware | Laag (node taint) |

Agent Sandbox WarmPool is het meest elegant:

```yaml
apiVersion: sandbox.k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: coding-sandboxes
spec:
  templateRef: druppie-coding-sandbox
  minReady: 3       # Altijd 3 warme sandboxes beschikbaar
  maxSize: 20       # Max 20 totaal
  ttlSecondsAfterIdle: 600  # Cleanup na 10 min idle
```

### 3.5 Multi-Tenant Schaalbaarheid

Als Druppie meerdere organisaties moet bedienen:

| Isolation level | Hoe | Overhead | Security |
|----------------|-----|----------|----------|
| **Namespace per tenant** | Aparte K8s namespace met ResourceQuota en NetworkPolicy | Laag | Medium |
| **Node pool per tenant** | Dedicated nodes via taints/tolerations | Hoog | Hoog |
| **Cluster per tenant** | Aparte K3s clusters via Rancher | Zeer hoog | Zeer hoog |
| **Virtuele clusters** | vCluster (open source) — virtuele K8s clusters in namespaces | Medium | Hoog |

Voor Druppie is **namespace per tenant + vCluster** de sweet spot: volledige Kubernetes API isolatie zonder de overhead van aparte clusters. vCluster (open source, Loft Labs) creëert virtuele Kubernetes clusters in bestaande namespaces — elke tenant denkt een eigen cluster te hebben.

### 3.6 Control Plane Schaalbaarheid

**Probleem:** De sandbox-control-plane gebruikt SQLite — kan niet over meerdere replicas.

**Suggestie:** Migreer control plane storage naar PostgreSQL (kan dezelfde CNPG cluster gebruiken). Dit maakt multi-replica deployment mogelijk en elimineert de last single-point-of-failure in de architectuur.

Alternatief: als de control plane voornamelijk caching en session state doet, overweeg Redis als backing store (sneller dan PostgreSQL voor key-value lookups, maar minder durable).

### 3.7 Concrete codebase-wijzigingen voor schaalbaarheid

Onderstaande wijzigingen zijn nodig om van single-replica naar horizontaal schaalbaar te gaan. Geordend op prioriteit:

| Prioriteit | Wijziging | Bestand(en) | Wat |
|------------|-----------|-------------|-----|
| **P0** | Replica count configureerbaar | `helm/druppie/templates/backend-deployment.yaml` | Hardcoded `replicas: 1` → `{{ .Values.backend.replicas }}` |
| **P0** | Workspace PVC naar RWX | `helm/druppie/templates/persistentvolumeclaims.yaml` | `ReadWriteOnce` → `ReadWriteMany` + storageClass |
| **P0** | HPA toevoegen | `helm/druppie/templates/` (nieuw) | HPA resources voor backend, frontend, MCP modules |
| **P1** | Session locking naar database | `druppie/core/background_tasks.py` | `_active_session_tasks` dict → PostgreSQL advisory lock of `FOR UPDATE SKIP LOCKED` |
| **P1** | Sandbox manager naar K8s API | `background-agents/.../docker_manager.py` | `docker run` subprocess → `kubernetes` Python client |
| **P2** | PDB's toevoegen | `helm/druppie/templates/` (nieuw) | PodDisruptionBudget per kritieke service |
| **P2** | Anti-affinity configureren | `helm/druppie/templates/*-deployment.yaml` | Pod anti-affinity op hostname |
| **P2** | Graceful shutdown | `druppie/api/main.py` | `terminationGracePeriodSeconds` + SIGTERM handler uitbreiden |
| **P3** | Control plane SQLite → PG | `background-agents/` | SQLite vervangen door PostgreSQL client |
| **P3** | Replica counts in values.yaml | `helm/druppie/values.yaml` | Expose `replicas` per service in values |

---

## 4. Fasering

### Fase 1 — Minimaal Productie-Ready (4-6 weken)

| Item | Werk | Tooling |
|------|------|---------|
| K3s cluster setup | 3-node HA cluster op cloud VMs | K3s, Terraform (optioneel) |
| Container registry | Gitea container registry configureren | Gitea (al aanwezig) |
| CloudNativePG | Operator v1.29.1+, 3 database clusters | CloudNativePG operator |
| Longhorn storage | Installatie, RWX PVC voor workspace | Longhorn |
| Helm chart updates | `values-k3s.yaml` overlay, Traefik config | Helm |
| TLS certificaten | cert-manager + Let's Encrypt | cert-manager |
| Sealed Secrets | API keys, DB passwords versleuteld in git | Sealed Secrets |
| CI/CD pipeline | GitHub Actions: build → push → helm upgrade | GitHub Actions |
| Monitoring | kube-prometheus-stack installatie | Prometheus, Grafana |
| Sandbox als K8s Jobs | Refactor sandbox-manager (fallback voor Agent Sandbox) | Kubernetes Python client |

### Fase 2 — Schaalbaar & Operationeel (6-10 weken)

| Item | Werk | Tooling |
|------|------|---------|
| Agent Sandbox | Evalueer en adopteer kubernetes-sigs/agent-sandbox | Agent Sandbox operator |
| HPA voor stateless services | CPU + custom metrics per service | HPA, Prometheus |
| KEDA | Event-driven autoscaling op queue depth | KEDA |
| ArgoCD | GitOps deployment pipeline | ArgoCD |
| Backend multi-replica | Database-driven resume pattern implementeren | Applicatie code |
| Per-session workspace | Elimineer shared RWX volume | Architectuur refactor |
| gVisor runtime | RuntimeClass configuratie voor sandboxes | gVisor |
| Network Policies | Per-namespace isolation | Kubernetes NetworkPolicy |
| Harbor registry | Vulnerability scanning, image signing | Harbor |

### Fase 3 — Enterprise-Ready (optioneel)

| Item | Werk | Tooling |
|------|------|---------|
| Rancher management | Multi-cluster beheer via UI | Rancher |
| Kata Containers | VM-level isolatie voor multi-tenant | Kata Containers |
| Database read replicas | CloudNativePG read-only endpoints voor reporting | CloudNativePG |
| Distributed tracing | Request tracing door alle services | Jaeger |
| Chaos engineering | Failure testing | Litmus (CNCF) |
| Backup/DR | Cluster-level backup en disaster recovery | Velero (open source) |

---

## 5. Risico's

| Risico | Impact | Kans | Mitigatie |
|--------|--------|------|-----------|
| Agent Sandbox te onvolwassen (v1alpha1) | Sandbox refactor vertraagd | Medium | Start met K8s Jobs als fallback; evalueer Agent Sandbox parallel |
| Longhorn RWX performance onvoldoende | Trage workspace file operations | Laag | Benchmark vroeg; fallback = NFS server pod |
| CloudNativePG operationele kennis ontbreekt | Database issues in productie | Medium | Training + runbooks schrijven; test failover scenario's op staging |
| Backend multi-replica race conditions | Data inconsistentie bij webhooks | Medium | Fase 1 draait single replica; fase 2 implementeert DB-driven resume |
| K3s cluster management overhead | Meer ops werk dan verwacht | Laag | K3s is minimaal; bij groei upgrade naar Rancher |
| Sealed Secrets key verloren | Alle secrets ontoegankelijk na cluster rebuild | Medium | Key backup procedure documenteren en testen |

---

## 6. Aannames

1. Het team heeft basis Kubernetes kennis of is bereid dit op te bouwen.
2. Er is geen strict data-residency vereiste dat een specifieke hosting locatie afdwingt.
3. De huidige load past op een 3-node cluster (4 vCPU, 16GB RAM per node).
4. Sandboxes hoeven geen Docker-in-Docker te draaien (alleen code execution + git).
5. Er is geen 99.99% uptime SLA vereist in fase 1.
6. Alle tooling moet open source zijn (Apache 2.0, MIT, GPL, MPL — geen BSL of proprietary).

---

## 7. Kostenschatting

### Optie A: Cloud VMs (bijv. Hetzner)

| Component | Specificatie | Geschatte kosten/maand |
|-----------|-------------|----------------------|
| Server nodes (3x) | CPX31 (4 vCPU, 8GB RAM, 160GB NVMe) | 3 × €13 = ~€39 |
| Extra storage | 200GB block storage voor Longhorn | ~€10 |
| Load balancer | Hetzner LB | ~€6 |
| Backup storage | 100GB (DB backups via MinIO/S3) | ~€5 |
| **Totaal** | | **~€60/maand** |

### Optie B: Dedicated servers (hogere performance)

| Component | Specificatie | Geschatte kosten/maand |
|-----------|-------------|----------------------|
| Server nodes (3x) | AX42 (8 vCPU, 64GB RAM, 2x512GB NVMe) | 3 × €49 = ~€147 |
| **Totaal** | | **~€147/maand** |

### Optie C: On-premises (bestaande hardware)

| Component | Specificatie | Kosten |
|-----------|-------------|--------|
| Hardware | 3 servers (bestaand) | €0 (al beschikbaar) |
| Stroom + koeling | Afhankelijk van locatie | Variabel |
| **Totaal** | | **€0 + stroom** |

Opmerking: Sandbox workloads zijn bursty. Overweeg een aparte worker node die aan/uit gezet wordt voor sandboxes (K3s agent join/leave is triviaal).

---

## 8. Vervolgstappen

1. **Spike: Agent Sandbox evaluatie** — Installeer operator op Kind, test Python SDK als vervanging voor `docker_manager.py`. Fallback: K8s Jobs. Dit is het grootste technische risico.
2. **K3s staging cluster** — Zet een 3-node K3s HA cluster op (cloud VMs of on-prem). Test het volledige Helm chart.
3. **CloudNativePG test** — Deploy operator v1.29.1+ op Kind, test HA failover en backup/restore naar MinIO.
4. **Longhorn benchmark** — Meet RWX performance voor workspace volume (git clone, file write throughput).
5. **CI/CD pipeline** — GitHub Actions: build → push naar Gitea registry → helm upgrade op K3s.
6. **Helm chart updates** — `values-k3s.yaml`, Traefik/NGINX toggle, Longhorn StorageClass.

---

## 9. Kanttekeningen bij dit onderzoek

- **Agent Sandbox is v1alpha1** (pre-stable) — API kan significant veranderen voor GA. Fallback op K8s Jobs moet klaarliggen.
- **CloudNativePG CVE-2026-44477** vereist onmiddellijke patching bij elke productie-inzet.
- **Sysbox risico:** Containerd integratie is "still evolving" met best-effort community support — niet aanbevolen.
- **HashiCorp Vault** is geen open source meer (BSL 1.1 sinds 2023). OpenBao (MPL 2.0 fork) is een alternatief maar minder volwassen.
- **Kostenschattingen** zijn indicatief en gebaseerd op publieke prijzen (juni 2026). Werkelijke kosten variëren per provider en gebruik.

---

## 10. Referenties

### Geverifieerd via deep research (adversarial verification, 23/25 claims bevestigd)

- [Agent Sandbox — Kubernetes blog](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)
- [Agent Sandbox — Google Open Source blog](https://opensource.googleblog.com/2025/11/unleashing-autonomous-ai-agents-why-kubernetes-needs-a-new-standard-for-agent-execution.html)
- [Kata Containers + Agent Sandbox integratie](https://katacontainers.io/blog/kata-containers-agent-sandbox-integration/)
- [CloudNativePG v1.29.1 release notes](https://cloudnative-pg.io/releases/cloudnative-pg-1-29.1-released/)
- [GKE autoscaling best practices voor LLM inference](https://docs.cloud.google.com/kubernetes-engine/docs/best-practices/machine-learning/inference/autoscaling)
- [KEDA GPU autoscaling — CNCF blog](https://www.cncf.io/blog/2026/05/27/gpu-autoscaling-on-kubernetes-with-keda-building-an-external-scaler/)
- [vLLM Production Stack — KEDA autoscaling](https://docs.vllm.ai/projects/production-stack/en/latest/use_cases/autoscaling-keda.html)
- [Sysbox + K3s integratie](https://docs.k3s.io/blog/2025/09/27/k3s-sysbox)

### Platform documentatie

- [K3s documentatie](https://docs.k3s.io/)
- [Rancher documentatie](https://ranchermanager.docs.rancher.com/)
- [OKD documentatie](https://docs.okd.io/)
- [CloudNativePG documentatie](https://cloudnative-pg.io/documentation/)
- [Longhorn documentatie](https://longhorn.io/docs/)
- [KEDA documentatie](https://keda.sh/docs/)
- [ArgoCD documentatie](https://argo-cd.readthedocs.io/)
- [Sealed Secrets](https://sealed-secrets.netlify.app/)
- [Traefik documentatie](https://doc.traefik.io/traefik/)
- [cert-manager documentatie](https://cert-manager.io/docs/)
- [Harbor documentatie](https://goharbor.io/docs/)
- [gVisor documentatie](https://gvisor.dev/docs/)

### Bestaande Druppie resources

- Helm chart: `helm/druppie/`
- K8s setup guide: `docs/guides/kubernetes-deployment.md`
- Kind cluster config: `kind/cluster-dev.yaml`
