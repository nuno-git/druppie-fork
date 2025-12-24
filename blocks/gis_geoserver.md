---
id: gis-geoserver
name: GIS Data Server (GeoServer)
type: block
version: 1.0.0
auth_group: []
description: "GIS Data Server (GeoServer)"
capabilities: ["gis"]
---

# GIS Data Server (GeoServer)

## 🎯 Selectie: GeoServer
Voor het robuust en gestandaardiseerd ontsluiten van onze ruimtelijke data kiezen we voor **GeoServer**. Waar QGIS Server goed is in *visualisatie* (Maps), is GeoServer de koning van de *data-distributie* en standaarden (WFS, WCS, WPS).

### 💡 Onderbouwing van de Keuze
1.  **De Standaard**: GeoServer is de referentie-implementatie voor veel OGC standaarden. Als een externe partij (bijv. Kadaster of Provincie) data bij ons wil ophalen, is een GeoServer WFS-endpoint de universele taal.
2.  **Fine-grained Security**: GeoServer heeft een ingebouwd beveiligingsmodel. We kunnen instellen dat gebruiker "Stagiair" alleen de attributen `ID` en `Type` mag zien van een laag, maar niet het attribuut `Eigenaar`.
3.  **Caching (GeoWebCache)**: Ingebouwde tiling en caching zorgt voor razendsnelle kaarten, zelfs bij terabytes aan data.
4.  **Data Formats**: Kan output leveren in KML, GeoJSON, GML, Shapefile, Excel, PDF, etc.

---

## 🛠️ Installatie

We gebruiken de officiele Kartoza Docker image of een Helm chart.

### Installatie via Docker/Helm
```bash
helm repo add oscarfonts https://oscarfonts.github.io/helm-charts
helm upgrade --install geoserver oscarfonts/geoserver \
  --namespace gis-system --create-namespace \
  --set persistence.enabled=true \
  --set persistence.size=20Gi \
  --set tomcat.extras.javaOpts="-Xms2G -Xmx4G"
```

*Configuratie*: We koppelen GeoServer aan onze **PostGIS** store en **MinIO** store (via de S3 plugin).

---

## 🚀 Gebruik

### Scenario: "Publieke Dienst WFS"
Stel we willen partner-waterschappen toegang geven tot onze "Waterlopen" dataset.

1.  **Store Aanmaken**: Koppel de PostGIS tabel `waterlopen`.
2.  **Layer Publiceren**: Publiceer de tabel als Layer `druppie:waterlopen`.
3.  **Styling (SLD/CSS)**: Definieer een standaard blauwe lijn stijl (optioneel, vooral voor WMS).
4.  **Security**: Zet de layer op "Read-Only" voor groep `Anonymous` of vereis een API Key.

**Resultaat**:
Een URL: `https://geodata.druppie.nl/geoserver/wfs?request=GetFeature&typeName=druppie:waterlopen&outputFormat=application/json`

## 🔄 Integratie in Druppie
1.  **GeoNode**: GeoServer is vaak de "engine" onder de motorkap van GeoNode (zie GeoNode bouwblok). GeoNode beheert dan de config.
2.  **Performance**: Voor high-performance tile serving van onze Drone orthofoto's (WMS-T) is GeoServer (met GeoWebCache) zeer geschikt.
