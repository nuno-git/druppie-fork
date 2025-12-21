# Bouwblok: Media & Brand Management (Headless CMS/DAM)

## 🎯 Doelstelling
Het centraliseren van rijke media (afbeeldingen, video's, 3D-modellen) en merkidentiteit in een **Headless Digital Asset Management (DAM)** systeem. Dit systeem moet:
1.  **Bron van Waarheid** zijn voor logo's, kleurcodes en media.
2.  **API-first** zijn, zodat AI Agents assets kunnen uploaden en ophalen.
3.  **Schaalbaar** draaien binnen Kubernetes.

## ⚙️ Technologie Selectie: Strapi

Na evaluatie van Pimcore (te zwaar), ResourceSpace (te monolithisch) en Directus, kiezen we voor **Strapi** als onze Headless CMS/DAM oplossing.

**Waarom Strapi?**
*   **Kubernetes-Native**: Eenvoudig te deployen als NodeJS container met een database backend (PostgreSQL).
*   **Media Library**: Ingebouwde, krachtige media management met plugin support (bijv. image optimalisatie).
*   **Gestructureerde Data**: Kan niet alleen bestanden opslaan, maar ook "Brand Guidelines" als gestructureerde content (kleurpaletten, typography regels) die Agents kunnen lezen.
*   **Extensible**: Volledig aanpasbaar via Javascript/Typescript.

### Integratie in Druppie
Strapi fungeert als de **Geheugenbank voor Creatieve Assets**.

*   **Input**: De AI Video pipeline uploadt de definitieve `.mp4` films naar Strapi.
*   **Output**: De Director Agent leest de "Corporate Identity" collectie om te weten welke hex-codes en font-files hij moet gebruiken in de video overlays.
*   **Opslag**: Strapi slaat de metadata op in Postgres en de binary files in **MinIO** (S3 compatible), wat perfect past in onze bestaande infrastructuur.

## 🛠️ Technische Implementatie

### Kubernetes Deployment
We draaien Strapi als een stateless Deployment, gekoppeld aan externe services.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: strapi-cms
spec:
  template:
    spec:
      containers:
      - name: strapi
        image: strapi/strapi:latest
        env:
          - name: DATABASE_CLIENT
            value: "postgres"
          - name: DATABASE_HOST
            value: "postgres-cluster"
          # S3 Plugin Configuratie (MinIO)
          - name: AWS_ACCESS_KEY_ID
            valueFrom:
              secretKeyRef:
                name: minio-creds
                key: accesskey
```

### Data Model (Content Types)

We definiëren twee kern collecties:

1.  **MediaAssets**:
    *   `title` (Text)
    *   `file` (Media)
    *   `tags` (JSON: bijv. `["scene_01", "approved"]`)
    *   `generated_by` (Relation: Agent ID)

2.  **BrandIdentity**:
    *   `primary_color` (Color Hex)
    *   `logo_light` (Media)
    *   `font_family` (Text)
    *   `voice_tone` (Text: "Professioneel en direct")

## ✅ Voordelen
*   **AI-Leesbaar**: Agents kunnen via REST/GraphQL direct vragen: "Geef mij het logo en de primaire kleur".
*   **Gecentraliseerd**: Geen rondslingerende bestandjes in git repo's.
*   **Schaalbaar**: Maakt gebruik van de reeds aanwezige Storage (MinIO) en DB (Postgres) infrastructuur.
