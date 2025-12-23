# 📊 Grafana - Observability Dashboard

## Wat is het?
Grafana is het centrale visualisatieplatform van de Observability stack. Het fungeert als de "single pane of glass" waarmee je de status, prestaties en fouten van het hele platform kunt inzien. Het maakt gebruik van de zogenaamde **LGTM** stack (Loki, Grafana, Tempo, Mimir/Prometheus).

## Geïntegreerde Tools & Mogelijkheden

### 📋 Prometheus (Metrics) - "Is het systeem gezond?"
Prometheus verzamelt cijfermatige data (metrics) zoals CPU-gebruik, geheugengebruik en het aantal requests per seconde.
- **Gebruik dit voor:** Het bouwen van dashboards die trends laten zien (bijv. "Loopt het geheugen vol?" of "Hoeveel bezoekers zijn er nu?").

### 🪵 Loki (Logging) - "Wat is er gebeurd?"
Loki is een log-aggregatiesysteem dat vaak wordt omschreven als "Prometheus voor logs". Het indexeert logs op basis van labels (zoals app naam of namespace) in plaats van de volledige tekst, wat het erg snel en efficiënt maakt.
- **Gebruik dit voor:** Het doorzoeken van logs van al je containers op één plek. Gebruik LogQL (Loki Query Language) om foutmeldingen te filteren, bijvoorbeeld: `{app="gitea"} |= "error"`.

### ⏱️ Tempo (Tracing) - "Waar zit de vertraging?"
Tempo is een distributed tracing backend. Het volgt een request terwijl het door verschillende services in je cluster reist.
- **Gebruik dit voor:** Performance optimalisatie en debugging. Als een pagina traag laadt, kun je met Tempo precies zien welke microservice of database query de vertraging veroorzaakt.

### 🤖 Alloy (Collector)
Alloy (voorheen Grafana Agent) draait op de achtergrond op je cluster. Het verzamelt automatisch alle logs, metrics en traces van je applicaties en stuurt deze naar bovenstaande tools.

## Inloggen
- **URL**: [https://grafana.localhost](https://grafana.localhost)
- **Gebruikersnaam**: `admin`
- **Wachtwoord**: Zie het `.secrets` bestand (`DRUPPIE_GRAFANA_PASS`)

## Hoe te gebruiken
1. **Dashboards**: Ga naar 'Dashboards' om kant-en-klare overzichten van je Kubernetes cluster te zien.
2. **Explore (Logs bekijken)**: 
   - Klik op het kompas-icoon (Explore).
   - Kies bovenaan **Loki** als source.
   - Selecteer bij 'Label filters' bijvoorbeeld `app` = `portal`.
   - Klik op "Run query" om live logs te zien.
3. **Explore (Traces bekijken)**:
   - Als je in de logs een `TraceID` ziet (vaak automatisch gedetecteerd door onze configuratie), klik erop om direct naar de Tempo trace te springen.
