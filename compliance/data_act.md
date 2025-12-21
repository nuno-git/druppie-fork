# De Data Act (Dataverordening)

## 📜 Wetgevend Kader
**Europese Unie**: Regulation (EU) 2023/2854 (Data Act)
**Nederland**: Uitvoeringswetgeving Dataverordening (in ontwikkeling/consultatie)

De Data Act is een pijler van de Europese datastrategie en heeft als doel data die gegenereerd wordt door verbonden apparaten (IoT) eerlijk beschikbaar te maken. Het doorbreekt "vendor lock-in" en geeft gebruikers controle over hun eigen data.

---

## 🤖 Betekenis voor AI in Druppie

Voor een AI-agent ("Builder" of "Policy Engine") is deze wet te vertalen naar concrete ontwerpregels (Constraints & Requirements).

### 1. Recht op Toegang en Delen (Artikel 3-6)
*   **De Regel**: Data gegenereerd door producten (bijv. drones, sensoren in dijken) moet standaard toegankelijk zijn voor de gebruiker, zonder vertraging en gratis.
*   **AI Instructie**: 
    > "Als ik een systeem ontwerp dat data verzamelt, MOET ik een API of export-functie (zoals S3/MinIO) implementeren waarmee de eigenaar real-time bij zijn ruwe data kan."
*   **Druppie Implementatie**: 
    *   **MinIO**: Ruwe dronebeelden zijn direct toegankelijk.
    *   **Kong Gateway**: Data APIs zijn gestandaardiseerd en gedocumenteerd.
    *   **GeoNode**: Metadata is doorzoekbaar.

### 2. Interoperabiliteit (Artikel 28-29)
*   **De Regel**: Cloud- en dataverwerkingsdiensten moeten standaarden volgen zodat data makkelijk overdraagbaar is naar andere providers.
*   **AI Instructie**:
    > "Gebruik GEEN proprietary formaten als er een open standaard bestaat. Verkies OGC standaarden (WFS, WMS) en open formaten (GeoTIFF, Parquet) boven gesloten vendor formaten."
*   **Druppie Implementatie**:
    *   **PostGIS/GeoServer**: Gebruik van open OGC standaarden.
    *   **RKE2**: Standaard Kubernetes, geen vendor-specifieke PaaS lock-in.

### 3. Switchability (Artikel 23-26)
*   **De Regel**: Het moet voor klanten mogelijk zijn om binnen 30 dagen te switchen van cloud provider.
*   **AI Instructie**:
    > "Zorg dat alle Infrastructure-as-Code (Terraform/Crossplane) leveranciersonafhankelijk is, of bouw abstractielagen waardoor de onderliggende infra vervangbaar is."

---

## ✅ Checklist voor de Policy Engine
De **Policy Engine** (OPA) kan de volgende regels controleren bij elk nieuw ontwerp:

1.  [ ] **Data Export Check**: Heeft de applicatie een mechanisme om data te exporteren?
2.  [ ] **Standard Format Check**: Wordt data opgeslagen in een formaat dat op de 'Druppie Open Standaarden Lijst' staat?
3.  [ ] **API First**: Is de data ook machinaal leesbaar via een API, niet alleen via een UI?
