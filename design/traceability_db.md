# Traceability DB (Audit Log)

## 🎯 Doelstelling
De **Traceability DB** fungeert als de onveranderlijke "zwarte doos" (flight recorder) van het Druppie platform. Het doel is om volledige verantwoording en reproduceerbaarheid te garanderen. In een AI-gedreven systeem is het cruciaal om precies te kunnen reconstrueren *waarom* een AI een bepaalde beslissing nam en *volgens welke instructies* code is gegenereerd.

## 📋 Functionele Specificaties

### 1. Granulaire Logging
- **Prompts & Responses**: Slaat exact op wat er als input naar de LLM ging en wat er terugkwam.
- **Decision Trees**: Logt de redenering (Thought Process) van de planner.
- **Code Changes**: Logt diffs van gegenereerde code.
- **Approval Events**: Logt wie, wanneer, en waarom goedkeuring gaf (inclusief digitale handtekening).

### 2. Zoekbaarheid & Analyse
- **Correlatie ID's**: Koppelt alle logs van één sessie/verzoek aan elkaar (`TraceID`).
- **Niet-technische weergave**: Moet data zo kunnen structureren dat auditors (niet-developers) het kunnen lezen.

### 3. Integriteit
- **Immutability**: Eenmaal geschreven logs mogen NOOIT gewijzigd of verwijderd worden (Write Once, Read Many).
- **Retention**: Data moet bewaard blijven conform wettelijke termijnen (bijv. 7 jaar).

## 🔧 Technische Requirements

- **High Throughput**: Moet grote stromen logdata aankunnen zonder de Core te vertragen (async writing).
- **Storage Tiering**: Hot storage voor recente logs, Cold storage (Azure Blob/S3 Glacier) voor archief.
- **Time Series**: Geoptimaliseerd voor tijdreeks-data.

## 🔒 Security & Compliance

- **Encryption at Rest & in Transit**: Alle data is versleuteld.
- **Access Control**: Alleen Security Officers en Auditors hebben leesrechten. Niemand heeft schrijfrechten (behalve het systeem zelf).
- **Anomaly Detection**: Activeert alerts bij verdachte patronen (bijv. massale export van logs).

## 🔌 Interacties

De DB is passief en ontvangt data van alle componenten.

| Bron | Type Data | Frequentie |
| :--- | :--- | :--- |
| **Druppie Core** | Prompts, Tokens, Plans | Hoog |
| **Policy Engine** | Checks, Violations | Gemiddeld |
| **Mens in de Loop** | Approvals, Rejections | Laag |

## 🏗️ Relaties tot andere blokken
- **Ondersteunt**: [Compliance Layer](./../design/compliance_layer.md) (levert bewijslast).