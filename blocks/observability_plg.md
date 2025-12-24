---
id: observability-plg
name: Observability Stack (PLG)
type: block
description: "Promtail, Loki, and Grafana stack for log aggregation and visualization."
capabilities: ["logging", "visualization", "monitoring"]
version: 1.0.0
auth_group: []
---
# Observability & Logging (PLG Stack)

## 🎯 Selectie: Prometheus, Loki & Grafana
Voor het monitoren van de gezondheid, performance en het doorzoekbaar maken van logs kiezen we voor de **PLG Stack** (Prometheus, Loki, Grafana). Dit is de industriestandaard voor open-source cloud-native observability.

### 💡 Onderbouwing van de Keuze
Deze stack is cruciaal voor de "Traceerbaarheid" en "Beheersbaarheid" van het Druppie platform:

1.  **Prometheus (Metrics)**: Verzamelt cijfermatige data (CPU, Memory, Request Count). Kubernetes is gemodelleerd om metrics in Prometheus formaat aan te bieden. Het stelt ons in staat om te *alerten* als er iets mis is (bijv. "Error rate > 5%").
2.  **Loki (Logs)**: Een log-aggregatie systeem dat is ontworpen als "Prometheus voor logs". Het is extreem efficiënt omdat het logs niet volledig indexeert, maar alleen metadata (labels). Dit maakt het mogelijk om *alle* logs (audit trails!) goedkoop te bewaren en razendsnel te doorzoeken.
3.  **Grafana (Visualisatie)**: Het centrale dashboard. Hier komen metrics (Prometheus) en logs (Loki) samen in één overzichtelijk scherm.
4.  **Correlatie**: Omdat alles in hetzelfde dashboard zit, kun je direct springen van een "High CPU Alert" in Prometheus naar de exacte "Error Logs" in Loki van dat moment.

---

## 🛠️ Installatie

We installeren de volledige stack via de officiële Helm charts (vaak gebundeld als de `kube-prometheus-stack` en `loki-stack`).

### 1. Prometheus & Grafana
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

### 2. Loki (Logging)
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm upgrade --install logging grafana/loki-stack \
  --namespace monitoring \
  --set grafana.enabled=false # We gebruiken de grafana uit stap 1
```

---

## 🚀 Gebruik

Deze componenten werken grotendeels automatisch ("Zero Config" voor de ontwikkelaar).

### 1. Metrics (Automatisch)
De cluster-metrics (Nodes, Pods) worden direct opgehaald.
Voor applicatie-specifieke metrics hoeft de **Builder Agent** alleen een `ServiceMonitor` toe te voegen of de standaard annotaties te gebruiken:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mijn-app
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
spec:
  ports:
  - port: 8080
    targetPort: 8080
```

### 2. Logs (Automatisch)
Alles wat een applicatie naar `stdout` (console) schrijft, wordt door Promtail (onderdeel van Loki) opgepakt, gelabeld met de Pod-naam en naar Loki gestuurd.
De ontwikkelaar hoeft **geen** log-files te beheren of log-shippers te configureren.

### 3. Traceability Dashboard
In Grafana kan een "Compliance Dashboard" worden ingericht dat queries doet op Loki:
```bash
{namespace="productie"} |= "UserLogin"
```
Dit toont direct een audit trail van wie wanneer heeft ingelogd.

## 🔄 Integratie in Druppie
1.  **Compliance Layer**: De *Compliance* component kan alerts instellen in AlertManager (onderdeel van Prometheus). Bijvoorbeeld: "Waarschuw de CISO als er een root-shell wordt geopend".
2.  **Mens in de Loop**: Beheerders kijken in Grafana om de impact van een nieuwe release te valideren.
3.  **Traceerbaarheid**: Alle logs worden centraal bewaard, wat essentieel is voor de uitlegbaarheid van AI-beslissingen (waarom gaf de bot dit antwoord? -> Check de logs).
