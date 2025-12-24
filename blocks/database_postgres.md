---
id: database-postgres
name: Database Cluster (PostgreSQL)
type: block
description: "High-availability PostgreSQL cluster using CloudNativePG operator."
capabilities: ["relational-database", "backups", "ha"]
version: 1.0.0
auth_group: []
---
# Database Cluster (PostgreSQL)

## 🎯 Selectie: CloudNativePG (CNPG)
Voor de relationele database oplossing binnen het Druppie platform is gekozen voor **CloudNativePG (CNPG)**. Dit is een Kubernetes-native operator die volledig is ontworpen om PostgreSQL-clusters te beheren binnen een containeromgeving.

### 💡 Onderbouwing van de Keuze
De keuze voor CloudNativePG is gebaseerd op de volgende criteria die essentieel zijn voor de betrouwbaarheid van Druppie:

1.  **Kubernetes Native**: CNPG breidt de Kubernetes API uit met een `Cluster` resource. In plaats van complexe statefulsets te beheren, definieer je simpelweg de gewenste staat van je database in YAML.
2.  **High Availability (HA)**: Automatische failover en "self-healing" functionaliteit. Als de primaire node uitvalt, promoveert de operator automatisch een standby node.
3.  **Backups & Disaster Recovery**: Ingebouwde ondersteuning voor Point-In-Time Recovery (PITR) naar object storage (zoals S3 of Azure Blob Storage).
4.  **Immutable Application support**: CNPG beheert de connectie via services en secrets die automatisch worden geüpdatet, wat naadloos aansluit bij de *Runtime* applicaties van Druppie.
5.  **Open Source & Community**: Oorspronkelijk ontwikkeld door EDB, maar nu een volledig open-source project met een zeer actieve community.

---

## 🛠️ Installatie

De operator wordt geïnstalleerd op het cluster en beheert vervolgens alle database instanties.

### 1. Installatie via Manifest
De snelste manier om de operator te installeren:

```bash
kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.21/releases/cnpg-1.21.0.yaml
```

Controleer of de operator draait:
```bash
kubectl get pods -n cnpg-system
```

*(Alternatief kan installatie ook via Helm chart `cnpg/cloudnative-pg`)*

---

## 🚀 Gebruik

Net als bij andere bouwblokken, definiëren we een database declaratief. De **Builder Agent** kan deze definities genereren wanneer een applicatie opslag nodig heeft.

### 1. Database Cluster Definitie
Een voorbeeld van een High-Available cluster met 3 instances (1 Primary, 2 Replicas):

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: druppie-core-db
spec:
  instances: 3
  
  # Opslag configuratie
  storage:
    size: 10Gi
  
  # Backup configuratie (optioneel voorbeeld)
  backup:
    barmanObjectStore:
      destinationPath: s3://druppie-backups/
      endpointURL: http://minio:9000
      s3Credentials:
        accessKeyId:
          name: backup-secret
          key: key
        secretAccessKey:
          name: backup-secret
          key: secret
```

### 2. Connecteren vanuit Applicaties
Zodra het cluster draait, maakt CNPG automatisch de volgende resources aan die door applicaties gebruikt kunnen worden:

*   **Service (`druppie-core-db-rw`)**: Een stabiel endpoint voor schrijfoperaties (Primary).
*   **Service (`druppie-core-db-ro`)**: Een stabiel endpoint voor leesoperaties (Read-Only replicas).
*   **Secret (`druppie-core-db-app`)**: Bevat de inloggegevens (`username`, `password`, `dbname`, `host`).

*Voorbeeld Pod gebruik:*
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-met-db
spec:
  containers:
  - name: app
    image: my-app:latest
    env:
      - name: DB_HOST
        value: druppie-core-db-rw
      - name: DB_USER
        valueFrom:
          secretKeyRef:
            name: druppie-core-db-app
            key: username
      - name: DB_PASS
        valueFrom:
          secretKeyRef:
            name: druppie-core-db-app
            key: password
```

## 🔄 Integratie in Druppie
1.  **Spec-Driven**: Een applicatie specificeert in zijn definitie "Ik heb een database nodig".
2.  **Builder Agent**: Genereert de `Cluster` YAML definitie en voegt de juiste environment variabelen toe aan de Deployment manifest van de applicatie.
3.  **Runtime**: Bij het deployen van de applicatie zorgt de operator dat de database beschikbaar is en de applicatie direct kan verbinden.
