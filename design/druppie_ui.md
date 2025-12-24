
# Druppie UI

## 🎯 Doelstelling
De **Druppie UI** is het gezicht van het platform. Het biedt een intuïtieve, chat-gebaseerde interface (Copilot) waarmee gebruikers op natuurlijke wijze interactie hebben met de complexe agent-architectuur. Het doel is om de complexiteit van de backend te abstraheren en de gebruiker in controle te houden ("Human in the Loop").

## 📋 Functionele Specificaties

### 1. Conversational Interface & Integratie
- **Microsoft 365 Copilot**: De primaire interface voor medewerkers, geïntegreerd in Teams, Outlook en Word via **Declarative Agents**.
- **Druppie Custom UI**: Een fallback/admin chat interface voor geavanceerde taken.
- **Streaming Response**: Ondersteuning voor real-time text streaming.
- **Rich Media**: Adaptieve kaarten en deep links naar specifieke applicaties.

### 2. Interactieve Elementen
- **Slash Commands**: Ondersteunt commando's (bijv. `/reset`, `/help`, `/new-project`) voor directe sturing.
- **Adaptive Cards**: Toont gestructureerde formulieren voor input (bijv. bij requirements intake).
- **Status Indicatoren**: Geeft duidelijk aan wat het systeem aan het doen is ("Thinking...", "Building...", "Waiting for Approval").

### 3. Human Approval Interface
- **Notifications**: Toont alerts wanneer de gebruiker actie moet ondernemen (goedkeuring geven).
- **Decision Context**: Biedt alle noodzakelijke informatie om een goedkeuring te kunnen doen (diffs, risico-analyse).

## 🔧 Technische Requirements

- **Proxy Pattern**: Gebruik van **Azure Functions** als brug tussen M365 Copilot en de Azure AI Agent Service.
- **Protocol Translatie**: Mappen van M365 conversationIds naar Azure Agent Thread IDs.
- **Security**: Validatie van M365 tokens en gebruik van Managed Identity voor backend communicatie.
- **Responsive Design**: Custom UI moet responsive zijn.

## 🔒 Security & Compliance

- **Auth Integration**: Integreert naadloos met IAM (SSO).
- **Input Sanitization**: Client-side filtering om XSS en injecties te voorkomen.
- **Privacy Mode**: Visuele indicatie wanneer gevoelige data wordt verwerkt.

## 🔌 Interacties

| Actie | Richting | Omschrijving |
| :--- | :--- | :--- |
| **User Prompt** | UI -> Core | Gebruiker stuurt vraag of commando. |
| **Stream Chunk** | Core -> UI | Real-time tekst updates van de AI. |
| **Approval Request** | Policy -> UI | Pop-up voor menselijke goedkeuring. |

## 🏗️ Relaties tot andere blokken
- **Authenticeert via**: [IAM](../compliance/iam.md).
- **Stuurt aan**: [Druppie Core](./druppie_core.md).
- **Toont requests van**: [Mens in de Loop](./../design/mens_in_de_loop.md).