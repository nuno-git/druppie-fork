---
name: technical-research-format
description: >
  Format template for docs/technical-research.md. Use this skill when writing
  the technical research document during the architect phase.
---

# Technisch Onderzoek

## Inleiding

### Onderwerp
[Korte beschrijving van wat onderzocht wordt — samengevat uit de FD.]

### Onderzoeksvraag
[Welke architectuurkeuze moet dit onderzoek ondersteunen? Formuleer als vraag.]

### Uitgangspunten
[Relevante platform-standaarden, NORA-lagen, Water Authority principes en
harde constraints (wetgeving, bestaande systemen, PII) die elke oplossing
moet respecteren.]

## Overwogen Benaderingen

Beschouw minimaal 2, bij voorkeur 3 wezenlijk verschillende benaderingen.
Herhaal het onderstaande blok voor elke benadering.

### Benadering A — [naam]
* **Beschrijving:** [hoe lost deze benadering het probleem op?]
* **Hergebruik:** [welke Druppie-modules, componenten of template-onderdelen?]
* **Voor- en nadelen:**
    | Aspect | Score | Toelichting |
    |--------|-------|-------------|
    | Complexiteit | + / - | ... |
    | Herbruikbaarheid | + / - | ... |
    | Operationele kosten | + / - | ... |
    | Risico | + / - | ... |
    | Fit met principes | + / - | ... |
* **Wanneer geschikt:** [in welk scenario zou je hiervoor kiezen?]

### Benadering B — [naam]
[idem]

### Benadering C — [naam]
[idem — overslaan alleen als er aantoonbaar geen derde zinvolle variant is]

## Externe Systeemkoppelingen (VERPLICHT)

Binnen Druppie worden koppelingen met externe systemen in principe
gerealiseerd als **MCP-modules**, zodat ze herbruikbaar zijn voor
toekomstige projecten. Afwijken van dit uitgangspunt mag, maar vereist
een expliciete onderbouwing.

### Inventarisatie koppelingen
| # | Extern systeem | Categorie | Richting | Protocol / auth | Sync/Async | Data (kort) |
|---|----------------|-----------|----------|------------------|-----------|-------------|
| 1 | ... | organizational / other | in / uit / beide | ... | ... | ... |
| 2 | ... | ... | ... | ... | ... | ... |

De kolom **Categorie** is bindend: `organizational` voor waterschap/HHR
systemen (bronsystemen, zaaksysteem, DMS, archiefsysteem, referentiedata,
waterschap-auth, …), `other` voor 3rd-party SaaS, publieke APIs, etc.

### Per koppeling: hergebruik-analyse
Herhaal per koppeling uit de tabel hierboven:

#### Koppeling 1 — [extern systeem]
* **Categorie:** organizational / other
* **Bestaande module gecheckt:** [zoekopdrachten via registry_search_modules
  en registry_list_modules + resultaat]
* **Beslissing (kies er exact één):**
    - [ ] REUSE — bestaande module `<module_id>` dekt de behoefte
    - [ ] EXTEND — bestaande module `<module_id>` wordt uitgebreid met
          tools: [namen + korte beschrijving]
    - [ ] NEW MODULE — nieuwe module `<voorgestelde_naam>` met tools:
          [namen + korte beschrijving]
    - [ ] PROJECT-SPECIFIC — geen module (**alleen toegestaan voor categorie
          `other`** — voor `organizational` is deze optie niet geldig)
* **Onderbouwing:** [waarom deze keuze; verwijs naar principes zoals
  hergebruik, loose coupling en standaardisatie.]
* **Direct integration rationale** (VERPLICHT als je PROJECT-SPECIFIC kiest,
  anders weglaten):
    - (a) Waarom is deze koppeling niet herbruikbaar voor toekomstige
          projecten?
    - (b) Waarom zou een module hier onevenredige overhead opleveren?
    - (c) Welk toekomstig hergebruik-risico accepteer je expliciet?
* **Impact op TD:** [wat verandert hierdoor in de component-structuur /
  integration points van het TD?]

#### Koppeling 2 — [extern systeem]
[idem]

### Samenvatting nieuwe/uitgebreide modules
| Module | Type | Tools | Reden |
|--------|------|-------|-------|
| ... | new / extend | ... | ... |

Rijen in deze tabel betekenen BUILD_PATH=CORE_UPDATE (zie Stap 2b).

## Aanbeveling

* **Gekozen benadering:** [A / B / C]
* **Rationale:** [verwijs naar de trade-off tabellen en de
  externe-koppelingen analyse.]
* **Afgeleide beslissingen voor TD:** [welke onderzoekskeuzes worden
  architectuurbeslissingen in docs/technical-design.md?]
* **Afgeleide Technical Requirements:** [welke onderzoeksuitkomsten
  moeten als TR-xx in het TD terechtkomen?]
* **Openstaande aannames/risico's:** [punten die gevalideerd moeten
  worden tijdens build/test of in een latere iteratie.]
