# Hoe werkt ArchiMate (in Druppie)

Een korte uitleg van de ArchiMate-begrippen die je nodig hebt om de platen
in een technical design te lezen, te reviewen en te herzien. Het doel is
niet om ArchiMate volledig te leren, maar om de **kernbegrippen** scherp te
krijgen — vooral het verschil tussen het *model*, de *elementen* en de
*views*, want daar zit de meeste verwarring.

> **Korte versie:** een **element** (entiteit) bestaat **één keer** in het
> **model**. Een **view** is een diagram (plaat) dat een selectie van die
> elementen tóónt. Hetzelfde element kan in meerdere views verschijnen. Iets
> uit een view halen is niet hetzelfde als het uit het model verwijderen.

---

## 1. Het mentale model: model ↔ element ↔ view

ArchiMate scheidt **wat er is** van **hoe je het tekent**. Dat zijn drie
lagen die je uit elkaar moet houden:

| Begrip | Wat het is | In Druppie |
|--------|-----------|------------|
| **Model** | De volledige verzameling elementen + relaties van een project. De "waarheid". | Eén bestand: `docs/architecture.archimate` (Open Exchange XML) |
| **Element** (entiteit) | Eén bouwsteen: een applicatie, een proces, een server, een principe. Heeft een eigen identiteit (id). | Een `<element>` in het model |
| **Relatie** | Een formele verbinding tussen twee elementen (bv. "gebruikt", "realiseert"). | Een `<relationship>` in het model |
| **View** | Een diagram dat een **selectie** van elementen + relaties tóónt, met posities en kleuren. | Een `<view>` in hetzelfde model; gerenderd als SVG in `docs/diagrams/` |

### Waarom dit onderscheid ertoe doet

Een element leeft in het **model**, niet in een plaat. Een view *verwijst*
ernaar. Concreet:

- **Eén element, meerdere views.** De applicatie "Zaaksysteem" bestaat één
  keer in het model. Je kunt 'm tonen in een Applicatie-Cooperation-view én
  in een Technology-view. Het is in beide views *hetzelfde* element — wijzig
  je z'n naam, dan verandert hij overal mee.
- **Een element uit een view halen ≠ verwijderen.** Haal je "Zaaksysteem"
  weg uit één view, dan staat hij nog steeds in het model en in alle andere
  views. Pas als je het *element* verwijdert, is het echt weg (en cascadeert
  dat naar al z'n relaties en alle views waarin het stond).
- **De plaat is een projectie.** Twee verschillende views van hetzelfde
  model kunnen er totaal anders uitzien terwijl de onderliggende
  architectuur identiek is.

Vergelijk het met een database: het **model** is de tabel met records
(elementen), een **view** is een `SELECT` die een subset toont in een
bepaalde volgorde/opmaak. Je verwijdert geen record door 'm uit één query
weg te laten.

---

## 2. Elementen — de entiteiten, geordend per laag

Elk element hoort bij een **laag**. De laag bepaalt de betekenis (en in
Rijnland-platen ook de kleur — zie §6). De vier lagen die je het meeste
tegenkomt:

| Laag | Waarvoor | Voorbeeldtypes |
|------|----------|----------------|
| **Business** | Wat de organisatie doet, los van IT | Business Process, Business Actor/Role, Business Service |
| **Application** | De applicaties en wat ze leveren | Application Component, Application Service, Application Function |
| **Technology** | Infrastructuur waarop het draait | Node, Device, System Software, Technology Service |
| **Motivation** | Het "waarom": eisen, principes, drijfveren | Driver, Principle, Requirement, Constraint |

Daarnaast bestaan o.a. de **Implementation**-laag (bv. `Plateau`,
`Work Package`) en grouping-elementen (zoals een `Grouping` voor een
beveiligingsdomein).

**Vuistregel actief vs. gedrag:** een *structuur*-element (component, node)
is een doos die "iets is"; een *gedrag*-element (service, function, process)
beschrijft "iets dat gebeurt". Dat onderscheid bepaalt de vorm in de plaat.

---

## 3. Relaties — de belangrijkste in één regel

Relaties zijn **gericht** (van bron naar doel) en hebben een betekenis. De
zes die je het vaakst nodig hebt:

| Relatie | Betekenis | Typisch gebruik |
|---------|-----------|-----------------|
| **Composition / Aggregation** | "bestaat uit" / "groepeert" | Een systeem dat subcomponenten bevat; wordt visueel *geneste* dozen |
| **Serving** | "levert dienst aan" | Een service die een proces of andere component bedient |
| **Realization** | "verwezenlijkt" | Een component die een service realiseert; een oplossing die een eis invult |
| **Flow** | "stroom van info/goederen naar" | Gegevensstroom tussen twee gedrag-elementen |
| **Triggering** | "zet in gang" | Een proces/event dat het volgende proces start |
| **Access** | "leest/schrijft data" | Een proces dat een data-object benadert (met read/write-richting) |

De richting is niet vrijblijvend: een Realization van service → component is
fout (het is component → service). De `validate_view`-tool controleert dit
soort regels automatisch.

---

## 4. Views & viewpoints

Een **view** is een plaat met een doel. Een **viewpoint** is het "sjabloon"
dat bepaalt welke soort elementen erin horen en hoe ze geordend worden.
Druppie bouwt platen met twee standaard-viewpoints:

- **Layered** — de lagen boven elkaar (Business boven, Application midden,
  Technology onder), met optioneel Motivation. Voor een cross-layer
  blueprint van een hele oplossing.
- **Application Cooperation** — applicaties naast elkaar met hun onderlinge
  koppelingen en gedeelde services. Voor het applicatielandschap.

### De plaat in het technical design

In `docs/technical-design.md` staat de plaat niet als XML, maar als een
verwijzing naar een view-id:

````
```archimate
view-id: <uuid>
file: docs/architecture.archimate
```
````

De TD-viewer haalt het `.archimate`-bestand op en rendert de genoemde view
interactief (pan/zoom). Eén model-bestand, één view-id per plaat in de TD.

**ArchiMate vs. Mermaid:** ArchiMate is voor **structurele** architectuur
(componenten, lagen, relaties). Gedrag in de tijd — sequence, state, flow,
ER — blijft Mermaid. De twee zijn complementair; een TD kan beide bevatten.

---

## 5. Hoe Druppie een plaat bouwt (kort)

1. De architect bouwt de hele plaat in **één call** met een composite
   builder: `add_layered_view` of `add_cooperation_view` (view + elementen +
   relaties tegelijk). Voor losse aanpassingen op een bestaande plaat zijn er
   primitieve tools (`create_element`, `create_relationship`, `add_to_view`,
   `add_connection_to_view`, …).
2. `validate_view` is de kwaliteitsgate: het controleert metamodel-regels
   (relatierichting, Access-richting, naam/type) én de Rijnland-tekenregels.
3. `save_model` schrijft het model naar `docs/architecture.archimate` **en**
   exporteert per view een SVG naar `docs/diagrams/` (zodat Gitea de plaat
   inline toont).
4. De architect schrijft de TD via `submit_design_for_review` met het `archimate`-blok.

> **Eén goedkeurmoment.** De afzonderlijke archimate-tools zijn *ongated* —
> de architect bouwt de plaat vrij. Het enige menselijke goedkeurpunt is de
> `submit_design_for_review`-call op de technical design: de reviewer ziet daar de
> markdown én de gerenderde plaat als één geheel en keurt de TD in z'n
> geheel goed.
>
> Bij een revisie past de architect **alleen de gevraagde delta** toe op de
> bestaande view (nooit de plaat opnieuw genereren), zodat posities behouden
> blijven en de reviewer een herkenbare diff ziet.

---

## 6. Rijnland-tekenregels — kort

Voor waterschap-platen (Rijnland/HHR) gelden bovenop standaard-ArchiMate een
paar **tekenafspraken**. Het volledige overzicht (13 sheets) staat in
[`docs/archimate-rijnland-tekenafspraken.md`](archimate-rijnland-tekenafspraken.md);
hier de kern:

- **Kleur = laag.** De kleur van een element volgt z'n laag, consistent over
  alle platen. (Beveiligingszones zijn de uitzondering: die kleuren op
  trust-niveau volgens NORA.)
- **Vast vocabulaire + stereotypes.** Bepaalde begrippen hebben een vaste
  ArchiMate-type-keuze en een `«stereotype»`-label (bv. «Account»,
  «Beveiligingsdomein»). Een stereotype op het verkeerde type wordt
  geweigerd.
- **Actief vs. gedrag op eigenaarschap.** De vormkeuze (structuur- vs.
  gedrag-element) volgt wie iets bezit/uitvoert.
- **Beveiligingsdomeinen.** Een `Grouping` met `«Beveiligingsdomein»` en een
  trust-niveau; systemen nesten erin via Composition/Aggregation.
- **Relatie-conventies.** Flow voor gegevensstromen, Access met
  read/write-richting, Serving in de juiste richting tussen lagen.

`validate_view` dwingt het meeste hiervan af, dus afwijkingen komen al tijdens
het bouwen naar boven in plaats van pas bij de review.

---

## Samengevat

- Het **model** is de waarheid; **views** zijn projecties ervan.
- Een **element** bestaat één keer en kan in meerdere views staan; uit een
  view halen ≠ verwijderen.
- **Relaties** zijn gericht en betekenisvol; richting doet ertoe.
- Druppie bouwt platen met **composite builders**, valideert met
  `validate_view`, persisteert met `save_model`, en kent **één**
  goedkeurmoment: de `submit_design_for_review`-gate op de TD.
- Voor waterschap-platen gelden de **Rijnland-tekenregels** (kleur = laag,
  vocabulaire, stereotypes, beveiligingsdomeinen) — kort hier, volledig in
  `archimate-rijnland-tekenafspraken.md`.
