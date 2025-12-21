# Het AI Register (Algoritmeregister)

## 📘 Wat is het AI Register?
Overheidsorganisaties, waaronder waterschappen, zijn verplicht transparant te zijn over de inzet van algoritmes en AI. Dit is verankerd in de **AI Act** (Artikel 60: EU Database voor Hoog Risico AI) en de Nederlandse richtlijn voor het **Algoritmeregister** (algoritmeregister.overheid.nl).

Het register fungeert als de "publieke bijsluiter" van een AI-systeem. Het stelt burgers, journalisten en toezichthouders in staat om te controleren welke systemen impact hebben op hun leven of leefomgeving.

---

## 📋 Wat staat er in? (Het Schema)
Het register bevat **niet** de broncode, maar wel de metadata die de werking en risico's beschrijven. Binnen Druppie baseren we dit op de 'Standaard voor Algoritme-beschrijvingen'.

### Kerngegevens
1.  **Naam & Eigenaar**: Wie is verantwoordelijk? (bijv. "Waterschap X, afdeling Waterkeringen").
2.  **Doel**: Waarom is dit systeem gebouwd? (bijv. "Vroegtijdig detecteren van graverij door muskusratten om dijkdoorbraak te voorkomen").
3.  **Werking**: Hoe werkt het technisch? (bijv. "Computer Vision model getraind op dronebeelden").

### Risico & Impact
4.  **Risicoclassificatie**: Volgens de AI Act (Laag/Hoog/Verboden).
5.  **Impact**: Wat is het gevolg van een fout? (bijv. "Onterechte inzet van muskusrattenbestrijder" of "Gemiste kadebreuk").
6.  **Juridische Grondslag**: Op basis van welke wettaak handelen we? (Waterwet).

### Data & Toezicht
7.  **Data**: Op welke data is het getraind? (Verwijzing naar DVC dataset versie).
8.  **Menselijk Toezicht**: Hoe is de Human-in-the-Loop geregeld? (bijv. "Bestrijder valideert elke detectie vòòr actie").

---

## 🛠️ Hoe te vullen? (Automated Governance)
In traditionele organisaties is het register vaak een verouderde Excel-sheet. In Druppie is het registeren **geautomatiseerd en verplicht**.

### Stap 1: 'Register-as-Code'
Bij elk project hoort een `algorithm.yaml` bestand in de Git repository. De **Builder Agent** genereert de eerste opzet op basis van de interactie met de gebruiker.

*Voorbeeld `algorithm.yaml`:*
```yaml
metadata:
  name: "Muskusrat Detectie V2"
  owner: "Afd. Keringen"
  status: "In Productie"
legal:
  ground: "Waterwet Art. 5.1"
  risk_class: "Hoog" # Critical Infra
technical:
  model_type: "YOLOv8"
  training_data: "dvc://datasets/drone-2025-v1"
human_oversight:
  role: "Schadebeheerder"
  method: "Handmatige validatie via GeoNode"
```

### Stap 2: Validatie door Policy Engine
Tijdens de deployment (CI/CD) checkt de Policy Engine:
*   [ ] Is `algorithm.yaml` aanwezig?
*   [ ] Zijn alle verplichte velden ingevuld?
*   [ ] Klopt de 'training_data' link met de werkelijke DVC hash?
*   *Zo niet -> Deployment Failed.*

### Stap 3: Publicatie
Bij een succesvolle release naar Productie, pusht de pipeline de metadata automatisch naar:
1.  Het **Interne Register** (in Archi/GeoNode).
2.  Het **Publieke Register** (via API koppeling met `algoritmeregister.overheid.nl`).

---

## 🚀 Hoe te gebruiken?
1.  **Voor de Burger**: Via de website van het Waterschap kan men zoeken in het register. "Welke AI wordt gebruikt in mijn polder?"
2.  **Voor de Toezichthouder (AP)**: Bij een audit hoeven we niets handmatig op te zoeken. Het register is de "Single Source of Truth", direct gekoppeld aan de draaiende techniek.
3.  **Voor de Data Scientist**: Ziet direct of zijn model correct geregistreerd staat en wie de 'Human-in-the-loop' is.
