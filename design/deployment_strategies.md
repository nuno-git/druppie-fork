# Technisch Ontwerp: Deployment Strategieën & Rolling Upgrades

## 🎯 Doelstelling
Dit ontwerp beschrijft hoe wijzigingen (updates) gecontroleerd worden uitgerold naar de verschillende omgevingen (TEST, ACC, PROD). Het doel is de balans te vinden tussen **snelheid** (in Test) en **stabiliteit** (in Productie).

De gebruiker heeft regie over de **"Rollout Pace"**: hoe agressief of conservatief een update wordt doorgevoerd, afhankelijk van de impact van de wijziging (Major vs. Minor/Patch).

---

## 🏗️ Het Concept: Spec-Driven Deployment Profile

In plaats van handmatig `kubectl` commando's te tikken, definieert de gebruiker (of de Builder Agent) een **Deployment Profile** in de `service.yaml`.

De Kubernetes `Deployment` resource biedt native ondersteuning voor Rolling Upgrades via `spec.strategy`. Wij tunen deze parameters op basis van het profiel.

### De Paremeters
1.  **Max Surge**: Hoeveel *extra* pods mogen er tijdelijk bij komen? (Hoger = Sneller, kost meer resources).
2.  **Max Unavailable**: Hoeveel pods mogen er *stuk* zijn tijdens de update? (0 = Zero Downtime).
3.  **Min Ready Seconds**: Hoe lang moet een nieuwe pod "goed" draaien voordat we hem vertrouwen en de volgende stap zetten? (Dit is de "wachttijd").

---

## 📊 Strategie Matrix

We onderscheiden drie standaard profielen die de **Builder Agent** automatisch toepast.

| Profiel | Omgeving | Type Wijziging | Max Surge | Max Unavail | Ready Wait (s) | Gedrag |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Blitz** | TEST | Alles | 100% | 50% | 0s | **Zo snel mogelijk**. Vervang de helft direct. Downtime is acceptabel. |
| **Cautious** | PROD | Minor / Patch | 25% | 0 | 30s | **Stabiel**. Stap-voor-stap (1 op 4). Geen downtime. Wacht 30s per stap. |
| **Paranoid** | PROD | Major | 1 | 0 | 300s | **Zeer Voorzichtig**. Eén pod per keer. Wacht 5 minuten (300s) per pod. |

---

## ⚙️ Technische Implementatie (Helm/Flux)

De implementatie vindt plaats in de **Helm Chart** die door Flux wordt uitgerold.

### 1. Configuratie (`values.yaml`)
De gebruiker specificeert in de `HelmRelease`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: drone-api
spec:
  values:
    # Keuze door gebruiker/agent:
    deploymentStrategy: "Paranoid" # Want: Major upgrade V1 -> V2
```

### 2. Vertaling naar Kubernetes (`deployment.yaml`)
De Helm chart vertaalt de string "Paranoid" naar harde cijfers:

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 10
  minReadySeconds: {{ .Values.readinessDelay | default 0 }} # De "Wachttijd"
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: {{ .Values.maxSurge }}
      maxUnavailable: {{ .Values.maxUnavailable }}
```

---

## 🔄 Visuele Flow: "De Paranoid Rollout"

Stel we upgraden de Drone API van V1 naar V2 in Productie (Paranoid Mode).
We hebben 4 Pods actief.

```mermaid
sequenceDiagram
    participant Flux as 🔄 Flux CD
    participant K8s as ☸️ Kubernetes
    participant Pod1 as 📦 Pod-1 (V1)
    participant Pod2 as 📦 Pod-2 (V1)
    participant PodNew as ✨ Pod-New (V2)

    Note over Flux, PodNew: Start Major Update (Paranoid: Surge 1, Wait 300s)
    
    Flux->>K8s: Apply Deployment Image: V2
    
    K8s->>PodNew: Start 1x V2 Pod
    Note right of PodNew: Opstarten...
    PodNew-->>K8s: Readiness Probe OK!
    
    Note over K8s: ⏱️ Wacht 300 seconden (MinReadySeconds)
    
    K8s-->>K8s: Geen crashes? Metrics OK?
    
    K8s->>Pod1: Terminate V1 Pod
    Pod1-->>K8s: Shutdown
    
    Note over K8s: Herhaal voor volgende Pod...
```

### Safety Gates (Health Checks)
Tijdens de "Wachttijd" (die 5 minuten) monitort Kubernetes de **Liveness** en **Readiness** probes.
*   Als de nieuwe V2 pod crasht (Reboot Loop), stopt de rollout automatisch.
*   De oude V1 pods blijven draaien.
*   Gebruikers merken (bijna) niets, behalve dat de update "hangt".

---

## 🚀 Gebruikerservaring

### Scenario: Developer configureert een update
De developer praat tegen de **Builder Agent**:

> **User**: *"Ik wil de nieuwe Drone AI (V2) naar productie brengen. Het is een grote wijziging, dus doe maar rustig aan."*

> **Agent**: *"Begrepen. Ik configureer de HelmRelease voor 'drone-ai' met strategie **Paranoid**. Dit betekent dat de uitrol 1 pod per 5 minuten vervangt. Akkoord?"*

> **User**: *"Maak er maar 2 minuten van."*

> **Agent**: *"Aangepast. `minReadySeconds` gezet op 120s."*

De Agent commiit vervolgens:
```yaml
# deploy/prod/drone-ai-release.yaml
spec:
  values:
    deploymentStrategy: "Custom"
    customStrategy:
      maxSurge: 1
      maxUnavailable: 0
      readinessDelay: 120
```

## ✅ Samenvatting
Door simpelweg gebruik te maken van de native kracht van Kubernetes RollingUpdates, gecombineerd met slimme defaults ("Profiles") in onze Helm Charts, geven we de gebruiker volledige controle over het risico, zonder complexe extra tools te hoeven installeren.
