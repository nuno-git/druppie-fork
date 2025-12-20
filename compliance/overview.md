# Compliance Overview

De **Compliance Layer** is verantwoordelijk voor het waarborgen van veiligheid, privacy en regelgeving binnen het gehele Druppie-ecosysteem. Het werkt volgens het principe van "Continuous Compliance" en maakt zwaar gebruik van native Azure governance features.

## 📜 Doelstellingen

- **Security by Design**: Beveiliging is ingebakken in de 'Agent Factory' pipeline.
- **Auditeerbaarheid**: Elke actie van een agent is traceerbaar tot een unieke identiteit.
- **Automatic Enforcement**: Regels worden automatisch afgedwongen via **Azure Policy**.

## 🧩 Onderdelen

- **[IAM (Identity & Access Management)](./iam.md)**
  - **Entra Agent ID**: Unieke identiteiten voor agents (geen gedeelde service accounts).
  - **Managed Identity**: Wachtwoordloze authenticatie tussen services.
  - **RBAC**: Fijnmazige rolverdeling op Foundy projecten en resources.

- **[BIO & NIS2 Framework](./bio4_nis2.md)**
  - Concrete invulling van de Baseline Informatiebeveiliging Overheid en EU NIS2 richtlijn.
  - Mapping van controls op Druppie technologie en processen.

- **Governance & Policy**
  - **Azure Policy**: Dwingt regels af op infrastructuur niveau (bijv. "Alleen GPT-4o in West Europe", "Verplicht Private Link").
  - **Policy Engine** (zie [Bouwblokken](../bouwblokken/policy_engine.md)): Dwingt regels af op applicatie niveau (functionele checks).

- **Data Protection**
  - **Private Endpoints**: Verkeer blijft binnen het Azure backbone netwerk.
  - **Data Exfiltration Control**: Agents kunnen alleen communiceren met gewhiteliste domeinen.

- **Security Scanners** (onderdeel van [Foundry](../build_plane/foundry.md))
  - Automatische scans in de CI/CD pipeline.
