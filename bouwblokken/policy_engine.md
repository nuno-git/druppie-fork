# Policy Engine

## 🎯 Doelstelling
De **Policy Engine** is de bewaker van de integriteit, veiligheid en compliance van het platform. Dit blok zorgt ervoor dat geen enkele geautomatiseerde actie in strijd is met bedrijfsregels, wetgeving of ethische kaders. Het is de "nee, tenzij"-laag die elk plan van de Orchestrator valideert.

## 📋 Functionele Specificaties

### 1. Actie Validatie (Pre-Execution Guardrails)
- **Real-time Controle**: Elke actie of tool-aanroep die de Orchestrator wil doen, moet eerst langs de Policy Engine.
- **Contextuele Regels**: Regels kunnen afhangen van context (bijv. "Geen productie-deployments op vrijdagmiddag", "Alleen Seniors mogen databases droppen").

### 2. Risico Classificatie
- **Risk Scoring**: Kent een risicoscore toe aan een actie (Low, Medium, High, Critical).
- **Threshold Management**: Bepaalt op basis van score of een actie mag doorgaan, geblokkeerd wordt, of menselijke goedkeuring vereist.

### 3. Policy-as-Code
- **Declaratieve Regels**: Policies worden gedefinieerd in code (bijv. OPA/Rego) en niet in ondoorzichtige logica.
- **Versiebeheer**: Wijzigingen in policies volgen een strikt change proces via Git.

## 🔧 Technische Requirements

- **Performance**: Validatie moet extreem snel zijn (< 50ms) om de gebruikerservaring niet te vertragen.
- **Fail-Closed**: Als de Policy Engine niet bereikbaar is of faalt, moeten alle risicovolle acties worden geblokkeerd.
- **Hot Reload**: Nieuwe regels moeten geladen kunnen worden zonder downtime.

## 🔒 Security & Compliance

- **Immutability**: Regels mogen niet tijdens runtime door de AI zelf aangepast kunnen worden.
- **Audit Trail**: Elke Allow/Deny beslissing moet cryptografisch ondertekend en opgeslagen worden in de Traceability DB.

## 🔌 Interacties

| Input | Bron | Verwerking | Output |
| :--- | :--- | :--- | :--- |
| **Proposed Plan** | Orchestrator | Evalueer tegen regelset | `ALLOW`, `DENY`, of `REQUIRE_APPROVAL` |
| **Policy Update** | Git CI/CD | Laad nieuwe ruleset | Bevestiging activatie |

## 🏗️ Relaties tot andere blokken
- **Blokkeert/Stuurt**: [Druppie Core](./druppie_core.md)
- **Initieert**: [Mens in de Loop](./mens_in_de_loop.md) (bij `REQUIRE_APPROVAL` status).
- **Logt naar**: [Traceability DB](./traceability_db.md).
