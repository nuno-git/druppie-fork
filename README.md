# Druppie – Spec-Driven AI Architectuur

Druppie is een geavanceerd architectuur-platform voor **Spec-Driven AI** en **Human-in-the-Loop** automatisering. Dit project beschrijft hoe AI-agents, compliance-regels en menselijke interactie samenkomen om software veilig, schaalbaar en consistent te bouwen en te beheren. Waarbij de focus ligt op het ontwikkelen van **compliance** en **security** oplossingen. De tools en technieken die gebruikt worden zijn geselecteerd op basis van hun **security** en **compliance** compliance en **ease of use** tijdens de onderzoeksfase waarin dit project zich bevindt.

De architectuur is ontworpen om volledig **declaratief** te zijn: in plaats van imperatieve scripts, definiëren we **specificaties** (specs) die door AI-agents worden geïnterpreteerd en uitgevoerd.

## 🚀 Aan de slag

De volledige architectuur is interactief te verkennen.

1. Open **`index.html`** in je browser.
2. Gebruik het dashboard om door de verschillende lagen (Bouwblokken, Skills, Runtime) te navigeren.
3. Draai simulaties (Scenarios) om de interactie tussen componenten te visualiseren.

## 📂 Projectstructuur

De repository is opgebouwd uit verschillende functionele domeinen:

### 🧱 [Bouwblokken](./bouwblokken/)
De fundamentele componenten van het systeem. Hier vind je definities voor onder andere:
- **Druppie Core (Orchestrator)**: Het brein dat taken plant en verdeelt.
- **Policy Engine**: Bewaakt regels en compliance.
- **Mens in de Loop**: Interfaces voor goedkeuring en menselijke controle.
- **Traceability DB**: Audit logging voor volledige traceerbaarheid.

### 🏗️ [Build Plane](./build_plane/)
De "fabriek" van het platform. De Build Plane is verantwoordelijk voor het omzetten van specificaties naar werkende software artifacts.
- **Spec-driven**: Bouwen op basis van definities, niet scripts.
- **Builder Agent**: AI die code en infrastructuur genereert.
- **Foundry**: De veilige omgeving voor compilatie, tests en security scans.

### ⚙️ [Runtime](./runtime/)
De uitvoeromgeving waar applicaties en agents draaien.
- **Kubernetes**: De basislaag voor orchestratie.
- **RBAC & Security**: Toegangsbeheer en netwerkpolicies.
- **MCP Interface**: Standaard protocol voor tool-gebruik door AI.

### ⚡ [Skills](./skills/)
De cognitieve en functionele vaardigheden waarover de agents beschikken.
- **Research**: Analyseren en plannen.
- **Build & Test**: Genereren en valideren van code.
- **Deploy**: Uitrollen naar de runtime omgeving.

### 🛡️ [Compliance](./compliance/)
Governance en beveiliging staan centraal.
- **IAM**: Identiteit en toegangsbeheer.
- **Auditing**: Continue monitoring en rapportage.

## 💡 Kernprincipes

1.  **Alles is een Spec**: Van infrastructuur tot agent-gedrag, alles wordt vastgelegd in leesbare specificaties.
2.  **Human-in-the-Loop**: Kritieke beslissingen vereisen altijd menselijke goedkeuring.
3.  **Secure by Design**: Compliance en security policies zijn ingebakken in elke stap van het proces.
4.  **Traceerbaarheid**: Elke actie, van prompt tot deployment, wordt gelogd en is auditeerbaar.

---
*Open `index.html` voor de interactieve visualisatie.*
