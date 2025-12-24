# Foundry

## 🎯 Doelstelling
**Microsoft Foundry** (voorheen Azure AI Studio) fungeert als de centrale "Agent Factory" en "Control Plane" voor het Druppie platform. Het consolideert de creatie, het beheer en de beveiliging van AI-agenten in één omgeving.

Waar de **Build Plane** het conceptuele domein is, is **Foundry** het concrete platform waarop dit domein draait.

## 📋 Functionele Specificaties

### 1. Spec-Driven Agent Creatie (Agent-as-Code)
- **Repo-based**: Agenten worden niet handmatig in een portal geklikt, maar gedefinieerd in code (YAML).
- **Automated Pipeline**: Een CI/CD proces (Agent Factory Pipeline) vertaalt deze YAML-definities naar API-calls naar de Azure AI Agent Service.
- **Validatie**: De pipeline valideert specs tegen beleidsregels (bijv. "Mag deze afdeling GPT-4o gebruiken?").

### 2. Agent Management & Runtime
- **Hosting**: Faciliteert de runtime omgeving voor agenten via de **Azure AI Agent Service**.
- **Model Hub**: Biedt centrale toegang tot modellen (OpenAI, Phi, Llama) via een eenduidige API.
- **Tooling**: Beheert de integratie met tools via OpenAPI definities en Python functies.

### 3. Evaluatie & Monitoring
- **Evaluation Flows**: Automatisch testen van agent-responses tegen ground-truth datasets om kwaliteit/hallucinaties te meten.
- **Tracing**: Volledige traceerbaarheid van elke stap (Prompt -> LLM -> Tool -> Response) via integratie met Azure Monitor/Purview.

## 🔧 Technische Requirements

- **API-First**: Alle interactie met Foundry verloopt via de `Foundry SDK` of REST API voor automatisering.
- **Private Networking**: Foundry resources (Hubs, Projects) zijn verbonden via Private Endpoints en afgeschermd van het publieke internet.
- **Identity**: Diepe integratie met Entra ID voor RBAC op project- en agent-niveau.

## 🔒 Security & Compliance

- **Data Exfiltration Protection**: Policy-regels voorkomen dat data naar niet-goedgekeurde URL's wordt gestuurd.
- **Model Safety**: Standaard content filters (Hate, Self-harm, Violence) zijn actief op alle endpoints.

## 🔌 Interacties (Factory Process)

| Stap | Actie | Component |
| :--- | :--- | :--- |
| **Commit** | Dev pusht `agent.yaml` | Git |
| **Validate** | Pipeline checkt beleid | Build Agent |
| **Deploy** | Pipeline roept API aan | Foundry API |
| **Register** | Agent ID opgeslagen | Agent Registry |

## 🏗️ Relaties tot andere blokken
- **Host voor**: [Build Plane Domein](./overview.md).
- **Levert Runtime aan**: [Runtime Domein](../runtime/overview.md).
- **Beveiligd door**: [Compliance Layer](../compliance/overview.md).
