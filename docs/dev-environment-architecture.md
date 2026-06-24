# Aanbevolen Architectuur: Dev, Preview & Prod op Local Rancher RKE2

> **Status:** Definitief architectuurvoorstel  
> **Datum:** 2026-06-23  
> **Gebaseerd op:** [research-dev-environments.md](./research-dev-environments.md)  

---

## Current Implementation Status (k3s dev)

This table shows how the current k3s development cluster compares to the target RKE2
architecture described in the rest of this document.

| Component | Target (RKE2) | Current (k3s dev) | Status |
|-----------|--------------|-------------------|--------|
| Cluster | RKE2 8 nodes | k3s single node | ✅ Working |
| Container runtime | Kata Containers | Docker (sysbox optional) | ⚠️ No Kata |
| Harbor | In cluster | In cluster (k3s) | ✅ |
| Keycloak | In namespace | In namespace | ✅ |
| Frontend | Helm deployed | Helm deployed, image from Harbor | ✅ |
| Backend | Helm deployed | Helm deployed, Docker socket mounted | ✅ |
| Guacamole | In cluster | In cluster (standalone manifest) | ✅ |
| Dev VM creation | Kata pods | Docker containers (sysbox) | ✅ Working |
| PriorityClasses | 5 classes | 5 classes applied | ✅ |
| Secrets (3-layer) | Vault + ESO | Static (Layer 1 only) | ❌ Not implemented |
| FluxCD | GitOps auto-deploy | Not installed | ❌ |
| Vault | External | Not installed | ❌ |
| Traefik Ingress | Per-dev-VM routing | Not configured | ❌ |
| CI/CD | Gitea Actions | Workflow + act-runner (manual test passed) | ⚠️ Partial |
| Blue-green deploy | Zero-downtime | Default RollingUpdate (1 replica) | ❌ No zero-downtime |
| Monitoring | Prometheus + Grafana | Running | ✅ |

For the step-by-step setup of the current k3s dev cluster, see
[K3S-DEV-SETUP.md](./K3S-DEV-SETUP.md).

---

## Top-Level Architectuur

```mermaid
flowchart TB
    subgraph Internet["Internet / DNS"]
        USER["Gebruiker · druppie.rijnland.dev"]
        DEV_USER["Developer · dev-branch.druppie.rijnland.dev"]
        REVIEWER["Reviewer · PR preview URL"]
    end

    subgraph Rancher["Rancher RKE2 Cluster (1TB RAM, Xeon, 4× RTX 6000 Pro)"]
        direction TB

    %% ── Infrastructure Layer ──
    subgraph Infra["Infrastructure"]
            direction LR
            TRAEFIK["Traefik Ingress + TLS"]
            CM["cert-manager · Let's Encrypt"]
            LONGHORN["Longhorn Storage"]
            VAULT["Vault (extern) + ESO (in cluster)"]
            GITEA["Gitea (extern) + Actions CI"]
            FLUXCD["FluxCD (extern)"]
            HARBOR["Harbor Registry (in cluster)"]
            PROM["Prometheus + Grafana"]
            GPU_OP["NVIDIA GPU Operator"]
        end

        %% ── Prod + Dev Namespaces (FluxCD auto-deploy) ──
        subgraph ProdNS["Namespace: druppie-prod"]
            PROD_KC["Keycloak"]
            PROD_BE["Backend 3-8× (KEDA)"]
            PROD_FE["Frontend 1-8× (HPA)"]
            PROD_MCP["9× MCP Modules"]
            PROD_CNPG["CNPG PostgreSQL (HA, 3 instances)"]
            PROD_GITEA["Gitea"]
            PROD_NFS["NFS RWX Workspace"]
        end

        subgraph DevNS["Namespace: druppie-colab-dev"]
            DEV_KC["Keycloak"]
            DEV_BE["Backend 2×"]
            DEV_FE["Frontend 2×"]
            DEV_MCP["9× MCP Modules"]
            DEV_CNPG["CNPG PostgreSQL"]
            DEV_GITEA["Gitea"]
        end

        %% ── Kata Pods (managed by Druppie, not FluxCD) ──
        subgraph KataPods["Kata Container Pods"]
            direction TB

            subgraph DevVM1["Dev VM: dev-feature-xyz"]
                D1_CODE["code-server :8080"]
                D1_SSH["SSH :22"]
                D1_RDP["RDP :3389"]
                D1_STACK["Druppie Stack · Hot Reload<br/>backend :8000 · frontend :5273<br/>9× modules · PG :5432<br/>Lokale Gitea :3000 (DinD)<br/>Mock Auth · Docker-in-Docker"]
                D1_HOME["50Gi Longhorn PVC"]
            end

            subgraph DevVM2["Dev VM: dev-feature-abc"]
                D2_IDE["code-server · SSH · RDP"]
                D2_STACK["Druppie Stack · Hot Reload"]
                D2_HOME["50Gi Longhorn PVC"]
            end

            subgraph AgentVM1["Agent Sandbox"]
                A1_STACK["Druppie Stack · Headless<br/>git clone · agent code run"]
                A1_EPHEMERAL["Ephemeral · TTL: 5 min"]
            end

            subgraph AgentVM2["Agent Sandbox"]
                A2_STACK["Druppie Stack · Headless"]
                A2_EPHEMERAL["Ephemeral"]
            end
        end

        %% ── FluxCD GitOps ──
        subgraph FluxLayer["FluxCD (GitOps, extern)"]
            FL_MAIN["main → druppie-prod<br/>Auto-deploy"]
            FL_COLAB["colab-dev → druppie-colab-dev<br/>Auto-deploy"]
        end

        %% ── Druppie Backend (Provisioning Controller) ──
        subgraph DruppieController["Druppie Backend (Provisioning)"]
            DC_API["Dev VM API<br/>create / stop / delete / status"]
            DC_AGENT["k8s_manager.py<br/>Agent sandbox provisioning"]
        end
    end

    %% ── Connections ──
    USER -->|"druppie.rijnland.dev"| TRAEFIK
    DEV_USER -->|"dev-*.druppie.rijnland.dev"| TRAEFIK
    REVIEWER -->|"PR preview URL"| TRAEFIK

    TRAEFIK -->|"/api /"| ProdNS
    TRAEFIK -->|"dev.colab.*"| DevNS
    TRAEFIK -->|"dev-feature-*"| DevVM1
    TRAEFIK -->|"dev-feature-*"| DevVM2

    DC_API -->|"create/stop pod"| KataPods
    DC_AGENT -->|"spawn agent sandbox"| AgentVM1

    VAULT -->|"Laag 2: ESO sync<br/>user creds (SSH, LLM)"| DevVM1
    VAULT -->|"Laag 2: ESO sync"| DevVM2

    GITEA -->|"git clone/push<br/>(developer's persoonlijke repo)"| KataPods
    GITEA -->|"Gitea Actions: build images"| HARBOR
    HARBOR -->|"13 Druppie images"| ProdNS
    HARBOR -->|"13 Druppie images"| DevNS
    HARBOR -->|"Kata base image<br/>(dev VM + agent sandbox)"| KataPods

    FL_MAIN -->|"Helm deploy"| ProdNS
    FL_COLAB -->|"Helm deploy"| DevNS

    %% ── Styling ──
    style Rancher fill:#1a1a2e,color:#e0e0e0,stroke:#0f3460,stroke-width:3px
    style Infra fill:#2d3436,color:#e0e0e0,stroke:#636e72
    style ProdNS fill:#0984e3,color:#ffffff,stroke:#74b9ff
    style DevNS fill:#00b894,color:#1a1a2e,stroke:#55efc4
    style KataPods fill:#e17055,color:#ffffff,stroke:#fab1a0
    style FluxLayer fill:#6c5ce7,color:#ffffff,stroke:#a29bfe
    style Infra fill:#2d3436,color:#e0e0e0,stroke:#636e72
    style HARBOR fill:#d63031,color:#ffffff
    style DruppieController fill:#fdcb6e,color:#1a1a2e,stroke:#ffeaa7
```

---

## Node Topology & Workload Placement

Het cluster heeft **8 fysieke nodes** (na provisioning). Namespaces zijn logische isolatie — pods uit verschillende namespaces draaien op dezelfde node. Fysieke scheiding tussen prod en dev is **niet nodig** — we gebruiken PriorityClasses (prod wordt bij pressure beschermd, dev VMs geëvinceerd).

```mermaid
flowchart TB
    subgraph Cluster["RKE2 Cluster — 8 nodes, ~480GB worker RAM"]
        direction TB

        subgraph Masters["3× Master Nodes (control plane + etcd)"]
            M1["master1<br/>16-32GB RAM<br/>NoSchedule taint"]
            M2["master2<br/>16-32GB RAM"]
            M3["master3<br/>16-32GB RAM"]
            M_NOTE["Geen workloads<br/>Alleen control plane"]
        end

        subgraph GPUNode["1× GPU Node (128GB+ RAM)"]
            GPU1["RTX 6000 Pro #1 (~48GB VRAM)"]
            GPU2["RTX 6000 Pro #2 (~48GB VRAM)"]
            GPU_TAINT["Taint: gpu=true:NoSchedule"]
            LLM_POD["Prod LLM Pod (vLLM)<br/>2× nvidia.com/gpu (exclusive)<br/>96GB VRAM totaal<br/>OpenAI-compatible API op :8000"]
        end

        subgraph Workers["4× Worker Nodes (96GB RAM elk = 384GB totaal)"]
            direction LR
            W1["worker1<br/>96GB RAM · 16+ vCPU<br/>label: node-type=worker"]
            W2["worker2<br/>96GB RAM · 16+ vCPU"]
            W3["worker3<br/>96GB RAM · 16+ vCPU"]
            W4["worker4<br/>96GB RAM · 16+ vCPU"]
        end
    end

    subgraph Workloads["Workload Placement (gemengd op worker nodes)"]
        direction TB

        subgraph OnWorkers["Op worker nodes (PriorityClass bepaalt prioriteit)"]
            WS_PROD["druppie-prod<br/>~35GB RAM · priority 10000"]
            WS_DEVNS["druppie-colab-dev<br/>~30GB RAM · priority 8000<br/>(zelfde stack als prod)"]
            WS_DEVVM["10× Dev VMs (Kata pods)<br/>16GB per VM = 160GB · priority 1000"]
            WS_AGENT["Agent Sandboxes (max 5)<br/>~40GB · priority 500"]
            WS_CI["CI/CD runners<br/>~10GB · priority 3000"]
        end

        subgraph OnGPU["Op GPU node (toleration: gpu=true)"]
            WS_LLM["Prod LLM Pod<br/>64GB RAM, 96GB VRAM"]
        end
    end

    LLM_POD -->|"llm-prod.druppie-prod.svc.cluster.local:8000/v1<br/>(OpenAI-compatible)"| OnWorkers

    WS_DEVNS -.->|"LLM calls via prod URL"| LLM_POD
    WS_DEVVM -.->|"LLM calls via prod URL"| LLM_POD
    WS_AGENT -.->|"LLM calls via prod URL"| LLM_POD

    style Cluster fill:#1a1a2e,color:#e0e0e0,stroke:#0f3460,stroke-width:3px
    style Masters fill:#2d3436,color:#e0e0e0
    style GPUNode fill:#d63031,color:#ffffff
    style Workers fill:#0984e3,color:#ffffff
    style Workloads fill:#2d3436,color:#e0e0e0
    style OnWorkers fill:#00b894,color:#1a1a2e
    style OnGPU fill:#e17055,color:#ffffff
```

### GPU Strategie — prod only, gedeeld via URL

De GPU node (2× RTX 6000 Pro, 96GB VRAM totaal) is **exclusief voor de prod LLM pod**. Dev VMs, colab-dev, en agent sandboxes gebruiken géén lokale GPU — zij benaderen de prod LLM via een interne service URL.

```
GPU Node (128GB+ RAM, exclusief)
└── Prod LLM Pod (vLLM of Ollama)
    ├── 2× nvidia.com/gpu (exclusive limit, 96GB VRAM)
    ├── Taint toleration: gpu=true:NoSchedule
    └── Exposeert OpenAI-compatible endpoint:
        http://llm-prod.druppie-prod.svc.cluster.local:8000/v1

Dev VMs + Colab-dev + Agent Sandboxes
└── LLM_PROVIDER=internal
    LLM_BASE_URL=http://llm-prod.druppie-prod.svc.cluster.local:8000/v1
    → Alle LLM calls gaan naar prod LLM pod
    → Geen GPU node nodig in dev/colab-dev
```

**Waarom niet MIG of time-slicing:** Met 1 GPU node geeft partitionering prod inferentie minder VRAM. Exclusief voor prod is simpeler en geeft beste prod performance. Devs testen tegen dezelfde modellen via de URL.

### Node labels en taints (door Druppie team te zetten)

```bash
# GPU node — exclusief voor LLM workload
kubectl label node <gpu-node> node-type=gpu gpu=true
kubectl taint node <gpu-node> gpu=true:NoSchedule

# Worker nodes — alle andere workloads
kubectl label node <worker-1> node-type=worker
kubectl label node <worker-2> node-type=worker
kubectl label node <worker-3> node-type=worker
# (Master nodes hebben al NoSchedule taint van RKE2)
```

### Namespace isolatie — wat het wél en niet doet

| Wat namespaces isoleren | Wat ze NIET isoleren |
|------------------------|---------------------|
| ✅ ResourceQuota (RAM/CPU per namespace) | ❌ Fysieke node (pods delen nodes) |
| ✅ NetworkPolicy (netwerkverkeer blokkeren) | ❌ Kernel (vandaar Kata voor dev VMs) |
| ✅ RBAC (wie mag wat) | ❌ CPU/RAM (tenzij nodeSelector) |
| ✅ DNS (prod services niet zomaar bereikbaar) | |

### Prod/dev isolatie — PriorityClasses (géén aparte nodes)

Prod, colab-dev, dev VMs en agents draaien op **dezelfde worker nodes**. Geen verspilling van nodes aan dedicated prod. Isolatie komt van PriorityClasses: bij node pressure evicteert K8s eerst dev VMs, dan agents — prod blijft altijd draaien.

```yaml
# PriorityClasses
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: druppie-prod }
value: 10000          # Altijd gescheduled, nooit geëvinceerd
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: druppie-colab-dev }
value: 8000           # Hoog, maar onder prod
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: druppie-ci }
value: 3000           # CI runners
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: druppie-dev-vm }
value: 1000           # Lage prioriteit — geëvinceerd bij pressure
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: druppie-agent }
value: 500            # Laagste — agents zijn ephemeral
```

**Gedrag bij node memory pressure:**

```
Node krijgt memory pressure (bijv. dev VM draait zware build)
  │
  └→ K8s kubelet: "Ik moet pods evicten"
       │
       └→ Eviction order (laagste priority eerst):
            agent sandbox (500)     → EVICTED ✗
            dev VM (1000)           → EVICTED ✗ (PVC blijft, dev kan herstarten)
            CI runner (3000)        → EVICTED ✗
            colab-dev (8000)        → STAYS ✓
            prod (10000)            → STAYS ✓
```

Prod overleeft altijd. Dev VMs worden geëvinceerd — PVC blijft behouden, developer klikt "Restart" in Druppie UI.

---

## Dev VM — Close-up

```mermaid
flowchart TB
    subgraph DevVM["Dev VM: dev-feature-xyz (Kata Container)"]
        direction TB

        subgraph Access["Toegang (alles via 443 HTTPS)"]
            CS["code-server :8080<br/>VS Code in browser<br/>» dev-feature-xyz.druppie.rijnland.dev"]
            GUAC["Guacamole (extern, via 443)<br/>RDP + SSH in browser<br/>» remote.druppie.rijnland.dev → pod:3389/22"]
            RDPGW_OPT["~~RDPGW~~ (later, fase 2)<br/>Native RDP via mstsc<br/>Alleen als team er om vraagt"]
        end

        subgraph Secrets["Secrets — 3 lagen"]
            SEC_BOOT["Laag 1: Bootstrap (per-VM gegenereerd)<br/>LOCAL_GITEA_TOKEN · LOCAL_PG_PASSWORD<br/>INTERNAL_API_KEY · MODULE_API_TOKEN<br/>→ Lokale Druppie stack config"]
            SEC_USER["Laag 2: User (Vault → ESO)<br/>SSH_PRIVATE_KEY · ZAI_API_KEY<br/>GIT_REMOTE_URL<br/>→ Developer's persoonlijke credentials"]
            SEC_CLUST["Laag 3: Cluster (static)<br/>REGISTRY_URL · VAULT_ADDR<br/>LLM_BASE_URL → prod LLM pod<br/>→ Infrastructuur config"]
        end

        subgraph Stack["Druppie Stack (hot reload, localhost)"]
            BE["Backend :8000<br/>uvicorn --reload"]
            FE["Frontend :5273<br/>npm run dev (Vite HMR)"]
            MODULES["9× MCP Modules :9001-9011"]
            LAYOUT["Layout Service :8090"]
            PG["PostgreSQL :5432<br/>standalone container"]
            LOCAL_GITEA["Lokale Gitea :3000<br/>in Docker-in-Docker<br/>Init scripts gebruiken deze<br/>(niet prod Gitea)"]
            AUTH["Mock Auth<br/>geen Keycloak"]
            DIND["Docker Daemon<br/>docker-compose up · docker build"]
        end

        subgraph Persistence["Storage"]
            HOME["/home/dev<br/>50Gi Longhorn PVC<br/>git repo · venv · node_modules"]
            CACHE["/var/lib/docker<br/>Docker image cache<br/>+ lokale Gitea data"]
        end
    end

    HARBOR_EXT["Harbor (in cluster)<br/>→ levert Kata base image<br/>→ dev VMs bouwen Druppie lokaal"]

    HARBOR_EXT -.->|"base image pull"| DevVM

    SEC_BOOT --> Stack
    SEC_USER --> SSH
    SEC_CLUST --> Stack

    BE --> FE
    BE --> MODULES
    BE --> PG
    BE --> LOCAL_GITEA
    FE --> AUTH
    DIND --> Stack

    HOME --> BE
    HOME --> FE
    HOME --> MODULES

    style DevVM fill:#e17055,color:#ffffff,stroke:#fab1a0,stroke-width:2px
    style Access fill:#2d3436,color:#e0e0e0
    style Secrets fill:#6c5ce7,color:#ffffff
    style Stack fill:#1a1a2e,color:#e0e0e0
    style Persistence fill:#00b894,color:#1a1a2e
```

---

## Dev VM Base Image — shared across all branches

Alle dev VMs (en agent sandboxes) gebruiken **één shared base image** in Harbor, gebouwd vanuit de `colab-dev` branch. Dit maakt startup snel: containerd cached de image layers op de node, dus alleen de eerste dev VM per node is traag.

### Image layers

```
dev-vm-base:latest (in Harbor, ~4-5GB)
  ├── Layer 1: Ubuntu 22.04 + Python 3.12 + Node 20 + Git + Docker
  ├── Layer 2: code-server + SSH + xrdp + lokale Gitea
  ├── Layer 3: Druppie repo cloned at colab-dev HEAD
  ├── Layer 4: node_modules (frontend)
  └── Layer 5: venv (backend)
```

Gebouwd door Gitea Actions CI op push naar `colab-dev` (samen met de 13 prod images).

### Startup flow (per feature branch)

```mermaid
flowchart TB
    START["Dev VM pod start<br/>(runtimeClassName: kata)"] --> PULL{"Base image<br/>op node?"}
    PULL -->|"Nee (eerste op node)"| DOWNLOAD["docker pull dev-vm-base<br/>~2-3 min"]
    PULL -->|"Ja (cached)"| CACHED["Layer cache hit<br/><10s"]
    DOWNLOAD --> SEED
    CACHED --> SEED

    SEED["Seed PVC van image<br/>(alleen als PVC leeg — eerste keer)"] --> CHECKOUT

    CHECKOUT["git fetch + checkout feature-xyz<br/>Alleen file diffs — snel"] --> DEPS

    DEPS{"package.json of<br/>requirements.txt<br/>veranderd?"}
    DEPS -->|"Nee (meestal)"| SKIP["Skip install<br/>Deps al in image"]
    DEPS -->|"Ja"| INSTALL["npm install / pip install<br/>Alleen diff (snel)"]
    SKIP --> STARTUP
    INSTALL --> STARTUP

    STARTUP["docker-compose up<br/>code-server + SSH + RDP starten"] --> READY["✅ Ready"]

    style START fill:#fdcb6e,color:#1a1a2e
    style PULL fill:#0984e3,color:#ffffff
    style DOWNLOAD fill:#d63031,color:#ffffff
    style CACHED fill:#00b894,color:#1a1a2e
    style SEED fill:#6c5ce7,color:#ffffff
    style CHECKOUT fill:#6c5ce7,color:#ffffff
    style DEPS fill:#fdcb6e,color:#1a1a2e
    style SKIP fill:#00b894,color:#1a1a2e
    style READY fill:#00b894,color:#1a1a2e
```

### Waarom dit snel is

| Scenario | Zonder base image | Met shared base image |
|----------|------------------|----------------------|
| Eerste dev VM op node | 2-5 min (clone + install) | 2-3 min (image pull) |
| 2e-10e dev VM op node | 2-5 min (opnieuw install) | **<30s** (image cached) |
| Restart (PVC exists) | <30s | <30s |
| Reset (PVC weg) | 2-5 min | **<30s** (image cached) |
| Nieuwe branch, zelfde node | 2-5 min | **<30s** (image cached, alleen git checkout) |

De key insight: feature branches veranderen zelden `package.json` of `requirements.txt`. Dus `git checkout feature-xyz` (alleen code diffs) + skip dep install = bijna instant.

---

## Remote Access Gateway (Guacamole + optioneel RDPGW)

Extern is alleen poort 443 (HTTPS) beschikbaar op `*.rijnland.dev`. RDP (3389) en SSH (22) zijn niet rechtstreeks bereikbaar. Oplossing: een remote access gateway die deze protocollen tunnelt over HTTPS.

### Apache Guacamole — primair

Guacamole is een clientless remote desktop gateway. RDP, SSH en VNC sessies lopen in de browser, allemaal over poort 443. Geen client installatie nodig.

```mermaid
flowchart LR
    DEV["Developer browser"] -->|"https://remote.druppie.rijnland.dev:443"| TRAEFIK["Traefik Ingress"]
    TRAEFIK --> GUAC_WEB["Guacamole Web App<br/>Auth + Web UI"]
    GUAC_WEB --> GUACD["guacd daemon<br/>RDP/SSH/VNC client"]
    GUACD -->|"RDP :3389 (intern)"| DEVVM1["dev-jan pod"]
    GUACD -->|"SSH :22 (intern)"| DEVVM2["dev-jan pod"]
    GUACD -->|"VNC :5900 (intern)"| DEVVM3["dev-maria pod"]

    style DEV fill:#fdcb6e,color:#1a1a2e
    style TRAEFIK fill:#533483,color:#ffffff
    style GUAC_WEB fill:#0984e3,color:#ffffff
    style GUACD fill:#6c5ce7,color:#ffffff
    style DEVVM1 fill:#e17055,color:#ffffff
    style DEVVM2 fill:#e17055,color:#ffffff
    style DEVVM3 fill:#e17055,color:#ffffff
```

**Wat Guacamole biedt:**
- RDP desktop in browser (XFCE desktop van dev VM)
- SSH terminal in browser (voor quick commands)
- VNC in browser (alternatief voor RDP)
- File transfer (via RDP drive mapping)
- Clipboard sharing (copy/paste tussen browser en remote)
- Audio forwarding
- Eigen user database of Keycloak OIDC integratie

**Deploy in cluster:**
```yaml
# Namespace: remote-access
# Helm chart: apache-guacamole (beschikbaar via community charts)
#
# Componenten:
#   - guacamole-web    (Web UI + auth, ~512MB)
#   - guacd            (daemon, RDP/SSH/VNC client, ~256MB)
#   - postgresql       (session storage, ~256MB)
#
# Ingress: remote.druppie.rijnland.dev → guacamole-web:8080
# Totaal: ~1GB RAM
```

### Hoe Guacamole werkt

Guacamole is géén per-host proxy. Er is **één deployment achter één URL** (`remote.druppie.rijnland.dev`). Een developer authenticeert één keer en ziet een lijst met verbindingen waarvoor hij geautoriseerd is. Dit lost het "lijstje met machines en wachtwoorden bijhouden"-probleem op dat Guacamole oorspronkelijk voor ontworpen is.

**Drie componenten:**

| Component | Rol |
|-----------|-----|
| **Web applicatie** (Java server + JavaScript client in de browser) | Authenticatie afhandelen, verbindingsdefinities opslaan, de HTML5 client UI serveren. Implementeert zelf géén remote-desktop protocol. |
| **guacd** | Native C proxy daemon. Ontvangt het Guacamole protocol van de web app, laadt een protocol plugin (`libguac-client-rdp`, `-vnc` of `-ssh`) en maakt de daadwerkelijke verbinding met de remote VM. Luistert standaard op TCP 4822. |
| **libguac** | Gedeelde C library waarop guacd en de protocol plugins leunen. |

**Verbindingsmodel.** Elke dev VM (`dev-jan-vm`, enz.) wordt geregistreerd als één *connection* in Guacamole's database: een benoemde configuratie met protocol, hostname, poort, credentials en weergaveparameters. Op de VM zelf draait niets Guacamole-specifieks, alleen een normale RDP of SSH service.

**Waarom één URL, niet per-VM subdomeinen.** Een per-VM subdomein patroon (`dev-jan-vm.rijnland.dev`) vereist óf een aparte Guacamole deployment per VM (verspillend: aparte guacd, DB, certificaat en user store), óf een reverse-proxy die elk subdomein terugrouteert naar dezelfde Guacamole. Dat laatste koopt niets dat het home-scherm niet al biedt, en het herintroduceert precies het probleem dat Guacamole moest oplossen: onthouden welke machine en welke credentials je ook alweer nodig had.

**Per-VM isolatie via RBAC.** Elke connection heeft object-level permissies: `READ` (vereist om te verbinden), `UPDATE`, `DELETE` en `ADMINISTER`. Permissies worden per-user of per-user-group verleend. Voorbeeld: maak connection `dev-jan-vm`, verleen `READ` aan user `jan`. Als Jan inlogt ziet haar home-scherm exact `dev-jan-vm`; Mary ziet alleen `dev-mary-vm`; admins zien alles. Groeps-overerving is recursief, dus een `developers` groep kan baseline toegang verlenen aan alle leden.

**Deep-links (optioneel, voor portal integratie).** Directe links naar een specifieke connection hebben de vorm `/guacamole/#/client/<encoded-id>`, waarbij `<encoded-id>` de base64url is van de null-joined tuple `[connection_id, type, dataSource]`. De gebruiker moet nog steeds authenticeren; een deep-link slaat alleen de home-screen klik over. Handig voor een "Open mijn VM" knop in de Druppie frontend, maar geen manier om login te omzeilen.

```mermaid
flowchart LR
    BROWSER["Developer browser"] -->|"HTTPS :443"| WEB["Guacamole Web App<br/>remote.druppie.rijnland.dev<br/>Auth + connections DB + Web UI"]
    WEB -->|"Guacamole protocol<br/>TCP :4822"| GUACD["guacd daemon<br/>laadt RDP / SSH / VNC plugin"]
    GUACD -->|"RDP :3389 (intern)"| VMRDP["Dev VM<br/>bijv. dev-jan-vm"]
    GUACD -->|"SSH :22 (intern)"| VMSSH["Dev VM<br/>bijv. dev-jan-vm"]

    style BROWSER fill:#fdcb6e,color:#1a1a2e
    style WEB fill:#0984e3,color:#ffffff
    style GUACD fill:#6c5ce7,color:#ffffff
    style VMRDP fill:#e17055,color:#ffffff
    style VMSSH fill:#e17055,color:#ffffff
```

### Login & Authenticatie (Keycloak OIDC SSO)

Guacamole heeft een officiële OpenID Connect extensie. Daarmee hergebruiken we de bestaande Keycloak installatie (realm `druppie`, dezelfde users als de Druppie frontend: `admin`, `architect`, `developer`, `analyst`, `normal_user`). Een developer logt één keer in bij Keycloak en is daarna zowel in de Druppie frontend als in Guacamole ingelogd.

**SSO flow:**

1. Developer navigeert naar `remote.druppie.rijnland.dev`.
2. Guacamole (met de OpenID Connect extensie aan) redirect naar het Keycloak authorization endpoint voor realm `druppie`.
3. Developer authenticeert bij Keycloak, met dezelfde credentials als de Druppie frontend (`admin` / `Admin123!`, enz.).
4. Keycloak redirect terug naar Guacamole met een authorization code / id_token.
5. Guacamole valideert het token, mapt de OIDC subject naar een lokale Guacamole user (bij eerste login auto-aangemaakt indien zo geconfigureerd), en toont het home-scherm gefilterd op de connections van die user.

**Auto-provisioning.** Guacamole kan zo geconfigureerd worden dat de lokale user-record bij eerste OIDC login automatisch wordt aangemaakt. Er hoeft dus geen handmatige user-duplicatie tussen Keycloak en Guacamole.

**Authorisatie is los van authenticatie.** Keycloak beantwoordt "wie ben je?"; Guacamole's eigen RBAC beantwoordt "welke VMs mag je zien?". De provisioning API (zie de Deploy flow hieronder) verleent `READ` op de juiste connection aan de juiste user, nadat de VM is aangemaakt.

**Single logout (optioneel).** Keycloak SSO logout propageert naar alle geïntegreerde apps, dus uitloggen bij Keycloak logt ook uit Guacamole.

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Browser as Browser
    participant Guac as Guacamole (OIDC ext.)
    participant KC as Keycloak (realm druppie)

    Dev->>Browser: Navigeert naar remote.druppie.rijnland.dev
    Browser->>Guac: GET / (geen sessie)
    Guac-->>Browser: 302 redirect naar Keycloak
    Browser->>KC: Authorization request (realm druppie)
    KC-->>Browser: Login pagina
    Dev->>KC: Login (admin / Admin123!)
    KC-->>Browser: 302 redirect + authorization code / id_token
    Browser->>Guac: Callback met token
    Guac->>KC: Valideer token
    KC-->>Guac: Geldig (subject = user)
    Guac->>Guac: Map OIDC subject naar lokale user<br/>(auto-aanmaken bij eerste login)
    Guac-->>Browser: Home-scherm (connections gefilterd op RBAC)
    Browser-->>Dev: Lijst met geautoriseerde VMs
```

### RDPGW — later (fase 2)

Voor ontwikkelaars die de native Windows RDP client (mstsc) willen gebruiken i.p.v. browser. [bolkedebruin/rdpgw](https://github.com/bolkedebruin/rdpgw) is een Go-based RD Gateway voor K8s. **Niet in de eerste fase** — Guacamole dekt RDP en SSH. RDPGW toevoegen als er behoefte is aan native mstsc.

```
Windows mstsc
  → remote-rdp.druppie.rijnland.dev:443 (Traefik)
  → RDPGW (Go binary, ~100MB)
  → dev-jan:3389 (intern)
```

- Native RDP ervaring (mstsc, Remmina, Microsoft Remote Desktop)
- Alleen RDP (geen SSH)
- Lichter dan Guacamole (~100MB vs ~1GB)
- Go binary, K8s-native, Helm chart beschikbaar
- **Prioriteit: Laag — alleen als team native RDP vraagt**

### Overzicht toegangsmethoden

| Methode | URL | Poort extern | Wat | Client nodig? |
|---------|-----|-------------|-----|--------------|
| **code-server** | `dev-jan.druppie.rijnland.dev` | 443 HTTPS | VS Code in browser + preview | Nee |
| **Guacamole RDP** | `remote.druppie.rijnland.dev` | 443 HTTPS | RDP desktop in browser | Nee |
| **Guacamole SSH** | `remote.druppie.rijnland.dev` | 443 HTTPS | SSH terminal in browser | Nee |
| ~~RDPGW~~ (later) | ~~`remote-rdp.druppie.rijnland.dev`~~ | 443 HTTPS | Native RDP via mstsc | Ja — fase 2 |

Alle externe toegang gaat via poort 443. Geen poort 22 of 3389 naar buiten.

---

## Deploy → Werk → Stop flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant UI as Druppie UI
    participant BE as Druppie Backend
    participant Vault as Hashicorp Vault
    participant ESO as ESO
    participant K8s as Kubernetes API
    participant Pod as Dev VM (Kata Pod)
    participant Git as Gitea
    participant Guac as Guacamole

    Note over Dev,Git: Start — developer wil feature branch deployen

    Dev->>UI: Opent "Dev Environments" tab
    UI->>BE: GET /branches (van Gitea)
    BE->>Git: List branches
    Git-->>BE: [main, colab-dev, feature-xyz, ...]
    BE-->>UI: Branches lijst

    Dev->>UI: Selecteert "feature-xyz" → klikt "Deploy"
    UI->>BE: POST /dev-vms {branch: "feature-xyz"}

    BE->>BE: 1. Check of PVC al bestaat
    BE->>ESO: 2. Maak ExternalSecret (Vault → K8s)
    ESO->>Vault: Fetch secret/developers/jan
    Vault-->>ESO: Tokens, keys
    ESO->>K8s: Sync K8s Secret

    BE->>K8s: 3. Maak Kata Pod
    K8s->>Pod: 4. Pod start

    Pod->>Pod: Startup script:
    Pod->>Pod: 1. Seed PVC van base image (colab-dev HEAD + deps)
    Pod->>Git: 2. git fetch + checkout feature-xyz (alleen file diffs)
    Pod->>Pod: 3. Deps check → package.json/requirements.txt veranderd?
    Pod->>Pod:    Nee → skip. Ja → npm install / pip install (alleen diff)
    Pod->>Pod: 4. docker-compose up (hot reload!)
    Pod->>Pod: 5. Start code-server, SSH, RDP

    Pod-->>BE: Ready
    BE->>K8s: 5. Maak Traefik IngressRoute
    BE->>Guac: 6. Maak Guacamole connection<br/>POST /api/session/data/postgresql/connections<br/>(protocol=rdp, hostname=pod IP, port=3389, creds uit secret)
    Guac-->>BE: connection-id
    BE->>Guac: 7. Verleen READ permissie op connection aan developer
    BE-->>UI: Status: ✅ Ready (2m 34s)
    UI-->>Dev: code-server: https://dev-feature-xyz.druppie.rijnland.dev
    UI-->>Dev: Open VM: https://remote.druppie.rijnland.dev/#/client/&lt;encoded-id&gt;

    Note over Dev,Git: Developer werkt in de pod

    Dev->>UI: Klikt "Connect"
    UI-->>Dev: Opent https://dev-feature-xyz.druppie.rijnland.dev
    Dev->>Pod: Edit code in code-server
    Pod->>Pod: Hot reload: wijziging < 1s zichtbaar
    Dev->>Pod: Test, debug, herhaal

    Dev->>Pod: git commit -m "feature done"
    Dev->>Pod: git push origin feature-xyz
    Pod->>Git: Push commits

    Note over Dev,Git: Klaar — opruimen of laten staan

    Dev->>UI: Klikt "Stop"
    UI->>BE: POST /dev-vms/feature-xyz/stop
    BE->>Guac: Verwijder Guacamole connection<br/>(of trek READ permissie in)
    BE->>K8s: Delete pod (PVC blijft)
    BE-->>UI: Status: Stopped (PVC behouden)

    Note over Dev,Git: Later: herstarten met git pull (< 30s)
```

---

## Agent + Developer samenwerking

```mermaid
sequenceDiagram
    participant Dev as Developer (Dev VM)
    participant UI as Druppie UI
    participant BE as Druppie Backend
    participant AgentBE as Agent Runtime (k8s_manager)
    participant AgentPod as Agent Sandbox (Kata)
    participant Git as Gitea

    Note over Dev,Git: Developer vraagt agent om code te schrijven

    Dev->>UI: Chat: "Optimaliseer de login flow"
    UI->>BE: POST /chat/session/start
    BE->>AgentBE: Start coding agent task

    AgentBE->>AgentPod: 1. Maak Kata sandbox pod
    AgentPod->>AgentPod: 2. Startup: git clone repo
    AgentPod->>Git: Clone branch feature-xyz

    loop Agent coding loop
        AgentPod->>AgentPod: Schrijf code
        AgentPod->>AgentPod: Test code
    end

    AgentPod->>Git: git commit + push code changes
    AgentPod->>AgentPod: Cleanup (ephemeral pod)
    AgentBE-->>BE: Task complete ✅
    BE-->>UI: Agent: klaar

    Note over Dev,Git: Developer reviewt agent's werk

    Dev->>Pod: git pull (in dev VM)
    Dev->>Pod: Review changes in VS Code
    Dev->>Pod: Accepteer of verwerp

    Note over Dev,Git: Agent en dev VM: zelfde runtime, aparte pods
    Note over Dev,Git: Interface: git — niet shared filesystem
```

---

## Secrets Flow — 3-laags model

Dev VMs gebruiken **drie secret bronnen** met verschillende levensduren en doelen. De belangrijkste reden: Druppie init scripts maken repos aan in Gitea. Als elke dev VM prod Gitea gebruikt, vervuilt die. Daarom draait elke dev VM een **lokale Gitea** in Docker-in-Docker.

```mermaid
flowchart TB
    subgraph Trigger["Provisioning trigger"]
        A["Druppie UI: 'Deploy feature-xyz'"]
    end

    subgraph Layer1["Laag 1: Bootstrap (per-VM, gegenereerd)"]
        direction TB
        B1["Druppie Backend genereert random secrets<br/>secrets.token_urlsafe()"]
        B2["K8s Secret: dev-feature-xyz-bootstrap<br/>LOCAL_GITEA_TOKEN · LOCAL_PG_PASSWORD<br/>INTERNAL_API_KEY · MODULE_API_TOKEN<br/>label: ephemeral=true"]
    end

    subgraph Vault["Hashicorp Vault"]
        V1["secret/developers/jan<br/>├── ssh_private_key<br/>├── zai_api_key<br/>└── git_remote_url"]
    end

    subgraph Layer2["Laag 2: User (Vault → ESO)"]
        direction TB
        C1["ExternalSecret CRD<br/>ref: secret/developers/jan"]
        C2["ESO sync: Vault → K8s Secret<br/>dev-feature-xyz-user"]
    end

    subgraph Layer3["Laag 3: Cluster (static)"]
        D1["ConfigMap: cluster-config<br/>REGISTRY_URL · VAULT_ADDR"]
    end

    subgraph Pod["Kata Dev Pod"]
        direction TB
        P1["envFrom: bootstrap + user secrets"]
        P2["ConfigMap: cluster-config"]
        P3["Startup script:<br/>1. Start lokale Gitea (Docker-in-Docker)<br/>2. git config (user creds from Vault)<br/>3. Druppie init → lokale Gitea (localhost:3000)<br/>4. Developer git push → echte Gitea (via SSH key)"]
        P4["Lokale Gitea: prullenbak<br/>Echte Gitea: schoon"]
    end

    A --> B1
    B1 --> B2
    A --> C1
    C1 --> C2
    V1 --> C1

    B2 --> P1
    C2 --> P1
    D1 --> P2
    P1 --> P3
    P2 --> P3
    P3 --> P4

    style Trigger fill:#fdcb6e,color:#1a1a2e
    style Layer1 fill:#00b894,color:#1a1a2e
    style Vault fill:#6c5ce7,color:#ffffff
    style Layer2 fill:#0984e3,color:#ffffff
    style Layer3 fill:#2d3436,color:#e0e0e0
    style Pod fill:#e17055,color:#ffffff
```

**Twee Gitea's in één pod:**

| Gitea | URL | Gebruikt door | Repos | Levensduur |
|-------|-----|--------------|-------|------------|
| **Lokale Gitea** (Docker-in-Docker) | `localhost:3000` | Druppie init scripts | Sample repos, test data | Ephemeral — weg bij pod delete |
| **Echte Gitea** (cluster) | `gitea.druppie.rijnland.dev` | Developer's git push/pull | Alleen echte Druppie code | Permanent — blijft schoon |

---

## Deploy Triggers — 3 typen

```mermaid
flowchart TB
    subgraph Triggers["Hoe deployments worden getriggerd"]
        direction LR

        subgraph Auto["Automatisch (Git PR merge)"]
            PR1["PR merge → main"] --> F1["FluxCD sync → druppie-prod"]
            PR2["PR merge → colab-dev"] --> F2["FluxCD sync → druppie-colab-dev"]
        end

        subgraph Manual["Handmatig (Druppie UI)"]
            D1["Developer selecteert branch"] --> K1["Druppie: maak Kata pod"]
            D1 --> K2["Druppie: maak IngressRoute"]
            D1 --> K3["Druppie: maak ExternalSecret"]
            K1 --> P1["Dev VM actief<br/>» https://dev-branch.druppie.rijnland.dev"]
        end

        subgraph AgentAuto["Automatisch (Druppie Agent Runtime)"]
            A1["Agent coding task"] --> A2["k8s_manager: spawn Kata pod"]
            A2 --> A3["Agent Sandbox actief<br/>» headless, ephemeral"]
        end
    end

    style Triggers fill:#1a1a2e,color:#e0e0e0
    style Auto fill:#00b894,color:#1a1a2e
    style Manual fill:#e17055,color:#ffffff
    style AgentAuto fill:#6c5ce7,color:#ffffff
```

---

## Druppie varianten per omgeving

```mermaid
flowchart TB
    subgraph Variants["Druppie varianten — resources"]
        direction LR

        subgraph Full["Volledig (prod + colab-dev)"]
            F_KC["Keycloak · 2GB"]
            F_PG["CNPG PostgreSQL · 1GB"]
            F_GITEA["Gitea · 1GB"]
            F_MCP["9× MCP Modules · 4.5GB"]
            F_BE2["Backend · 2GB"]
            F_FE2["Frontend · 512MB"]
            F_TOTAL["Totaal: ~11GB"]
        end

        subgraph Dev["Dev VM (Kata pod)"]
            D_AUTH["Mock Auth · 0MB"]
            D_PG["Standalone PG · 256MB"]
            D_ALL["Alles in 1 pod"]
            D_HOT["Hot reload: <1s"]
            D_TOTAL["~4GB per dev"]
        end

        subgraph Sandbox["Agent Sandbox (Kata pod)"]
            A_AUTH["Mock Auth · 0MB"]
            A_PG["Standalone PG · 256MB"]
            A_EPHEMERAL["Ephemeral · geen PVC"]
            A_TOTAL["~3GB per sandbox"]
        end
    end

    style Variants fill:#1a1a2e,color:#e0e0e0
    style Full fill:#0984e3,color:#ffffff
    style Dev fill:#e17055,color:#ffffff
    style Sandbox fill:#6c5ce7,color:#ffffff
```

---

## Resource Budget (1TB RAM totaal)

| Omgeving | Type | RAM | vCPU | Storage | GPU |
|----------|------|-----|------|---------|-----|
| `druppie-prod` | Namespace | 32GB | 16 | Longhorn/NFS | — |
| `druppie-colab-dev` | Namespace | 16GB | 8 | Longhorn/NFS | — |
| Dev VMs (max 10) | Kata pods | 4GB × 10 = 40GB | 4 × 10 = 40 | 50Gi × 10 = 500Gi | 1× MIG |
| Agent Sandboxes (max 5) | Kata pods | 3GB × 5 = 15GB | 2 × 5 = 10 | Ephemeral | — |
| Infrastructuur (Vault, Prometheus, etc.) | System | 32GB | 16 | ~200Gi | — |
| **Subtotaal** | | **~135GB** | **~90** | **~700Gi** | **1 GPU** |
| **Vrij** | | **~865GB** | — | — | **3 GPUs** |

---

## Samenvatting

| Component | Technologie | Provisioning | Secrets |
|-----------|------------|-------------|---------|
| **druppie-prod** (namespace) | Volledige Druppie stack | FluxCD GitOps, auto op PR→main | Vault + Helm values |
| **druppie-colab-dev** (namespace) | Volledige Druppie stack | FluxCD GitOps, auto op PR→colab-dev | Vault + Helm values |
| **Dev VM** (Kata pod) | Alles in 1 pod, hot reload | Druppie UI, handmatig | 3-laags: bootstrap + Vault + cluster |
| **Agent Sandbox** (Kata pod) | Headless, ephemeral | Druppie agent runtime (k8s_manager.py) | Bootstrap only, geen user secrets |
| **Lokale Gitea** (in dev VM) | Docker-in-Docker, localhost:3000 | Pod startup script | Bootstrap random wachtwoord |
| **Echte Gitea** (extern) | Git repos + Gitea Actions CI | Extern (infra beheert) | Developer SSH key uit Vault |
| **Harbor** (in cluster) | Container registry + scanning | Zelf geïnstalleerd | Basic auth via Vault/ESO |
| **dev-vm-base** (in Harbor) | Shared base image voor alle dev VMs + agents | CI bouwt op colab-dev push | Deps in image, git checkout per branch |
| **FluxCD** (extern) | GitOps → cluster sync | Extern (infra beheert) | kubeconfig naar cluster |
| **Vault** (extern) | Secrets management | Extern (infra beheert) | ESO sync naar K8s secrets |

---

## Faseringsplan

| Fase | Week | Wat | Deliverable |
|------|------|-----|-------------|
| **1** | 1-2 | Fundering: node labels/taints, Kata operator, Harbor registry, LLM pod op GPU node, namespaces, FluxCD config, quotas | Cluster klaar voor workloads |
| **2** | 3-4 | Dev VMs: base image, Vault secrets structuur, Druppie provisioning API + UI, LLM config via prod URL, **Guacamole installeren** (remote access gateway) | Devs kunnen VM deployen + RDP/SSH via browser |
| **3** | 5-6 | Agent sandboxes: k8s_manager.py, zelfde image, git interface | Agents werken op K8s |
| **4** | 7-8 | CI/CD: Gitea Actions pipeline, monitoring, developer docs | Productie-klaar, gedocumenteerd |
| **Later** | — | RDPGW (native RDP client support) — alleen als team er om vraagt | Optioneel |

---

## Genomen beslissingen — definitief

| # | Beslissing | Keuze |
|---|-----------|-------|
| 1 | Cluster | Rancher RKE2 (containerd), 8 nodes (3 master + 1 GPU + 4 worker × 96GB), ~480GB worker RAM |
| 2 | Runtime dev pods + agent sandboxes | Kata Containers |
| 3 | Dev model | Model A: alles in 1 pod, hot reload lokaal |
| 4 | GitOps prod/dev namespaces | FluxCD (extern, door infra) |
| 5 | Dev VM provisioning | Druppie backend + UI, handmatig |
| 6 | Secrets injectie | 3-laags: bootstrap (per-VM) + Vault/ESO (per-user) + cluster (static) |
| 7 | Storage | Longhorn (al aanwezig) |
| 8 | Ingress + TLS | Traefik + cert-manager (al aanwezig) |
| 9 | Auth dev VMs | Mock auth (geen Keycloak) |
| 10 | Agent ↔ Dev interface | Git (geen shared filesystem) |
| 11 | Code lifecycle | Developer pull/push via git |
| 12 | Preview auto-deploy | Alleen prod + colab-dev via FluxCD |
| 13 | GPU node | Exclusief voor prod LLM pod (2× RTX 6000 Pro, 96GB VRAM, NoSchedule taint) |
| 14 | LLM toegang dev/colab-dev | Via prod LLM URL (OpenAI-compatible endpoint) |
| 15 | Node placement | Workers voor alles, GPU node alleen LLM |
| 16 | Cluster toegang | Druppie team heeft cluster-admin |
| 17 | Prod/dev isolatie | PriorityClasses (prod=10000, colab-dev=8000, CI=3000, dev VM=1000, agent=500) |
| 18 | Colab-dev | Zelfde stack als prod, alleen minder replicas en geen HA |
| 19 | Remote access | Apache Guacamole (RDP + SSH via 443 HTTPS, browser-based). RDPGW later indien native client gewenst |
| 20 | Container registry | Harbor (in cluster, zelf geïnstalleerd) — scanning, signing, UI |
| 21 | Gitea/Vault/FluxCD | Extern (infra beheert). Cluster = pure compute |
| 22 | Dev VM base image | Shared base vanuit colab-dev (in Harbor). Startup: image pull + git checkout feature branch. Eerste dev VM op node ~2-3 min, daarna <30s door containerd layer cache |
