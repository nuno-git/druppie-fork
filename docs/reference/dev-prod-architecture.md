# Druppie Infrastructure: Dev vs Prod Architecture

> **Status:** Geaccepteerd
> **Datum:** 2026-06-16
> **Type:** Architecture Decision Record
> **Referentie:** [ADR-KUBERNETES.md](../adrs/002-kubernetes-migration.md), [KUBERNETES-STRATEGY.md](../research/006-kubernetes-strategy.md)

---

## Inhoud

1. [Overzicht](#1-overzicht)
2. [Dev Setup (Single VM)](#2-dev-setup-single-vm)
3. [Prod Setup (Multi-VM)](#3-prod-setup-multi-vm)
4. [Per-Laag Vergelijking](#4-per-laag-vergelijking)
5. [Wat Blijft Hetzelfde](#5-wat-blijft-hetzelfde)
6. [Values Overlays](#6-values-overlays)
7. [Schakelen Tussen Dev en Prod](#7-schakelen-tussen-dev-en-prod)
8. [Kostenvergelijking](#8-kostenvergelijking)
9. [Migratiepad: Dev naar Prod](#9-migratiepad-dev-naar-prod)

---

## 1. Overzicht

Druppie gebruikt **dezelfde Helm chart, de samme CI/CD pipeline, en dezelfde Docker images** voor zowel dev als prod. Het verschil zit puur in de infrastructuurlaag (aantal VMs, storage driver, networking) en de `values.yaml` overlay.

```
┌─────────────────────────────────────────────────────────────┐
│                    Gedeelde Laag                             │
│                                                             │
│  GitHub Repo (colab-dev)                                    │
│    ├── helm/druppie/          (1 Helm chart)                │
│    ├── .github/workflows/     (1 CI/CD pipeline)            │
│    ├── druppie/               (applicatie code)             │
│    └── iac/                   (infrastructuur manifests)    │
│                                                             │
│  Pipeline flow (identiek voor beide):                       │
│    PR merge → build 13 images → push registry → helm deploy │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌─────────────────┐      ┌─────────────────────┐
     │  DEV (1 VM)     │      │  PROD (5-6 VMs)     │
     │                 │      │                     │
     │  values-dev.yaml│      │  values-prod.yaml   │
     │  SQLite         │      │  etcd (3 nodes)     │
     │  local-path     │      │  hcloud CSI         │
     │  1 replica      │      │  3+ replicas        │
     │  ~€50/mo        │      │  ~€150/mo           │
     └─────────────────┘      └─────────────────────┘
```

**Kernprincipe:** De applicatie weet niet waar ze draait. Alleen de infrastructuur en values verschillen.

---

## 2. Dev Setup (Single VM)

### Architectuur

```
┌──────────────────────────────────────────────────────┐
│  CCX33 (Hetzner Cloud)                               │
│  8 vCPU dedicated AMD EPYC                           │
│  32 GB RAM                                           │
│  320 GB NVMe SSD                                     │
│  Ubuntu 24.04 LTS                                    │
│  ~€50/maand                                          │
│                                                      │
│  K3s single-server (SQLite backend)                  │
│  ├── Traefik (gebundeld, ingress + TLS)             │
│  ├── local-path-provisioner (opslag op lokale disk)  │
│  ├── cert-manager (Let's Encrypt TLS)               │
│  ├── CoreDNS custom (interne DNS herschrijvingen)    │
│  │                                                   │
│  ├── Registry:2 (10.43.60.14:5000, intern)          │
│  ├── GitHub Actions Runner (DinD, bouwt images)      │
│  │                                                   │
│  └── Druppie Helm release                           │
│      ├── backend (2 replicas)                        │
│      ├── frontend (1 replica)                        │
│      ├── layout-service (1 replica)                  │
│      ├── 8x MCP modules (1 replica elk)              │
│      ├── CNPG Postgres (1 instance)                  │
│      ├── Keycloak (1 replica)                        │
│      └── Gitea (1 replica)                           │
│                                                      │
│  DNS: *.druppie.rijnland.dev → dit VM's publieke IP  │
│  Ingress: Traefik op poort 80/443                    │
└──────────────────────────────────────────────────────┘
```

### VM Keuze: CCX33

| Eigenschap | Waarde | Waarom |
|------------|--------|--------|
| CPU | 8 vCPU **dedicated** | Geen noisy neighbors bij Docker builds |
| RAM | 32 GB | Genoeg voor alle pods + CI runner + DinD |
| Disk | 320 GB NVMe | Images (~15 GB), registry (~30 GB), databases |
| Arch | x86_64 | Alle Docker images werken (geen ARM compatibiliteitsproblemen) |
| Netwerk | 20 TB traffic | Ruim voldoende |

**Alternatieven overwogen:**

| VM | Specs | Prijs | Waarom niet |
|----|-------|-------|-------------|
| CAX41 (ARM) | 16 vCPU, 32GB, 320GB | ~€35/mo | ARM: Microsoft ODBC drivers en sommige images werken niet |
| CPX51 (shared) | 16 vCPU, 32GB, 400GB | ~€56/mo | Shared CPU: onvoorspelbare bouwtijden |
| CCX43 (dedicated) | 16 vCPU, 32GB, 320GB | ~€78/mo | Meer CPU dan nodig voor dev |

### Installatie

```bash
# 1. VM aanmaken via hcloud CLI (of web console)
hcloud server create \
  --name druppie-dev \
  --type cpx33 \
  --image ubuntu-24.04 \
  --ssh-key <key-name> \
  --location nbg1

# 2. K3s installeren (1 commando)
ssh root@<VM-IP>
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644 \
  --disable traefik \
  --disable servicelb

# 3. Kubeconfig ophalen
cat /etc/rancher/k3s/k3s.yaml > kubeconfig
# Vervang 127.0.0.1 door het VM's publieke IP

# 4. Infrastructuur deployen
kubectl apply -f iac/dev/
kubectl apply -f iac/registry/registry.yaml
kubectl apply -f iac/coredns-custom.override

# 5. Druppie deployen
helm upgrade druppie ./helm/druppie -n druppie \
  -f helm/druppie/values-dev.yaml \
  -f helm/druppie/values-dev.secrets.yaml \
  --create-namespace --wait --timeout 10m
```

### Kenmerken

| Eigenschap | Dev |
|------------|-----|
| HA | Nee (single point of failure) |
| Storage | local-path (lokale NVMe, geen replicatie) |
| LoadBalancer | Nee (NodeIP direct) |
| DB replicatie | Nee (1 CNPG instance) |
| Backup | Handmatig (optioneel: snapshot via hcloud) |
| Auto-scaling | Nvt (1 node) |
| CI runner | Same node (deelt resources met workloads) |

---

## 3. Prod Setup (Multi-VM)

### Architectuur

```
┌─────────────────────────────────────────────────────────────────┐
│  Hetzner Cloud — 2 netwerken (private + public)                 │
│                                                                 │
│  ┌─────────────────────────────────────────────┐                │
│  │  Master Pool (3x CPX21)                     │                │
│  │  3 vCPU, 4GB, 80GB elk                      │                │
│  │  ~€18/mo elk = ~€54/mo                      │                │
│  │                                             │                │
│  │  K3s embedded etcd (3 nodes = quorum)       │                │
│  │  Alleen control plane, geen workloads       │                │
│  │  (tainted: CriticalAddonsOnly)              │                │
│  └─────────────────────────────────────────────┘                │
│                                                                 │
│  ┌─────────────────────────────────────────────┐                │
│  │  Worker Pool Infra (1x CCX33)               │                │
│  │  8 vCPU, 32GB, 320GB                        │                │
│  │  ~€50/mo                                    │                │
│  │                                             │                │
│  │  Registry, CI runner, Gitea, Keycloak       │                │
│  │  CNPG Postgres, core services               │                │
│  └─────────────────────────────────────────────┘                │
│                                                                 │
│  ┌─────────────────────────────────────────────┐                │
│  │  Worker Pool App (1-3x CPX41)               │                │
│  │  8 vCPU, 16GB, 240GB elk                    │                │
│  │  ~€30/mo elk = ~€30-90/mo                   │                │
│  │  (autoscaled via Cluster Autoscaler)        │                │
│  │                                             │                │
│  │  Backend, frontend, MCP modules             │                │
│  │  Layout-service                              │                │
│  └─────────────────────────────────────────────┘                │
│                                                                 │
│  totaal: ~€134-194/maand                                        │
│                                                                 │
│  Hulpservices:                                                  │
│  ├── MetalLB (LoadBalancer IP failover)                        │
│  ├── hcloud CSI (gedeelde volumes tussen nodes)                 │
│  ├── cert-manager (Let's Encrypt)                              │
│  ├── KEDA (event-driven autoscaling)                           │
│  └── Velero (automated backups → S3)                           │
└─────────────────────────────────────────────────────────────────┘
```

### VM Indeling

| Rol | VM Type | Aantal | Specs elk | Prijs/VM | Totale Prijs |
|-----|---------|--------|-----------|----------|-------------|
| Master (etcd + control plane) | CPX21 | 3 | 3 vCPU, 4GB, 80GB | ~€18/mo | ~€54/mo |
| Worker Infra | CCX33 | 1 | 8 vCPU, 32GB, 320GB | ~€50/mo | ~€50/mo |
| Worker App | CPX41 | 1-3 | 8 vCPU, 16GB, 240GB | ~€30/mo | ~€30-90/mo |
| **Totaal** | | **5-7** | | | **~€134-194/mo** |

### Installatie

```bash
# Master 1 (cluster init)
ssh root@<master1-IP>
curl -sfL https://get.k3s.io | sh -s - \
  --cluster-init \
  --tls-san <master1-IP> \
  --tls-san druppie-k8s.internal \
  --node-taint CriticalAddonsOnly=true:NoSchedule

# Haal cluster token op
cat /var/lib/rancher/k3s/server/node-token

# Master 2 + 3 (join etcd quorum)
curl -sfL https://get.k3s.io | sh -s - \
  --server https://<master1-IP>:6443 \
  --token <NODE_TOKEN> \
  --node-taint CriticalAddonsOnly=true:NoSchedule

# Workers (join als agent)
curl -sfL https://get.k3s.io | sh -s - \
  --server https://<master1-IP>:6443 \
  --token <NODE_TOKEN> \
  --node-label nodepool=infra    # of nodepool=app
```

### Prod-specifieke componenten

| Component | Doel | Waarom niet in dev |
|-----------|------|-------------------|
| MetalLB | Floating IP failover bij node crash | 1 node = niets te failoveren |
| hcloud CSI | PVs volgen pods naar andere nodes | 1 node = volumes altijd lokaal |
| KEDA | Scale backend obv LLM queue depth | 1 node = kan niet schalen |
| Cluster Autoscaler | Voeg VMs toe bij Pending pods | 1 node = geen autoscaling |
| Velero | Geautomatiseerde backups naar S3 | Dev data is vervangbaar |
| PodDisruptionBudgets | Bescherm pods bij node drains | 1 node = geen rolling updates |
| Anti-affinity rules | Verspreid pods over nodes | 1 node = nergens te verspreiden |

### Kenmerken

| Eigenschap | Prod |
|------------|------|
| HA | Ja (1 node mag crashen zonder downtime) |
| Storage | hcloud CSI (volumes replicated door Hetzner) |
| LoadBalancer | MetalLB (floating IP failover) |
| DB replicatie | Ja (3 CNPG instances, auto-failover <30s) |
| Backup | Velero → S3 (dagelijks) |
| Auto-scaling | KEDA (pods) + Cluster Autoscaler (nodes) |
| CI runner | Aparte infra node (geen noise op app nodes) |

---

## 4. Per-Laag Vergelijking

| Laag | Dev (1 VM) | Prod (5-7 VMs) |
|------|------------|-----------------|
| **K3s backend** | SQLite (single server) | Embedded etcd (3 servers, quorum) |
| **Control plane** | 1 server (geen HA) | 3 servers (1 kan crashen) |
| **Workers** | Zelfde node als server | Dedicated worker pools |
| **Storage** | local-path (lokale NVMe) | hcloud CSI (network-attached volumes) |
| **Storage classes** | `local-path` | `hcloud-volumes`, `local-path` (fallback) |
| **LoadBalancer** | Nvt (NodeIP direct) | MetalLB (floating IP) |
| **Ingress** | Traefik op NodeIP | Traefik op MetalLB IP |
| **TLS** | cert-manager (Let's Encrypt) | cert-manager (Let's Encrypt) |
| **DNS** | Wildcard → NodeIP | Wildcard → MetalLB VIP |
| **CNPG Postgres** | 1 instance, local-path | 3 instances, hcloud-volumes |
| **Backend replicas** | 2 | 3+ (anti-affinity over nodes) |
| **Frontend replicas** | 1 | 2+ (anti-affinity) |
| **MCP modules** | 1 replica elk | 2+ per module (indien stateless) |
| **KEDA** | Nvt | Ja (backend + modules) |
| **Backup** | Handmatig snapshot | Velero → S3, dagelijks |
| **Monitoring** | Lightweight (optioneel) | Volledig (Prometheus + Grafana + Alerts) |
| **CI runner** | Same node | Infra worker node |

---

## 5. Wat Blijft Hetzelfde

Deze componenten veranderen **niet** tussen dev en prod:

### Applicatie

| Component | Bestand | Opmerking |
|-----------|---------|-----------|
| Helm chart | `helm/druppie/` | Zelfde chart, alleen values verschillen |
| Docker images | `druppie/*/Dockerfile` | Zelfde 13 images |
| Backend code | `druppie/` | Identiek |
| Frontend code | `frontend/` | Identiek |
| MCP servers | `druppie/mcp-servers/` | Identiek |
| Agent definitions | `druppie/agents/definitions/` | Identiek |

### CI/CD Pipeline

| Component | Bestand | Opmerking |
|-----------|---------|-----------|
| Build & Deploy workflow | `.github/workflows/build-and-deploy.yml` | Identiek |
| GitHub Actions Runner | `iac/arc-runners/runner-deployment.yaml` | Identiek manifest |
| Registry | `iac/registry/registry.yaml` | Identiek manifest |
| Docker daemon config | `iac/arc-runners/docker-daemon-config.yaml` | Identiek |
| CoreDNS rewrites | `iac/coredns-custom.override` | Identiek |

### Pipeline Flow (identiek voor beide)

```
Developer push → PR op colab-dev
  → GitHub Actions trigger
    → Runner pod (DinD)
      → 13x docker build --network=host
      → 13x push naar registry (10.43.x.x:5000)
      → manifest sync (tag voor pull registry)
      → kubectl + helm install
      → helm upgrade --values <env>.yaml
      → kubectl verify
  → Done
```

---

## 6. Values Overlays

De Helm chart gebruikt **environment-specific values files**. De base values (`values.yaml`) bevatten defaults die voor beide omgevingen werken.

### values-dev.yaml

```yaml
# Single-VM dev setup
imageRegistry: registry.druppie.rijnland.dev/druppie

# Storage: lokale disk (geen CSI nodig)
storageClass: local-path

# Replicas: minimaal (1 node)
backend:
  replicaCount: 2
frontend:
  replicaCount: 1
modules:
  replicaCount: 1

# CNPG: 1 instance (geen HA nodig voor dev)
postgresql:
  instances: 1
  storageClass: local-path

# Geen anti-affinity (1 node)
affinity: {}

# Geen KEDA
autoscaling:
  enabled: false
```

### values-prod.yaml

```yaml
# Multi-VM prod setup
imageRegistry: registry.druppie.rijnland.dev/druppie

# Storage: hcloud CSI (volumes volgen pods)
storageClass: hcloud-volumes

# Replicas: HA over meerdere nodes
backend:
  replicaCount: 3
frontend:
  replicaCount: 2
modules:
  replicaCount: 2

# CNPG: 3 instances met auto-failover
postgresql:
  instances: 3
  storageClass: hcloud-volumes

# Anti-affinity: verspreid over nodes
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: app.kubernetes.io/name
              operator: In
              values: ["druppie-backend"]
        topologyKey: kubernetes.io/hostname

# KEDA voor event-driven scaling
autoscaling:
  enabled: true
```

### Secrets (gitignored)

Beide omgevingen hebben een `<env>.secrets.yaml` overlay die niet in git staat:

```yaml
# values-dev.secrets.yaml of values-prod.secrets.yaml
zaiApiKey: "<key>"
deepinfraApiKey: "<key>"
internalApiKey: "<key>"
giteaToken: "<token>"
moduleApiToken: "<token>"
```

---

## 7. Schakelen Tussen Dev en Prod

De keuze tussen dev en prod is **enkel een deploy-target keuze** — geen code wijziging.

### Dev Deploy

```bash
# Lokaal handmatig
helm upgrade druppie ./helm/druppie -n druppie \
  -f helm/druppie/values-dev.yaml \
  -f helm/druppie/values-dev.secrets.yaml \
  --kubeconfig ./kubeconfig-dev \
  --wait --timeout 10m

# Via CI/CD (automatisch)
# GitHub Actions gebruikt KUBECONFIG secret voor dev cluster
```

### Prod Deploy

```bash
# Lokaal handmatig
helm upgrade druppie ./helm/druppie -n druppie \
  -f helm/druppie/values-prod.yaml \
  -f helm/druppie/values-prod.secrets.yaml \
  --kubeconfig ./kubeconfig-prod \
  --wait --timeout 10m

# Via CI/CD (automatisch)
# GitHub Actions gebruikt KUBECONFIG secret voor prod cluster
```

### Pipeline Configuratie

De CI/CD pipeline kan beide targets aan via environment variabelen:

```yaml
# In GitHub Actions
env:
  KUBECONFIG: ${{ secrets.KUBECONFIG_DEV }}  # of KUBECONFIG_PROD
  VALUES_FILE: values-dev.yaml                # of values-prod.yaml
  SECRETS_FILE: values-dev.secrets.yaml       # of values-prod.secrets.yaml
```

---

## 8. Kostenvergelijking

| Component | Dev (1 VM) | Prod (5-7 VMs) |
|-----------|------------|-----------------|
| Master nodes | — | 3x CPX21 = €54/mo |
| Infra worker | — | 1x CCX33 = €50/mo |
| App workers | — | 1-3x CPX41 = €30-90/mo |
| **Totaal VMs** | **1x CCX33 = €50/mo** | **€134-194/mo** |
| Storage (extra) | Inbegrepen (320GB) | Inbegrepen + hcloud volumes (~€5-15/mo) |
| Traffic | 20 TB inbegrepen | 20 TB inbegrepen |
| Backups | Handmatig (gratis snapshot) | Velero → S3 (~€2-5/mo) |
| **Totaal** | **~€50/mo** | **~€140-210/mo** |

---

## 9. Migratiepad: Dev naar Prod

Wanneer Druppie van dev naar prod gaat:

### Stap 1: Master pool toevoegen
```bash
# Creëer 3 CPX21 VMs via hcloud
# Installeer K3s met --cluster-init op nieuwe master1
# Join master2 + master3 aan het nieuwe cluster
```

### Stap 2: Worker pools toevoegen
```bash
# Creëer 1 CCX33 (infra) en 1-3 CPX41 (app)
# Join als K3s agents met juiste node-labels
```

### Stap 3: Prod infrastructuur installeren
```bash
kubectl apply -f iac/prod/    # MetalLB, hcloud CSI, Velero
```

### Stap 4: Values overlay wisselen
```bash
# In GitHub repo: update workflow secrets
# KUBECONFIG_DEV → KUBECONFIG_PROD
# values-dev.yaml → values-prod.yaml
```

### Stap 5: Data migreren (optioneel)
```bash
# Backup dev database
kubectl exec -n druppie druppie-druppie-db-1 -- pg_dumpall > backup.sql

# Restore op prod cluster
kubectl exec -i -n druppie druppie-druppie-db-1 -- psql < backup.sql
```

### Stap 6: DNS wisselen
```bash
# Wijzig DNS records van dev IP naar prod MetalLB VIP
# *.druppie.rijnland.dev → <prod-vip>
```

### Stap 7: Dev VM afbreken
```bash
hcloud server delete druppie-dev
```

**Belangrijk:** De repo code verandert niet — alleen de `iac/` map groeit met prod-specifieke manifests, en de CI/CD secrets wijzigen naar het prod cluster.

---

## Besluitvorming

| # | Beslissing | Keuze | Reden |
|---|-----------|-------|-------|
| 1 | Dev infrastructuur | Single CCX33 VM | Goedkoopst, simpelst, voldoende voor ontwikkeling |
| 2 | Prod infrastructuur | 3 masters + infra + app workers | HA, schaalbaar, failure tolerance |
| 3 | Gedeelde code | 1 Helm chart, 1 pipeline | DRY, geen duplicatie, zelfde images |
| 4 | Verschil mechanisme | Values overlays | Industriestandaard, geen code changes nodig |
| 5 | Storage dev | local-path | Geen CSI driver nodig, lokale NVMe is snel |
| 6 | Storage prod | hcloud CSI | Volumes volgen pods, HA storage |
| 7 | Migratie pad | Stapsgewijs uitbreiden | Geen big-bang, dev kan blijven draaien |
