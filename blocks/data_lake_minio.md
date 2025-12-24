---
id: data-lake-minio
name: Data Lake (MinIO)
type: block
description: "S3-compatible object storage for unstructured data."
capabilities: ["object-storage", "s3-compatible", "data-lake"]
version: 1.0.0
auth_group: ["developers"]
---
# Data Lake & Object Storage (MinIO)

## 🎯 Selectie: MinIO
Voor de opslag van grootschalige ongestructureerde data, specifiek **drone-beelden**, **satelliet-data** en AI-modellen, kiezen we voor **MinIO**. MinIO is een High-Performance Object Storage oplossing die volledig compatible is met de Amazon **S3 API**.

### 💡 Onderbouwing van de Keuze
Relationele databases (zoals Postgres) zijn niet geschikt voor het opslaan van Terabytes aan ruwe pixel-data (Raster files). MinIO vult dit gat:

1.  **De facto Standaard (S3 API)**: Vrijwel elke moderne data-tool spreekt "S3".
    *   **GIS Tools**: GDAL, QGIS, GeoServer kunnen direct lezen/schrijven naar S3.
    *   **AI/ML Frameworks**: PyTorch, TensorFlow en MLflow laden datasets direct uit S3.
    *   **Pipeline Tools**: OpenDroneMap (voor stichting) en Tekton kunnen S3 als input/output gebruiken.
2.  **Versioning & Immutability**: MinIO ondersteunt S3 Bucket Versioning. Als je een bestand overschrijft, bewaart MinIO de oude versie. Dit is cruciaal voor *reproduceerbare AI*: "Op welke versie van de dataset is dit model getraind?".
3.  **Performance**: MinIO is geoptimaliseerd voor snelheid (gebruikt SIMD instructies) en kan de enorme doorvoer aan die nodig is voor het trainen van modellen op GPU's.
4.  **Kubernetes Native**: Integreert naadloos met de rest van het platform.

---

## 🛠️ Installatie

We installeren een stand-alone MinIO cluster (of een Distributed cluster voor productie).

### 1. Installatie via Helm
```bash
helm repo add minio https://charts.min.io/
helm upgrade --install data-lake minio/minio \
  --namespace data-systems --create-namespace \
  --set rootUser=admin \
  --set rootPassword=VERY_SECRET_KEY \
  --set persistence.size=1Ti \
  --set buckets[0].name=drone-raw \
  --set buckets[0].policy=public \
  --set buckets[0].versioning=true \
  --set buckets[1].name=drone-ortho \
  --set buckets[2].name=ai-models
```

---

## 🚀 Gebruik: De Drone Workflow

Dit bouwblok vormt de fundering voor de geavanceerde verwerking van beelden. Hieronder schetsen we hoe de "Drone Pipeline" gebruik maakt van MinIO.

### Stap 1: Ingestie & Versiebeheer
De ruwe beelden (van de drone of satelliet provider) worden geupload naar de `drone-raw` bucket.
*   **Bestand**: `projects/dijk-a/flight-2025/image_001.tiff`
*   **Versie**: Dankzij bucket versioning krijgt elk bestand een uniek `VersionID`.

### Stap 2: Verwerking (Stitching)
Een **Tekton** pipeline start een container met **OpenDroneMap (ODM)** of **GDAL**.
*   **Input**: Leest de raw images direct uit `s3://drone-raw`.
*   **Process**: "Stitcht" de losse foto's aan elkaar tot één grote kaart (Orthophoto).
*   **Output**: Schrijft het resultaat naar `s3://drone-ortho/dijk-a-merged.geotiff`.

### Stap 3: Object Herkenning (AI)
Zodra de nieuwe Orthophoto beschikbaar is, start de AI-job (bijvoorbeeld een **YOLOv8** model in een Python container).
*   **Input**: Leest de `merged.geotiff` uit MinIO.
*   **Inference**: Het model scant de foto op specifieke objecten (bijv. "Muskusrat klem" of "Beschadiging oever").
*   **Output**: 
    *   De gevonden locaties (coördinaten) worden opgeslagen in **PostGIS** (zie Database bouwblok).
    *   Annotated images (met bounding boxes) gaan terug naar MinIO `s3://ai-results/`.

### MetadataCatalogus (STAC)
Om overzicht te houden in deze miljoenen bestanden, gebruiken we de **SpatioTemporal Asset Catalog (STAC)** standaard. De metadata (waar is de foto gemaakt? wanneer? welke cloud-cover?) slaan we op in PostGIS (of een dedicated STAC server), maar de *link* wijst altijd naar de binary in MinIO (`href: s3://drone-raw/...`).

## 🔄 Integratie in Druppie
1.  **MCP Server**: We kunnen een MCP tool maken (`list_drone_images`) die de inhoud van de buckets aan de AI toont.
2.  **Model Training**: Data Scientists koppelen hun Jupyter notebooks direct aan MinIO om nieuwe modellen te trainen.
3.  **Governance**: Via MinIO Policies (IAM) regelen we dat de "Stagiair" alleen mag lezen, en alleen de "Pipeline Service Account" mag schrijven in de `drone-ortho` bucket.
