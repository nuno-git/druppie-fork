# Bouwblok Definities (Registry)

## 🎯 Doelstelling
De **Bouwblok Definities** vormen de catalogus en metadata-laag van het platform. Om de AI (Druppie Core) in staat te stellen zichzelf samen te stellen en de juiste tools te kiezen, moet er een gestructureerde definitie zijn van alle beschikbare capabilities, skills, en services. Dit is de "telefoongids" en "handleiding" voor de AI.

## 📋 Functionele Specificaties

### 1. Spec-Driven Agent Creatie (Agent-as-Code)
- **Declaratieve Definities**: Capabilities en Agents worden gedefinieerd in **YAML/JSON** schema's (zie research).
- **Inhoud Definitie**: Bevat Model config, Instructies (Prompts), Tools (OpenAPI) en Governance metadata (Owner, Cost Center).
- **Versiebeheer**: Alle definities worden opgeslagen in Git voor auditability en rollback mogelijkheden.

### 2. Agent Registry
- **Central Repository**: Een database (Cosmos DB) die fungeert als "Telefoonboek" voor de Router Agent.
- **Interface Beschrijving**: Bevat technische specs (OpenAPI) zodat de Router weet hoe een Spoke aan te roepen is.

## 🔧 Technische Requirements

- **Standaard Formaat**: Gebruikt open standaarden zoals OpenAPI (Swagger) of Model Context Protocol (MCP) definities.
- **Extensible**: Nieuwe definities moeten makkelijk toegevoegd kunnen worden zonder herstart van de Core (Plugin architectuur).

## 🔒 Security & Compliance

- **Scoped Access**: Definities bevatten metadata over vereiste permissies (scopes), zodat de Orchestrator vooraf checks kan doen.

## 🔌 Interacties

| Wie | Actie | Doel |
| :--- | :--- | :--- |
| **Druppie Core Planner** | Query Registry | "Welke tool kan e-mails sturen?" |
| **Developer** | Register Tool | Nieuwe capability toevoegen |

## 🏗️ Relaties tot andere blokken
- **Geraadpleegd door**: [Druppie Core](./druppie_core.md).
- **Bevat definities voor**: [Build Plane](./build_plane.md), [Runtime](./runtime.md) en alle [Skills](../skills/overview.md).
