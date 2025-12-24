---
id: git-gitea
name: Git & Versiebeheer (Gitea)
type: block
version: 1.0.0
auth_group: []
description: "beheren van de broncode (Source Code Management) en de infrastructuur-configuraties (GitOps) binnen het eigen cluster"
capabilities: ["git"]
---

# Git & Versiebeheer (Gitea)

## 🎯 Selectie: Gitea
Voor het beheren van de broncode (Source Code Management) en de infrastructuur-configuraties (GitOps) binnen het eigen cluster kiezen we voor **Gitea**.

### 💡 Onderbouwing van de Keuze
Hoewel cloud-diensten (zoals GitHub/GitLab.com) populair zijn, vereist de strikte compliance en autonomie van een waterschap vaak dat data (inclusief code en configs) in eigen beheer blijft.
1.  **Self-Hosted & Soeverein**: Gitea draait volledig binnen de eigen Kubernetes omgeving. Code verlaat nooit de veilige muren van het cluster/VNet.
2.  **Extreem Lichtgewicht**: In tegenstelling tot GitLab (dat veel resources vreet), is Gitea geschreven in Go en draait het soepel op minimale resources. Dit past perfect in de modulaire "Micro-services" gedachte van Druppie.
3.  **Feature Compleet**: Biedt alle essentiële functies: Git repository hosting, Issue tracking, Pull Requests, en Webhooks (voor Tekton/Flux triggers).
4.  **Kubernetes Ready**: Eenvoudig te installeren en schalen via Helm.

---

## 🛠️ Installatie

We installeren Gitea via de officiële Helm chart.

### 1. Voeg Helm Repo toe
```bash
helm repo add gitea-charts https://dl.gitea.io/charts/
helm repo update
```

### 2. Installeer Gitea
We configureren Gitea om de interne PostgreSQL database (zie Database bouwblok) te gebruiken voor opslag.

```bash
helm upgrade --install gitea gitea-charts/gitea \
  --namespace git-system --create-namespace \
  --set gitea.admin.username=druppie_admin \
  --set gitea.admin.password=SUPER_SECRET_PASSWORD \
  --set persistence.size=10Gi \
  --set postgresql.enabled=false \
  --set gitea.database.type=postgres \
  --set gitea.database.host=druppie-core-db-rw.default.svc.cluster.local \
  --set gitea.database.user=druppie \
  --set gitea.database.name=gitea
```

*(Opmerking: In productie gebruiken we een Secret voor het wachtwoord ipv plain text params)*

---

## 🚀 Gebruik

### 1. Repository Aanmaken (De "Project Kluis")
De **Builder Agent** maakt voor elk nieuw project (bijv. "Drone Service") een nieuwe repository aan.
Dit gebeurt via de Gitea API:

```http
POST /api/v1/user/repos
{
  "name": "drone-service",
  "private": true,
  "description": "Service voor het verwerken van drone beelden"
}
```

### 2. Access Tokens (De "Sleutel")
Om **Tekton** (CI) en **Flux** (CD) toegang te geven, genereren we een Access Token.
*   **Tekton** heeft schrijf-rechten nodig (om image tags te updaten in `deployment.yaml`).
*   **Flux** heeft lees-rechten nodig (om de cluster state op te halen).

### 3. Webhooks (De "Trigger")
Zodra er code gepusht wordt, vuurt Gitea een webhook af naar de **Tekton EventListener**:
`POST http://el-tekton-listener.tekton-pipelines:8080`
Dit start automatisch de bouw-straat.

## 🔄 Integratie in Druppie
1.  **Opslag (Single Source of Truth)**: Alle code die de *Builder Agent* genereert, wordt hier opgeslagen.
2.  **Versiebeheer**: Elke wijziging is een Git commit. Dit vormt de wettelijk verplichte **Audit Trail**. We kunnen altijd terugkijken: "Wie heeft deze regel code veranderd en wanneer?".
3.  **GitOps Bron**: Gitea is de bron voor **Flux**. Als Gitea uitvalt, draait de productie gewoon door, maar kunnen er tijdelijk geen updates worden uitgerold.
