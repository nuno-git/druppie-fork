# Kubernetes Migration — Implementation Plan

| Veld | Waarde |
|------|--------|
| **Status** | Geïmplementeerd (fase 1 + CNPG) |
| **Datum** | 2026-06-15 (laatst bijgewerkt) |
| **Gebaseerd op** | [ADR-KUBERNETES.md](./ADR-KUBERNETES.md) |
| **Referentie** | [KUBERNETES-STRATEGY.md](./KUBERNETES-STRATEGY.md), [kubernetes.md](./kubernetes.md) |
| **Delivery** | 1 PR naar `colab-dev` |

---

## Acceptatiecriteria (Story 3)

- [x] Druppie volledig deploybaar via Helm
- [x] Autoscaling: Backend (KEDA PostgreSQL) en frontend (HPA CPU) schalen horizontaal
- [x] High availability: PDB + anti-affinity templates beschikbaar (uitgeschakeld per gebruikersvoorkeur)
- [x] Database: Productiegeschikte PostgreSQL oplossing (CNPG met PgBouncer — Task 6 ✅, instances=1 voor kosten, HA bij instances=3)
- [x] Persistent storage via PVCs (NFS RWX voor workspace, hcloud-volumes voor DBs)
- [x] Secrets + ConfigMaps correct ingericht (gitignored values overlay — bewuste keuze, zie Task 5)
- [x] Complete flow werkt: login → chat → agent sessie → HTTPS via cert-manager
- [x] Documentatie: setup, scaling gedrag, beperkingen (Task 10, bijgewerkt)
- [x] Backlog item: stateless maken backend (al geïmplementeerd)
- [x] KEDA: Dual-trigger autoscaling (PostgreSQL + CPU 55%) met aggressive scale-up
- [x] NFS: RWX storage voor multi-node backend scheduling
- [x] Gitea Container Registry: images builden en pushen naar eigen registry
- [x] DB connection pool fix: pool_size=5/max_overflow=5 + PgBouncer (was 20/30, crashde bij 125+ rps)

---

## Huidige Staat (AS-IS)

De repo bevat een **werkende K3s productie deployment** op Hetzner Cloud + Kind voor lokale development:

| Onderdeel | Bestaand | Status |
|-----------|----------|--------|
| Helm chart | `helm/druppie/` (30+ templates) | ✅ Werkend op K3s + Kind |
| K3s cluster | `iac/cluster.yaml` (3 servers + 1 infra + 1-10 app) | ✅ Productie draait op Hetzner |
| Ingress | Traefik (K3s) + NGINX (Kind) | ✅ Subdomain routing met TLS |
| PostgreSQL | 3x CNPG Cluster (instances=1) + PgBouncer pooler | ✅ Productie, PgBouncer lost pool exhaustion op |
| NFS RWX | In-cluster NFSv4 server + static PVs | ✅ Backend pods mounten workspace over meerdere nodes |
| Autoscaling backend | KEDA dual-trigger (PostgreSQL + CPU 55%) + CA | ✅ E2E geverifieerd: 1→6 pods @ 125 rps, p95=508ms |
| Autoscaling frontend | HPA CPU 70% | ✅ 1→8 replicas |
| cert-manager | Let's Encrypt TLS | ✅ Alle subdomains HTTPS |
| Gitea Registry | OCI-compatible, images push/pull werkt | ✅ Backend/frontend images via registry |
| Secrets | Gitignored `values-hetzner.secrets.yaml` overlay | ⚠️ Werkt, maar Sealed Secrets is Task 5 |
| Monitoring | kube-prometheus-stack in `monitoring` namespace | ✅ Prometheus + Grafana draaien |
| CI/CD | Alleen `sync-main-to-colab-dev.yml` | ❌ Geen deploy pipeline (Task 11) |
| Backend | Stateless, DB-driven task guard, multi-replica | ✅ Task 1 afgerond |
| DB pool | pool_size=5, max_overflow=5 + PgBouncer | ✅ Was 20/30, crashde bij 125+ rps |
| Docker on nodes | DaemonSet installeert Docker via nsenter | ⚠️ Werkt op bestaande nodes, CA nodes hebben timing issues |

### Cluster state (juni 2026)

```
NAME                          STATUS   ROLES                       VERSION
druppie-master1               Ready    control-plane,etcd          v1.35.5+k3s1
druppie-master2               Ready    control-plane,etcd          v1.35.5+k3s1
druppie-master3               Ready    control-plane,etcd          v1.35.5+k3s1
druppie-pool-infra-worker1    Ready    <none>                      v1.35.5+k3s1
druppie-app-*                 Ready    <none>                      v1.35.5+k3s1  (1-10, autoscaled)
```

### KEDA autoscaling (geïmplementeerd)

KEDA schaalt de backend met **dual triggers** — PostgreSQL query + CPU:

| Trigger | Type | Doel | Reden |
|---------|------|------|-------|
| PostgreSQL | `SELECT COUNT(*) FROM agent_runs WHERE status = 'running'` | 5 running per replica | Reactief op daadwerkelijke LLM werkload |
| CPU | Utilization 55% | Scale bij hoge CPU | Vangt read-heavy GET load op (sessions, projects) |

**Gedrag:**
- **minReplicas:** 3 (proactieve baseline)
- **Scale-up:** +4 pods per 30s, `stabilizationWindowSeconds: 0` (agressief)
- **Scale-down:** 300s stabilization
- **Polling:** elke 15 seconden
- **metricType:** op trigger niveau (KEDA v2.20 API — NIET in metadata)

**Bewezen load test resultaten (CPX32, 3 runs):**

| Run | Max RPS | p95 latency | Pods | Success rate | Opmerking |
|-----|---------|-------------|------|--------------|-----------|
| 1 (geen CPU trigger) | 50 | 7.163ms | 1 (stuck) | ~99% | PostgreSQL-only trigger te traag voor GET load |
| 2 (CPU trigger toegevoegd) | 50 | 205ms | 1→3 | 100% | CPU trigger vangt read-heavy load op |
| 3 (aggressive ramp) | 125 | 508ms | 1→6 | 100% | Bewijst PgBouncer lost pool exhaustion op |

Multi-node: Piekt op 8 pods, 2 app nodes bij 200 rps.

Frontend blijft op CPU HPA (70%, 1→8 replicas).

### Bekende beperkingen

1. **CNPG instances=1 (geen HA)**: Alle 3 databases draaien single-instance op de infra node. Geen auto-failover, geen read replicas. CNPG operator is aanwezig, `instances: 3` is een one-line values change, maar vereist een tweede infra node om nuttig te zijn (replica's op dezelfde node = geen echte HA). PgBouncer (2 instances) zorgt wel voor connection-level beschikbaarheid.
2. **CA nodes missen Docker**: Nieuw gemaakte nodes door de CA hebben Docker nog niet geïnstalleerd. De docker-installer DaemonSet installeert Docker via nsenter, maar pods die reeds ingepland zijn voordat de installatie klaar is, blijven steken in `Init:0/3`. _Fix in progress: Docker installatie via cloud-init in cluster.yaml._
3. **CNPG app user password management**: CNPG genereert willekeurige wachtwoorden bij bootstrap. Handmatig gesynchroniseerd via `ALTER USER` + secret patch. Bij toekomstige CNPG reconciliatie kan het wachtwoord overschreven worden. _Oplossing: CNPG-managed secret reference in DATABASE_URL in plaats van hardcoded wachtwoord._
4. **DB data handmatig gemigreerd**: Data van oude StatefulSet PVCs naar CNPG gemigreerd via `pg_dump | psql`. Niet geautomatiseerd — bij een volgende migratie is handmatige interventie nodig.

---

## Taken (geordend op uitvoering)

Alle taken gaan in **1 PR**. De volgorde hieronder is de aanbevolen implementatievolgorde.

---

### Task 1: Maak backend stateless (database-driven task guard)

**Story points:** 3 | **Priority:** P0 — blokkeert alles

**Probleem:** `_active_session_tasks` dict in `background_tasks.py` is per-process. Bij 2+ replicas betekent dit race conditions, duplicate tasks, en verloren webhooks.

**Oplossing:** Vervang in-memory dict door database status check. De session tabel heeft al een `status` kolom. Gebruik `SELECT ... FOR UPDATE SKIP LOCKED` of PostgreSQL advisory lock als atomic guard.

**Concrete wijzigingen:**

```
Wijzigen: druppie/core/background_tasks.py
  - _active_session_tasks dict → verwijderen
  - is_session_task_running() → DB query: check session status
  - create_session_task() → DB guard: atomic status update (RUNNING)
  - SessionTaskConflict → nog steeds raisen, maar op basis van DB status

Wijzigen: druppie/api/routes/sessions.py
  - is_session_task_running() calls blijven hetzelfde (interface gelijk)
  - Webhook handlers: elke replica kan oppakken via DB-driven resume

Wijzigen: druppie/api/routes/approvals.py
  - create_session_task() calls blijven hetzelfde

Wijzigen: druppie/api/routes/questions.py
  - create_session_task() calls blijven hetzelfde

Wijzigen: druppie/api/routes/chat.py
  - create_session_task() calls blijven hetzelfde

Wijzigen: druppie/api/routes/sandbox.py
  - create_session_task() calls blijven hetzelfde

Wijzigen: druppie/services/job_service.py
  - create_session_task() calls blijven hetzelfde
```

**Implementatie detail:**
```python
# Nieuwe aanpak in background_tasks.py
async def is_session_task_running(session_id: UUID) -> bool:
    """Check via DB of er een actieve taak is voor deze session."""
    from druppie.db.database import SessionLocal
    from druppie.domain.common import SessionStatus
    db = SessionLocal()
    try:
        session = db.execute(
            select(Session).where(Session.id == session_id)
        ).scalar_one_or_none()
        return session is not None and session.status == SessionStatus.RUNNING
    finally:
        db.close()

def create_session_task(session_id, coro, *, name=None):
    """Maak task aan na DB guard. Interface blijft gelijk."""
    # DB guard gebeurt in de caller (session_service) via DB transaction
    # Hier alleen nog de asyncio.Task tracking
    task = create_tracked_task(coro, name=name)
    return task
```

**Acceptatiecriteria:**
- [x] `_active_session_tasks` dict volledig verwijderd
- [x] `is_session_task_running()` leest uit database
- [x] `create_session_task()` guard via database (atomic)
- [x] Complete flow werkt op 1 replica: login → chat → agent sessie → approval → resume
- [x] Bestaande tests slagen
- [x] Kind deploy + smoke test slaagt

---

### Task 2: K3s cluster inrichten op Hetzner

**Story points:** 2 | **Priority:** P0 | **Status:** ✅ Voltooid

**Scope:**
- `iac/cluster.yaml` aanmaken met hetzner-k3s configuratie
- Cluster provisionen: 3 servers + 1-2 infra agents + 1-10 autoscaled app agents
- Traefik ingress verifiëren (K3s standaard)
- kube-prometheus-stack deployen
- `kubectl` context configureren

```
Aanmaken: iac/cluster.yaml
  - hetzner_token: <from secrets>
  - cluster_name: druppie
  - k3s_version: v1.35.5+k3s1
  - schedule_workloads_on_masters: false
  - masters_pool: 3x CPX32, fsn1
  - worker_node_pools:
      - name: infra, 1x CPX42, autoscaling: false, labels: {pool: infra}
      - name: app, 1-10x CPX32, autoscaling: true, labels: {pool: app}
      - additional_packages: [nfs-common]
  - addons:
      - cluster_autoscaler: tuned scale-down (2m delay, 2m unneeded)
      - csi_driver: enabled
      - cloud_controller_manager: enabled
```

**Benodigdheden:**
- Hetzner Cloud account + API token
- `hetzner-k3s` CLI geïnstalleerd (`gem install hetzner-k3s`)
- `kubectl` lokaal beschikbaar

**Acceptatiecriteria:**
- [x] `hetzner-k3s create cluster --config iac/cluster.yaml` slaagt in <5 min
- [x] `kubectl get nodes` toont 3 servers + minimaal 1 infra + 1 app agent
- [x] Alle nodes `Ready`
- [x] Masters hebben `NoSchedule` taint (geen workloads)
- [x] Infra nodes hebben label `pool: infra`
- [x] App nodes hebben label `pool: app`
- [x] Traefik ingress controller actief (K3s standaard)
- [x] kube-prometheus-stack gedeployed in `monitoring` namespace
- [x] `kubectl get pods -A` toont alleen system/monitoring pods op masters

---

### Task 3: Helm chart productie-ready (resources, replicas, PVCs)

**Story points:** 2 | **Priority:** P0 | **Status:** ✅ Voltooid

**Scope:**
- Resource `requests` + `limits` toevoegen aan álle Deployments
- Replica counts configureerbaar maken in `values.yaml`
- `values-prod.yaml` aanmaken als productie overlay
- PVCs: expliciete `storageClassName` en sizes
- Backend deployment: `terminationGracePeriodSeconds: 60`
- Ingress className configureerbaar (NGINX voor Kind, Traefik voor K3s)

```
Wijzigen: helm/druppie/values.yaml
  - resources.requests/limits per service (dev defaults)
  - backend.replicaCount: 1 (dev), configureerbaar
  - frontend.replicaCount: 1 (dev)
  - global.ingress.className: nginx (default, Traefik via values-prod)

Aanmaken: helm/druppie/values-prod.yaml
  - global.domain: druppie.example.com
  - global.ingress.className: traefik
  - global.ingress.tls.enabled: true
  - backend.replicaCount: 2
  - frontend.replicaCount: 2
  - Hardere resource limits
  - cert-manager issuer referentie

Wijzigen: helm/druppie/templates/backend-deployment.yaml
  - resources block toevoegen
  - terminationGracePeriodSeconds: 60
  - replica count via values

Wijzigen: helm/druppie/templates/frontend-deployment.yaml
  - resources block toevoegen
  - replica count via values

Wijzigen: helm/druppie/templates/keycloak-deployment.yaml
  - resources uit values

Wijzigen: helm/druppie/templates/gitea-deployment.yaml
  - resources uit values

Wijzigen: helm/druppie/templates/module-*-deployment.yaml (8x)
  - resources uit values

Wijzigen: helm/druppie/templates/persistentvolumeclaims.yaml
  - storageClass configureerbaar
  - expliciete sizes
```

**Acceptatiecriteria:**
- [x] `helm template --validate` slaagt
- [x] `helm template -f values-prod.yaml` genereert geldige productie YAML
- [x] Elke Deployment heeft `resources.requests` en `resources.limits`
- [x] Replica counts configureerbaar per environment
- [x] PVCs hebben configureerbare `storageClassName`

---

### Task 4: Ingress — Traefik support + TLS (cert-manager)

**Story points:** 2 | **Priority:** P1 | **Status:** ✅ Voltooid

**Scope:**
- Ingress template ondersteunen zowel NGINX (Kind) als Traefik (K3s)
- NGINX-specifieke annotations conditioneel maken
- Traefik IngressRoute/Middleware voor Gitea path rewrite
- cert-manager ClusterIssuer template (Let's Encrypt)
- TLS annotations op Ingress

```
Wijzigen: helm/druppie/templates/ingress.yaml
  - className via values (nginx of traefik)
  - NGINX annotations conditioneel: {{- if eq .Values.global.ingress.className "nginx" }}
  - Traefik annotations conditioneel
  - TLS cert-manager annotation toevoegen

Aanmaken: helm/druppie/templates/cluster-issuer.yaml
  - letsencrypt-staging (HTTP01)
  - letsencrypt-prod (HTTP01)
  - Conditioneel: alleen als cert-manager.enabled

Wijzigen: helm/druppie/values.yaml
  - cert-manager sectie (enabled, email, issuer)

Wijzigen: helm/druppie/values-prod.yaml
  - cert-manager.enabled: true
  - global.ingress.tls.enabled: true
```

**Acceptatiecriteria:**
- [x] `helm template` met `className: nginx` → NGINX Ingress (Kind blijft werken)
- [x] `helm template` met `className: traefik` → Traefik Ingress (geen NGINX annotations)
- [x] ClusterIssuer template gegenereerd wanneer `cert-manager.enabled: true`
- [x] TLS annotations aanwezig wanneer `tls.enabled: true`
- [x] **Live**: `https://druppie.rijnland.dev/` → 200 met geldig Let's Encrypt cert
- [x] **Live**: Traefik pinned to infra node via nodeSelector

---

### Task 5: Secrets Management — Gitignored Overlay (beslissing overschreven)

**Story points:** 0 | **Priority:** P1 | **Status:** ✅ Afgerond — gitignored overlay geaccepteerd

**Oorspronkelijk plan:** Sealed Secrets (Bitnami) voor encryptie van secrets in git.

**Beslissing overschreven (juni 2026):** De gitignored `values-hetzner.secrets.yaml` overlay wordt geaccepteerd als de productie-oplossing. Redenen:
1. Secrets staan **helemaal niet** in git — veiliger dan Sealed Secrets (waar encrypted secrets wel in de repo staan)
2. Geen extra operator of key management nodig
3. Kleine team — het secrets bestand wordt handmatig gedeeld met nieuwe teamleden
4. Sealed Secrets voegt complexiteit toe (key backup procedures, controller) zonder duidelijke meerwaarde voor deze use case

**Huidige aanpak:**
- `values-hetzner.secrets.yaml` bevat alle secrets (API keys, DB wachtwoorden, tokens)
- Bestand staat in `.gitignore`
- Wordt toegepast via: `helm upgrade druppie ./helm/druppie -n druppie -f values-hetzner.yaml -f values-hetzner.secrets.yaml`
- Backup: het bestand wordt offline bewaard (password manager, offline vault)

**Acceptatiecriteria:**
- [x] `values-hetzner.secrets.yaml` in `.gitignore`
- [x] Alle secrets via overlay, niet hardcoded in templates
- [x] Procedure gedocumenteerd (dit document)

---

### Task 6: CloudNativePG — HA PostgreSQL

**Story points:** 3 | **Priority:** P1 | **Status:** ✅ Voltooid (afwijking: instances=1, PgBouncer pooler)

**Huidige state:** 3 CNPG Clusters operationeel (druppie, keycloak, gitea), elk met `instances: 1`. PgBouncer transaction-mode pooler (2 instances) voor druppie-db. Oude StatefulSets verwijderd. Data gemigreerd van oude PVCs.

**Scope:**
- CloudNativePG operator v1.29.1+ geïnstalleerd (`cnpg-system` namespace)
- 3 database cluster CRDs: druppie-db, keycloak-db, gitea-db (instances=1)
- PgBouncer Pooler CRD voor druppie-db (2 instances, transaction mode)
- Bestaande PostgreSQL StatefulSets vervangen
- Alle deployments bijwerken: connection strings naar CNPG naming
- NetworkPolicies bijgewerkt: CNPG egress/ingress rules
- postInitApplicationSQL voor app user password sync bij bootstrap

```
Aangemaakt: helm/druppie/templates/databases/druppie-db-cluster.yaml
Aangemaakt: helm/druppie/templates/databases/keycloak-db-cluster.yaml
Aangemaakt: helm/druppie/templates/databases/gitea-db-cluster.yaml
Aangemaakt: helm/druppie/templates/databases/druppie-db-pooler.yaml (PgBouncer)

Verwijderd: helm/druppie/templates/druppie-db-statefulset.yaml
Verwijderd: helm/druppie/templates/keycloak-db-statefulset.yaml
Verwijderd: helm/druppie/templates/gitea-db-statefulset.yaml

Gewijzigd: helm/druppie/templates/backend-deployment.yaml
  - DATABASE_URL → CNPG pooler service (druppie-db-pooler-rw:5432)
  - wait-for-db initContainer → CNPG rw service

Gewijzigd: helm/druppie/templates/secrets.yaml
  - 3 CNPG superuser secrets
  - DATABASE_URL gebruikt pooler service

Gewijzigd: helm/druppie/templates/keda-networkpolicy.yaml
  - CNPG label selector branch
  - Ingress: KEDA + druppie namespace + cloudnative-pg managed pods

Gewijzigd: helm/druppie/templates/networkpolicy.yaml
  - Egress rule voor cloudnative-pg managed pods (port 5432)

Gewijzigd: helm/druppie/values-hetzner.yaml
  - cnpg.enabled: true
  - instances: 1 (cost-optimal, upgrade naar 3 voor HA)
```

**Acceptatiecriteria:**
- [x] 3 CNPG Cluster CRDs gedefinieerd (elk instances=1, upgrade naar 3 voor HA)
- [x] Oude StatefulSets verwijderd
- [x] `helm template` genereert CNPG clusters + pooler + bijgewerkte deployments
- [x] Connection strings verwijzen naar CNPG `-pooler-rw` service (PgBouncer)
- [x] Backend verbindt via PgBouncer (transaction mode)
- [x] Data gemigreerd van oude StatefulSet PVCs
- [x] NetworkPolicies staan CNPG + PgBouncer traffic toe
- [x] Load test bewijst: 125 rps, p95=508ms, 1→6 pods, 100% success

** wat nog ontbreekt voor volledige HA:**
- `instances: 3` (1 primary + 2 read replicas met auto-failover <30s)
- Tweede infra node (replica's op zelfde node = geen echte HA)
- CNPG backups naar S3/MinIO (`barmanObjectStore` in Cluster spec)
- Geautomatiseerde password synchronisatie (ipv handmatige ALTER USER)

---

### Task 7: Autoscaling — KEDA (backend) + HPA (frontend)

**Story points:** 2 | **Priority:** P1 | **Status:** ✅ Voltooid (afwijking van ADR)

**Afwijking van ADR §4.4:** ADR beschrijft KEDA met Prometheus trigger. Geïmplementeerd met **dual triggers**: PostgreSQL query (LLM workload) + CPU utilization 55% (read-heavy GET load). Beide triggers zijn nodig — de PostgreSQL-only trigger was te traag voor GET endpoint load (p95=7163ms), CPU trigger alleen mist LLM I/O-bound werk.

**Scope:**
- KEDA operator via Helm in `keda` namespace
- ScaledObject voor backend: **dual triggers** (PostgreSQL + CPU)
- TriggerAuthentication: references CNPG app user secret
- NetworkPolicy: `druppie-keda-db-access` (KEDA namespace + druppie namespace + CNPG pods → DB port 5432)
- Frontend HPA: CPU 70%, 1→8 replicas (ongewijzigd)
- Backend CPU HPA: disabled wanneer KEDA enabled (CPU trigger zit in KEDA)

```
Aangemaakt: helm/druppie/templates/keda-scaledobject-backend.yaml
  - PostgreSQL trigger: SELECT COUNT(*) FROM agent_runs WHERE status = 'running'
  - CPU trigger: Utilization 55% (metricType op trigger niveau, KEDA v2.20 API)
  - targetQueryValue: "5"
  - minReplicaCount: 3 (proactive baseline), maxReplicaCount: 10
  - pollingInterval: 15, cooldownPeriod: 300
  - Aggressive scale-up: +4 pods/30s, stabilizationWindowSeconds: 0
  - FQDN host voor cross-namespace DNS

Aangemaakt: helm/druppie/templates/keda-triggerauth.yaml
  - References CNPG app user secret

Aangemaakt: helm/druppie/templates/keda-networkpolicy.yaml
  - KEDA namespace + druppie selector pods + cloudnative-pg managed pods → CNPG DB port 5432
```

**Acceptatiecriteria:**
- [x] KEDA operator draait in `keda` namespace (3 pods)
- [x] ScaledObject `READY: True`, HPA `keda-hpa-druppie-backend` aangemaakt
- [x] Backend schaalt op dual triggers: PostgreSQL query + CPU 55%
- [x] Backend CPU HPA uitgeschakeld wanneer KEDA enabled
- [x] Frontend HPA: CPU 70%, 1→8 replicas
- [x] Stabilization windows: scaleUp 0s (aggressive), scaleDown 300s
- [x] **Load test bewezen** (3 runs op CPX32):
  - Run 1 (PostgreSQL-only): 50 rps, p95=7163ms, 1 pod stuck — trigger te traag
  - Run 2 (+CPU trigger): 50 rps, p95=205ms, 1→3 pods, 100% success
  - Run 3 (aggressive ramp): 125 rps, p95=508ms, 1→6 pods, 100% success
- [x] Multi-node: 8 pods, 2 app nodes bij 200 rps bevestigd

---

### Task 8: HA — PDB + anti-affinity + graceful shutdown

**Story points:** 1 | **Priority:** P1 | **Status:** ✅ Templates klaar, uitgeschakeld per voorkeur

**Let op:** PDB en anti-affinity zijn geïmplementeerd in Helm templates maar **uitgeschakeld** (`highAvailability.pdb.enabled: false`, `highAvailability.antiAffinity.enabled: false`). Gebruiker prefereert pods op dezelfde node (minder nodes = lagere kosten). Kan worden ingeschakeld via values.

**Scope:**
- PodDisruptionBudgets voor backend en frontend (`minAvailable: 1`)
- Pod anti-affinity: spreid pods over verschillende nodes
- Graceful shutdown: SIGTERM handler in FastAPI

```
Aanmaken: helm/druppie/templates/pdb-backend.yaml
Aanmaken: helm/druppie/templates/pdb-frontend.yaml

Wijzigen: helm/druppie/templates/backend-deployment.yaml
  - podAntiAffinity (preferred, weight 100)
  - terminationGracePeriodSeconds: 60

Wijzigen: helm/druppie/templates/frontend-deployment.yaml
  - podAntiAffinity (preferred, weight 100)

Wijzigen: druppie/api/main.py
  - SIGTERM handler
  - shutdown_background_tasks() aanroepen in lifespan shutdown
```

**Graceful shutdown pseudo-code:**
```python
# main.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown — drain background tasks
    from druppie.core.background_tasks import shutdown_background_tasks
    await shutdown_background_tasks(timeout=55.0)
```

**Acceptatiecriteria:**
- [x] PDB's gedefinieerd: minAvailable 1 voor backend en frontend
- [x] Anti-affinity: pods verspreid over nodes
- [ ] Graceful shutdown: SIGTERM → drain tasks → exit binnen 60s

---

### Task 9: Monitoring — kube-prometheus-stack

**Story points:** 1 | **Priority:** P2 | **Status:** ✅ Voltooid

**Live state:** kube-prometheus-stack draait in `monitoring` namespace. Prometheus + Grafana + Alertmanager actief.

**Scope:**
- Installatie instructies voor kube-prometheus-stack (aparte Helm release)
- Prometheus scrape config
- Grafana standaard dashboards

```
Aanmaken: docs/monitoring-setup.md
  - helm install kube-prometheus-stack instructies
  - Port-forward commando's
  - CNPG PodMonitor integratie
```

**Acceptatiecriteria:**
- [x] Installatie instructies compleet
- [x] Prometheus scrape alle pods
- [x] Grafana bereikbaar met dashboards

---

### Task 10: Documentatie — setup, scaling, beperkingen

**Story points:** 1 | **Priority:** P0 | **Status:** ⚠️ Deels verouderd

**Wat ontbreekt:**
- iac/README.md nog niet volledig bijgewerkt met KEDA, NFS, Gitea registry details
- ADR §4.4 beschrijft Prometheus trigger, niet PostgreSQL (implementatie wijkt af — bewuste keuze)
- Geen runbook voor CA scale-up/scale-down gedrag

**Scope:**
- Setup guide: Kind dev + K3s productie deploy procedure
- Scaling documentatie: HPA thresholds, replica ranges, wanneer knelpunt
- Beperkingen: sandbox blijft Docker, MCP modules schalen niet onafhankelijk
- Backlog item aanmaken voor "stateless maken backend" als Task 1 niet volledig af

```
Wijzigen: docs/KUBERNETES-IMPLEMENTATION-PLAN.md
  - Status: Geaccepteerd (na review)
  - Acceptatiecriteria afvinken

Wijzigen: docs/BACKLOG.md
  - Backlog items voor Phase 2 work (KEDA, ArgoCD, sandbox, message queue)
```

**Acceptatiecriteria:**
- [ ] Setup guide compleet (Kind + K3s) — iac/README.md bestaat, moet worden bijgewerkt
- [ ] Scaling gedrag gedocumenteerd — ADR beschrijft doel, implementation plan moet werkelijke state reflecteren
- [ ] Beperkingen en bekende issues gedocumenteerd
- [ ] Backlog items voor Phase 2 aangemaakt

---

### Task 11: NFS RWX Storage (extra, niet in oorspronkelijk plan)

**Story points:** 1 | **Priority:** P0 | **Status:** ✅ Voltooid

**Waarom nodig:** HPA/KEDA schaalt backend pods over meerdere nodes. PVCs met `ReadWriteOnce` (local-path) werken alleen op 1 node. NFS biedt `ReadWriteMany` zodat alle pods dezelfde workspace delen.

**Scope:**
- In-cluster NFSv4 server als Deployment, gepind op infra node
- Backed by Hetzner Cloud Volume (hcloud-volumes StorageClass)
- Twee statische PVs: `nfs-workspace` en `nfs-sandbox-bundles` (RWX)
- NFS client installer DaemonSet: installeert `nfs-common` op app pool nodes

```
Aanmaken: helm/druppie/templates/nfs-server.yaml
  - NFS server Deployment + Service + PVC
  - Pinned to infra node via nodeSelector

Aanmaken: helm/druppie/templates/nfs-storage.yaml
  - StorageClass (nfs-workspace)
  - Twee statische PVs (workspace, sandbox-bundles)

Aanmaken: helm/druppie/templates/nfs-client-installer.yaml (DaemonSet in kube-system)
  - Installeert nfs-common op pool=app nodes
```

**Acceptatiecriteria:**
- [x] NFS server draait op infra node
- [x] Twee PVs gebonden met RWX access mode
- [x] Backend pods op meerdere nodes mounten dezelfde workspace
- [x] `additional_packages: [nfs-common]` in cluster.yaml voor nieuwe nodes

---

### Task 12: Docker Installer DaemonSet (extra)

**Story points:** 1 | **Priority:** P1 | **Status:** ✅ Opgelost via cloud-init

**Waarom nodig:** Backend module-docker heeft `/var/run/docker.sock` voor compose_up sandbox. CA-provisioned nodes hebben Docker niet voorgeïnstalleerd.

**Oplossing:** `docker.io` toegevoegd aan `additional_packages` in `iac/cluster.yaml`. Nieuw gemaakte CA nodes installeren Docker via cloud-init (samen met `nfs-common`). De DaemonSet (`druppie-docker-installer`) blijft als fallback voor bestaande nodes.

```
cluster.yaml:
  additional_packages:
    - nfs-common
    - docker.io
```

**Acceptatiecriteria:**
- [x] `docker.io` in `additional_packages` in cluster.yaml
- [x] DaemonSet template in Helm chart als fallback
- [x] Init image gepushed naar Gitea registry (nodig voor helm hooks)

---

### Task 13: Gitea Container Registry (ADR §4.8)

**Story points:** 1 | **Priority:** P1 | **Status:** ✅ Voltooid

**Scope:**
- Gitea registry ingeschakeld op bestaande Gitea instance
- Backend/frontend images gebouwd en gepushed naar `git.druppie.rijnland.dev/gitea_admin/druppie-{backend,frontend}:{latest,1.0.0}`
- `imagePullSecrets: [gitea-registry]` geconfigureerd in Helm values
- `imagePullPolicy: Always` voor productie

**Acceptatiecriteria:**
- [x] Images beschikbaar in Gitea registry
- [x] Kubernetes pullt images via gitea-registry secret
- [x] Backend/frontend draaien vanuit registry images

---

### Task 14: Helm Upgrade Fix (operational)

**Priority:** P1 | **Status:** ✅ Voltooid

**Probleem:** Resources die via `kubectl apply` waren aangepakt (KEDA ScaledObject, TriggerAuthentication, NetworkPolicy, NFS resources) misten Helm ownership annotations. `helm upgrade` faalde met ownership validatie errors. Daarnaast ontbrak het `druppie-init` image in de Gitea registry, waardoor de post-upgrade hook faalde met ImagePullBackOff.

**Oplossing:**
1. Helm annotations (`meta.helm.sh/release-name`, `meta.helm.sh/release-namespace`) + labels (`app.kubernetes.io/managed-by: Helm`) toegevoegd aan alle orphaned resources
2. Duplicate PVs (`druppie-nfs-workspace`, `druppie-nfs-sandbox-bundles`) die waren ontstaan bij `helm template | kubectl apply` blast verwijderd
3. `druppie-init` image gebouwd en gepushed naar Gitea registry
4. `helm upgrade` slaagt nu: revision 23, `STATUS: deployed`

**Acceptatiecriteria:**
- [x] `helm upgrade druppie helm/druppie/ -n druppie -f values-hetzner.yaml` slaagt zonder errors
- [x] Alle resources hebben correcte Helm ownership annotations
- [x] Init image beschikbaar in Gitea registry
- [x] `helm list` toont `STATUS: deployed`

---

### Task 15: Backend uvicorn workers

**Priority:** P2 | **Status:** ✅ Voltooid — 2 workers per pod optimaal

**Bevinding:** Oorspronkelijk plan was 10 workers per pod. Load testing bewees dat **2 workers optimaal** is:
- 4 workers crashde zelfs op CCX33 (8 vCPU/32GB) — DB pool exhaustion: 4 workers × pool_size=20 × 5 pods = 1000 connections vs PostgreSQL max 100
- Met PgBouncer is `pool_size=5` voldoende, dus 2 workers × 5 pool = 10 connections per pod
- Bij 10 pods: 10 × 10 = 100 connections (precies PostgreSQL max)
- Meer workers per pod = meer memory pressure zonder performance win (I/O-bound workload)

Workers worden overschreven via Helm `command:` in backend-deployment.yaml:

```yaml
command: ["uvicorn", "druppie.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "{{ .Values.backend.workers }}"]
```

`values-hetzner.yaml`: `backend.workers: "2"`

**Acceptatiecriteria:**
- [x] Dockerfile gebruikt configureerbare workers (via Helm override)
- [x] Backend draait met 2 workers per pod op CPX32
- [x] Load test bewijst: geen crashes bij 125 rps met 6 pods (PgBouncer + pool_size=5)

---

## Afhankelijkheden

```
Task 1 (Stateless backend) ─── P0 ─── ✅ Voltooid
│
├── Task 2 (K3s cluster Hetzner) ─ P0 ─── ✅ Voltooid
│   ├── Task 9 (Monitoring) ────── P2 ─── ✅ Voltooid
│   └── Task 11 (NFS RWX) ──────── P0 ─── ✅ Voltooid
│
├── Task 3 (Helm chart ready) ─── P0 ─── ✅ Voltooid
│   ├── Task 4 (Ingress + TLS) ─── P1 ─── ✅ Voltooid
│   ├── Task 5 (Sealed Secrets) ── P1 ─── ❌ Niet gestart
│   ├── Task 6 (CloudNativePG) ─── P1 ─── ✅ Voltooid (instances=1 + PgBouncer)
│   ├── Task 7 (KEDA + HPA) ────── P1 ─── ✅ Voltooid (dual trigger: PG + CPU)
│   │   └── Task 8 (PDB + HA) ──── P1 ─── ✅ Templates klaar (disabled)
│   ├── Task 12 (Docker installer) P1 ─── ⚠️ Template klaar, runtime issues
│   ├── Task 13 (Gitea Registry) ─ P1 ─── ✅ Voltooid
│   └── Task 14 (Helm upgrade fix) P1 ─── ✅ Voltooid
│
├── Task 10 (Documentatie) ────── P0 ─── ✅ Bijgewerkt (dit document)
├── Task 15 (uvicorn workers) ─── P2 ─── ✅ Voltooid (2 workers, niet 10)
└── Task 16 (DB pool fix) ─────── P0 ─── ✅ Voltooid (pool_size=5 + PgBouncer)
```

**Samenvatting:** 13 van 16 taken voltooid. Overgebleven werk: Sealed Secrets (Task 5), CI/CD pipeline, CNPG HA (instances=3 + tweede infra node), CNPG backups.

---

## Bestandswijzigingen Overzicht

### Nieuwe bestanden

| Bestand | Task | Omschrijving | Status |
|---------|------|-------------|--------|
| `iac/cluster.yaml` | 2 | hetzner-k3s cluster definitie | ✅ |
| `helm/druppie/values-hetzner.yaml` | 3 | Hetzner productie Helm overlay | ✅ |
| `helm/druppie/templates/cluster-issuer.yaml` | 4 | Let's Encrypt issuers | ✅ |
| `secrets/sealed/README.md` | 5 | Sealed Secrets procedure | ❌ |
| `helm/druppie/templates/databases/druppie-db-cluster.yaml` | 6 | CNPG cluster: druppie | ✅ |
| `helm/druppie/templates/databases/keycloak-db-cluster.yaml` | 6 | CNPG cluster: keycloak | ✅ |
| `helm/druppie/templates/databases/gitea-db-cluster.yaml` | 6 | CNPG cluster: gitea | ✅ |
| `helm/druppie/templates/databases/druppie-db-pooler.yaml` | 6 | PgBouncer Pooler (2 instances) | ✅ |
| `helm/druppie/templates/hpa-backend.yaml` | 7 | Backend HPA (conditioneel bij KEDA) | ✅ |
| `helm/druppie/templates/hpa-frontend.yaml` | 7 | Frontend HPA | ✅ |
| `helm/druppie/templates/pdb-backend.yaml` | 8 | Backend PDB | ✅ |
| `helm/druppie/templates/pdb-frontend.yaml` | 8 | Frontend PDB | ✅ |
| `docs/monitoring-setup.md` | 9 | Monitoring installatie | ✅ |
| `helm/druppie/templates/nfs-server.yaml` | 11 | NFS server Deployment + Service + PVC | ✅ |
| `helm/druppie/templates/nfs-storage.yaml` | 11 | NFS StorageClass + PVs | ✅ |
| `helm/druppie/templates/docker-installer-daemonset.yaml` | 12 | Docker installatie op app nodes | ✅ |
| `helm/druppie/templates/keda-scaledobject-backend.yaml` | 7 | KEDA ScaledObject (PostgreSQL trigger) | ✅ |
| `helm/druppie/templates/keda-triggerauth.yaml` | 7 | KEDA DB authentication | ✅ |
| `helm/druppie/templates/keda-networkpolicy.yaml` | 7 | KEDA → DB NetworkPolicy | ✅ |
| `iac/metrics-server.yaml` | 2 | metrics-server manifest | ✅ |
| `testing/autoscaling/test-keda-ramp.py` | 7 | E2E KEDA load test script | ✅ |
| `druppie/llm/mock_provider.py` | 7 | MockLLM provider voor load testing | ✅ |

### Gewijzigde bestanden

| Bestand | Task | Wijziging | Status |
|---------|------|-----------|--------|
| `druppie/core/background_tasks.py` | 1 | In-memory dict → DB-driven task guard | ✅ |
| `druppie/api/routes/sessions.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `druppie/api/routes/approvals.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `druppie/api/routes/questions.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `druppie/api/routes/chat.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `druppie/api/routes/sandbox.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `druppie/services/job_service.py` | 1 | Aanpassen aan nieuw task guard interface | ✅ |
| `helm/druppie/values.yaml` | 3,4,7 | Resources, ingress, KEDA config | ✅ |
| `helm/druppie/values-hetzner.yaml` | 3,4,7 | Hetzner overlay: KEDA, NFS, Gitea registry | ✅ |
| `helm/druppie/templates/backend-deployment.yaml` | 3,7,8 | Resources, docker-sock, anti-affinity, terminationGracePeriod | ✅ |
| `helm/druppie/templates/frontend-deployment.yaml` | 3,7,8 | Resources, anti-affinity | ✅ |
| `helm/druppie/templates/keycloak-deployment.yaml` | 3,6 | Resources, DB connection | ✅ |
| `helm/druppie/templates/gitea-deployment.yaml` | 3,6 | Resources, DB connection | ✅ |
| `helm/druppie/templates/module-*-deployment.yaml` | 3 | Resources | ✅ |
| `helm/druppie/templates/ingress.yaml` | 4 | NGINX/Traefik conditioneel, TLS | ✅ |
| `helm/druppie/templates/secrets.yaml` | 5 | CNPG superuser secrets + DATABASE_URL (pooler) | ⚠️ Werkt, Sealed Secrets is Task 5 |
| `helm/druppie/templates/configmap.yaml` | 6 | CNPG service naming | ✅ |
| `helm/druppie/templates/services.yaml` | 6 | DB services bijgewerkt voor CNPG | ✅ |
| `helm/druppie/templates/init-job.yaml` | 6 | CNPG connection strings | ✅ |
| `helm/druppie/templates/persistentvolumeclaims.yaml` | 3,11 | Configureerbare storageClass, NFS PVCs | ✅ |
| `druppie/api/main.py` | 8 | SIGTERM handler, graceful shutdown | ✅ |
| `docs/ADR-KUBERNETES.md` | 10 | ADR (doelarchitectuur, ongewijzigd) | ✅ |
| `docs/KUBERNETES-IMPLEMENTATION-PLAN.md` | 10 | Dit document | ✅ |
| `iac/cluster.yaml` | 2,11 | NFS packages, CA tuning | ✅ |
| `iac/README.md` | 10 | Cluster setup documentatie | ⚠️ Deels verouderd |
| `druppie/llm/__init__.py` | 7 | MockLLM provider registratie | ✅ |
| `druppie/llm/service.py` | 7 | MockLLM provider support | ✅ |

### Verwijderde bestanden

| Bestand | Task | Reden |
|---------|------|-------|
| `helm/druppie/templates/druppie-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |
| `helm/druppie/templates/keycloak-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |
| `helm/druppie/templates/gitea-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |

---

## Out of Scope (Phase 2+)

| Onderwerp | Waarom niet nu | Wanneer | Status |
|-----------|----------------|---------|--------|
| Sandbox migratie (Docker → K8s) | Docker socket dependency | Phase 2 | ⬚ |
| ArgoCD | Push-based CI/CD is voldoende | Phase 2 | ⬚ |
| Message queue (Redis Streams/NATS) | Database-driven resume volstaat | Phase 2 | ⬚ |
| ~~KEDA (queue-based scaling)~~ | ~~HPA op CPU is voldoende~~ | ~~Phase 2~~ | ✅ Geïmplementeerd met PostgreSQL trigger (Task 7) |
| ~~Network Policies per-namespace~~ | ~~Niet blocking~~ | ~~Phase 2~~ | ⚠️ Deels: `druppie-app-net` + `druppie-keda-db-access` |
| ~~Longhorn RWX~~ | ~~MCP modules gebruiken local-path~~ | ~~Phase 2~~ | ✅ NFS RWX geïmplementeerd (Task 11) |
| gVisor / Kata Containers | Sandbox blijft op Docker | Phase 2 | ⬚ |
| Harbor registry | Gitea registry volstaat | Phase 2 | ⬚ |
| CI/CD pipeline (GitHub Actions) | Kan na eerste handmatige deploy | Phase 2 | ❌ Niet gestart |
| Distributed tracing (Jaeger/Tempo) | Nog niet nodig bij deze schaal | Phase 3 | ⬚ |

---

## Risico's en Mitigaties

| Risico | Impact | Kans | Status | Mitigatie |
|--------|--------|------|--------|-----------|
| Backend stateless refactor breekt bestaande flows | Regression | ~~Medium~~ | ✅ Opgelost | DB-driven task guard werkt met 10 replicas |
| ~~CloudNativePG operationele kennis ontbreekt~~ | ~~DB issues in productie~~ | ~~Medium~~ | ✅ Geïmplementeerd | CNPG draait, data gemigreerd, PgBouncer actief. HA (instances=3) is volgende stap. |
| ~~HPA scaling te agressief of te traag~~ | ~~Oscillatie~~ | ~~Laag~~ | ✅ Opgelost | KEDA dual-trigger (PG + CPU) met aggressive scale-up werkt stabiel |
| Sealed Secrets key verloren | Alle secrets ontoegankelijk | Medium | ⬚ Open | Private key backup procedure + test. |
| ~~Traefik path rewrite voor Gitea~~ | ~~Broken routing~~ | ~~Medium~~ | ✅ Opgelost | Subdomain routing werkt (geen path rewrite nodig) |
| Backend image ~4GB, te groot voor 10 replicas | Hoge RAM costs | Medium | ⬚ Open | Multi-stage build als vervolgstap. |
| Docker niet beschikbaar op CA-provisioned nodes | Pods stuck in Init | Hoog | ⚠️ Deels opgelost | DaemonSet installeert Docker, maar timing issue bij nieuwe nodes. Fix: cloud-init of optional mount. |
| ~~Helm upgrade faalt door ownership annotations~~ | ~~Geen declaratieve upgrades~~ | ~~Hoog~~ | ✅ Opgelost | Helm annotations toegevoegd, `helm upgrade` slaagt (revision 23+) |
| CNPG instances=1 (single point of failure) | DB uitval bij infra node failure | Medium | ⬚ Open | `instances: 3` + tweede infra node voor HA. PgBouncer geeft connection-level resilience. |
| DB pool exhaustion bij hoge load | Crashes bij 125+ rps | ~~Hoog~~ | ✅ Opgelost | pool_size=5/max_overflow=5 + PgBouncer transaction-mode multiplexing |
| CNPG password drift | Auth failures na reconciliatie | Laag | ⚠️ Handmatig opgelost | ALTER USER + secret patch. Lange termijn: CNPG-managed secret reference. |
