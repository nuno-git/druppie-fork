# CI/CD Pipeline (Tekton)

## 🎯 Selectie: Tekton Pipelines
Voor de CI/CD oplossing binnen het Druppie platform is gekozen voor **Tekton**. Tekton is een krachtig en flexibel, Kubernetes-native open-source raamwerk voor het maken van CI/CD systemen.

### 💡 Onderbouwing van de Keuze
De keuze voor Tekton is gebaseerd op de volgende criteria die naadloos aansluiten bij de architectuur van Druppie:

1.  **Kubernetes Native**: Tekton draait volledig binnen Kubernetes en gebruikt Custom Resource Definitions (CRD's) zoals `Task` en `Pipeline`. Dit betekent dat pipelines beheerd kunnen worden via dezelfde tools als de applicatie zelf (`kubectl`, GitOps) en perfect passen in het "Spec-Driven" concept.
2.  **Modulair (Bouwblokken)**: Tekton werkt met herbruikbare "Tasks". Dit sluit perfect aan op de bouwblokken-filosofie van Druppie. Een taak om een container te bouwen (bijv. met Kaniko) kan in meerdere pipelines hergebruikt worden.
3.  **Serverless Scaling**: In tegenstelling tot traditionele servers (zoals Jenkins), draait elke pipeline stap als een Pod. Dit schaalt naar 0 als er niets gebeurt en schaalt oneindig op bij drukte, wat efficiënt is voor de infrastructuur.
4.  **Ontkoppeling**: De pipeline definities staan los van de broncode repo's (hoewel ze erin kunnen wonen), wat flexibele orchestratie mogelijk maakt door de *Builder Agent* van Druppie.
5.  **Industry Standard**: Tekton is een project van de CD Foundation, wat zorgt voor brede ondersteuning en toekomstbestendigheid.

---

## 🛠️ Installatie

Tekton installeer je direct op het Kubernetes cluster.

### 1. Tekton Pipelines Controller & Webhook
Installeer de core componenten:

```bash
kubectl apply --filename https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml
```

Controleer of de pods draaien:
```bash
kubectl get pods -n tekton-pipelines
```

### 2. (Optioneel) Tekton Dashboard
Voor een visueel overzicht van de builds:

```bash
kubectl apply --filename https://storage.googleapis.com/tekton-releases/dashboard/latest/release.yaml
```

### 3. (Optioneel) Tekton CLI (tkn)
Installeer `tkn` lokaal om interactief pipelines te beheren (voorbeeld voor macOS):
```bash
brew install tektoncd-cli
```

---

## 🚀 Gebruik

Het gebruik van Tekton bestaat uit drie lagen:

### 1. Task (De "Wat")
Een `Task` definieert een reeks stappen die in volgorde worden uitgevoerd in dezelfde container (Pod).

*Voorbeeld: Een 'Hello World' taak*
```yaml
apiVersion: tekton.dev/v1beta1
kind: Task
metadata:
  name: hello
spec:
  steps:
    - name: say-hello
      image: alpine
      command: ["echo"]
      args: ["Hallo vanuit Druppie CI/CD!"]
```

### 2. Pipeline (De "Hoe")
Een `Pipeline` koppelt meerdere Tasks aan elkaar en bepaalt de volgorde en data-uitwisseling.

*Voorbeeld: Een simpele pipeline*
```yaml
apiVersion: tekton.dev/v1beta1
kind: Pipeline
metadata:
  name: hello-pipeline
spec:
  tasks:
    - name: hello-task
      taskRef:
        name: hello
```

### 3. PipelineRun (De "Wanneer")
Om een pipeline daadwerkelijk te starten, maak je een `PipelineRun` (of `TaskRun`) aan. Dit is de daadwerkelijke uitvoering.

```bash
tkn pipeline start hello-pipeline --showlog
```
Of via YAML:
```yaml
apiVersion: tekton.dev/v1beta1
kind: PipelineRun
metadata:
  generateName: hello-run-
spec:
  pipelineRef:
    name: hello-pipeline
```

## 🔄 Integratie in Druppie
Binnen de Druppie architectuur wordt Tekton aangestuurd door de **Builder Agent** en **Foundry**:
1.  **Builder Agent** genereert de code en een bijbehorende `PipelineRun` specificatie.
2.  De **Foundry** component past deze YAML toe op het Kubernetes cluster.
3.  Tekton voert de bouwstappen uit (Linting, Testen, Container Build, Security Scan).
4.  Resultaten worden teruggekoppeld naar de Traceability DB.
