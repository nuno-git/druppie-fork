# GIS Desktop & Server (QGIS)

## 🎯 Selectie: QGIS (Quantum GIS)
Voor geavanceerde ruimtelijke analyses, kaarten maken en data-bewerking kiezen we voor **QGIS**. Dit is de absolute marktleider in open-source GIS software.
We zetten QGIS in op twee manieren:
1.  **QGIS Desktop**: De applicatie voor de GIS-specialist en Data Scientist.
2.  **QGIS Server**: Een OGC-compliant server die `.qgs` projectbestanden direct publiceert als WMS/WFS services.

### 💡 Onderbouwing van de Keuze
1.  **Gebruikersgemak**: Biedt een rijke interface die vergelijkbaar is met ArcGIS, maar dan zonder licentiekosten.
2.  **Integratie**: Werkt native samen met onze **PostGIS** database en **MinIO** (via VSI S3 of plugins).
3.  **Project-as-a-Service (QGIS Server)**: Een unieke krachtige feature. Je maakt een mooie kaart op in Desktop (styling, labels, kleuren), slaat het project op, en de Server serveert het *exact* zo als web-kaart. Geen gedoe met SLD's (Styled Layer Descriptors) schrijven in XML.
4.  **Extensible**: Enorm ecosysteem van plugins (Python-based), wat automatisering door onze **Builder Agent** makkelijk maakt.

---

## 🛠️ Installatie

### 1. QGIS Desktop (Client)
Wordt geïnstalleerd op de werkplekken (Windows/Mac/Linux) of aangeboden via een VDI (Virtual Desktop) oplossing (bijv. KasmWeb of Apache Guacamole) binnen de browser.

### 2. QGIS Server (Kubernetes)
We draaien QGIS Server als container in het cluster om de projecten te ontsluiten.

*Docker Image*: `camptocamp/qgis-server:latest`

**Deployment snippet:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qgis-server
spec:
  template:
    spec:
      containers:
      - name: qgis-server
        image: camptocamp/qgis-server:3.34
        env:
        - name: QGIS_PROJECT_FILE
          value: "/data/projects/dijk_analyse.qgs"
        volumeMounts:
        - name: project-data
          mountPath: /data
```

---

## 🚀 Gebruik

### Workflow: "Van Analyse naar Webkaart"
1.  **Data Laden**: De GIS-specialist opent QGIS Desktop en verbindt met PostGIS (vector data) en MinIO (drone foto's).
2.  **Opmaak**: Hij stelt de symbologie in (bijv. dijken rood kleuren als conditie < 6).
3.  **Opslaan**: Slaat het project op als `inspectie_kaart.qgs` in **Gitea**.
4.  **Publish**:
    *   De CI/CD pipeline ziet de commit.
    *   Pusht het bestand naar de QGIS Server volume.
    *   Resultaat: Een WMS link (`https://maps.druppie.nl/wms/inspectie`) die exact toont wat de specialist zag.

## 🔄 Integratie in Druppie
1.  **WebODM**: Resultaten uit de drone-pipeline (Orthofoto's) worden vaak in QGIS gevalideerd voordat ze definitief worden.
2.  **Frontend**: Onze web-apps (React + Leaflet/OpenLayers) gebruiken de WMS/WFS feeds van QGIS Server als ondergrondlaag.
