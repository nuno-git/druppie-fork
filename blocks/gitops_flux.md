---
id: gitops-flux
name: GitOps & State Management (Flux)
type: block
version: 1.0.0
auth_group: ["provisioning","developer"]
description: "GitOps & State Management (Flux)"
capabilities: ["gitops"]
---

# GitOps & State Management (Flux)

## 🎯 Selectie: Flux CD
Omdat Tekton de *processen* (CI/bouw) afhandelt, zoeken we een component die de *gewenste staat* (CD/deployment) op het cluster handhaaft en bewaakt. **Flux** is hier de ideale partner voor.

### 💡 Waarom past dit bij Tekton?
Waar ArgoCD soms werd gezien als een volledige suite die (deels) overlapt met pipeline-taken, is Flux een pure, lichtgewicht **GitOps operator**.
1.  **Complementair**: Tekton is een "Task Runner" (Imperatief: "Doe dit nu"), Flux is een "State Enforcer" (Declaratief: "Zorg dat het zo is"). Ze zitten elkaar niet in de weg.
2.  **Kubernetes Native (net als Tekton)**: Flux gebruikt - net als Tekton - standaard Custom Resource Definitions (CRD's) en integreert naadloos in het cluster zonder zware eigen UI of database.
3.  **De "Push-to-Pull" Workflow**:
    *   **Tekton (CI)**: Bouwt de image, test deze, en *push*t een update naar de Git configuratie repo (bijv. update image tag).
    *   **Flux (CD)**: Ziet de wijziging in Git en *pull*t deze naar het cluster.
4.  **Automatic Drift Correction**: Flux controleert continu of de live omgeving nog klopt met Git. Als iemand handmatig iets kapot maakt, repareert Flux het direct.

---

## 🛠️ Installatie

Flux "bootstrappen" we op het cluster. Dit commando installeert de controllers én configureert direct een Git repository om zichzelf te beheren (GitOps voor de GitOps tool).

### 1. Flux Bootstrap
(Vereist een Github Personal Access Token met repo rechten)

```bash
flux bootstrap github \
  --owner=$GITHUB_USER \
  --repository=druppie-infra \
  --branch=main \
  --path=./clusters/productie \
  --personal
```
Dit installeert de `Source Controller`, `Kustomize Controller`, `Helm Controller` en `Notification Controller`.

### 2. Controle
```bash
kubectl get pods -n flux-system
```

---

## 🚀 Gebruik

We definiëren twee dingen: *Waar* staat de config (Source) en *Hoe* passen we het toe (Kustomization/Helm).

### 1. Source (GitRepository)
Vertel Flux waar de applicatie configuraties staan.

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: druppie-apps
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/waterschap/druppie-apps
  ref:
    branch: main
```

### 2. Kustomization (Sync)
Vertel Flux welke map in die repo hij op het cluster moet toepassen.

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: drone-service-prod
  namespace: flux-system
spec:
  interval: 5m
  targetNamespace: productie
  sourceRef:
    kind: GitRepository
    name: druppie-apps
  path: "./envs/prod/drone-service"
  prune: true     # Verwijder resources die uit Git zijn gehaald
  wait: true      # Wacht tot alles 'Healthy' is
```

## 🔄 Integratie in Druppie
De samenwerking tussen de **Builder Agent**, **Tekton** en **Flux** is de kern van het platform:

1.  **Code Change**: Developer (of Agent) commit code.
2.  **Tekton (CI)**:
    *   Triggered door de commit.
    *   Draait unit tests & security scans.
    *   Bouwt Docker image.
    *   ⚠️ **Cruciale stap**: Tekton commit de nieuwe image tag (bijv. `v1.0.5`) naar de `druppie-apps` Git repo (INFRA repo).
3.  **Flux (CD)**:
    *   Detecteert de nieuwe commit in `druppie-apps`.
    *   Reconciled de state: "Hee, de deployment moet nu image `v1.0.5` draaien".
    *   Update de Pods op het Kubernetes cluster.
