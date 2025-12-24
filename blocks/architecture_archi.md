---
id: archimate
name: Architectuur Modellering (Archi)
type: block
version: 1.0.0
auth_group: []
description: "Beheren van de Enterprise Architectuur conform de ArchiMate standaard"
capabilities: ["archimate"]
git_repo: "https://gitea.druppie.nl/blocks/archimate/archimate.git"
---

# Architectuur Modellering (Archi)

## 🎯 Selectie: Archi & Model Repository (coArchi)
Voor het vastleggen en beheren van de Enterprise Architectuur conform de **ArchiMate 3.2** standaard kiezen we voor **Archi**. Om samenwerking en versiebeheer mogelijk te maken, gebruiken we de **coArchi** plugin in combinatie met onze **Gitea** Git-server.

### 💡 Onderbouwing van de Keuze
Waarom Archi in een DevOps omgeving?
1.  **De Open Source Standaard**: Archi is de referentie-implementatie voor ArchiMate. Het is gratis, open-source en wordt breed gedragen.
2.  **Git-Based (coArchi)**: Dankzij de coArchi plugin wordt het model niet als één monolithisch bestand opgeslagen, maar als losse objecten/files in Git.
    *   Dit maakt **Merge Conflicts** beheersbaar.
    *   Het integreert naadloos met onze "Alles is Code" filosofie. Wijzigingen in de architectuur zijn commits in Gitea.
3.  **Automatisering (CLI)**: Archi heeft een Command Line Interface. We kunnen hiermee automatisch (via **Tekton**) rapporten en plaatjes genereren zodra een architect iets commit.
4.  **Machine Readable**: Het `.archimate` (XML) bestandsformaat is leesbaar voor onze **Builder Agent**. De AI kan de architectuur lezen om te "begrijpen" hoe componenten samenhangen voordat hij code gaat schrijven.

---

## 🛠️ Installatie

De tool bestaat uit een Client (voor de architect) en een Pipeline (voor publicatie).

### 1. Client Setup (Op laptop van Architect)
*   Download Archi 5.x+.
*   Installeer de [coArchi Plugin](https://github.com/archimatetool/archi-modelrepository-plugin).
*   Verbind met Gitea:
    *   URL: `https://gitea.druppie.nl/architectuur/enterprise-model.git`
    *   Auth: Gebruikersnaam + Token.

### 2. CI/CD Setup (In het Cluster)
We gebruiken een Docker container met de Archi CLI om rapporten te genereren in onze bouwstraat.

*Docker Image*: `ghcr.io/archi-contrib/docker-archi:latest`

Implementatie in een **Tekton Task**:
```yaml
apiVersion: tekton.dev/v1beta1
kind: Task
metadata:
  name: generate-archi-report
spec:
  steps:
    - name: export-html
      image: ghcr.io/archi-contrib/docker-archi:latest
      command:
        - /opt/Archi/Archi
        - -application
        - com.archimatetool.commandline.app
        - -consoleLog
        - -nosplash
        - --html.createReport
        - /workspace/output
        - --modelrepository.loadModel
        - /workspace/source
```

---

## 🚀 Gebruik: Van Model naar Publicatie

### Workflow
1.  **Modelleren**: De architect past het model aan in Archi (b.v. "Nieuwe applicatie toevoegen aan landschap").
2.  **Commit & Push**: Via de coArchi plugin "Publish Changes". Dit stuurt de wijzigingen naar Gitea.
3.  **Pipeline Trigger**: Gitea stuurt een webhook naar Tekton.
4.  **Generatie**:
    *   Tekton start de `docker-archi` container.
    *   Genereert een interactief HTML rapport.
    *   Genereert losse PNG's van alle views.
5.  **Publicatie**: De HTML wordt geüpload naar een webserver (bijv. via Nginx Ingress) op `https://architectuur.druppie.nl`.

### AI Integratie (Builder Agent)
De **Builder Agent** kan het model analyseren:
*   *Vraag*: "Welke applicaties gebruiken de 'Klant Database'?"
*   *Actie*: Agent leest de XML export (via MCP tool `read_repo`).
*   *Analyse*: Zoekt relaties `Serving` of `Access` richting het object `Klant Database`.
*   *Resultaat*: "Volgens het model gebruiken 'MijnOmgeving' en 'Facturatie' deze database."

## 🔄 Integratie in Druppie
1.  **Levende Documentatie**: Het architectuurmodel is geen statisch PDF in een lade, maar een levende website die altijd up-to-date is met de laatste commit.
2.  **Compliance**: Wijzigingen in de architectuur (bijv. toevoegen van een externe koppeling) zijn traceerbaar in Git (Wie? Wanneer? Waarom?). Dit ondersteunt de BIO/ISO audits.
3.  **Ontwerp Validatie**: Voordat een team begint met bouwen, checkt de Builder Agent of de voorgenomen oplossing past binnen de kaders van het ArchiMate model.
