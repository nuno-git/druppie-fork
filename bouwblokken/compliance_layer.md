# Compliance Layer Definitie

## 🎯 Doelstelling
De **Compliance Layer** is het overkoepelende kader dat niet zozeer "iets doet" (zoals code bouwen), maar "overal naar kijkt". Het definieert de standaarden en audit-mechanismen. Zie [Compliance Domein](../compliance/overview.md) voor de diepte-uitwerking.

## 📋 Functionele Specificaties

### 1. Continuous Audit
- **Aggregatie**: Verzamelt signalen uit Policy Engine, Traceability DB, en Runtime logs.
- **Reporting**: Genereert rapportages voor auditors (bijv. "Lijst van alle code changes die zonder 4-eyes principle naar prod zijn gegaan").

### 2. Machine Identity (Agent ID)
- **Entra Agent ID**: Elke AI-agent krijgt een unieke identiteit in Entra ID (voorheen Azure AD).
- **Granulaire Rechten**: Permissies worden toegekend aan de specifieke agent (bijv. "Finance Agent" mag alleen bij de Finance Sharepoint).
- **Managed Identity**: Gebruik van Managed Identities voor veilige service-to-service communicatie zonder secrets.

## 🏗️ Relaties
- **Verwijst naar**: [Compliance Domein](../compliance/overview.md).
- **Integreert met**: Alle andere bouwblokken (elke actie genereert compliance data).
