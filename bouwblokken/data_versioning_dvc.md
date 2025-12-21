# AI Dataset Versioning (DVC)

## 🎯 Selectie: DVC (Data Version Control)
Voor het semantisch beheren van versies van datasets ("Trainingsset V1", "Validatieset V2.3") bovenop onze ruwe opslag kiezen we voor **DVC**. DVC brengt de kracht van Git naar grote data-bestanden, zonder dat die bestanden daadwerkelijk in Git worden opgeslagen.

### 💡 Onderbouwing van de Keuze
MinIO heeft *Object Versioning* (technisch), maar DVC biedt *Dataset Versioning* (logisch).
1.  **Git voor Data**: DVC werkt exact zoals Git. Data Scientists gebruiken commando's die ze al kennen (`dvc checkout`, `dvc commit`).
2.  **Meta-data in Git, Data in MinIO**:
    *   De grote bestanden (GB's aan Tiff's) blijven in MinIO.
    *   DVC maakt kleine pointer-files (`dataset.dvc`) aan.
    *   Deze pointer-files slaan we op in **Gitea**.
    *   Hierdoor is de relatie tussen *Code* (het model) en *Data* (de trainingsset) onlosmakelijk verbonden in één Git commit hash. Dit garandeert volledige reproduceerbaarheid.
3.  **CI/CD Integratie**: Omdat de dataset-definities in Git staan, kan **Tekton** automatisch een training pipeline starten zodra er een nieuwe dataset-versie wordt gepusht.

---

## 🛠️ Installatie

DVC is een command-line tool en Python library. Er hoeft geen server geïnstalleerd te worden op het cluster; het maakt gebruik van de infrastructuur die er al is (Gitea + MinIO).

Wel kunnen we een (optionele) **DVC Studio** of een visualisatie-tool hosten, maar de kern werkt client-side.

### 1. Configuratie in Project
Een Data Scientist initialiseert DVC in zijn project repo (op zijn laptop of in een DevContainer):

```bash
# In de git repo
dvc init

# Stel MinIO in als 'remote' storage
dvc remote add -d my-minio s3://ai-datasets
dvc remote modify my-minio endpointurl https://minio.druppie.nl
dvc remote modify my-minio access_key_id AR_IS_EEN_KEY
dvc remote modify my-minio secret_access_key SUPER_GEHEIM
```

---

## 🚀 Gebruik: Een Gecontroleerde Dataset Maken

Stel we hebben een map `data/raw_images` met 10.000 drone foto's.

### Stap 1: Tracken van Data
```bash
dvc add data/raw_images
```
Dit doet 2 dingen:
1.  Uploadt de bestanden naar MinIO.
2.  Maakt `data/raw_images.dvc` aan (bevat MD5 hashes van de data).

### Stap 2: Versie Vastleggen (Git)
We committen de pointer naar Gitea.
```bash
git add data/raw_images.dvc .gitignore
git commit -m "Dataset V1: Initiële drone set"
git push
```

### Stap 3: Werken met Versies
Stel een collega (of de **Builder Agent**) wil het model trainen op deze specifieke versie.

```bash
git clone https://gitea.druppie.nl/projecten/drone-ai.git
dvc pull
```
DVC ziet de hash in het `.dvc` bestand, haalt exact die versie van de bestanden uit MinIO, en plaatst ze in de werkmap.
Zelfs als de dataset inmiddels is aangepast naar V2, haalt deze commit altijd V1 op.

## 🔄 Integratie in Druppie (MLOps)
1.  **Reproduceerbaarheid (Compliance)**: Als een auditor vraagt "Op welke data is dit model getraind?", wijzen we naar de Git commit hash. Via DVC kunnen we bewijzen welke bestanden dat waren.
2.  **Pipeline Triggering**:
    *   De *Builder Agent* ziet een update in de dataset (nieuwe `.dvc` file).
    *   Triggert een **Tekton** pipeline.
    *   Tekton doet `dvc pull` -> `python train.py` -> `dvc metrics log`.
    *   Het resultaat is een nieuw AI model.
