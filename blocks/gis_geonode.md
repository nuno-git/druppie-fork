---
id: gis-geonode
name: patial Data Infrastructure (GeoNode)
type: block
version: 1.0.0
auth_group: []
description: "Portaal voor het vinden en delen van geografische data"
capabilities: []
---

# Spatial Data Infrastructure (GeoNode)

## 🎯 Selectie: GeoNode
Als centraal portaal voor het **vinden** en **delen** van geografische data kiezen we **GeoNode**. GeoNode is een Open Source Geospatial Content Management System (GeoCMS).

### 💡 Onderbouwing van de Keuze
Waarom hebben we GeoNode nodig naast GeoServer en QGIS?
1.  **De "Catalogus" (Metadata)**: Met duizenden drone-vluchten en GIS-lagen raak je het overzicht kwijt. GeoNode biedt een zoekbalk, previews, en metadata (CSW) ondersteuning. Het is de "Google" voor je interne data.
2.  **Self-Service**: Een medewerker kan zelf een Excel met coördinaten of een Shapefile uploaden. GeoNode regelt op de achtergrond automatisch de opslag in PostGIS en publicatie in GeoServer.
3.  **Social**: Gebruikers kunnen comments plaatsen, kaarten raten, en kaarten combineren tot "Map Stories" om inzichten te delen met het management.
4.  **Backend Integratie**: Onder water gebruikt GeoNode gewoon **GeoServer** (voor OGC services) en **PostGIS** (voor data). Het vervangt deze niet, maar management ze.

---

## 🛠️ Installatie

GeoNode is een complexe stack (Django + Celery + GeoServer + DB + RabbitMQ). Het installeren via Docker Compose (of een Helm chart wrapper) is de standaard.

### Componenten in de Stack
*   **Django App**: De web interface.
*   **GeoServer**: De map engine (beheerd door Django).
*   **PostGIS**: Data opslag.
*   **RabbitMQ**: Voor asynchrone taken (bijv. upload processing).

*(In Druppie configureren we GeoNode zo dat hij onze bestaande centrale PostGIS en MinIO clusters gebruikt in plaats van eigen containers te starten.)*

---

## 🚀 Gebruik

### Workflow: "Data Delen met de Organisatie"
De **Drone Operator** heeft net een nieuwe kaart gemaakt.

1.  **Upload**: Gaat naar `geoportal.druppie.nl` en sleept de GeoTIFF erin.
2.  **Processing**: GeoNode valideert het bestand en registreert het in GeoServer.
3.  **Verrijken**: De operator vult metadata in: "Vlucht 2025, locatie XYZ, vlieger Jan".
4.  **Delen**: Hij zet de rechten op "Zichtbaar voor Team Ecologie".
5.  **Ontdekken**: Een ecoloog zoekt op "Vegetatie 2025", vindt de kaart, en opent hem direct in de browser of laadt hem in QGIS via de geboden WMS link.

## 🔄 Integratie in Druppie
1.  **Single Source of Truth**: GeoNode fungeert als de catalogus. Als de **AI Knowledge Bot** een vraag krijgt ("Hebben we kaarten van gebied X?"), zoekt hij via de GeoNode API (CSW/API v2).
2.  **Samenhang**: GeoServer doet het zware werk, GeoNode maakt het mens-vriendelijk.
