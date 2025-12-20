# Druppie Core (Orchestrator)

## 🎯 Doelstelling
De **Druppie Core** fungeert als het centrale zenuwstelsel van het platform. Het is verantwoordelijk voor het interpreteren van gebruikersvragen (intents), het plannen van complexe takenreeksen, en het orkestreren van gespecialiseerde agents en tools om tot een antwoord of oplossing te komen.

Een kerntaak van de Core is het beheren van **Multi-Agent samenwerking** om grote problemen automatisch op te delen in bestaande of nieuwe oplossingen.

## 📋 Functionele Specificaties

### 1. Intent Recognition & Routing (The Hub)
- **Hub-and-Spoke Model**: De Core fungeert als de centrale **Router Agent** (Hub) die verzoeken ontvangt en distribueert naar gespecialiseerde agents (Spokes).
- **Context Awareness**: Analyseert de vraag en context om de juiste specialist uit het register te kiezen.
- **Dispatcher Pattern**: Gebruikt mechanismen zoals "Connected Agents" om taken te delegeren zonder de controle te verliezen.

### 2. Multi-Agent Planning & Decompositie
- **Problem Decomposition**: De Router breekt complexe vragen op in sub-taken.
- **Agent Swarm Management**: Coördineert de samenwerking tussen verschillende domein-experts (bijv. Finance, IT, HR).
- **Consensus & Review**: Organiseert waar nodig peer-reviews tussen agents.

### 3. Capability Gap Analysis & Creatie
Voordat de Core een taak uitvoert, checkt hij de [Bouwblok Definities](./bouwblok_definities.md):
1.  **Check**: Bestaat er al een bouwblok dat dit sub-probleem oplost?
    *   *Ja:* Gebruik het bestaande blok (hergebruik).
    *   *Nee:* **Initieer Creatie Flow**.
2.  **New Project Scaffolding**: De Core stelt voor om een nieuw bouwblok te maken.
3.  **Specification Refinement**: De Core gaat interactief met de gebruiker in gesprek om de specificaties voor dit *nieuwe* blok uit te werken (samen met de Business Analyst Agent).

### 4. Tool Gebruik (Capability Invocation)
- Moet via gestandaardiseerde interfaces (MCP) tools kunnen aanroepen.
- Moet parameters correct extraheren uit de gebruikersvraag om tools mee aan te sturen.

## 🔧 Technische Requirements

- **Platform**: Gebaseerd op **Microsoft Foundry** (voorheen Azure AI Studio) als centraal beheersplatform.
- **Runtime**: Maakt gebruik van de **Azure AI Agent Service** voor stateful execution en thread management.
- **Model Agnostic**: Gebruik van Semantic Kernel of LangChain als abstractielaag om flexibel tussen modellen (GPT-4o, etc.) te wisselen.
- **Latency**: Time-to-first-token < 500ms voor routing beslissingen.
- **State Prevention**: Threads en context worden beheerd door de Agent Service (Azure storage).

## 🔒 Security & Compliance

- **Safety Rails**: Alle user input moet door een safety filter (jailbreak detection, PII screening).
- **Least Privilege**: De Core mag alleen tools aanroepen waar de ingelogde gebruiker rechten toe heeft.
- **Audit Logging**: Elke planningsbeslissing, en met name de keuze om iets *nieuws* te bouwen, wordt gelogd.

## 🔌 Interacties

| Trigger | Bron | Actie | Output |
| :--- | :--- | :--- | :--- |
| **New Prompt** | Druppie UI | Analyseer intentie & start plan | Response stream |
| **Missing Capability** | Planner | Stel voor nieuw blok te bouwen | Interactieve specs dialoog |
| **Tool Response** | MCP / Agent | Verwerk resultaat & volgende stap | Volgende instructie |

## 🏗️ Relaties tot andere blokken
- **Raadpleegt**: [Bouwblok Definities](./bouwblok_definities.md) om te zien wat er al is.
- **Initieert**: [Builder Agent](../build_plane/builder_agent.md) als er een nieuw blok gebouwd moet worden.
- **Controleert**: [Policy Engine](./policy_engine.md) voor validatie van het plan.
