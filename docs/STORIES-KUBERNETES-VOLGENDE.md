# Kubernetes Stories — Volgende Sprint

## Context

We hebben de Kubernetes migratie naar Hetzner k3s afgerond: backend en frontend zijn stateless en horizontaal schaalbaar. De volgende sprint focust op vijf thema's: migratie naar lokale Rancher cluster, CI/CD, sandbox performance, module schaalbaarheid, en lokale LLM inferentie.

**Belangrijke constraint:** We krijgen 1 lokaal Kubernetes cluster van team infra. Prod, staging, dev en preview omgevingen delen dit cluster via namespaces met strikte isolatie (NetworkPolicies, ResourceQuotas, LimitRanges, RBAC, PriorityClasses, Pod Security Admissions). Een apart cluster voor prod is gewenst maar binnen dit cluster niet mogelijk — mitigatie via processen, backups en disaster recovery runbooks.

Zie [ADR-KUBERNETES.md](./ADR-KUBERNETES.md) voor de oorspronkelijke architectuur beslissingen. Herzie daarin de Hetzner-specifieke keuzes (4.12 hetzner-k3s, 4.13 Cluster Autoscaler met Hetzner provider) die niet overdraagbaar zijn naar lokaal hardware.

---

## Migratie

### M1: Druppie migreren naar lokale Rancher cluster

Team infra levert clustertoegang. Druppie team migreert alle workloads, persistente data en DNS van Hetzner naar het lokale cluster, en verifieert end-to-end dat het platform werkt.

Onderdeel van deze story is het inrichten van de namespace-structuur met isolatie (`prod`, `staging`, `dev`, `preview-*`) inclusief NetworkPolicies, ResourceQuotas, LimitRanges, RBAC, PriorityClasses en Pod Security Admissions.

**Acceptatiecriteria**
- Alle workloads draaien op het lokale cluster
- Data succesvol gemigreerd (databases, Gitea repositories, secrets)
- DNS wijst naar het lokale cluster
- Namespace-isolatie actief en getest (dev pod kan niet bij prod database)
- Herziene ADR voor lokale hardware (node sizing, autoscaler strategie)
- Platform end-to-end werkend: login → chat → agent sessie

---

## CI/CD (momenteel niet werkend)

### C1: Auto-deploy pipeline bij PR merge

Pipeline die automatisch bouwt, pusht en deployed wanneer een PR gemerged wordt naar `colab-dev` (dev omgeving) en `main` (prod omgeving). Deploy target de juiste namespace per branch.

Deployment status is zichtbaar in Druppie, gekoppeld aan branch en commit.

**Acceptatiecriteria**
- PR merge naar `colab-dev` triggert deploy naar `dev` namespace
- PR merge naar `main` triggert deploy naar `prod` namespace
- Trigger werkt zowel via Git UI als command line zonder handmatige actie in Druppie
- Voortgang en resultaat (succes/mislukt) zichtbaar in Druppie, gekoppeld aan branch en commit
- Optioneel: melding via gekoppeld kanaal (Slack, e-mail)

### C2: Quality gate voor deploy

Lint, tests en type checks draaien als vereiste checks voordat een deploy mag starten. Voorkomt dat gebroken code automatisch naar een omgeving gaat.

**Acceptatiecriteria**
- `pytest`, `ruff`, `black` slagen voor backend
- `npm run lint`, `npm test` slagen voor frontend
- Bij falende checks gaat de deploy niet door
- Status zichtbaar in de PR (required check)

### C3: Preview omgevingen per feature branch

UI flow in Druppie om een geselecteerde feature branch te deployen naar een geïsoleerde omgeving met een unieke, voorspelbare URL. Automatische teardown wanneer de branch verwijderd wordt.

**Acceptatiecriteria**
- Lijst van beschikbare feature branches zichtbaar in Druppie-interface
- Eén knop ("Deploy feature branch") die actief wordt na selectie
- Geselecteerde branch wordt gebouwd en gedeployed naar geïsoleerde omgeving
- Andere deployments worden niet overschreven (andere branches, prod, staging, dev)
- Na succesvolle deployment bereikbaar via unieke, voorspelbare URL
- Namespace wordt automatisch opgeruimd wanneer branch verwijderd wordt
- ResourceQuota voorkomt dat preview omgevingen dev/ondermijnen

---

## Sandbox (blokkeert vergunningzoeker E2E)

### SB1: Sandbox architectuur spike

De sandbox is momenteel traag — agents verliezen veel tijd met installaties, elke sessie opnieuw. Beslissen over de richting voordat we verder bouwen.

Drie opties om te evalueren:
1. Op Docker Compose blijven met warme images en persistente cache (incrementeel)
2. Per-sessie Kubernetes namespaces met Podman rootless (geeft agents cluster access)
3. Sandbox operator adopteren (bv. gVisor / Kata Containers / Agent Sandbox operator)

Output is een ADR beslissing.

**Acceptatiecriteria**
- Drie opties onderzocht met voor- en nadelen
- ADR beslissing geschreven en goedgekeurd
- Spike documentatie in `/docs`

### SB2: Warme base images per project type

Pre-bake base images met veelgebruikte dependencies per gedetecteerd project type (Node.js, Python, etc.) zodat agents niet vanaf nul installeren elke sessie.

**Acceptatiecriteria**
- Base images beschikbaar voor de gangbare project types (Node.js met pnpm, Python met uv, etc.)
- Agent detecteert project type en selecteert juiste image
- Installatietijd meetbaar gereduceerd (target: onder de 30 seconden voor bestaande projecten)

### SB3: Persistente dependency cache over sessies

Sandbox herstarts overleven met gedeelde cache mounts voor package managers (pip, npm, pnpm, uv). Cheaper dan warme images, complementair aan SB2.

**Acceptatiecriteria**
- Cache mounts geconfigureerd per package manager
- Sandbox herstart behoudt cache
- Installatietijd bij herstart meetbaar gereduceerd

---

## Module Schaalbaarheid

### MS1: Beslissen — MCP modules schalen of migreren naar built-in backend tools?

ADR 4.10 stelt expliciet dat modules herbouwd worden als built-in backend tools ("ze verdwijnen als losse services"). Dit botst met de wens om modules te schalen. Beslissen welke kant we op gaan. Coding module is de bottleneck.

**Acceptatiecriteria**
- Beslissing gedocumenteerd met onderbouwing
- Bij "scale": geüpdatet ADR + nieuwe stories voor per-module HPA en RWX storage (Longhorn)
- Bij "built-in": geüpdatet ADR + nieuwe stories voor module-per-module migratie, startend met coding module

---

## Lokale LLMs

### LL1: Lokale inferentie stack spike (voorlopige keuze)

Opties evalueren (vLLM, text-generation-inference, Ollama, LLM-Kube/KubeAI) en een voorlopige top 2-3 kiezen om uit te deployen en te benchmarken. Definitieve keuze volgt na LL3 (benchmarks op onze hardware).

Selectiecriteria: GPU efficiëntie, autoscaling gedrag, OpenAI API compatibiliteit met onze bestaande LLM client code, community support, en complexiteit van operationeel beheer.

**Acceptatiecriteria**
- Top 3 opties vergeleken op features, performance, complexiteit, community support
- Voorlopige shortlist van 2-3 stacks om uit te deployen in LL2
- ADR met voorlopige beslissing geschreven en goedgekeurd
- Spike documentatie in `/docs`

### LL2: GPU node provisioneren + candidate stacks deployen

GPU node toegang via team infra. De shortlist uit LL1 als candidate stacks deployen via Helm, zodat ze vergeleken kunnen worden in LL3. Nadien, na benchmark-uitslag, de winnaar registreren als nieuwe LLM provider in Druppie.

**Acceptatiecriteria**
- GPU node beschikbaar in cluster (NVIDIA GPU operator actief)
- Minimaal 2 candidate stacks draaiend (bijv. vLLM en Ollama), beiden via Helm
- Elke stack heeft een OpenAI-compatible endpoint bereikbaar vanuit backend
- Stacks hebben HPA op GPU utilization
- Winnaar (na LL3) geregistreerd als nieuwe LLM provider in Druppie
- End-to-end werkend op de winnaar: token streaming, tool calling, long-context support

### LL3: LLM performance benchmark uitvoeren op onze hardware

We hebben een benchmark framework met 20 scenarios over 5 categorieën: latency, generation speed, context scaling, tool calling overhead, en stress/consistency. Met streaming support en TTFT (time to first token) meting. Multi-endpoint via YAML config (Azure AI Foundry, Ollama, vLLM, TGI).

Draai dit framework tegen de lokale endpoints (uit LL2) om te meten hoe goed modellen draaien op ónze hardware. Vergelijk lokale serving stacks onderling én met cloud baselines (Azure AI Foundry). Resultaten bepalen welke stack we definitief adopteren (input voor LL1's definitieve beslissing).

**Acceptatiecriteria**
- Benchmark framework draait tegen lokale endpoints zodra deze online zijn (LL2)
- Volledige scenario-suite uitgevoerd: latency, generation speed, context scaling, tool calling overhead, stress/consistency
- Metrics verzameld: TTFT, generation speed, context scaling gedrag, tool calling overhead, stabiliteit onder load
- Vergelijking tussen minimaal 2 lokale stacks en 1 cloud baseline (Azure)
- Output in JSON/CSV voor analyse
- Documentatie met aanbeveling voor optimale stack/configuratie op onze hardware
- Definitieve stack-keuze vastgelegd in geüpdatete ADR

---

## Volgorde en Afhankelijkheden

```
M1 (migratie) ─────┬─→ C1 (auto-deploy)
                   ├─→ C3 (preview envs) ──→ C2 (quality gate)
                   └─→ SB2 (warme images)

SB1 (spike) ────→ SB2 + SB3 (implementatie)

MS1 (beslissing) ──→ nieuwe stories (na keuze)

LL1 (voorlopige spike) ──→ LL2 (deploy candidates) ──→ LL3 (benchmark) ──→ LL1 (definitieve keuze)
```

**Blokkeertes op volgorde:**
- C1, C2, C3 kunnen niet voor M1 (cluster moet er zijn)
- SB2 kan niet voor SB1 (architectuur moet duidelijk zijn)
- LL2 kan niet voor LL1 (voorlopige shortlist moet gekozen zijn)
- LL3 meet resultaten die teruggaan naar LL1 voor de definitieve stack-keuze

---

## Risico's en Open Vragen

1. **Hetzner-specifieke ADR keuzes** — Cluster Autoscaler met Hetzner provider en `hetzner-k3s` CLI werken niet op lokaal hardware. Nieuwe oplossing nodig (manuele scaling? Karpenter bare metal? Metal³?).
2. **Single cluster risico's** — etcd corruptie, operator upgrades en K8s versie-upgrades kunnen niet per namespace getest worden. Mitigatie via strikte processen, regelmatige backups en een disaster recovery runbook.
3. **GPU node access** — Team infra moet GPU node kunnen leveren. Behoefte aan A100-klasse of L40S/consumer-grade? Afhankelijk van budget en model keuze.
4. **Sandbox architectuur keuze** — Als we voor per-sessie K8s namespaces gaan, heeft dit impact op M1 (extra RBAC, resource quotas, network policies per sessie).
5. **Module scalability conflict** — MS1 moet worden opgelost vóórdat we investeren in schaling die mogelijk weggegooid geld is (zoals ADR 4.10 aangeeft).
