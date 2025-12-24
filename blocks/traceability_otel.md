---
id: traceability-otel
type: block
name: Traceability & Audit (Tempo & OpenTelemetry)
version: 1.0.0
auth_group: ["developers"]
description: "Volledige Traceability (herleidbaarheid) van elke actie binnen het Druppie platform"
capabilities: []
---

# Traceability & Audit (Tempo & OpenTelemetry)

## 🎯 Selectie: Grafana Tempo & OpenTelemetry
Om volledige **Traceability** (herleidbaarheid) van elke actie binnen het Druppie platform te garanderen, kiezen we voor de combinatie **OpenTelemetry (OTEL)** als standaard voor data-verzameling en **Grafana Tempo** als backend voor de opslag van traces.

### 💡 Onderbouwing van de Keuze
Deze combinatie maakt de "Black Box" transparant:

1.  **De Standaard (OpenTelemetry)**: OTEL is de wereldwijde standaard voor het verzamelen van telemetry data. Door deze standaard te omarmen, voorkomen we "vendor lock-in". Elke component (Agent, API, DB) instrumenteren we met de OTEL SDK.
2.  **Correlatie (The "Trace ID")**: De kracht zit in de `TraceID`. Wanneer een gebruiker een vraag stelt, wordt één uniek ID gegenereerd die meereist door het hele systeem:
    *   Gebruiker vraagt iets -> `TraceID: abc-123`
    *   Router Agent kiest tool -> Logt met `TraceID: abc-123`
    *   Postgres DB draait query -> Logt met `TraceID: abc-123`
    *   Tempo stelt ons in staat om deze hele keten als één tijdlijn te visualiseren.
3.  **Integratie met bestaande Stack**: Tempo integreert naadloos met **Grafana** (Dashboard) en **Loki** (Logs) die we al geselecteerd hebben. Je kunt in Grafana klikken op een logregel en direct de hele trace zien.
4.  **High Volume, Low Cost**: Tempo is ontworpen om extreem goedkoop enorme hoeveelheden traces op te slaan in Object Storage (S3/MinIO), in tegenstelling tot dure index-based oplossingen.

---

## 🛠️ Installatie

We voegen Tempo toe aan onze monitoring namespace.

### 1. Tempo Installeren
Via Helm:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm upgrade --install tempo grafana/tempo \
  --namespace monitoring \
  --set persistence.enabled=true \
  --set persistence.size=10Gi
```

### 2. OTEL Collector
De collector fungeert als "makelaar". Applicaties sturen data naar de collector, en de collector stuurt het door naar Tempo (Traces) en Loki (Logs).

```bash
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  --namespace monitoring
```

---

## 🚀 Gebruik

Het gebruik vergt een kleine aanpassing in de applicatie-code (de Agents), wat we faciliteren via de *Builder Agent*.

### 1. Instrumentatie (Code)
Elke Python/NodeJS agent krijgt standaard de OTEL-library mee.
*Voorbeeld (Python Agent):*

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def handle_user_question(question):
    # Start een 'Span' (een blokje in de tijdlijn)
    with tracer.start_as_current_span("process_question") as span:
        span.set_attribute("user.id", "user_123")
        span.set_attribute("question.category", "waterbeheer")
        
        # Voer logica uit...
        result = planner.create_plan(question)
        
        # Log de beslissing als 'Event' in de trace
        span.add_event("Plan Created", attributes={"plan.steps": str(len(result.steps))})
        return result
```

### 2. Audit & Analyse (Grafana)
In Grafana kunnen we nu zoeken op `TraceID`.
We zien een tijdlijn (Gantt-chart) van exact wat er gebeurde:
*   `0ms`: Request binnen
*   `50ms`: Authenticatie Check (IAM)
*   `120ms`: Router Agent start
*   `400ms`: LLM Call (Azure OpenAI) - *Hier zien we exact hoe lang de LLM erover deed*
*   `1500ms`: Antwoord naar gebruiker

### 3. De "Audit Log" Link
Omdat we de `TraceID` ook wegschrijven in de **Loki** logs (bijv: `{"level":"info", "traceID":"abc-123", "msg":"Prompt verstuurd..."}`), kunnen we in één klik van het technische plaatje naar de inhoudelijke payload springen om te lezen **wat** er precies naar de LLM is gestuurd.

## 🔄 Integratie in Druppie
1.  **Compliance**: De `TraceID` wordt de sleutel voor de audit. Als een auditor vraagt "Wat gebeurde er bij incident X?", zoeken we de TraceID op en hebben we het volledige verhaal.
2.  **Performance**: We zien direct waar de vertraging zit (bijv. "De Database query duurde 2 seconden").
3.  **Traceability DB**: In de spec noemden we de "Traceability DB". In de praktijk is dit dus de combinatie van **Tempo** (Structuur/Tijdlijn) en **Loki** (Inhoud), ontsloten via **Grafana**.
