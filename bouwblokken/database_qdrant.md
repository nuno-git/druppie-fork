# Vector Database (Qdrant)

## 🎯 Selectie: Qdrant
Voor het opslaan en doorzoekbaar maken van onze AI-kennis (Embeddings) kiezen we voor **Qdrant**.

### 💡 Onderbouwing van de Keuze
Waarom Qdrant boven alternatieven zoals Weaviate, Pinecone of pgvector?

1.  **Performance & Resource Efficiency**: Qdrant is geschreven in **Rust**. Dit maakt het extreem snel en geheugenefficiënt, wat perfect past bij onze kubernetes-gebaseerde infrastructuur waar resources soms schaars zijn.
2.  **Native Faceted Filtering (ACLs)**: Qdrant blinkt uit in "Filtered Search". Dit is **cruciaal** voor onze *Secure RAG* eis. We kunnen heel efficiënt zoeken: *"Geef de top 10 vectoren die lijken op deze vraag, MAAR alleen als `metadata.group IN ['finance', 'admin']`"*. Veel andere databases worden traag bij complexe filters ("Post-filtering"), Qdrant doet dit tijdens het zoeken ("Pre-filtering/HNSW").
3.  **Kubernetes-Native**: Qdrant is ontworpen als cloud-native distributed system. Het schaalt makkelijk horizontaal mee met onze pods.
4.  **Open Source**: Volledig open source en self-hostable (geen vendor lock-in of data die naar een Amerikaanse cloud service lekt).

*(Noot: pgvector in PostgreSQL is goed voor simpele use-cases, maar mist de geavanceerde filtering en snelheid van een dedicated vector engine zoals Qdrant bij miljoenen vectoren.)*

---

## 🛠️ Installatie

We draaien Qdrant als een StatefulSet in de **Runtime**.

### Installatie via Helm
```bash
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm upgrade --install qdrant qdrant/qdrant \
  --namespace data-system --create-namespace \
  --set replicaCount=3 \
  --set persistence.size=50Gi
```

---

## 🚀 Gebruik: Van Tekst naar Vector

Dit bouwblok wordt gebruikt door de **Ingest Agent** en de **RAG Agent**.

### 1. Opslaan (Upsert)
Wanneer de Ingest Agent een document verwerkt:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

client = QdrantClient(host="qdrant.data-system", port=6333)

client.upsert(
    collection_name="bedrijfs_kennis",
    points=[
        PointStruct(
            id=123,
            vector=[0.1, 0.9, ...], # De AI betekenis (Embedding)
            payload={ # De Metadata
                "filename": "begroting_2025.pdf",
                "text_snippet": "Het totaalbedrag is 1M...",
                "acls": ["group:finance", "user:jan"] 
            }
        )
    ]
)
```

### 2. Zoeken met Beveiliging (Search)
Wanneer Jan (lid van 'engineering') iets vraagt:

```python
search_result = client.search(
    collection_name="bedrijfs_kennis",
    query_vector=[0.1, 0.9, ...], # De vraag vector
    query_filter=Filter(
        must=[
            FieldCondition(
                key="acls",
                match=MatchAny(any=["group:engineering", "group:public"])
            )
        ]
    )
)
```
De database geeft **alleen** resultaten terug die Jan mag zien. Dit gebeurt op database-niveau, dus de applicatie kan niet per ongeluk iets lekken.

## 🔄 Integratie in Druppie
*   **Traceability**: Elke 'hit' in de vector database kan gelogd worden, zodat we weten welke kennisbronnen zijn gebruikt voor een antwoord.
*   **Backups (Velero)**: Omdat Qdrant op een Persistent Volume draait, wordt deze automatisch meegenomen in de standaard backup policy.
