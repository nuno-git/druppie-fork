# Kubernetes Migration — Implementation Plan

| Veld | Waarde |
|------|--------|
| **Status** | Draft |
| **Datum** | 2026-06-09 |
| **Gebaseerd op** | [ADR-KUBERNETES.md](./ADR-KUBERNETES.md) |
| **Referentie** | [KUBERNETES-STRATEGY.md](./KUBERNETES-STRATEGY.md), [kubernetes.md](./kubernetes.md) |
| **Delivery** | 1 PR naar `colab-dev` |

---

## Acceptatiecriteria (Story 3)

- [x] Druppie volledig deploybaar via Helm
- [ ] Autoscaling: Backend en frontend schalen horizontaal (HPA)
- [ ] High availability: Minimale redundantie voor kritieke services
- [ ] Database: Productiegeschikte PostgreSQL oplossing (volgens spike)
- [ ] Persistent storage via PVCs
- [ ] Secrets + ConfigMaps correct ingericht
- [ ] Complete flow werkt: login → chat → agent sessie
- [ ] Documentatie: setup, scaling gedrag, beperkingen
- [ ] Backlog item: stateless maken backend (indien niet volledig af)

---

## Huidige Staat (AS-IS)

De repo bevat al een **werkende Kind setup** met Helm chart voor lokale development:

| Onderdeel | Bestaand | Status |
|-----------|----------|--------|
| Helm chart | `helm/druppie/` (25 templates, ~43 K8s resources) | Werkend op Kind |
| Kind config | `kind/cluster.yaml`, `kind/cluster-dev.yaml` | Twee varianten |
| Build scripts | `scripts/setup-kind.sh`, `scripts/build-and-load.sh` | Bouwt alle images + laadt in Kind |
| NGINX Ingress | Path-based routing op `localhost:9080` | Werkend |
| PostgreSQL | 3x StatefulSet (containers, geen HA) | Dev-only |
| Secrets | Plaintext in `values.yaml` + `secrets.yaml` template | Niet productie-ready |
| CI/CD | Alleen `sync-main-to-colab-dev.yml` | Geen deploy pipeline |
| Ingress | NGINX (Kind default) | ADR kiest Traefik (K3s default) |
| Backend | 1 replica, in-memory session task tracking, geen HPA/KEDA | Niet stateless, niet schaalbaar |
| TLS | Uitgeschakeld | Geen HTTPS |
| Monitoring | Geen | Ontbreekt |

### Kritiek probleem: Backend is niet stateless

De backend gebruikt `_active_session_tasks: dict[UUID, asyncio.Task]` in `druppie/core/background_tasks.py` — een **in-memory dict** die session tasks bijhoudt. Bij meerdere replicas:

1. Webhook komt binnen op replica A, maar de actieve task draait op replica B → task niet gevonden
2. `is_session_task_running()` checkt alleen lokale memory → false negative → duplicate tasks
3. `create_session_task()` guard via dict → race condition tussen replicas

**Dit moet worden opgelost vóór multi-replica kan werken.** Gelukkig bestaat `reconstruct_from_db()` al — de oplossing is een database-driven task guard.

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
- [ ] `_active_session_tasks` dict volledig verwijderd
- [ ] `is_session_task_running()` leest uit database
- [ ] `create_session_task()` guard via database (atomic)
- [ ] Complete flow werkt op 1 replica: login → chat → agent sessie → approval → resume
- [ ] Bestaande tests slagen
- [ ] Kind deploy + smoke test slaagt

---

### Task 2: K3s cluster inrichten op Hetzner

**Story points:** 2 | **Priority:** P0 | **Depends on:** Task 1 (kan parallel, maar backend stateless moet eerst getest worden op het cluster)

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
  - k3s_version: v1.32.3+k3s1
  - schedule_workloads_on_masters: false
  - masters_pool: 3x CPX31, fsn1
  - worker_node_pools:
      - name: infra, 1-2x CPX31, autoscaling: false, labels: {pool: infra}
      - name: app, 1-10x CPX31, autoscaling: true, labels: {pool: app}
```

**Benodigdheden:**
- Hetzner Cloud account + API token
- `hetzner-k3s` CLI geïnstalleerd (`gem install hetzner-k3s`)
- `kubectl` lokaal beschikbaar

**Acceptatiecriteria:**
- [ ] `hetzner-k3s create cluster --config iac/cluster.yaml` slaagt in <5 min
- [ ] `kubectl get nodes` toont 3 servers + minimaal 1 infra + 1 app agent
- [ ] Alle nodes `Ready`
- [ ] Masters hebben `NoSchedule` taint (geen workloads)
- [ ] Infra nodes hebben label `pool: infra`
- [ ] App nodes hebben label `pool: app`
- [ ] Traefik ingress controller actief (K3s standaard)
- [ ] kube-prometheus-stack gedeployed in `monitoring` namespace
- [ ] `kubectl get pods -A` toont alleen system/monitoring pods op masters

---

### Task 3: Helm chart productie-ready (resources, replicas, PVCs)

**Story points:** 2 | **Priority:** P0 | **Depends on:** Task 1, Task 2

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
- [ ] `helm template --validate` slaagt
- [ ] `helm template -f values-prod.yaml` genereert geldige productie YAML
- [ ] Elke Deployment heeft `resources.requests` en `resources.limits`
- [ ] Replica counts configureerbaar per environment
- [ ] PVCs hebben configureerbare `storageClassName`

---

### Task 4: Ingress — Traefik support + TLS (cert-manager)

**Story points:** 2 | **Priority:** P1 | **Depends on:** Task 3

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
- [ ] `helm template` met `className: nginx` → NGINX Ingress (Kind blijft werken)
- [ ] `helm template` met `className: traefik` → Traefik Ingress (geen NGINX annotations)
- [ ] ClusterIssuer template gegenereerd wanneer `cert-manager.enabled: true`
- [ ] TLS annotations aanwezig wanneer `tls.enabled: true`

---

### Task 5: Sealed Secrets + productie secrets ingericht

**Story points:** 1 | **Priority:** P1 | **Depends on:** Task 3

**Scope:**
- Sealed Secrets controller installatie instructies
- `secrets.yaml` template markeren als dev-only fallback
- Productie: Sealed Secrets voor alle API keys, DB passwords
- `kubeseal` commando's documenteren

```
Wijzigen: helm/druppie/templates/secrets.yaml
  - Comment: "DEV ONLY — use Sealed Secrets for production"

Aanmaken: secrets/sealed/README.md
  - kubeseal installatie
  - Secret versleutelen procedure
  - Private key backup procedure

Wijzigen: helm/druppie/values-prod.yaml
  - secrets sectie: verwijzing naar Sealed Secrets (lege waarden)
```

**Acceptatiecriteria:**
- [ ] `secrets.yaml` gemarkeerd als dev-only
- [ ] Sealed Secrets procedure gedocumenteerd
- [ ] Private key backup procedure gedocumenteerd

---

### Task 6: CloudNativePG — HA PostgreSQL

**Story points:** 3 | **Priority:** P1 | **Depends on:** Task 3

**Scope:**
- CloudNativePG operator v1.29.1+ installatie instructies
- 3 database cluster CRDs: druppie-db, keycloak-db, gitea-db
- Bestaande PostgreSQL StatefulSets vervangen
- Alle deployments bijwerken: connection strings naar CNPG naming

```
Aanmaken: helm/druppie/templates/databases/druppie-db-cluster.yaml
Aanmaken: helm/druppie/templates/databases/keycloak-db-cluster.yaml
Aanmaken: helm/druppie/templates/databases/gitea-db-cluster.yaml

Verwijderen: helm/druppie/templates/druppie-db-statefulset.yaml
Verwijderen: helm/druppie/templates/keycloak-db-statefulset.yaml
Verwijderen: helm/druppie/templates/gitea-db-statefulset.yaml

Wijzigen: helm/druppie/templates/configmap.yaml
  - DATABASE_URL → CNPG service naming (druppie-db-rw:5432)

Wijzigen: helm/druppie/templates/services.yaml
  - DB services bijwerken voor CNPG

Wijzigen: helm/druppie/templates/backend-deployment.yaml
  - wait-for-db initContainer → CNPG service

Wijzigen: helm/druppie/templates/keycloak-deployment.yaml
  - KC_DB_URL → CNPG service (keycloak-db-rw:5432)

Wijzigen: helm/druppie/templates/gitea-deployment.yaml
  - GITEA__database__HOST → CNPG service (gitea-db-rw:5432)

Wijzigen: helm/druppie/templates/init-job.yaml
  - DB connection strings → CNPG
```

**Acceptatiecriteria:**
- [ ] 3 CNPG Cluster CRDs gedefinieerd (elk 3 instances)
- [ ] Oude StatefulSets verwijderd
- [ ] `helm template` genereert CNPG clusters + bijgewerkte deployments
- [ ] Connection strings verwijzen naar CNPG `-rw` service

---

### Task 7: HPA — Backend en frontend horizontaal schaalbaar

**Story points:** 2 | **Priority:** P1 | **Depends on:** Task 1, Task 3

**Scope:**
- HPA templates voor backend (2-10 replicas) en frontend (2-8 replicas)
- CPU target 70%
- Stabilization windows: scaleUp 60s, scaleDown 300s

```
Aanmaken: helm/druppie/templates/hpa-backend.yaml
  - minReplicas: 2, maxReplicas: 10
  - CPU target 70%
  - behavior: scaleUp +2 pods / 60s, scaleDown -50% / 300s

Aanmaken: helm/druppie/templates/hpa-frontend.yaml
  - minReplicas: 2, maxReplicas: 8
  - CPU target 70%
  - behavior: scaleUp +2 pods / 60s, scaleDown -50% / 300s

Wijzigen: helm/druppie/values-prod.yaml
  - autoscaling.backend.enabled: true
  - autoscaling.frontend.enabled: true
```

**Acceptatiecriteria:**
- [ ] `helm template` genereert HPA resources
- [ ] Backend HPA: min 2, max 10, CPU 70%
- [ ] Frontend HPA: min 2, max 8, CPU 70%
- [ ] Stabilization windows geconfigureerd (geen oscillatie)

---

### Task 8: HA — PDB + anti-affinity + graceful shutdown

**Story points:** 1 | **Priority:** P1 | **Depends on:** Task 7

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
- [ ] PDB's gedefinieerd: minAvailable 1 voor backend en frontend
- [ ] Anti-affinity: pods verspreid over nodes
- [ ] Graceful shutdown: SIGTERM → drain tasks → exit binnen 60s

---

### Task 9: Monitoring — kube-prometheus-stack

**Story points:** 1 | **Priority:** P2 | **Depends on:** Task 2

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
- [ ] Installatie instructies compleet
- [ ] Prometheus scrape alle pods
- [ ] Grafana bereikbaar met dashboards

---

### Task 10: Documentatie — setup, scaling, beperkingen

**Story points:** 1 | **Priority:** P0 | **Depends on:** alle taken

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
- [ ] Setup guide compleet (Kind + K3s)
- [ ] Scaling gedrag gedocumenteerd
- [ ] Beperkingen en bekende issues gedocumenteerd
- [ ] Backlog items voor Phase 2 aangemaakt

---

## Afhankelijkheden

```
Task 1 (Stateless backend) ─── P0, geen dependencies
│
├── Task 2 (K3s cluster Hetzner) ─ P0, kan parallel met 1
│   └── Task 9 (Monitoring) ────── P2, depends on 2
│
├── Task 3 (Helm chart ready) ─── P0, depends on 1+2
│   ├── Task 4 (Ingress + TLS) ─── P1, depends on 3
│   ├── Task 5 (Sealed Secrets) ── P1, depends on 3
│   ├── Task 6 (CloudNativePG) ─── P1, depends on 3
│   └── Task 7 (HPA) ───────────── P1, depends on 1+3
│       └── Task 8 (PDB + anti-affinity) ── P1, depends on 7
│
└── Task 10 (Documentatie) ─────── P0, depends op alles
```

**Parallel uitvoerbaar:**
- Task 1 + Task 2 (stateless backend + cluster provisioning tegelijk)
- Task 4 + Task 5 + Task 6 + Task 7 + Task 9 (na Task 3)

---

## Bestandswijzigingen Overzicht

### Nieuwe bestanden

| Bestand | Task | Omschrijving |
|---------|------|-------------|
| `iac/cluster.yaml` | 2 | hetzner-k3s cluster definitie |
| `helm/druppie/values-prod.yaml` | 3 | Productie Helm overlay |
| `helm/druppie/templates/cluster-issuer.yaml` | 4 | Let's Encrypt issuers |
| `secrets/sealed/README.md` | 5 | Sealed Secrets procedure |
| `helm/druppie/templates/databases/druppie-db-cluster.yaml` | 6 | CNPG cluster: druppie |
| `helm/druppie/templates/databases/keycloak-db-cluster.yaml` | 6 | CNPG cluster: keycloak |
| `helm/druppie/templates/databases/gitea-db-cluster.yaml` | 6 | CNPG cluster: gitea |
| `helm/druppie/templates/hpa-backend.yaml` | 7 | Backend HPA |
| `helm/druppie/templates/hpa-frontend.yaml` | 7 | Frontend HPA |
| `helm/druppie/templates/pdb-backend.yaml` | 8 | Backend PDB |
| `helm/druppie/templates/pdb-frontend.yaml` | 8 | Frontend PDB |
| `docs/monitoring-setup.md` | 9 | Monitoring installatie |

### Gewijzigde bestanden

| Bestand | Task | Wijziging |
|---------|------|-----------|
| `druppie/core/background_tasks.py` | 1 | In-memory dict → DB-driven task guard |
| `druppie/api/routes/sessions.py` | 1 | Aanpassen aan nieuw task guard interface |
| `druppie/api/routes/approvals.py` | 1 | Aanpassen aan nieuw task guard interface |
| `druppie/api/routes/questions.py` | 1 | Aanpassen aan nieuw task guard interface |
| `druppie/api/routes/chat.py` | 1 | Aanpassen aan nieuw task guard interface |
| `druppie/api/routes/sandbox.py` | 1 | Aanpassen aan nieuw task guard interface |
| `druppie/services/job_service.py` | 1 | Aanpassen aan nieuw task guard interface |
| `helm/druppie/values.yaml` | 3,4,6,7 | Resources, ingress, CNPG, HPA config |
| `helm/druppie/templates/backend-deployment.yaml` | 3,6,7,8 | Resources, CNPG init, anti-affinity, terminationGracePeriod |
| `helm/druppie/templates/frontend-deployment.yaml` | 3,7,8 | Resources, anti-affinity |
| `helm/druppie/templates/keycloak-deployment.yaml` | 3,6 | Resources, CNPG connection |
| `helm/druppie/templates/gitea-deployment.yaml` | 3,6 | Resources, CNPG connection |
| `helm/druppie/templates/module-*-deployment.yaml` | 3 | Resources |
| `helm/druppie/templates/ingress.yaml` | 4 | NGINX/Traefik conditioneel, TLS |
| `helm/druppie/templates/secrets.yaml` | 5 | Dev-only marker |
| `helm/druppie/templates/configmap.yaml` | 6 | CNPG service naming |
| `helm/druppie/templates/services.yaml` | 6 | DB services bijwerken |
| `helm/druppie/templates/init-job.yaml` | 6 | CNPG connection strings |
| `helm/druppie/templates/persistentvolumeclaims.yaml` | 3 | Configureerbare storageClass |
| `druppie/api/main.py` | 8 | SIGTERM handler, graceful shutdown |

### Verwijderde bestanden

| Bestand | Task | Reden |
|---------|------|-------|
| `helm/druppie/templates/druppie-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |
| `helm/druppie/templates/keycloak-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |
| `helm/druppie/templates/gitea-db-statefulset.yaml` | 6 | Vervangen door CloudNativePG |

---

## Out of Scope (Phase 2+)

| Onderwerp | Waarom niet nu | Wanneer |
|-----------|----------------|---------|
| Sandbox migratie (Docker → K8s) | Docker socket dependency | Phase 2 |
| ArgoCD | Push-based CI/CD is voldoende | Phase 2 |
| Message queue (Redis Streams/NATS) | Database-driven resume volstaat | Phase 2 |
| KEDA (queue-based scaling) | HPA op CPU is voldoende voor Phase 1 | Phase 2 |
| Network Policies per-namespace | Niet blocking | Phase 2 |
| Longhorn RWX | MCP modules gebruiken local-path | Phase 2 (indien nodig) |
| gVisor / Kata Containers | Sandbox blijft op Docker | Phase 2 |
| Harbor registry | Gitea registry volstaat | Phase 2 |
| CI/CD pipeline (GitHub Actions) | Kan na eerste handmatige deploy | Vervolgstory |
| Distributed tracing (Jaeger/Tempo) | Nog niet nodig bij deze schaal | Phase 3 |

---

## Risico's en Mitigaties

| Risico | Impact | Kans | Mitigatie |
|--------|--------|------|-----------|
| Backend stateless refactor breekt bestaande flows | Regression | Medium | Alle routes testen. Kind smoke test. Bestaande tests moeten slagen. |
| CloudNativePG operationele kennis ontbreekt | DB issues in productie | Medium | Failover testen op staging. Runbooks schrijven. |
| HPA scaling te agressief of te traag | Oscillatie of vertraging | Laag | Stabilization windows (300s/60s). Tunen op load tests. |
| Sealed Secrets key verloren | Alle secrets ontoegankelijk | Medium | Private key backup procedure + test. |
| Traefik path rewrite voor Gitea | Broken routing | Medium | Testen op Kind met Traefik. IngressRoute CRDs als fallback. |
| Backend image ~4GB, te groot voor 10 replicas | Hoge RAM costs | Medium | Multi-stage build als vervolgstap. |
