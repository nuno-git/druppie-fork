# Research: Developer & Preview Environments on Local Rancher RKE2 Cluster

> **Status:** Research — alle beslissingen genomen  
> **Datum:** 2026-06-23  
> **Cluster:** Rancher RKE2 (containerd) · 1TB RAM · Xeon CPUs · 4× RTX 6000 Pro  
> **Stories:** [1/3 K8s] Migratie · [2/3 K8s] CI/CD · [3/3 K8s] Preview/Dev omgevingen  

---

## Genomen beslissingen (totaaloverzicht)

| # | Beslissing | Keuze | Rationale |
|---|-----------|-------|-----------|
| 1 | Cluster | **Rancher RKE2 met containerd** (8 nodes: 3 master + 1 GPU + 4 worker, ~480GB worker RAM) | Rancher-managed, CIS hardened, al aanwezig |
| 2 | Container runtime (dev + sandbox) | **Kata Containers** | Native containerd RuntimeClass, Docker-in-Docker, SSH, systemd, VM-level isolatie |
| 3 | Dev pod model | **Model A: alles in 1 pod** | Simpel, hot reload, geen K8s-networking, developer-centrisch |
| 4 | GitOps voor prod/dev namespaces | **FluxCD** (door infra buiten cluster gezet) | CNCF Graduated, git → cluster sync, drift detection |
| 5 | Preview/Dev VMs — provisioning | **Druppie backend + UI** | Handmatig, één knop, developer selecteert branch |
| 6 | Preview/Dev VMs — lifecycle | **Handmatig**, niet auto per PR | Developer bepaalt wanneer deploy, review, stop |
| 7 | Secrets | **3-laags: bootstrap (per-VM) + Vault/ESO (per-user) + cluster (static)** | Lokale Gitea voorkomt prod vervuiling, Vault beheert developer credentials |
| 8 | Storage | **Longhorn** (al in cluster) | PVCs voor dev VMs, snapshots, backups |
| 9 | Ingress + TLS | **Traefik + cert-manager** (al in cluster) | Wildcard DNS, Let's Encrypt, werkt al |
| 10 | Container registry | **Harbor** (in cluster, zelf geïnstalleerd) | Scanning, signing, UI, replication. CNCF Graduated |
| 11 | Monitoring | **Prometheus** (al in cluster) | Metrics, alerting, Grafana |
| 12 | GPU node | **Exclusief voor prod LLM pod** (2× RTX 6000 Pro, 96GB VRAM) | NoSchedule taint, 2× nvidia.com/gpu exclusive |
| 13 | LLM toegang dev/colab-dev | **Via prod LLM URL** (OpenAI-compatible endpoint via K8s service DNS) | Geen GPU node nodig in dev,zelfde modellen als prod |
| 14 | Auth in dev VMs | **Mock auth** (geen Keycloak) | Developer is al geauthenticeerd op de pod |
| 15 | Auth in colab-dev namespace | **Keycloak** (volledig) | Zelfde als prod — realistische staging |
| 16 | Agent sandboxes vs Dev VMs | **Gescheiden pods**, zelfde runtime, via git | Agent commit → developer pull/review → sync |
| 17 | MCP modules in dev VMs | **Alles lokaal** in de pod | Simpel beginnen, later shared pool voor ongewijzigde modules |
| 18 | Cluster toegang | **Druppie team heeft cluster-admin** | Volledige autonomie over namespaces, labels, operators |
| 19 | Prod/dev isolatie | **PriorityClasses** (prod=10000, colab-dev=8000, CI=3000, dev VM=1000, agent=500) | Geen aparte nodes — K8s evict laagste priority eerst bij pressure |
| 20 | Colab-dev | **Zelfde stack als prod**, alleen minder replicas en geen HA | Identiek functioneel, ~30GB RAM vs ~35GB prod |
| 21 | Remote access | **Apache Guacamole** (RDP + SSH via 443 HTTPS, browser-based) | Alles over 443, geen extra poorten openen. RDPGW later als native client gewenst |

---

## 1. Infrastructuur — wat er al is

Sommige services draaien **buiten het cluster** (beheerd door infra-team), andere **in het cluster** (via GitOps).

### Buiten het cluster (infra beheert)

| Component | Functie | Impact voor ons |
|-----------|---------|-----------------|
| **Hashicorp Vault** | Secrets management (SSO) | Alle tokens, API keys, SSH keys komen uit Vault |
| **External Secrets Operator** | Synct Vault → K8s secrets | Draait in cluster, praat met externe Vault |
| **Gitea (SSO)** | Git repos + Gitea Actions CI | Code repo, CI builds. Container Registry NIET enabled |
| **FluxCD** | GitOps deployment | Watcht git repo → sync naar cluster. Vervangt Fleet |

### In het cluster (via FluxCD GitOps)

| Component | Functie | Impact voor ons |
|-----------|---------|-----------------|
| **Traefik** | Ingress controller | Dev VM URLs via Traefik IngressRoute |
| **cert-manager** | Let's Encrypt TLS | Automatische certificaten voor dev VM URLs |
| **Longhorn** | Distributed block storage | PVCs voor dev VM home directories |
| **NVIDIA GPU Operator** | GPU time-slicing/MIG | GPU beschikbaar voor ML in dev VMs |
| **Kube VIP** | Virtual IP / load balancing | — |
| **Prometheus** | Monitoring + Grafana | Metrics van dev VMs |
| **System Upgrade Controller** | RKE2 upgrades | — |

### Zelf te installeren in cluster

| Component | Waarom |
|-----------|--------|
| **Harbor** | Container registry — Gitea registry staat niet aan, Harbor geeft scanning + signing + UI |
| **Kata Containers** | Runtime voor dev VMs en agent sandboxes |
| **Apache Guacamole** | Remote access gateway (RDP + SSH via 443) |

**Conclusie:** De hele infrastructuurlaag is geregeld. Gitea, Vault en FluxCD staan buiten het cluster (schone scheiding: state buiten, compute binnen). We installeren Harbor, Kata en Guacamole zelf.

---

## 2. Waarom Kata Containers (en niet Sysbox of gVisor)?

Druppie gebruikt nu `sysbox-runc` voor coding sandboxes op Docker. Op K8s met containerd (RKE2) is dit niet de beste keuze:

| | Kata Containers 3.x | Sysbox | gVisor |
|---|---|---|---|
| **containerd support** | ✅ Native RuntimeClass sinds 1.2 | ⚠️ Fix in sysbox-runc, "still evolving" | ✅ Native RuntimeClass |
| **Docker-in-Docker** | ✅ Volledige VM-kernel | ✅ User namespaces | ❌ Niet ondersteund |
| **systemd / SSH daemon** | ✅ Ja | ✅ Ja | ❌ Nee |
| **GPU (NVIDIA)** | ✅ PCI passthrough of vGPU | ✅ Via NVIDIA Container Toolkit | ⚠️ Beperkt |
| **Isolatie** | VM-level (dedicated kernel) | User namespace (shared kernel) | Syscall filter (user-space) |
| **Security** | Sterkste | Goed | Goed |
| **Cold start** | ~150-400ms (Firecracker) | ~1-2s | ~50-100ms |
| **Memory overhead** | ~60-120MB per pod | ~50MB | ~20-50MB |
| **Productie-bewezen** | ✅ Ant Group (1M+ containers/mnd) | ⚠️ Beperkt op K8s | ✅ Google GKE Sandbox |
| **CNCF status** | Sandbox (graduating) | Geen | Geen |

**Kata wint voor onze use case:**
- Docker-in-Docker is **essentieel** voor dev VMs (docker-compose up, docker build). gVisor valt af.
- Containerd support is **native** — geen hack zoals Sysbox. RKE2 gebruikt containerd.
- Sterkste isolatie — VM-level, elke pod heeft eigen kernel. Belangrijk voor untrusted agent code.
- 1 runtime voor alles: dev VMs én agent sandboxes. Minder maintenance.

**Nadeel:** ~100ms tragere cold start dan gVisor, ~70MB meer overhead dan Sysbox. Verwaarloosbaar op 1TB RAM.

### Installatie op RKE2

```bash
# 1. Installeer Kata operator
kubectl apply -f https://raw.githubusercontent.com/kata-containers/kata-containers/main/tools/packaging/kata-deploy/kata-rbac.yaml
kubectl apply -f https://raw.githubusercontent.com/kata-containers/kata-containers/main/tools/packaging/kata-deploy/kata-deploy.yaml

# 2. RuntimeClass
kubectl apply -f - <<EOF
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
EOF

# 3. Pod met Kata runtime
# spec:
#   runtimeClassName: kata
```

---

## 3. Dev VM — Model A gedetailleerd

### Concept: 1 pod = alles

```
┌──────────────────────────────────────────────────────────────────┐
│              Dev VM (Kata Container, eigen kernel, 8GB RAM)       │
│                                                                  │
│  ┌──────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ code-server  │  │ SSH (:22)   │  │ RDP (:3389)             │ │
│  │ :8080        │  │             │  │ xrdp + XFCE desktop     │ │
│  └──────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                  │
│  Secrets (via Vault → ESO → mounted env vars):                    │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ GITEA_TOKEN  → git clone/push naar Gitea                    ││
│  │ DOCKER_CONFIG → docker push naar Harbor Registry             ││
│  │ SSH_PRIVATE_KEY → git via SSH + custom SSH access            ││
│  │ ZAI_API_KEY → LLM calls voor agent testing                   ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Druppie stack (alles op localhost, hot reload):                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ backend          :8000  (uvicorn --reload --host 0.0.0.0)   ││
│  │ frontend         :5273  (npm run dev -- --host 0.0.0.0)    ││
│  │ module-coding    :9001  (python server.py)                  ││
│  │ module-docker    :9002                                      ││
│  │ module-registry  :9007                                      ││
│  │ module-archimate :9006                                      ││
│  │ module-data-access :9010                                    ││
│  │ module-filesearch :9004                                     ││
│  │ module-llm       :9008                                      ││
│  │ module-vision    :9011                                      ││
│  │ module-web       :9005                                      ││
│  │ layout-service   :8090                                      ││
│  │ PostgreSQL       :5432  (standalone container)               ││
│  │ Mock auth        (in-app, geen Keycloak nodig)               ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Persistent: /home/dev → 50Gi Longhorn PVC (code, venv, cache)   │
│  Docker: /var/lib/docker → docker-in-docker daemon                │
│  Git workspace: /home/dev/repo → git clone van geselecteerde branch│
└──────────────────────────────────────────────────────────────────┘
         │                          │
    Traefik Ingress             Interne routes
         │                          │
  https://dev-jan.druppie.local    localhost:* (binnen pod/RDP)
  https://dev-jan.druppie.local:3389 (RDP)
```

### Hoe hot reload werkt in deze pod

Alles draait op **hetzelfde filesystem** — géén PVC sync, géén pod restart, géén image rebuild:

| Developer wijzigt | Wat gebeurt er | Tijd |
|-------------------|---------------|------|
| `druppie/api/routes/chat.py` | `uvicorn --reload` detecteert | < 1s |
| `frontend/src/App.tsx` | Vite HMR (Hot Module Replacement) | < 100ms |
| `module-coding/server.py` | Dev herstart service handmatig of via watcher | < 2s |
| `.env` change | Herstart betreffende service | < 2s |
| `package.json` (nieuwe dep) | `npm install` in pod terminal | < 30s |
| `requirements.txt` | `pip install` in pod terminal | < 30s |

### Hoe developer de pod benadert — drie methoden

| Methode | Wat | URL / Command | Preview werkt? |
|---------|-----|--------------|---------------|
| **code-server** | VS Code in browser | `https://dev-jan.druppie.local` | ✅ code-server proxy: `localhost:5273` → `/proxy/5273` |
| **SSH + VS Code Remote** | Native VS Code, alles in pod | `ssh dev-jan.druppie.local` | ✅ SSH port forward: `-L 5273:localhost:5273` |
| **RDP** | Volledige desktop in browser/rdp client | `dev-jan.druppie.local:3389` | ✅ Browser in RDP opent `localhost:5273` |

Alle drie **dezelfde pod, dezelfde files, dezelfde draaiende services**. Developer wisselt flexibel.

### URL/Localhost probleem — opgelost

**Probleem:** Als frontend gebouwd is met vaste API URL → faalt in RDP (localhost) of externe browser.

**Oplossing:** Frontend draait **altijd in Vite dev mode**. Vite's dev server proxyt alle `/api` calls naar `localhost:8000`. Relatieve URLs, géén build-time `VITE_API_URL` nodig.

| Toegang | Browser URL | API calls | Werkt? |
|---------|------------|-----------|--------|
| RDP in pod | `localhost:5273` | → `localhost:8000` (Vite proxy) | ✅ Direct |
| code-server | `dev-jan.druppie.local` → Vite:5273 | → `localhost:8000` | ✅ Via Ingress |
| Externe browser | `dev-jan-app.druppie.local` → Vite:5273 | → `localhost:8000` | ✅ Via Ingress |

Mock auth: developer is al ingelogd op de pod — géén OIDC redirects.

---

## 4. Secrets — 3-laags model

Dev VMs hebben **drie soorten secrets** met verschillende herkomst, levensduur en doel. De kernreden: Druppie's init scripts maken repos/users aan in Gitea. Als elke dev VM de echte productie-Gitea gebruikt, vervuilt die met tientallen test-repo's. Daarom draait elke dev VM een **eigen lokale Gitea** (in Docker-in-Docker) met gegenereerde wachtwoorden.

### Twee Gitea's in één pod

```
Dev VM (Kata pod)
├── Docker-in-Docker
│   └── Lokale Gitea (localhost:3000)
│       ├── Druppie init scripts gebruiken deze
│       ├── Sample repos, OAuth apps komen hier
│       ├── Data op PVC of ephemeral
│       └── "Prullenbak" — mag vervuild raken, weg bij cleanup
│
└── Developer's terminal
    └── git remote → echte Gitea (gitea.druppie.rijnland.dev)
        ├── Developer cloned/pushed echte Druppie code hier
        ├── SSH key uit Vault
        └── Blijft schoon — geen test repos
```

### Laag 1: Bootstrap secrets (per-VM, gegenereerd, ephemeral)

Deze secrets configureert de **lokale** Druppie stack in de pod. Ze worden gegenereerd bij pod-creatie en zijn uniek per dev VM.

| Secret | Waarde | Doel |
|--------|--------|------|
| `LOCAL_GITEA_URL` | `http://localhost:3000` | Lokale Gitea, niet prod |
| `LOCAL_GITEA_ADMIN_PASSWORD` | Random per VM | Init script: realm, repos |
| `LOCAL_GITEA_TOKEN` | Random per VM | Druppie backend → lokale Gitea API |
| `LOCAL_PG_PASSWORD` | Random per VM | Lokale PostgreSQL |
| `INTERNAL_API_KEY` | Random per VM | Interne service auth |
| `MODULE_API_TOKEN` | Random per VM | MCP module auth |

**Hoe gegenereerd:** Druppie backend genereert deze bij "Deploy" klik via `secrets.token_urlsafe()`. Opgeslagen als K8s Secret met label `ephemeral: true`. Niet in Vault — dit zijn geen persistente credentials.

```python
# Druppie provisioning controller (pseudo-code)
import secrets

def create_dev_vm(branch: str, developer: str):
    # Genereer bootstrap secrets (random, per-VM)
    bootstrap = {
        "LOCAL_GITEA_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "LOCAL_GITEA_TOKEN": secrets.token_urlsafe(32),
        "LOCAL_PG_PASSWORD": secrets.token_urlsafe(24),
        "INTERNAL_API_KEY": secrets.token_urlsafe(32),
        "MODULE_API_TOKEN": secrets.token_urlsafe(32),
    }
    k8s.create_secret(
        name=f"dev-{branch}-bootstrap",
        data=bootstrap,
        labels={"type": "bootstrap", "ephemeral": "true"}
    )
```

### Laag 2: User secrets (Vault → ESO, per developer)

Deze secrets zijn de developer's **persoonlijke credentials** voor externe diensten. Ze staan in Vault en zijn persistent.

| Secret | Vault path | Doel |
|--------|-----------|------|
| `SSH_PRIVATE_KEY` | `secret/developers/{user}/ssh_private_key` | Git push/pull naar echte repo |
| `ZAI_API_KEY` | `secret/developers/{user}/zai_api_key` | LLM calls |
| `GIT_REMOTE_URL` | Static | `git@gitea.druppie.rijnland.dev:druppie/druppie-fork.git` |

**Flow:** Druppie backend maakt `ExternalSecret` CRD → ESO haalt uit Vault → K8s Secret → pod `envFrom`.

```
secret/developers/jan
  ├── ssh_private_key:  "-----BEGIN OPENSSH PRIVATE KEY-----..."
  ├── zai_api_key:      "sk-..."
  └── git_remote_url:   "git@gitea.druppie.rijnland.dev:druppie/..."
```

### Laag 3: Cluster secrets (static, infrastructuur)

Cluster-wide configuratie die voor alle dev VMs hetzelfde is.

| Secret | Waarde | Bron |
|--------|--------|------|
| `REGISTRY_URL` | `registry.druppie.rijnland.dev` | ConfigMap |
| `VAULT_ADDR` | `https://vault.druppie.rijnland.dev` | ConfigMap |

### Hoe het samenkomt in de pod

```bash
# .env in de dev VM (automatisch gegenereerd door startup script)

# === LAAG 1: Bootstrap (per-VM gegenereerd) ===
GITEA_URL=http://localhost:3000
GITEA_ADMIN_PASSWORD=${LOCAL_GITEA_ADMIN_PASSWORD}
GITEA_TOKEN=${LOCAL_GITEA_TOKEN}
DATABASE_URL=postgresql://druppie:${LOCAL_PG_PASSWORD}@localhost:5432/druppie
INTERNAL_API_KEY=${INTERNAL_API_KEY}
MODULE_API_TOKEN=${MODULE_API_TOKEN}

# === LAAG 2: User (uit Vault via ESO) ===
GIT_REMOTE_URL=${GIT_REMOTE_URL}
SSH_PRIVATE_KEY=${SSH_PRIVATE_KEY}
ZAI_API_KEY=${ZAI_API_KEY}

# === LAAG 3: Cluster (static) ===
REGISTRY_URL=registry.druppie.rijnland.dev
```

Druppie's init scripts gebruiken `GITEA_URL` → wijst naar `localhost:3000` (lokale Gitea). Sample repos komen daar aan. Prod Gitea blijft schoon.

---

## 5. Agents vs Dev VMs — zelfde runtime, aparte pods, via git

**Waarom aparte pods:** Dev VM bevat developer's persoonlijke secrets, code-in-progress, docker cache. Een agent (die untrusted AI-gegenereerde code draait) moet daar niet in kunnen.

**Hoe ze samenwerken — via git:**

```
┌──────────────────────────────────────────────────────────────────┐
│  Workflow: Developer vraagt agent om hulp                         │
│                                                                  │
│  ┌──────────────────────────┐        ┌─────────────────────────┐│
│  │  Dev VM (Kata pod)       │        │  Agent Sandbox (Kata)   ││
│  │                          │        │                         ││
│  │  Developer:              │        │  Druppie agent:         ││
│  │  "pas deze functie aan"  │───────→│  1. git clone repo      ││
│  │                          │        │  2. code schrijven      ││
│  │                          │        │  3. git commit + push   ││
│  │  git pull                │←───────│  4. pod cleanup         ││
│  │  review changes          │        │                         ││
│  │  accept / reject         │        │                         ││
│  └──────────────────────────┘        └─────────────────────────┘│
│                                                                  │
│  Zelfde image: druppie-dev-base                                  │
│  Zelfde resources: 8GB RAM, 4 vCPU                               │
│  Zelfde runtime: kata                                             │
│  Andere lifecycle: dev=persistent, agent=ephemeral               │
└──────────────────────────────────────────────────────────────────┘
```

**Versnelling — auto-sync:** Als je nog vlotter wilt, kan de dev VM een watcher hebben die auto-pullt op de branch die de agent gebruikt. Dan ziet de developer wijzigingen direct. Maar review blijft een expliciete stap — git history is de audit trail.

| | Dev VM | Agent Sandbox |
|---|---|---|
| **Wie maakt aan?** | Developer via Druppie UI | Druppie agent runtime (k8s_manager.py) |
| **Wie ruimt op?** | Developer via "Stop" knop | Auto-cleanup na task (TTL: 5 min idle) |
| **PVC / persistent?** | ✅ Longhorn PVC (50Gi) | ❌ Ephemeral (emptyDir) |
| **Interactief?** | ✅ code-server, SSH, RDP | ❌ Headless |
| **Netwerk** | Ingress + Gitea + Registry | Alleen backend API |
| **Security** | Vertrouwd (dev eigen code) | Untrusted (AI-generated) |

---

## 5b. Node Topology & GPU Strategie

### Fysieke cluster layout (na provisioning)

```
8 nodes, ~480GB worker RAM totaal:

  3× Master nodes   → Control plane + etcd. NoSchedule taint. Geen workloads.
                      16-32GB RAM elk.
  1× GPU node       → 2× RTX 6000 Pro (96GB VRAM totaal). 128GB+ RAM.
                      Exclusief voor prod LLM pod. Taint: gpu=true:NoSchedule.
  4× Worker nodes   → 96GB RAM elk = 384GB totaal. 16+ vCPU per node.
                      Alle Druppie workloads, dev VMs, agent sandboxes, CI/CD.
                      Label: node-type=worker.
                      Prod, colab-dev, dev VMs en agents delen dezelfde nodes.
                      Isolatie via PriorityClass (niet fysieke scheiding).
```

### Waarom 4 workers × 96GB?

Totaal benodigd:
- Prod Druppie (volledig): ~35GB
- Colab-dev Druppie (zelfde stack, minder replicas): ~30GB
- CI/CD runners: ~10GB
- Agent sandboxes (max 5 × 8GB): ~40GB
- Dev VMs (10 × 16GB): 160GB
- System/infra overhead: ~30GB
- Headroom (20%): ~61GB
- **Totaal: ~366GB → 384GB (4× 96GB)**

10 dev VMs × 16GB = 160GB (past op 2 nodes, 5 per node). Prod + colab-dev + agents + CI = ~115GB (1-2 nodes). 4e node = failure tolerance. Bij node failure: 3× 96GB = 288GB, genoeg voor alle workloads.

Bij groei naar 15+ developers: 5e worker toevoegen.

### Prod/dev op dezelfde nodes — PriorityClasses

Prod, colab-dev, dev VMs en agents draaien op **dezelfde worker nodes**. Geen aparte prod nodes (prod heeft maar ~35GB nodig — een hele 96GB node aan prod wijden verspilt 60GB).

Isolatie komt van **PriorityClasses**: bij node memory pressure evicteert K8s eerst agents (priority 500), dan dev VMs (1000), dan CI (3000) — prod (10000) en colab-dev (8000) blijven altijd draaien. Dev VM PVC blijft behouden bij evictie, developer kan herstarten via Druppie UI.

### Namespace isolatie vs fysieke isolatie

Namespaces zijn **logisch**, niet fysiek. Pods uit `druppie-prod` en `dev-vms` draaien op dezelfde worker node. Fysieke scheiding krijgt via:
- **nodeSelector** — pod mag alleen op nodes met bepaald label
- **Taints + Tolerations** — node weigert pods zonder expliciete toleration
- **Kata Containers** — elke pod krijgt eigen kernel (VM-level isolatie)

### GPU node: exclusief voor prod LLM

De GPU node (2× RTX 6000 Pro, 96GB VRAM totaal, 128GB+ systeem RAM) is exclusief voor de **prod LLM pod** (vLLM/Ollama). Dev VMs, colab-dev, en agent sandboxes gebruiken géén lokale GPU.

**Hoe dev/colab-dev toch LLM access hebben:** De prod LLM pod exposeert een OpenAI-compatible endpoint via K8s service DNS:

```
http://llm-prod.druppie-prod.svc.cluster.local:8000/v1
```

Dev VMs en colab-dev configureren hun LLM provider om deze URL te gebruiken. Geen GPU node nodig, maar toch dezelfde modellen als prod.

```bash
# .env in dev VM / colab-dev
LLM_PROVIDER=internal
LLM_BASE_URL=http://llm-prod.druppie-prod.svc.cluster.local:8000/v1
```

### Node labels en taints (door Druppie team te zetten)

```bash
# GPU node
kubectl label node <gpu-node> node-type=gpu gpu=true
kubectl taint node <gpu-node> gpu=true:NoSchedule

# Worker nodes
kubectl label node <worker-{1,2,3}> node-type=worker
```

### Helm chart aanpassingen

Alle prod/dev/agent deployments krijgen `nodeSelector: { node-type: worker }`. Alleen de LLM pod krijgt `nodeSelector: { gpu: true }` + toleration voor de GPU taint.

---

## 6. Prod en Colab-dev — auto-deploy via FluxCD (GitOps)

FluxCD is een CNCF Graduated GitOps tool die door infra-team **buiten het cluster** is gezet. FluxCD watcht de Gitea repo en synct wijzigingen automatisch naar het cluster.

### Externe services vs cluster

```
Buiten cluster (infra beheert):
  Gitea          → Git repos + Gitea Actions CI
  Hashicorp Vault → Secrets
  FluxCD         → GitOps → cluster sync

In cluster (Druppie beheert):
  Harbor         → Container registry (zelf geïnstalleerd)
  Traefik        → Ingress
  Longhorn       → Storage
  Prometheus     → Monitoring
  Alle workloads → prod, colab-dev, dev VMs, agents
```

### CI/CD flow

```
Developer push code → Gitea (extern)
  │
  ├── Gitea Actions (CI):
  │     1. docker build (13 images)
  │     2. docker push → Harbor (in cluster, via Traefik 443)
  │     3. Update Helm values met nieuwe image tag
  │     4. git commit + push (Helm values wijziging)
  │
  └── FluxCD (CD, extern):
        5. Ziet Helm values wijziging in Gitea
        6. helm upgrade op cluster (via kubeconfig)
        7. Cluster pullt image van Harbor (intern, snel)
```

```
FluxCD (GitOps, extern)
  │
  ├── GitRepo: druppie-fork (branch: main → druppie-prod)
  │     │
  │     ├── helm/druppie/values-prod.yaml
  │     └── Auto-deploy: PR merge → main → FluxCD sync
  │
  └── GitRepo: druppie-fork (branch: colab-dev → druppie-colab-dev)
        │
        ├── helm/druppie/values-dev.yaml
        └── Auto-deploy: PR merge → colab-dev → FluxCD sync
```

| | druppie-prod | druppie-colab-dev |
|---|---|---|
| **Type** | Namespace | Namespace |
| **Deploy trigger** | PR merge → main | PR merge → colab-dev |
| **Deploy tool** | FluxCD (GitOps, extern) | FluxCD (GitOps, extern) |
| **Stack** | Volledig | **Volledig (identiek aan prod)** |
| **Auth** | Keycloak | Keycloak |
| **Database** | CNPG (3 instances, HA) | CNPG (1 instance, geen HA) |
| **MCP modules** | Alle 9 | Alle 9 |
| **Backend replicas** | 3-8 (KEDA autoscaling) | 2 (statisch) |
| **PriorityClass** | 10000 | 8000 |
| **Toegang** | `druppie.rijnland.dev` | `dev.druppie.rijnland.dev` |
| **RAM** | ~35GB | ~30GB |

---

## 7. Dev VMs — lifecycle management via Druppie UI

**Flow:**

```
Druppie UI
  │
  ├── Tab: "Dev Environments"
  │     │
  │     ├── Lijst: actieve branches + status
  │     ├── Button: "Deploy" (selecteer branch uit dropdown)
  │     │     │
  │     │     ├── Druppie backend:
  │     │     │   1. Maak ExternalSecret CRD (Vault → K8s secret)
  │     │     │   2. Maak Longhorn PVC (als die nog niet bestaat)
  │     │     │   3. Maak Kata pod met juiste env + volumes
  │     │     │   4. Maak Traefik IngressRoute (wildcard subdomein)
  │     │     │   5. Return: https://dev-{branch}.druppie.rijnland.dev
  │     │     │
  │     │     └── Status: "Deploying..." → "✅ Ready (2m 34s)"
  │     │
  │     ├── Button: "Connect" → opent URL in browser / RDP client
  │     ├── Button: "Stop" → delete pod (PVC blijft voor herstart)
  │     └── Button: "Delete" → delete pod + PVC + ingress
  │
  └── Tab: "Git Sync"
        │
        ├── Status: branch, last commit, dirty files
        ├── Button: "Git Pull" → git pull in pod
        └── Button: "Git Push" → git push in pod
```

**PVC management:**
- Eerste deploy: maak PVC, seed van base image, git checkout branch (< 30s)
- Volgende deploy (zelfde branch): PVC bestaat al, alleen git pull (< 10s)
- Developer kan "Reset" kiezen: delete PVC + recreate = schone start (< 30s)

### Dev VM base image — shared across all branches

De dev VM base image wordt **één keer** gebouwd (vanuit colab-dev branch) en gedeeld door alle feature branches. Dit maakt startup snel omdat containerd de layers op de node cached.

**Wat er in de base image zit:**
```
dev-vm-base:latest (in Harbor)
  ├── Layer 1: Ubuntu 22.04 + Python 3.12 + Node 20 + Git + Docker
  ├── Layer 2: code-server + SSH + xrdp
  ├── Layer 3: Druppie repo cloned at colab-dev HEAD
  ├── Layer 4: node_modules (frontend, van package.json)
  └── Layer 5: venv (backend, van requirements.txt)
```

**Startup flow (per feature branch):**
```bash
# 1. Pod start met dev-vm-base image (containerd cached op node na eerste pull)

# 2. Seed PVC van image (alleen eerste keer — PVC leeg)
cp -r /app/repo /home/dev/repo

# 3. Checkout de feature branch (git diff — snel)
cd /home/dev/repo
git fetch origin
git checkout feature-xyz

# 4. Reinstalleer deps alleen als ze veranderd zijn
diff <(checksum package.json) <(cached checksum) || npm install
diff <(checksum requirements.txt) <(cached checksum) || pip install

# 5. Start services
docker-compose up
```

**Waarom dit snel is:**
- Alle branches delen dezelfde base image → containerd downloadt 1x per node
- `git checkout feature-xyz` is snel (alleen file diffs, geen full clone)
- Meeste feature branches veranderen `package.json` / `requirements.txt` niet → deps overgeslagen
- Alleen de eerste dev VM op een node downloadt de volledige image (~2-3 min)
- Dev VMs 2-10 op dezelfde node: image al gecached → <30s startup

**Speed per scenario:**

| Scenario | Zonder base image (install at startup) | Met shared base image |
|----------|---------------------------------------|----------------------|
| Eerste dev VM op node | 2-5 min (clone + install) | 2-3 min (image pull) |
| 2e-10e dev VM op node | 2-5 min (opnieuw install) | **<30s** (image cached) |
| Restart (PVC exists) | <30s | <30s |
| Reset (PVC weg) | 2-5 min | **<30s** (image cached) |
| Nieuwe branch, zelfde node | 2-5 min | **<30s** (image cached, git checkout) |

**CI pipeline voor base image:**
```
Gitea Actions, op push naar colab-dev:
  ├── 13 prod images → Harbor
  └── 1 dev-vm-base image → Harbor
      (rebuild als package.json of requirements.txt verandert op colab-dev)
```

---

## 8. Faseringsplan

### Fase 1 (Week 1-2): Fundering
- [x] Infrastructuur is al klaar (Traefik, cert-manager, Longhorn, Vault+ESO, FluxCD, Prometheus, GPU operator — Gitea/Vault/FluxCD extern)
- [ ] Kata Containers operator installeren + RuntimeClass aanmaken
- [ ] Harbor installeren in cluster (container registry met scanning + signing)
- [ ] Namespace structuur: `druppie-prod`, `druppie-colab-dev`
- [ ] FluxCD GitRepository configuratie voor prod + dev auto-deploy
- [ ] ResourceQuota + PriorityClass + NetworkPolicy

### Fase 2 (Week 3-4): Dev VMs + Remote Access
- [ ] Dev base image bouwen: Ubuntu + Python 3.12 + Node 20 + Git + Docker + code-server + SSH + xrdp + lokale Gitea
- [ ] 3-laag secrets provisioning: bootstrap (per-VM gegenereerd) + Vault/ESO (per-user) + cluster (static)
- [ ] Lokale Gitea in Docker-in-Docker (voorkomt prod vervuiling door init scripts)
- [ ] Druppie backend: Kata pod provisioning (create/stop/delete)
- [ ] Druppie UI: Dev Environments tab met branch selector, deploy button, status
- [ ] Traefik IngressRoute template per dev VM
- [ ] Mock auth middleware voor dev modus
- [ ] **Apache Guacamole installeren** (namespace: remote-access) — RDP + SSH via 443 HTTPS
- [ ] Testen: code-server, Guacamole RDP, Guacamole SSH

### Fase 3 (Week 5-6): Agent Sandboxes op K8s
- [ ] `k8s_manager.py` vervangt `docker_manager.py` — Kata pods i.p.v. Docker containers
- [ ] Agent sandbox: zelfde image als dev VM, maar ephemeral, headless
- [ ] NetworkPolicy: agent pods alleen backend API
- [ ] Auto-cleanup: TTL of pool manager

### Fase 4 (Week 7-8): CI/CD + Polish
- [ ] Full pipeline: Gitea Actions → build → push Harbor → FluxCD sync (prod + dev)
- [ ] Druppie agent voor dev VM management (monitoring, auto-repair)
- [ ] Developer onboarding: 1 commando om Vault secrets aan te maken
- [ ] GPU sharing voor dev VMs: NVIDIA MIG/time-slicing via GPU Operator
- [ ] Monitoring + docs

---

## 9. Openstaande vragen (voor later)

| Vraag | Status |
|-------|--------|
| Auto-detectie gewijzigde modules per PR (deploy only changed) | Later — eerst alles lokaal |
| Shared pool voor MCP modules (dev VMs delen modules die niet gewijzigd zijn) | Later — resource optimalisatie |
| Druppie agent die direct in dev VM werkt (niet via git) | Nee — security risico, git is interface |

---

## 10. Bronnen en referenties

- [**Aanbevolen Architectuur**](./dev-environment-architecture.md) — Definitieve architectuur met Mermaid diagrammen
- [Kata Containers](https://katacontainers.io/) — CNCF Sandbox, native containerd RuntimeClass
- [K3s + Sysbox blog](https://docs.k3s.io/blog/2025/09/27/k3s-sysbox) — Sysbox containerd fix status (sept 2025)
- [FluxCD](https://fluxcd.io/) — CNCF Graduated GitOps
- [Harbor](https://goharbor.io/) — CNCF Graduated container registry
- [External Secrets Operator](https://external-secrets.io/) — Vault → K8s sync
- [Druppie ADR-KUBERNETES.md](./ADR-KUBERNETES.md) — Bestaande K8s architectuur
- [Druppie AS-BUILT-ARCHITECTURE.md](./AS-BUILT-ARCHITECTURE.md) — Huidige Hetzner deployment
