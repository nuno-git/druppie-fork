# Workflow Orchestration (Argo Workflows)

## 🎯 Selectie: Argo Workflows
Voor het orkestreren van complexe werkprocessen en data-pipelines kiezen we voor **Argo Workflows**. Dit is de Kubernetes-native workflow engine waarmee je processen definieert als een reeks stappen (DAG - Directed Acyclic Graph).

### 💡 Onderbouwing van de Keuze
Waarom is dit ideaal voor een "door AI gegenereerde" workflow?

1.  **Declaratief (YAML)**: Een workflow is "gewoon" een Kubernetes resource (`kind: Workflow`). LLM's (zoals GPT-4) zijn uitstekend getraind in het genereren van gestructureerde YAML. De AI hoeft geen complexe, proprietary code te schrijven, maar alleen een logische lijst van stappen te definiëren.
2.  **Visueel**: Argo biedt een prachtige UI. De *Mens in de Loop* ziet precies het schema dat de AI heeft bedacht (A -> B -> C) en kan dit valideren.
3.  **Container Native**: Elke stap in de workflow is een container. Dit betekent dat we al onze bestaande bouwblokken (Python scripts, WebODM commando's, DVC acties) direct als stap kunnen hergebruiken. "Lijm code" is minimaal.
4.  **Schaalbaar**: In tegenstelling tot monolithische tools (zoals n8n of Airflow op één VM), draait elke stap als een Pod. Voor onze drone-data kunnen we dus duizenden stappen parallel draaien.

---

## 🛠️ Installatie

Argo Workflows staat los van ArgoCD en bijt elkaar niet.

### 1. Installatie via Helm
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argo-workflows argo/argo-workflows \
  --namespace workflow-system --create-namespace \
  --set server.serviceType=ClusterIP
```

### 2. (Optioneel) Argo Events
Om workflows te starten op basis van "Events" (bijv. een bestand in MinIO, een webhook, of een tijdstip):
```bash
helm upgrade --install argo-events argo/argo-events \
  --namespace workflow-system
```

---

## 🚀 Gebruik: AI-Driven Workflow Creatie

Het concept is: De gebruiker beschrijft het proces, de **Builder Agent** genereert de YAML.

### Scenario: "Verwerk Drone Foto's"
Gebruiker: *"Maak een flow die alle foto's uit de raw bucket haalt, ze verwerkt met WebODM, en mij een email stuurt als het klaar is."*

### De Generatie (door AI)
De Builder Agent genereert de volgende YAML (simpel weergegeven):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: drone-process-
spec:
  entrypoint: drone-dag
  templates:
  - name: drone-dag
    dag:
      tasks:
      # Stap 1: Check Data
      - name: fetch-data
        template: dvc-pull
        arguments:
          parameters: [{name: repo, value: "flight-2025"}]
      
      # Stap 2: Verwerking (Start pas als Stap 1 klaar is)
      - name: process-odm
        dependencies: [fetch-data]
        template: odm-stitch
        arguments:
          parameters: [{name: resolution, value: "high"}]
      
      # Stap 3: Notificatie
      - name: send-email
        dependencies: [process-odm]
        template: send-notification
        arguments:
          parameters: [{name: msg, value: "Verwerking gereed!"}]

  # Herbruikbare Templates (De "Bouwstenen")
  - name: dvc-pull
    container:
      image: my-registry/dvc-worker:latest
      command: [dvc, pull]
      # ...
```

### De Uitvoering
1.  **Submit**: De Agent (of Foundry) past deze YAML toe (`kubectl create -f flow.yaml`).
2.  **Visualisatie**: De gebruiker opent de Argo UI en ziet drie blokjes.
    *   `fetch-data` wordt groen ✅ (Klaar).
    *   `process-odm` wordt blauw 🔵 (Bezig).
3.  **Governance**: Omdat alles via Kubernetes loopt, geldt automatisch ons beveiligingsbeleid (Network Policies, IAM).

## 🔄 Integratie in Druppie
1.  **Business Logica**: Voor bedrijfsprocessen ("Nieuwe medewerker onboarden") werkt dit exact hetzelfde. De AI koppelt de `ad-create-user` en `email-send-welcome` stappen aan elkaar.
2.  **Samenwerking met Tekton**:
    *   **Tekton** gebruiken we voor CI/CD (het *bouwen* van de containers).
    *   **Argo Workflows** gebruiken we voor de *Processen* (het *uitvoeren* van de containers in een logische volgorde).
