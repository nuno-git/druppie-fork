# Identity & Access Management (IAM) voor AI

## 🎯 Doelstelling
In een AI-gedreven architectuur is **Identity & Access Management (IAM)** niet slechts een "poortwachter" voor gebruikers, maar een fundamenteel fundament voor veiligheid. Waar traditionele software deterministisch is, zijn AI-agents autonoom en onvoorspelbaar.

**Waarom is IAM cruciaal voor AI?**
1.  **Autonomie beperken**: Een AI-agent die zelfstandig taken uitvoert, moet een digitale identiteit hebben om afgerekend te kunnen worden op zijn daden ("Wie deed dit?").
2.  **Data Exfiltratie voorkomen**: Een agent mag nooit toegang hebben tot álle data. Door strikte scoping (RBAC) voorkomen we dat een agent gevoelige HR-data lekt aan een gebruiker die daar geen recht op heeft.
3.  **Chain of Trust**: In een keten van agents (Agent A roept Agent B aan) moet elke stap geauthenticeerd zijn (Zero Trust).

---

## 🔑 Kernconcepten in Druppie

Druppie maakt gebruik van **Microsoft Entra ID** (voorheen Azure AD) als centrale identity provider.

### 1. Entra Agent ID (Machine Identity)
Dit is een relatief nieuw concept. In plaats van generieke "Service Accounts" of "API Keys" die kunnen lekken, krijgt elke agent in Druppie (via de [Foundry](../build_plane/foundry.md) factory) een eigen **Entra Agent ID**.
*   **Cloud Native**: Geen wachtwoorden om te roteren (Managed Identity).
*   **Traceerbaar**: Elke logregel in de audit database verwijst naar deze unieke ID.
*   **Hardened**: Kan niet inloggen interactief (behalve via specifieke OBO flows).

### 2. On-Behalf-Of (OBO) Flow
Wanneer een gebruiker (bijv. "Jan") aan de Druppie Copilot vraagt om een bestand te lezen, mag de AI dit alléén doen als Jan daar recht op heeft.
*   **Context Propagatie**: Het token van Jan wordt doorgegeven aan de Agent.
*   **Security Trimming**: De Agent "ziet" alleen wat Jan ook zou zien. Dit voorkomt dat de AI een "backdoor" wordt naar gevoelige data.

---

## 🛡️ Beveiligingsmodel

### Zero Trust voor Agents
Het principe "Never trust, always verify" geldt ook voor interne componenten.
*   **Agent-to-Agent Auth**: Als de "Router Agent" de "Finance Agent" aanroept, controleert de Finance Agent het token van de Router.
*   **Just-in-Time Access**: Rechten worden waar mogelijk tijdelijk verleend.

### Granulaire RBAC (Role Based Access Control)
We definiëren specifieke rollen voor agents, niet voor computers.

| Rol | Omschrijving | Voorbeeld |
| :--- | :--- | :--- |
| **`AI.Reader`** | Mag data indexeren voor RAG (alleen lezen). | Knowledge Bot |
| **`AI.Builder`** | Mag nieuwe infrastructuur aanmaken. | Builder Agent |
| **`AI.Executor`** | Mag namens gebruikers acties uitvoeren in ERP. | HR Agent |

---

## 🚀 Implementatie in de Architectuur

### 1. Creatie
Wanneer een nieuwe agent wordt gedefinieerd in de **Agent Factory**, wordt automatisch:
1.  Een User Managed Identity aangemaakt in Azure.
2.  Deze identiteit gekoppeld aan de Agent Service.
3.  Specifieke rechten (Scopes) toegekend op de doelsystemen (bijv. `Storage Blob Data Reader` op `st-finance-data`).

### 2. Runtime
Tijdens uitvoering:
1.  De Agent haalt een token op bij de lokale Identity Endpoint (binnen de container/service).
2.  Dit token wordt als `Authorization: Bearer <token>` meegestuurd naar tools en API's.
3.  De ontvangende API valideert het token tegen Entra ID.

---

## 🔗 Relaties
*   **Ondersteunt**: [Compliance Overview](./overview.md) en [BIO4 & NIS2](./bio4_nis2.md).
*   **Wordt gebruikt door**: [Druppie UI](../bouwblokken/druppie_ui.md) (voor inloggen) en [Foundry](../build_plane/foundry.md) (voor provisioning).
