# Build Plane Interface

## 🎯 Doelstelling
Dit bouwblok definieert de **interface** naar de externe Build Plane. De Build Plane zelf is de "fabriek" die code produceert en verifieert (zie de gedetailleerde [Build Plane documentatie](../build_plane/overview.md)). Vanuit het perspectief van Druppie Core is dit bouwblok de abstractie die toegang geeft tot die fabriek.

## 📋 Functionele Specificaties

### 1. Job Submission
- **Spec-in, Artifact-out**: Accepteert een declaratieve `BuildSpec` als input.
- **Fire & Forget**: Start asynchrone build taken en geeft een Job ID terug.

### 2. Status Monitoring
- **Polling / Webhooks**: Mechanisme om de voortgang van de build (Compiling... Testing... Scanning...) terug te koppelen aan de Orchestrator en UI.
- **Log Streaming**: Live logs doorgeven bij failures.

### 3. Artifact Handover
- Zorgt dat geproduceerde images en packages geregistreerd worden en beschikbaar zijn voor de Runtime.

## 🏗️ Relaties
- **Verwijst naar**: [Build Plane Domein](../build_plane/overview.md).
- **Wordt gebruikt door**: [Druppie Core](./druppie_core.md) wanneer code gegenereerd of gebouwd moet worden.
