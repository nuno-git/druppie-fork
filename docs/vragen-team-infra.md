# Vragen voor Team Infra — Druppie Dev/Preview Omgevingen

> **Status:** Ter bespreking  
> **Datum:** 2026-06-23  
> **Context:** Druppie migratie naar lokaal Rancher RKE2 cluster — dev VMs, preview environments, CI/CD  
> **Toegang:** Druppie team krijgt **cluster-admin** rechten  
> **Referenties:** [research-dev-environments.md](./research-dev-environments.md), [dev-environment-architecture.md](./dev-environment-architecture.md)  

---

## 0. Node Provisioning — Concrete Aanvraag

Wij mogen nodes toevoegen en RAM provisionen. Hier is wat we nodig hebben voor de volle setup (10 dev VMs, prod, colab-dev, agents, CI/CD, LLM).

### Resource budget (volle setup)

| Workload | RAM | vCPU | Nodes |
|----------|-----|------|-------|
| Cluster system (RKE2, Traefik, Longhorn, Vault, ESO, Prometheus, Fleet, GPU Operator) | ~50GB | ~20 | Verspreid |
| druppie-prod (backend 3-8×, frontend, 9× modules, CNPG, Keycloak, Gitea, NFS) | ~35GB | ~16 | Workers |
| druppie-colab-dev (backend 2×, frontend, 9× modules, CNPG, Keycloak) | ~20GB | ~8 | Workers |
| **Dev VMs (10 × 16GB, Kata pods)** | **160GB** | **40** | Workers |
| Agent sandboxes (max 5 gelijktijdig, Kata pods) | ~40GB | ~10 | Workers |
| CI/CD runners (Gitea Actions, 2-3 runners) | ~12GB | ~4 | Workers |
| LLM pod (vLLM, 2× RTX 6000 Pro) | ~64GB | ~16 | GPU node |
| Headroom (20%) | ~76GB | — | — |
| **Totaal** | **~457GB** | **~114** | |

### Aanvraag: node topology

```
3× Master nodes (bestaand of upgraden)
   Min 16GB RAM, 4 vCPU elk (liefst 32GB voor headroom)
   Alleen control plane + etcd. NoSchedule taint.

1× GPU node (bestaand)
   2× RTX 6000 Pro (96GB VRAM totaal)
   Min 128GB systeem RAM (voor vLLM model loading + overhead)
   16+ vCPU
   Taint: gpu=true:NoSchedule (exclusief voor LLM pod)

4× Worker nodes (AAN TE VRAGEN — nieuw)
   Min 96GB RAM per node (= 384GB totaal)
   16+ vCPU per node
   NVMe/SSD opslag (voor Longhorn PVCs + Docker cache)
   Label: node-type=worker
   Prod, colab-dev, dev VMs en agents delen dezelfde nodes
   Isolatie via PriorityClass, niet fysieke scheiding

Totaal cluster: ~480GB worker RAM + 128GB GPU node = ~608GB
```

### Waarom 4 worker nodes × 96GB?

- Prod + colab-dev (dezelfde stack) + CI + agents = ~115GB
- 10 dev VMs × 16GB = 160GB
- System overhead + headroom = ~91GB
- Totaal: ~366GB → 384GB (4× 96GB) past met marge
- Bij 1 node failure: 3× 96GB = 288GB, genoeg voor alle workloads
- Bij groei naar 15+ developers: 5e worker toevoegen

### Prod/dev isolatie: PriorityClasses (géén aparte nodes)

Prod, colab-dev, dev VMs en agents draaien op dezelfde worker nodes. Geen verspilling van nodes aan dedicated prod. Isolatie komt van PriorityClasses:

| Workload | PriorityClass | Gedrag bij node pressure |
|----------|--------------|------------------------|
| Prod | 10000 | Altijd beschermd — nooit geëvinceerd |
| Colab-dev | 8000 | Hoog — alleen geëvinceerd na prod |
| CI/CD | 3000 | Medium — geëviceerd voor prod/colab-dev |
| Dev VMs | 1000 | Laag — geëviceerd bij pressure (PVC blijft) |
| Agent sandboxes | 500 | Laagste — als eerste geëviceerd (ephemeral) |

### Vragen aan infra:
- Kunnen jullie 4 worker nodes provisionen met minimaal 128GB RAM elk?
- Wat is de beschikbare disk capacity per worker node? (We rekenen op ~500Gi voor dev VM PVCs)
- Is de GPU node op te waarderen naar 128GB RAM als die nog minder heeft?
- Hebben de worker nodes NVMe/SSD, of SATA? (Performance voor Docker builds en dev VM home dirs)

---

## 0b. Cluster Topology — bevestigen

Onze aanname na provisioning:

```
8 nodes totaal:
  3× master nodes  (control plane + etcd, NoSchedule taint)
  1× GPU node      (2× RTX 6000 Pro, 128GB+ RAM, exclusief LLM pod)
  4× worker nodes  (96GB RAM elk = 384GB, CPU only, node-type=worker)
Totaal: ~608GB RAM (ruim binnen 1TB)
```

- Klopt deze topology na provisioning?
- Zijn er workloads van infra-team die op de worker nodes draaien en niet verstoord mogen worden?

---

## 1. CI/CD & Fleet

**1.1 — Zit Fleet hier dan volledig buiten? Wij willen een CI/CD pipeline inrichten dus misschien handig om dat ook te gebruiken? Of handiger om zelf iets in de cluster in te richten?**

Onze architectuur gaat ervan uit dat Fleet de GitOps deploy voor prod (`druppie-prod`) en colab-dev (`druppie-colab-dev`) namespaces doet. Vragen:
- Beheert infra-team de Fleet GitRepo's, of kunnen we die zelf aanmaken/beheren? (We hebben immers cluster-admin.)
- Kan Fleet ook de build pipeline (Docker images bouwen, tests draaien) doen, of is Fleet puur deploy-only (GitOps)?
- Als Fleet deploy-only is: wat is de aanbevolen manier om CI builds te doen in dit cluster? Gitea Actions? Eigen runner? Bestaande pipeline?
- Mogen we een eigen CI/CD tool (bijv. Gitea Actions runner) in een eigen namespace draaien, parallel aan Fleet?

---

## 2. Gitea & Container Registry

**2.1 — Heeft de git server ook een container registry? (Gitea biedt dit volgens mij ook aan.)**

Druppie bouwt 13 Docker images (backend, frontend, 9 modules, init, layout-service). Deze moeten ergens naartoe gepusht worden.
- Is de Gitea Container Registry feature ingeschakeld op de bestaande Gitea instantie?
- Zo ja: wat is de registry URL? Hoe authentiseren we (token, SSO)?
- Zo nee: is er een andere registry beschikbaar in het cluster? Of moeten we er zelf een draaien?
- Mogen dev VMs images pushen naar deze registry (voor preview builds)?

**2.2 — Welke Gitea instantie gebruiken dev VMs voor git push/pull?**

Onze architectuur heeft twee Gitea's per dev VM:
- **Lokale Gitea** (in Docker-in-Docker, `localhost:3000`) — voor Druppie init scripts, sample repos
- **Echte Gitea** (cluster-wide) — voor developer's git push/pull van de echte Druppie code

Vraag: is de echte Gitea bereikbaar vanuit alle namespaces? Zijn er network policies die dit beperken?

---

## 3. Backups

**3.1 — Wordt de git server (of andere delen van de omgeving) automatisch gebackupt? Hoe zouden we dit handig kunnen aanpakken?**

- Welke backup tooling is aanwezig? (Velero? Longhorn snapshots? Custom scripts?)
- Wat is de backup frequentie en retentie?
- Zijn de Gitea repos, Vault secrets, en Longhorn PVCs inbegrepen?
- Voor dev VMs: Longhorn PVCs bevatten developer code en lokale Gitea data. Willen we die backuppen? Of is "git push naar echte Gitea" voldoende als recovery mechanisme?
- Voor prod: CNPG databases — is er een backup strategie voor PostgreSQL?

---

## 4. Kata Containers

**4.1 — Kan Kata Containers geïnstalleerd worden op de cluster nodes?**

Onze architectuur vereist Kata Containers als runtime voor dev VMs en agent sandboxes (vervangt Sysbox). Vragen:
- Is nested virtualization / KVM ingeschakeld op de worker nodes? (Kata vereist `/dev/kvm` op de host.)
- Zijn er BIOS settings die virtualization uitschakelen op bepaalde nodes?
- Welke Kata configuratie heeft voorkeur? (QEMU vs Cloud Hypervisor vs Firecracker)
- Hebben we voldoende rechten om de Kata operator zelf te installeren? (We hebben cluster-admin, maar de operator draait op node-level.)

---

## 5. Vault & Secrets

**5.1 — Hoe krijgen we toegang tot Vault voor het aanmaken van secrets?**

Onze architectuur gebruikt 3 lagen secrets (bootstrap/user/cluster). Voor Laag 2 (user secrets) moeten we per developer secrets aanmaken in Vault.
- Welke Vault auth methode gebruiken we? (Token? Kubernetes auth? AppRole?)
- Hoe configureert External Secrets Operator (ESO) de Vault backend? Is er een `ClusterSecretStore` die we kunnen hergebruiken?
- Kunnen we eigen secret paths aanmaken (bijv. `secret/developers/jan`) of moeten die via infra-team?
- Wie beheert de SSH keys en Gitea tokens die in Vault komen? Druppie team of infra-team?

---

## 6. Netwerk & DNS

**6.1 — Kunnen we wildcard DNS records aanmaken voor dev VMs + Guacamole?**

Elke dev VM en de remote access gateway krijgen een URL:
- `https://dev-{branch}.druppie.rijnland.dev` — code-server per dev VM
- `https://remote.druppie.rijnland.dev` — Apache Guacamole (RDP + SSH gateway)
- Kunnen we een wildcard record `*.druppie.rijnland.dev` (of `*.dev.druppie.rijnland.dev`) laten aanwijzen naar het cluster?
- Wie beheert DNS? Kunnen we dat zelf, of moet infra-team records aanmaken?
- Is er een interne DNS (CoreDNS custom rewrites) die we moeten configureren?

**6.2 — Extern alleen 443 — bevestigen**

Wij begrijpen dat extern alleen poort 443 (HTTPS) beschikbaar is op `*.rijnland.dev`. Daarom gebruiken we Apache Guacamole om RDP/SSH naar dev VMs te tunnelen over HTTPS.
- Klopt het dat poort 22 (SSH) en 3389 (RDP) niet extern bereikbaar zijn?
- Is er een manier om extra poorten open te zetten als dat later nodig is?
- Of is Guacamole over 443 de definitieve oplossing?

---

## 7. GPU Node & LLM

**7.1 — GPU node is exclusief voor prod LLM pod. Is hiermee akkoord?**

Onze beslissing: de GPU node (2× RTX 6000 Pro, 96GB VRAM totaal) is exclusief gereserveerd voor de prod LLM pod (vLLM/Ollama). Dev VMs en colab-dev gebruiken géén lokale GPU — zij benaderen de prod LLM via een interne URL.

```
GPU node (exclusief):
└── prod LLM pod (vLLM)
    ├── 2× nvidia.com/gpu (exclusive, 96GB VRAM totaal)
    └── Exposes: http://llm-prod.druppie-prod.svc.cluster.local:8000/v1
                 (OpenAI-compatible endpoint)

Dev VMs + colab-dev:
└── LLM config wijst naar prod LLM URL (interne service DNS)
    └── Geen GPU node nodig
```

Vragen:
- Is de NVIDIA GPU Operator al volledig geconfigureerd op de GPU node?
- Ondersteunen de RTX 6000 Pro's MIG? (Niet nodig voor onze setup, maar goed om te weten.)
- Is de GPU node bereikbaar via K8s service DNS vanuit andere namespaces? (`llm-prod.druppie-prod.svc.cluster.local`)
- Heeft de GPU node minimaal 128GB systeem RAM? (vLLM heeft RAM nodig naast VRAM voor model loading)

---

## 8. Node Labels & Taints

**8.1 — Mogen we node labels en taints zelf aanpassen?**

We willen de volgende labeling:

```bash
# GPU node
kubectl label node <gpu-node> node-type=gpu gpu=true
kubectl taint node <gpu-node> gpu=true:NoSchedule

# Worker nodes
kubectl label node <worker-1> node-type=worker
kubectl label node <worker-2> node-type=worker
kubectl label node <worker-3> node-type=worker

# Master nodes (al getaint door RKE2 standaard)
```

Vragen:
- Mogen we deze labels/taints zelf zetten (cluster-admin)?
- Heeft infra-team eigen labels op de nodes staan die we niet mogen overschrijven?
- Zijn er workloads van infra-team die op de worker nodes draaien en niet verstoord mogen worden?

---

## 9. Storage

**9.1 — Welke Longhorn storage classes zijn beschikbaar?**

- Wat is de default storage class?
- Welke replicatie factor wordt gebruikt? (1, 2, of 3?)
- Willen we dev VM PVCs op `replicationFactor: 1` draaien (goedkoper, geen replicatie)?
- Wat is de beschikbare opslagcapaciteit? (We rekenen op ~500Gi voor 10 dev VM PVCs.)
- Ondersteunen jullie Longhorn snapshots? Kunnen we die gebruiken voor dev VM "reset" functionaliteit?

---

## 10. Backups

*(Zie §3 hierboven)*

---

## Volgende stappen

| Vraag | Prioriteit | Waarom urgent |
|-------|-----------|--------------|
| **Node provisioning (§0)** | **Blokkerend** | Zonder 4× 128GB workers kunnen we geen 10 dev VMs draaien |
| Cluster topology bevestigen (§0b) | **Hoog** | Basis voor alle node selectors en taints |
| Fleet / CI/CD (§1) | **Hoog** | Bepaalt hele deploy strategie |
| Gitea Registry (§2) | **Hoog** | Zonder registry geen image builds |
| Kata installatie / KVM (§4) | **Hoog** | Blokkeert alle dev VM work |
| GPU node config (§7) | **Hoog** | Bepaalt LLM architectuur |
| Node labels/taints (§8) | **Hoog** | Moeten kloppen voordat we deployments doen |
| Vault toegang (§5) | **Medium** | Nodig voor dev VM secrets provisioning |
| DNS wildcard (§6) | **Medium** | Nodig voor dev VM URLs, kan met nip.io fallback |
| Storage (§9) | **Medium** | Longhorn is er, details moeten kloppen |
| Backups (§3) | **Medium** | Belangrijk voor prod, minder urgent voor dev |
