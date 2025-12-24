# Ontwerpen Overview 

Dit is de centrale locatie voor functionele en technische ontwerpen van specifieke oplossingen en applicaties die met Druppie zijn gebouwd. Het ontwerp van het platform splitst zich in twee hoofdfases: de **Build Plane** (hoe we bouwen) en de **Runtime** (waar we draaien).

## 📂 Structuur

Hier worden ontwerpen opgeslagen die door de **Specificatie Experts** en **Architecten** zijn opgesteld.

*.  **Algemene Ontwerp**: Basis voor de druppie ontwerpen.
*   **AI Ontwerp (AI)**: Specificaties voor Agentic Workflows en LLM interacties.
*   **Architectuur Ontwerp (ARCH)**: High-level patronen en strategische keuzes.
*   **Technisch Ontwerp (TO)**: Hoe wordt het gebouwd? (Componenten, Data Model, API Specs)
*   **Functioneel Ontwerp (FO)**: Wat moet het systeem doen? (User Stories, Flowcharts)

## 🏭 Build Plane: De AI-Fabriek

De **Build Plane** is de "fabriek" die code en data transformeert naar draaiende software. In Druppie is dit proces **Spec-Driven**:
> Een AI-agent (de Builder Agent) voert taken uit op basis van strikte specificaties, niet op basis van ad-hoc commando's.

### Kernprincipes
1.  **Consistentie**: Code wordt altijd op dezelfde manier gebouwd, getest en gescand.
2.  **Traceerbaarheid**: Van elke build is bekend wie het startte, welke code erin zit (SBOM), en welke tests er zijn gedaan.
3.  **Security**: Vulnerability scans zijn verplichte "Gates". Code met kritieke gaten mag de runtime niet bereiken.

### Componenten
*   **[Builder Agent](./builder_agent.md)**: De AI-orkestrator van het bouwproces.
*   **[Foundry](./foundry.md)**: De ontwikkelomgeving en tooling stack.

## 🚀 Runtime: De Motor

De **Runtime** is waar de applicaties daadwerkelijk leven. Voor Druppie is dit een Kubernetes-omgeving geoptimaliseerd voor AI-workloads.

### Kernprincipes
*   **GitOps**: De staat van de runtime wordt bepaald door de configuratie in Git. Geen handmatige wijzigingen op de servers (zie [Git](./git.md)).
*   **Dynamic Slots**: AI-agents krijgen tijdelijke, geïsoleerde ruimtes om taken uit te voeren (zie [Dynamic Slot](./dynamic_slot.md)).
*   **Strict Access**: Toegang wordt geregeld via [RBAC](./rbac.md), zodat mensen en agents alleen bij data mogen die ze nodig hebben.

### Componenten
*   **[Runtime Implementation](./runtime_implementation.md)**: Details over de Kubernetes opzet.
*   **[MCP Interface](./mcp_interface.md)**: Hoe agents veilig externe tools aanroepen.

## 📝 Nieuw Ontwerp Toevoegen
1.  Maak een nieuwe map/markdown bestand voor jouw project in `design/`.
2.  Neem de standaard hoofdstukken op:
    *   Doelstelling
    *   Architecturele Keuzes (verwijzing naar Bouwblokken)
    *   Data Flow
    *   Security & Compliance

