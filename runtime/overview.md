# Runtime Overview

De Runtime is de "motor" van het Druppie platform. Hier draaien de AI agents, de microservices, de databases en de data-pipelines.

## 🏗️ De Infrastructuur

### [Kubernetes (RKE2)](../bouwblokken/runtime.md)
De fundering. Een gehard, secure Kubernetes cluster dat voldoet aan overheidsstandaarden.

### [Policy Enforcement (Kyverno)](./policy_kyverno.md)
De "douanier". Zorgt ervoor dat alles wat op het cluster draait voldoet aan de veiligheids- en compliance-eisen. Automatische validatie, mutatie en rapportage.

## 📦 Workloads
Op deze runtime draaien de volgende type applicaties, gedefinieerd als **Bouwblokken**:
*   AI Models & Agents
*   GIS Applicaties (GeoServer, QGIS)
*   Data Pipelines (Argo)
*   Web Apps (React frontends)
