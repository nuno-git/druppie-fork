# Mens in de Loop (Human in the Loop)

## 🎯 Doelstelling
Het bouwblok **Mens in de Loop** (HITL) integreert menselijke intelligentie en verantwoordelijkheid in het geautomatiseerde proces. Hoewel AI veel kan automatiseren, vereisen kritieke beslissingen, ethische afwegingen en hoge risico's altijd menselijke validatie. Dit blok voorkomt "AI hallucinations" die leiden tot productieschade.

## 📋 Functionele Specificaties

### 1. Goedkeurings Workflows
- **Critical Gating**: Blokkeert uitvoering bij specifieke triggers (bijv. deployments naar productie, verwijderen van data, kosten > €X).
- **Escalatie**: Kan verzoeken escaleren naar specifieke rollen (bijv. CISO voor security, PO voor features).

### 2. Contextuele Validatie
- **Diff Review**: Toont de gebruiker precies wat er gaat veranderen (bijv. Terraform plan, Code diff).
- **Explanation**: De AI moet uitleggen *waarom* hij deze actie wil doen, zodat de mens een geïnformeerde keuze kan maken.

### 3. Feedback Loop
- **Korrektie**: De mens moet niet alleen Ja/Nee kunnen zeggen, maar ook sturend commentaar kunnen geven ("Nee, doe dit opnieuw maar gebruik bibliotheek X").
- **Learning**: De feedback van de mens wordt (geanonimiseerd) gebruikt om toekomstige prompts te verbeteren.

## 🔧 Technische Requirements

- **Asynchroon**: Een goedkeuringsverzoek kan minuten of uren openstaan; het systeem mag niet time-outen.
- **Multi-channel**: Notificaties kunnen via Chat, Email, of ITSM tools (ServiceNow/Jira) verlopen.

## 🔒 Security & Compliance

- **Non-repudiation**: Het moet onweerlegbaar zijn WIE de goedkeuring heeft gegeven.
- **Segregation of Duties**: De persoon die de code aanvraagt mag (in sommige gevallen) niet dezelfde zijn die goedkeurt.

## 🔌 Interacties

| Trigger | Actie | Output |
| :--- | :--- | :--- |
| **Policy Violation (Requires Approval)** | Stuur notificatie + Context | Wachtstatus in Core |
| **User Action (Approve/Reject)** | Verwerk beslissing | Core hervat of stopt |

## 🏗️ Relaties tot andere blokken
- **Geactiveerd door**: [Policy Engine](./policy_engine.md).
- **Communiceert via**: [Druppie UI](./druppie_ui.md).
- **Gelogd in**: [Traceability DB](./traceability_db.md).
