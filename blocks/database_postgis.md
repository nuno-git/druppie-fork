---
id: postgis
name: Geo-Database (PostGIS)
type: block
version: 1.0.0
auth_group: []
description: "Opslag en verwerking van geografische data"
capabilities: []
---

# Geo-Database (PostGIS)

## 🎯 Selectie: CloudNativePG (met PostGIS)
Voor de opslag en verwerking van geografische data binnen het Druppie platform kiezen we voor dezelfde operator als voor de standaard databases: **CloudNativePG (CNPG)**. Echter, specifieke configuratie is vereist om de **PostGIS** extensie mogelijk te maken.

### 💡 Onderbouwing van de Keuze
Het hergebruiken van de CloudNativePG operator voor geospatiale data biedt grote voordelen:

1.  **Uniform Beheer**: Beheer, backup, failover en monitoring werken exact hetzelfde als voor standaard PostgreSQL databases. Dit vermindert de operationele complexiteit voor de *Run Experts*.
2.  **Bewezen Technologie**: PostGIS is de de-facto standaard voor open-source GIS. Het biedt krachtige features voor spatial queries, indexering en analyse die essentieel zijn voor waterschapstaken (dijken, watergangen, assets).
3.  **Kubernetes Native**: Door simpelweg een andere container image te specificeren in de CNPG `Cluster` definitie, rollen we een volledige GIS-stack uit zonder nieuwe infrastructuur componenten toe te voegen.

---

## 🛠️ Installatie

De operator (CloudNativePG) is naar verwachting al geïnstalleerd (zie [PostgreSQL Bouwblok](./database_postgres.md)). Er is geen aparte installatie nodig; we hoeven alleen maar een andere configuratie toe te passen bij het aanmaken van het cluster.

---

## 🚀 Gebruik

Om een PostGIS database te krijgen, moeten we twee dingen doen in de `Cluster` definitie:
1.  Een **Docker image** kiezen waar PostGIS al in is geïnstalleerd (bijv. de officiële `postgis/postgis` images).
2.  De extensie **activeren** na het opstarten (via `CREATE EXTENSION postgis;`). Dit kan geautomatiseerd worden met een `postInitSQL` command.

### 1. PostGIS Cluster Definitie
Hieronder een voorbeeld definitie voor een GIS-cluster. Let op de `imageName` en `postInitSQL`.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: druppie-geo-db
spec:
  instances: 2
  
  # Specifieke PostGIS image (ipv standaard postgres)
  imageName: ghcr.io/cloudnative-pg/postgis:16
  
  # Opslag (GIS data is vaak groot, dus ruim kiezen)
  storage:
    size: 50Gi
  
  # Automatisch de extensie aanzetten na init
  bootstrap:
    initdb:
      postInitSQL:
        - "CREATE EXTENSION IF NOT EXISTS postgis;"
        - "CREATE EXTENSION IF NOT EXISTS postgis_topology;"
  
  # Monitoring aanzetten is cruciaal voor zware GIS queries
  monitoring:
    enablePodMonitor: true
```

### 2. Connecteren & Gebruik
Applicaties verbinden op exact dezelfde manier als bij de standaard database (via de generated Secrets en Services).

De applicatie (of *Builder Agent*) kan nu direct geospatiale queries uitvoeren:

*Voorbeeld SQL Query (via de applicatie):*
```sql
-- Zoek alle dijken binnen 500 meter van een punt
SELECT naam, type 
FROM waterkeringen 
WHERE ST_DWithin(
  geometrie,
  ST_GeomFromText('POINT(134000 450000)', 28992),
  500
);
```

## 🔄 Integratie in Druppie
1.  **Capability Check**: Als een gebruiker vraagt om "Kaart functionaliteit" of "Locatie gebaseerde analyse", selecteert de **Planner** dit bouwblok in plaats van de standaard database.
2.  **Builder Agent**: 
    *   Genereert de `Cluster` YAML met de PostGIS image.
    *   Weet dat hij SQL queries kan genereren die gebruik maken van `ST_` functies (spatial types).
3.  **Foundry**: Rolt de container uit en zorgt dat de zware GIS berekeningen voldoende CPU/RAM limieten krijgen toegewezen.
