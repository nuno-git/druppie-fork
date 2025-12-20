# BIO & NIS2 Compliance Strategie

Druppie is ontworpen om te voldoen aan strikte overheids- en EU-regelgeving. Dit document beschrijft hoe de architectuur concrete invulling geeft aan de **Baseline Informatiebeveiliging Overheid (BIO)** en de **Network and Information Security Directive (NIS2)**.

## 🇪🇺 NIS2 (Network and Information Security Directive)

De NIS2-richtlijn legt zwaardere eisen op het gebied van cybersecurity, met een focus op *zorgplicht*, *meldplicht* en *ketenbeveiliging*.

### 1. Zorgplicht (Duty of Care)
Organisaties moeten passende maatregelen nemen om risico's te beheersen. Druppie vult dit in via:
- **Security by Design**: De [Foundry](../build_plane/foundry.md) pipeline blokkeert onveilige code vóór deployment.
- **Zero Trust**: Gebruik van **Entra Agent ID** en Private Endpoints zorgt dat geen enkele component elkaar blind vertrouwt.
- **Continuous Monitoring**: De [Compliance Layer](../bouwblokken/compliance_layer.md) voert dagelijkse geautomatiseerde checks uit.

### 2. Meldplicht (Incident Reporting)
Bij een incident moet binnen 24 uur gemeld worden.
- **Traceability DB**: Alle acties (prompts, wijzigingen, toegang) worden onveranderlijk vastgelegd. Dit maakt directe reconstructie van een incident mogelijk ("Wie deed wat en wanneer?").
- **Automated Alerting**: De Policy Engine detecteert afwijkingen (anomalies) en kan direct de CISO notificeren.

### 3. Supply Chain Security
Beveiliging van de toeleveringsketen is cruciaal.
- **Spec-Driven Agents**: Omdat agents "as-code" gedefinieerd zijn, is exact bekend welke modellen en tools gebruikt worden. Geen "Shadow AI".
- **SBOM (Software Bill of Materials)**: Foundry genereert bij elke build een SBOM, zodat kwetsbaarheden in libraries (bijv. Log4j) direct geïdentificeerd kunnen worden.

---

## 🇳🇱 BIO (Baseline Informatiebeveiliging Overheid)

De BIO is gebaseerd op ISO 27001/27002 en geldt voor de gehele overheid.

### Basisbeveiligingsniveaus (BBN)
Druppie ondersteunt differentiatie naar BBN-niveau via de **Policy Engine**.

| BIO Concept | Druppie Implementatie |
| :--- | :--- |
| **Identificatie & Authenticatie** | Alle agents en gebruikers authenticeren via **Entra ID**. MFA is verplicht voor beheerders. |
| **Autorisatie** | **RBAC** op basis van 'Least Privilege'. Een agent krijgt nooit meer rechten dan nodig voor zijn taak (scoped access). |
| **Logging & Controle** | De **Traceability DB** voldoet aan de eisen voor onweerlegbaarheid en bewaring. Logfiles zijn niet aanpasbaar (WORM storage). |
| **Cryptografie** | Alle data-in-transit (TLS 1.3) en data-at-rest (Azure Storage Encryption) is versleuteld. |
| **Kwetsbaarhedenbeheer** | Geautomatiseerde patch-management voor de container runtime en AI-modellen (via Microsoft managed updates). |

### BIO Mapping Tabel (Voorbeelden)

- **Control 9.1.1 (Toegangsbeleid)**: Geïmplementeerd via [IAM](../compliance/iam.md) policy rules.
- **Control 12.4.1 (Logging)**: Geïmplementeerd via [Traceability DB](../bouwblokken/traceability_db.md).
- **Control 14.2.1 (Veilig ontwikkelen)**: Geïmplementeerd via [Foundry](../build_plane/foundry.md) pipelines met SAST/DAST.

---

## 🛡️ Praktische Uitvoering

Wanneer een nieuwe Agent wordt gedeployed, valideert de Pipeline automatisch:
1.  Is de data-classificatie (BBN1/2/3) bekend?
2.  Voldoet de gekozen infrastructuur aan de eisen voor dat niveau?
    *   *Voorbeeld*: BBN2 mag data verwerken in EU, BBN3 vereist wellicht specifieke NL-only hosting of sleutelbeheer (BYOK).
3.  Zijn de logging-instellingen correct geconfigureerd?

Indien niet compliant, blokkeert de **Policy Engine** de deployment.
