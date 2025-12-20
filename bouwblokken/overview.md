# Bouwblokken Overview

De **Bouwblokken** (Building Blocks) vormen de modulaire componenten waaruit de Druppie-architectuur is opgebouwd. Elk bouwblok vertegenwoordigt een specifieke functionaliteit of capability binnen het platform.

Dit overzicht beschrijft de definities en contracten van deze componenten.

## 🏛️ Core Components

Deze blokken vormen het hart van het systeem.

- **[Druppie Core (Orchestrator)](./druppie_core.md)**
  - Het centrale brein dat user intents vertaalt naar acties. Gebruikt een planner en semantic kernel.
- **[Druppie UI](./druppie_ui.md)**
  - De interface voor interactie (Chat/Copilot).
- **[Bouwblok Definities](./bouwblok_definities.md)**
  - De metadata-catalogus die beschrijft wat elk blok kan en hoe het aangeroepen wordt.

## 🛡️ Governance & Control

Blokken die toezicht en veiligheid garanderen.

- **[Policy Engine](./policy_engine.md)**
  - Evalueert elke geplande actie tegen bedrijfs- en veiligheidsregels.
- **[Mens in de Loop](./mens_in_de_loop.md)**
  - Het mechanisme voor menselijke goedkeuring bij risicovolle beslissingen.
- **[Traceability DB](./traceability_db.md)**
  - De "black box" die alle beslissingen, prompts en acties onveranderlijk vastlegt.
- **[Compliance Layer](./compliance_layer.md)**
  - De overkoepelende laag voor auditing en security monitoring.

## 🏭 Execution & Factory

De lagen waar het werk daadwerkelijk wordt uitgevoerd.

- **[Build Plane](./build_plane.md)**
  - De definitie van de "fabriek" die code omzet in artifacts (zie ook de diepere [Build Plane directory](../build_plane/)).
- **[Runtime](./runtime.md)**
  - De definitie van de landingsplaats (Kubernetes) voor applicaties (zie ook de diepere [Runtime directory](../runtime/)).

## 🤖 Specialised Agents

Gespecialiseerde workers.

- **[Knowledge Bot](./knowledge_bot.md)**
  - Een RAG-enabled agent die informatie uit documentatie kan ontsluiten.
