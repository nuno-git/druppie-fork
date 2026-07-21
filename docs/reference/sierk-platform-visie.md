# Druppie Platform Visie — Sierk Hoeksma

> Origin repo: [sjhoeksma/druppie](https://github.com/sjhoeksma/druppie) — de visie
> waaruit deze fork is ontstaan. Dit document is een samenvatting van de
> oorspronkelijke projectbrief, README, en story documenten, plus het verhaal
> van Druppie zoals gepresenteerd binnen de Waterschappen.

---

## Het Verhaal van Druppie

Druppie is een AI-assistent ontwikkeld om te helpen bij het beheer van water
door Waterschappen.

### De Strategische Verschuiving

De kern van de Vaarkaart is de beweging van traditionele automatisering naar
een fundamentele digitale transformatie.

- **Van 'Samen Doen' naar 'Samenwerken als Concern'** — de 21 waterschappen
  moeten niet langer allemaal hun eigen IT-wiel uitvinden. Het doel is opereren
  als één concern om schaalvoordeel te behalen, kosten te drukken en kwaliteit
  te verhogen.
- **Datagedreven Waterbeheer** — de focus verschuift van het beheren van
  systemen naar het waardevol maken van data. Data wordt gezien als een
  strategisch asset om wateroverlast, droogte en waterkwaliteit beter te
  voorspellen en te beheren.
- **Uniformiteit als Basis** — om data uitwisselbaar te maken en samen te
  kunnen werken, is standaardisatie van processen en techniek noodzakelijk.

### De Pijlers van de Transformatie

- **Informatieveiligheid & Privacy (IBP)** — waterbeheer is vitale
  infrastructuur, cyberveiligheid is topprioriteit. Focus op weerbaarheid en
  voldoen aan wetgeving (BIO, NIS2).
- **De Digitale Werkplek** — een moderne, plaatsonafhankelijke werkomgeving
  die samenwerking tussen waterschappen en ketenpartners naadloos maakt.
- **Dataplatforms & Cloud** — de beweging naar de cloud om enorme hoeveelheden
  sensordata en satellietbeelden te kunnen verwerken.
- **Innovatie & Nieuwe Technologie** — actieve inzet van Digital Twins en
  Artificial Intelligence voor voorspellend onderhoud en peilbeheer.

### Verschillende Perspectieven — De Avatar Architectuur

Elke laag vertegenwoordigt een ander perspectief in een gelaagde architectuur
die het fundament vormt voor een veilig, compliant en innovatief AI assistent.

Wat Druppie uniek maakt, is het gebruik van meerdere **avatars**: elk avatar
staat voor een specifieke AI-expert met eigen vaardigheden en kennis, direct
gekoppeld aan menselijke expertise binnen het waterschap:

- **Gebruiker avatar** — stelt de vraag en krijgt het antwoord
- **Kennis avatar** — stelt eigen kennisbronnen voor de AI ter beschikking
- **Juridische avatar** — waarborgt naleving van wet- en regelgeving
- **Security avatar** — zorgt voor veiligheid en privacy
- **Data avatar** — beheert en ontsluit data
- **Ontwikkelaar avatar** — bouwt en test oplossingen
- **Architect avatar** — bewaakt de technische structuur

De mens blijft altijd in control: elke AI-avatar werkt samen met de gebruiker
en experts, zodat de digitale transformatie verantwoord en uitlegbaar verloopt.

### Van Visie naar Uitvoering

Digitale transformatie is geen gewoon project maar een verandertraject met
impact op de gehele organisatie. Gekozen is voor een natuurlijk proces van
**Leren, Experimenteren en Verbeteren**:

- **Stuurgroep** — bepaalt richting en scope, zorgt voor middelen en
  voorwaarden
- **Support groep** — vult randvoorwaarden in voordat de verandering start en
  begeleidt tijdens de verandering
- **Team** — verantwoordelijk voor realisatie en borging binnen dagelijkse
  werkzaamheden
- **Minimal Viable Change / Product** — klein beginnen, iteratief verbeteren

---

## Wat is Druppie?

Druppie is niet zomaar een "Chatbot" of een "Automatiseringstool". Het is een
**Autonoom AI-Platform voor Data Toegang & Software Creatie & Beheer**,
specifiek ontworpen voor de Publieke Sector (Waterschappen).

In essentie is Druppie een "Collega" (AI Workforce) die functioneert als de
intermediair tussen de **Business** (de vraag van de medewerker) en de
**Techniek** (de code/infrastructuur).

- **Identiteit**: Druppie manifesteert zich als een vriendelijke waterdruppel,
  maar erachter schuilt een netwerk van gespecialiseerde AI-agenten die
  samenwerken.
- **Functie**: Het platform neemt de volledige lifecycle van digitale
  oplossingen over: van vraagarticulatie, ontwerp en toetsing aan wetgeving,
  tot de daadwerkelijke bouw, automatische uitrol en beheer.
- **Resultaat**: Een volledig werkbare digitale oplossing die voldoet aan alle
  bestuurlijke kaders, ambities en veiligheid.

### Waarom? (De Noodzaak)

1. **Explosieve Vraag** — de vraag naar digitale oplossingen groeit
   exponentieel, sneller dan de organisatie mensen kan werven of opleiden.
2. **Toenemende Complexiteit** — wetgeving (AVG, BIO, WOO) en techniek worden
   steeds complexer.
3. **Wildgroei & Veiligheid** — zonder centraal platform ontstaan "Shadow IT"
   oplossingen die onveilig en onbeheersbaar zijn.

### Wat Druppie NIET is

- ❌ Geen "Magic Button" zonder toezicht — Druppie werkt volgens Human-in-the-Loop,
  security-by-design, en privacy-by-design.
- ❌ Geen vervanging van de mens — Druppie neemt repetitief en complex technisch
  werk over. Mensen richten zich op het probleem en de creativiteit.
- ❌ Geen "ChatGPT Wrapper" — Druppie denkt in specificaties, voert echte acties
  uit (Git commits, data analyse, deployments) en valideert eigen werk.
- ❌ Geen SaaS pakket — het is een platform dat eigendom is van het Waterschap,
  draaiend op eigen infrastructuur, met volledige controle over data en modellen.

---

## Architectuur — Drie Planes

De architectuur volgt een strikte scheiding tussen de "Hersenen" (Core) en
"Handen" (Agents):

```
┌─────────────────────────────────────────────────────┐
│  Control Plane (Hersenen)                           │
│  Druppie UI → Core (Orchestrator) → Registry        │
│  → Router → Planner → Policy Engine                 │
├─────────────────────────────────────────────────────┤
│  Execution Plane (Handen)                           │
│  AI Workforce (Agents) → Skills → MCP               │
│  → Git → Foundry (CI/CD & Security)                 │
├─────────────────────────────────────────────────────┤
│  Runtime Plane (Resultaat)                          │
│  Gegenereerde Apps → Kubernetes Cluster             │
└─────────────────────────────────────────────────────┘
```

### De "Flow" — Hoe Druppie werkt

1. **De Vraag** — gebruiker stelt vraag in natuurlijke taal. Druppie vraagt
   door om specificaties helder te krijgen.
2. **De Analyse (Router)** — analyseert intentie: simpele vraag, registry
   search, of nieuw project.
3. **Het Ontwerp (Architect)** — vertaalt vraag naar Technisch Ontwerp en
   selecteert bouwblokken.
4. **De Toetsing (Policy Engine)** — toetst het plan aan bestuurlijk kader
   voordat er code geschreven wordt (AVG, BIO, data-toegang).
5. **De Realisatie (Builder & Foundry)** — genereert code, bouwt containers,
   scant op kwetsbaarheden (Trivy), genereert SBOM.
6. **De Uitrol (Runtime)** — automatische deploy naar runtime omgeving.

---

## Kernprincipes

1. **Alles is een Spec** — van infrastructuur tot agent-gedrag, alles wordt
   vastgelegd in leesbare specificatiebestanden.
2. **Human-in-the-Loop** — kritieke beslissingen vereisen altijd menselijke
   goedkeuring.
3. **Secure by Design** — security tools staan "aan" by default.
4. **Traceerbaarheid** — elke actie, van prompt tot deployment, wordt gelogd.

---

## Centrale AI Omgeving & Specificatie-Gestuurde AI

- **Wettelijke verplichting** — de EU AI-verordening vereist menselijk toezicht
  en risicobeheersing bij AI-gebruik.
- **Compliance by design** — regels en wetgeving worden automatisch toegepast.
- **Veiligheid & privacy** — alleen goedgekeurde tools en datatoegang op basis
  van rechten.
- **Transparantie & uitlegbaarheid** — AI-output is herleidbaar, met
  bronvermelding en logregistratie.
- **Specificatie gestuurd** — AI werkt op basis van vooraf vastgelegde regels
  en versies (spec-driven).
- **Controleerbare AI** — elke vraag en output wordt getoetst aan wet- en
  regelgeving.
- **Volledige traceerbaarheid** — elke stap wordt automatisch gelogd (audit
  trail).
