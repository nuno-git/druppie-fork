# Goed Bestuur (Code Goed Openbaar Bestuur)

## 📘 Context en Kader
De **Code Goed Openbaar Bestuur** bevat de kernwaarden en gedragsnormen voor de Nederlandse overheid. Voor waterschappen, als functionele democratie, is het naleven van deze principes cruciaal voor het behoud van vertrouwen. In een tijd waarin besluitvorming steeds meer digitaliseert en AI-gedreven wordt, moeten deze 'analoge' principes vertaald worden naar digitale waarborgen.

---

## 🏛️ De Principes & Implementatie in Druppie

Hieronder vertalen we de algemene beginselen van behoorlijk bestuur naar technische requirements voor het Druppie platform.

### 1. Openheid en Transparantie
*   **Het Principe**: Het bestuur handelt open en inzichtelijk. Burgers moeten kunnen begrijpen hoe besluiten tot stand komen.
*   **Vertaalslag naar AI**: Geen "Black Box" besluitvorming.
*   **Implementatie**:
    *   **AI Register**: Publiceer actief welke algoritmes worden gebruikt (zie [AI Register](./ai_register.md)).
    *   **XAI (Explainable AI)**: Gebruik modellen die uitlegbaar zijn of voeg een uitleg-module toe.
    *   **Open Source**: Waar mogelijk wordt broncode van niet-gevoelige onderdelen (bv. rekenmodellen) openbaar gemaakt in Gitea/GitHub Public.

### 2. Verantwoording (Accountability)
*   **Het Principe**: Het bestuur moet zich achteraf kunnen verantwoorden voor gemaakte keuzes en resultaten.
*   **Vertaalslag naar AI**: Traceerbaarheid van elke handeling.
*   **Implementatie**:
    *   **Traceability DB**: Onwijzigbare opslag van *wie* (mens of AI), *wanneer* en *waarom* een actie heeft uitgevoerd.
    *   **GitOps**: Elke wijziging in infrastructuur of data is een commit met een auteur.
    *   **Audit Trail**: Zorg dat logs minimaal 7 jaar bewaard blijven (conform Archiefwet) in 'Cold Storage'.

### 3. Integriteit
*   **Het Principe**: Bestuurders en ambtenaren handelen integer, onpartijdig en zonder belangenverstrengeling.
*   **Vertaalslag naar AI**: Voorkomen van bias (vooroordelen) in data en modellen.
*   **Implementatie**:
    *   **Dataset Screening (DVC)**: De Policy Engine vereist een check op representativiteit van data om discriminatie te voorkomen (bijv. in handhaving of vergunningverlening).
    *   **IAM (Identity & Access Policy)**: Strikte scheiding van rechten. Datascientists mogen niet zomaar bij productie-data waar persoonsgegevens in staan (Privacy-by-Design).

### 4. Doelmatigheid en Doeltreffendheid
*   **Het Principe**: Middelen (belastinggeld) moeten efficiënt worden ingezet en doelen moeten daadwerkelijk bereikt worden.
*   **Vertaalslag naar AI**: Voorkom verspilling van dure cloud-resources en "hobby-projecten" die geen waarde toevoegen.
*   **Implementatie**:
    *   **Spec-Driven Design**: De **Builder Agent** dwingt af dat er eerst een doel (spec) is voordat er gebouwd wordt.
    *   **FinOps**: Monitoring van resource-gebruik (via Prometheus/Grafana) en automatische downscaling van ongebruikte pods (KEDA).
    *   **Hergebruik**: Het "Bouwblokken" principe voorkomt dat elk team zijn eigen database-oplossing gaat bouwen.

### 5. Participatie
*   **Het Principe**: Burgers en belanghebbenden worden betrokken bij besluitvorming.
*   **Vertaalslag naar AI**: Digitale toegankelijkheid.
*   **Implementatie**:
    *   **GeoNode Portal**: Maak data en kaarten toegankelijk voor ingelanden, zodat zij zienswijzen kunnen indienen op basis van dezelfde informatie als het waterschap.

---

## 🛡️ Borging in de Architectuur
Goed bestuur is geen 'sausje', maar zit ingebakken in de code:
*   Als een model **niet uitlegbaar** is, mag het niet in productie.
*   Als data **niet herleidbaar** is, faalt de build pipeline.
*   Als de **kosten** de baten overstijgen, signaleert het systeem dit aan de controller.

Door deze principes te codificeren (Policy-as-Code), garandeert Druppie dat innovatie hand in hand gaat met betrouwbaar overheidshandelen.
