# Druppie Chat UI

De **Druppie Chat UI** is de interface voor de "Mens-in-de-Loop" interactie binnen het Druppie platform. Hier kunnen gebruikers chatten met de AI-agenten, plannen goedkeuren, componenten inspecteren en de status van taken volgen via een dynamisch Kanban-bord.

## 📱 PWA Support (Mobile)

De UI is volledig geoptimaliseerd voor mobiel gebruik als een **Progressive Web App (PWA)**.
*   **Installatie**: Voeg de pagina toe aan je startscherm op iOS of Android voor een app-achtige ervaring.
*   **Native Feel**: Full-screen weergave, aangepaste status bar (Dark Blue), en touch-vriendelijke interface.
*   **Naadloze Navigatie**: Schakel eenvoudig tussen de Chat UI en het Architecture Portal zonder de app-context te verlaten.

## 🚀 Features

1.  **Chat Interface**: 
    *   Directe communicatie met de Druppie Core agenten.
    *   Syntax highlighting voor code blocks.
    *   Rendering van markdown responses.

2.  **Kanban Bord**: 
    *   Real-time visualisatie van de Agent Workflow.
    *   Statussen: *Pending*, *Waiting for Input*, *Running*, *Completed*.
    *   Inzicht in welke agent (b.v. Architect, Developer) aan welke taak werkt.

    *   **Plan Review**: Goedkeuren, aanpassen of afwijzen van door AI gegenereerde implementatieplannen.
    *   **Feedback**: Geef sturing tijdens het proces.
    *   **Task Controls**: 
        *   **Cancel**: Stop een taak of plan direct ("Cancel Task/Plan").
        *   **Resume**: Hervat een gestopt of gecrasht plan ("Resume").
        *   **Visual Status**: Geannuleerde taken worden rood gemarkeerd voor duidelijkheid.

4.  **Tools & Files**: 
    *   File Upload functionaliteit voor context.
    *   Slash commands (e.g. `/list`, `/stop`) voor snelle acties.

## 🛠️ Access & Deployment

De UI wordt automatisch meegeleverd in de `druppie` Docker container.

*   **URL**: `http://localhost:8080/ui/`
*   **Backend**: Communiceert met de Druppie Core API (default port 8080).

### Lokale Ontwikkeling
De UI bestaat uit een enkele, self-contained `index.html`.

1.  Zorg dat de backend draait (`./druppie serve` of via Docker).
2.  Open `ui/index.html` direct in de browser (voor layout tests) of via de backend server (voor API functionaliteit).
