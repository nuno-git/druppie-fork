---
id: webodm
name: Drone Mapping & 3D Processing (OpenDroneMap)
type: block
version: 1.0.0
auth_group: []
description: "Totale proces van fotogrammetrie — het omzetten van losse 2D dronefoto's naar georeferenced orthofoto's"
capabilities: []
---

# Drone Mapping & 3D Processing (OpenDroneMap)

## 🎯 Selectie: WebODM (OpenDroneMap)
Voor het totale proces van fotogrammetrie — het omzetten van losse 2D dronefoto's naar georeferenced orthofoto's en 3D-modellen — kiezen we voor **WebODM**. Dit is de gebruiksvriendelijke, web-based interface bovenop de krachtige **OpenDroneMap (ODM)** engine.

### 💡 Onderbouwing van de Keuze
Deze toolset is de open-source standaard in de GIS-wereld en sluit naadloos aan op onze infrastructuur:

1.  **Alles-in-één Pipeline**:
    *   **Preprocessing**: Herkent GPS data in foto's.
    *   **Stitching**: Plakt foto's aan elkaar (Orthofoto).
    *   **3D Modelling**: Genereert Point Clouds (.laz) en Textured 3D Models (.obj/gltf).
    *   **Analyses**: Kan ook vegetatie-indices (zoals NDVI voor landbouw/natuur) berekenen.
2.  **Kubernetes Ready**: WebODM is ontworpen als een set microservices (NodeODMICM) die schalen op ons cluster. "Zware" taken worden verdeeld over meerdere Processing Nodes.
3.  **Integratie**: Kan resultaten direct wegschrijven naar onze **PostGIS** database of als tiles serveren.
4.  **Vluchtplanning (QGroundControl)**: WebODM werkt perfect samen met open standaarden voor vluchtplannen. Hoewel de drone zelf vliegt, slaan we het *Vluchtplan* op als onderdeel van het project.

---

## 🛠️ Installatie

We installeren WebODM op het Kubernetes cluster, met toegang tot de GPU-nodes (indien beschikbaar) voor snellere 3D verwerking.

### 1. Installatie via Helm
Er is geen officiële Helm repository, maar we gebruiken vaak een community chart of de `docker-compose` conversie. Een typische deployment in Druppie ziet er zo uit:

```bash
# Clone de deployment configuratie uit onze GIT repo
flux create kustomization webodm \
  --source=druppie-infra \
  --path=./apps/webodm \
  --prune=true
```

Dit start:
*   **WebApp**: De interface voor gebruikers.
*   **NodeODM**: De worker(s) die het rekenwerk doen.
*   **Database**: Interne Postgres (of onze centrale Postgres Cluster).

---

## 🚀 Gebruik: Van Vlucht tot 3D Model

Het proces bestaat uit drie fasen, die door Druppie worden gefaciliteerd.

### Stap 1: Vluchtplanning & Uitvoering
*Tool: QGroundControl (Client-side)*
Om een vast interval (bijv. "elke 2 meter een foto") en overlap te garanderen, maakt de piloot een vluchtplan.
1.  Teken gebied in **QGroundControl**.
2.  Stel parameters in:
    *   **Front Overlap**: 70% (Cruciaal voor 3D).
    *   **Side Overlap**: 60%.
    *   **GSD (Ground Sampling Distance)**: 2cm/pixel.
3.  Sla het plan op (`mission.plan`) en upload dit naar **Gitea** bij het project. Dit garandeert reproduceerbaarheid ("Vlieg volgende maand exact dezelfde route").

### Stap 2: Upload & Verwerking (WebODM)
De foto's komen van de SD-kaart.
1.  **Upload**: Gebruiker (of script) uploadt de map met 500 foto's naar een WebODM Taak.
2.  **Opties**: Selecteer "High Resolution" voor dijkinspectie of "Fast" voor een snelle check.
3.  **Processing**: WebODM draait de *Structure from Motion* (SfM) algoritmes.
    *   *Feature Matching*: Zoekt dezelfde boom/struik in foto A en foto B.
    *   *Point Cloud*: Berekent de 3D positie van elk punt.
    *   *Texturing*: Plakt de foto-pixels op het 3D model.

### Stap 3: Resultaat & Analyse
De output wordt automatisch beschikbaar gemaakt:
*   **Orthofoto (2D)**: Een meetbare kaart. Te openen in QGIS of via de WebODM interface.
*   **3D Model**: Een interactief model. De gebruiker kan in de browser ronddraaien, afstanden meten en volumes berekenen (bijv. "Hoeveel kuub zand ligt hier?").

## 🔄 Integratie in Druppie
1.  **Data Lake**: WebODM gebruikt ons **MinIO** cluster (`s3://drone-ortho`) om de gigabytes aan resultaten op te slaan.
2.  **MCP Server**: We bouwen een MCP tool (`get_3d_snapshot`) waarmee de AI een screenshot kan maken van het 3D model vanuit een bepaalde hoek, om daar vervolgens vragen over te beantwoorden.
3.  **Traceability**: Het vluchtplan (`mission.plan` in Git) + de ruwe foto's (in DVC) + de WebODM instellingen = **100% Reproduceerbaar resultaat**.
