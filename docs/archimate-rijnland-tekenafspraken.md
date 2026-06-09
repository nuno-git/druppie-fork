# Analyse — Rijnland/HHR ArchiMate Tekenafspraken (13 sheets)

Bron: `volledigetekenafspraken.zip` — ArchiMate-tekenafspraken van HHR (Hoogheemraadschap van Rijnland)
+ HHSK (Schieland en de Krimpenerwaard). Gemaakt in **Bizzdesign/HoriZZon**. Refereren aan
**WILMA**, **NORA**, **BIO**, **NEN-ISO/IEC 27002:2022**, **IEC-62443**.

## 0. De rode draad — dit is één samenhangend systeem

De 13 sheets zijn geen losse plaatjes maar één **conventie-stelsel** met drie assen:

1. **Vast vocabulaire** — elk bedrijfs/applicatie/technologie-begrip is vastgepind op één ArchiMate-type
   mét eigen semantiek (bv. Account = *Bedrijfsrol*, niet Actor; Applicatie = *Applicatiecomponent*;
   Applicatie als service = *Applicatieservice*).
2. **Vaste visuele taal** — kleur = laag, vorm = actief/gedrag, stereotype = subtype.
3. **Vaste model-organisatie** — Bizzdesign-mappen A/C/E met IST vs SOLL vs doel-architectuur.

## 1. Kleurcodering (laag-gebaseerd, consistent over álle sheets)

| Laag | Kleur | Elementen |
|------|-------|-----------|
| **Business** | geel | Account, Bedrijfsfunctie, Bedrijfssubfunctie, Bedrijfsrol, Bedrijfsproces, Bedrijfsactiviteit, Bedrijfsactor (Waterschap/tenant, Hosting partij, Registrar) |
| **Application** | blauw | Applicatie, Applicatie als service, 'Eigen' Portaal, 'Extern' Portaal, 'Externe' informatiebron, Applicatiefunctie (bouwblok), Dataobject, Website, Applicatieproces, Applicatie-interface, Applicatie-event |
| **Technology** | groen | Systeem software, Programmeeromgeving, Technologieservice, Technologieproces, Artefact, MS Azure resources, Hostingdienst, Domein registratie, Deployed Resource |
| **Motivation** | paars | Driver (Drijfveren/Wet/Regelgeving), Principe, Requirement, Beperking (Constraint), Standaarden/normen, Usecase, Assessment/Observatie, Metriek |
| **Implementation & Migration** | roze/magenta | Plateau, Programma/Project, Wijziging/project |

**Uitzondering (belangrijk):** een **Constraint die een beveiligingsniveau weergeeft** volgt NIET de standaard
paarse Motivation-kleur, maar de **NORA-beschouwingsmodel-kleuren** (groen=semi-vertrouwd, geel=vertrouwd, etc.).

## 2. Vast vocabulaire met strikte definities (Definities + Programmeeromgevingen)

**Business:**
- **Account** → getekend als **Bedrijfsrol**. Intern samenwerkingsverband dat de informatievoorziening van
  1+ WILMA bedrijfs(sub)functies bespreekt/coördineert. Deelnemers: accountmanager + ICO/AVIM.
- **Bedrijfsfunctie** → capability ("wat de organisatie kan", niet wanneer/volgorde). **Uit WILMA.**
- **Bedrijfssubfunctie** → onderdeel van een bedrijfsfunctie. **Uit WILMA.**

**Application:**
- **Applicatie** → **Applicatiecomponent**. Zelfstandig inzetbaar/vervangbaar, ondersteunt gebruiker in CRUD
  van bedrijfsgegevens. Incl. APP + Webapplicatie.
- **Applicatie als service** → **Applicatieservice** (afgeronde vorm). SaaS, incl. onderliggende infra.
- **'Eigen' Portaal** → toegankelijk voor derden, waterschap = eigenaar/producent content.
- **'Extern' Portaal** → portaal/app van derde; één instance bedient meerdere klanten. (Niet altijd in CMDB.)
- **'Externe' informatiebron** → **specialisatie/subtype van 'Extern' Portaal**; externe partij biedt data, géén
  waterschap-data opgeslagen.
- **Applicatiefunctie (bouwblok)** → afgebakende functionaliteit, onderverdeelbaar; vooral in **doel-architectuur**;
  koppelbaar aan **WILMA referentiecomponenten**.
- **Dataobject** → georganiseerde gegevensverzameling, CRUD-gebruikt door ≥1 Applicatie/Portaal.

**Technology:**
- **Systeem software** → modulair/vervangbaar platform om applicaties te laten draaien; bewerkt GÉÉN
  bedrijfsgegevens maar heeft wel verwerk/opslag-functies. Bv. OS, emailserver, middleware, DBMS.
- **Programmeeromgeving** → **specialisatie van Systeem software**. Software om herbruikbare programma's/scripts
  te maken. Resultaat = applicatie- of technisch proces.

**Proces-onderscheid (cruciaal):**
- **Applicatieproces** (blauw) → WEL bewerking van bedrijfsgegevens.
- **Technologieproces** (groen) → GEEN bewerking van bedrijfsgegevens.

## 3. Actief vs. gedrag — vormkeuze op basis van eigenaarschap (Applicatiegebruik)

- **Actief concept** (Applicatiecomponent-vorm) → voor applicaties/portalen die wij (technisch) **zelf onderhouden**
  → Applicatie, 'Eigen' Portaal.
- **Gedrag concept** (afgeronde gedragvorm) → voor applicaties/portalen die we **van derden gebruiken / als dienst
  afnemen** → 'Extern' Portaal, Applicatie als service.

## 4. Tenant-modellering (Applicatiegebruik)

- Elk **waterschap = Bedrijfsactor**, bedoeld als **Tenant**.
- Gebruik vastgelegd via **associatierelatie** ("gebruikt/wordt gebruikt") tussen Waterschap en app/service/portaal.
- Tenancy-varianten: 1 waterschap / 2 elk eigen tenant / **shared tenant** (= Bedrijfssamenwerking).
- **Generiek vs. specifiek**: specialisatierelatie. Specifieke app **overerft koppelingen/eigenschappen** van de
  generieke. Relaties op de generieke gelden voor álle specialisaties.

## 5. Account-structuur (Applicatiegebruik + Definities + Projecten)

- Account (Rol) → Bedrijfsfunctie via **toewijzing**.
- Bedrijfsfunctie ◆ Bedrijfssubfunctie via **samenstelling** (composition).
- Applicatie **bedient** Bedrijfssubfunctie.
- **Account Applicatie Groep** (groepering) **aggregeert** apps/diensten/portalen per account; **realiseert** Bedrijfsfunctie.

## 6. Koppelingen / gegevensstromen (Koppelingen)

- Functionele gegevensstromen = **flowrelaties** tussen apps/diensten of van/naar externe Actoren.
- Optioneel koppelen aan Technologieservice/-proces voor technische spec; meerdere stappen → meerdere
  Technologieprocessen elk ondersteund door een Technologieservice.
- **ESB**: Systeemsoftware(ESB) **realiseert** ESB-service(generiek). **ETL**: Systeemsoftware(ETL) realiseert ETL-service.
- **Overdracht tussen Dataobjects** via Technologieproces: bron = **Access (lees)**, doel-Dataobject = **Access (schrijf)**.
  Wordt een **bestand** gemaakt → **flowrelatie** naar de doel-applicatie.

## 7. API-koppelvlak (Koppelvlak tussen applicaties)

- Landschap: een flow gerealiseerd via **API**; apps on-prem of cloud.
- Koppelvlak-spec: **API <naam>** (Applicatie-interface) + **Swagger file** (realiseert). **Integratie Specs**
  (Technologieproces-groepering) met **Step 1/Step 2** (Technologieprocessen).
- **(Api) call vanuit consumer** = Applicatie-event → **Trigger** naar consumer.
- Elke processtap → **onderdeel van** een **MS Azure**-infradienst: Azure Functions / Application Gateway /
  Logic Apps / API Management.
- Documenteren: welke service/landing zone, parameters/specs, **waar de API-key bewaard wordt**, tenant-locatie
  (Locatie-element, cloud/on-prem) per provider & consumer.

## 8. Exploitatie-omgeving (Exploitatie-omgeving Applicatie)

- Exploitatie/beheer = **Groepering-element "Locatie"** (generiek, geen exacte locatie).
- Onderscheid: **On-Premises** (waterschap-hardware, I&D-beheer) vs **Cloud** (extern bedrijf/SaaS).
  Sub: On-premises-Server, On-premises-Workstation, Cloud, Mobiel, DMZ, Thuis-locatie.
- **Applicatie op Werkstation / op Server** = specialisaties.
- Metrieken (Motivation): **Hosting-type Metriek** + **Integratieniveau Metriek** → voor Portfolio/Risk-management
  (niet voor élke applicatie).

## 9. Motivatie-elementen (Gebruik van motivatie elementen)

Vocabulaire: **Driver** (Drijfveren/Wet/Regelgeving; intern = "concerns" met stakeholder), **Principe**
(fundamenteel uitgangspunt), **Usecase** (scenario), **Beperking/Constraint** (verplichte tech/securitybeleid/
resource-grens), **Standaarden/normen** (verwijzing naar officiële NEN/ISO), **Requirement**, **Assessment/Observatie**.
Expliciet gebaseerd op Bizzdesign-richtlijn (support.bizzdesign.com).

## 10. Beveiligingszones (Zones met segmenten...)

- Zone met beveiligingseigenschappen = samengesteld concept **Beveiligingsdomein** (Security Domain).
- Zone = groep systemen met gelijke beveiligingseigenschappen. **NORA**: niet-/semi-/vertrouwd/zeer-vertrouwd.
  **IEC-62443**: Levels (L4, L5…). Beide passen in hetzelfde concept Beveiligingsdomein.
- Binnen een Beveiligingsdomein → **Groepering** plaatsen; **compositierelatie** = groep systemen hoort bij domein.
- Beveiligingsdomein heeft vaste eigenschappen met integer-waarde (0/1/2/3). Groeperingen kunnen sub-groepen zijn.
- Grafische symbolen (server/werkstation/laptop) toevoegbaar als specialisatie.
- Vertrouwelijkheidsniveau (aggregatie BIV-classificatie) optioneel via a) **Metriek**-eigenschap of b) **Beperking**.
- Constraint-kleur volgt **NORA**, niet standaard ArchiMate. Refs: NEN-ISO/IEC 27002:2022, BIO (8.2.1), BiWa 7.2.1.

## 11. MS Azure (MS Azure)

- MS Azure ◆ **beschikbaar** → MS Azure ResourceType (beide Technologieservice).
- **Subscription** (Groepering) bevat **Resource Groep** (Groepering); per groep autorisaties; groepsnaam =
  geconfigureerde naam.
- **Deployed Resource** (Technologieservice) in Resource Groep = **specialisatie van** MS Azure ResourceType;
  servicenaam = geconfigureerde naam; Azure ResourceType als **«stereotype»**.
- Deployed Resource → **bediening** → Specifiek technisch proces (Technologieproces).

## 12. Projecten & wijzigingen (Projecten en wijzigingen)

- **Plateau** = toekomstige situatie; symbool voor verandering t.o.v. IST. I-aanvraag/wijzigingsnummer in symbool;
  hyperlink naar de uitwerkings-view (projectmap).
- Map E: per project/wijziging een model met IST+SOLL; **aggregatierelaties** verbinden Plateau met betrokken
  elementen; relatienaam zegt nieuw/vervalt.
- Bij afsluiten → wijziging verwerken in nieuwe IST.
- Meerdere wijzigingsmomenten → meerdere plateaus (Plateau → Plateau(2) via "volgorde"-trigger).
- Account → Programma/Project (aanvraag); Programma/Project **realiseert** Plateau.

## 13. Relatie met CMDB (Relatie met CMDB)

- CMDB = **TopDesk** (ICT-middelen). In Bizzdesign: middel = **Artefact** (installset/licentie).
- Artefact **realiseert** Applicatie / Applicatie als service / 'Eigen' Portaal / 'Extern' Portaal / Systeem software.
- **Beslismatrix** (criteria → type): kolommen = Bewerkt bedrijfsgegevens / Waterschap eigenaar content /
  Toegankelijk voor aannemers / SAAS-dienst.

| Type | Bewerkt | Eigenaar | Aannemers | SaaS |
|------|:---:|:---:|:---:|:---:|
| Applicatie | + | + | − | − |
| 'Eigen' Portaal | + | + | + | − |
| Applicatie als service | + | + | − | + |
| 'Extern' Portaal | + | − | + | + |
| Systeem software | − | | | |

- CMDB-wijzigingen = Plateau. Let op: huidige landschap nog niet consistent ("work in progress").

## 14. Web-omgevingen (web omgevingen)

- **Website** (blauw) — Account Applicatie Groep **aggregeert** Website; Website **realiseert** Bedrijfsfunctie;
  **Document Publiceren** (Applicatiefunctie) → Website ("publicatie op website").
- **Hostingdienst** (groen, Technologieservice) bedient Website; **Hosting partij** (Bedrijfsactor) → Hostingdienst;
  **Domein registratie** = specialisatie van Hostingdienst; **Registrar** (Bedrijfsactor) → Domein registratie.
- Juridisch: **Wet digitale overheid (WDO) / Tijdelijk besluit Digitale Toegankelijkheid** (Driver) — wettelijke
  toetsing via «toetsing-website» https://internet.nl/.

## 15. Model-organisatie (Applicatie modellen) — de overkoepelende structuur

Bizzdesign-mappen:
- **A. Architectuur visie** → **Doel architecturen** (Applicatiefunctie/bouwblokken: hoe bouwblokken móeten
  samenwerken) + **Architectuur Principes** (Principe, Driver).
- **C. Informatie systemen architectuur** → **IST applicatie-landschapmodel** (alle gebruikte apps + gegevensstromen).
- **E. Kansen en Oplossingen** → **SOLL specifiek projectmodel** (Wijziging/project, Plateau).

Principe **beïnvloedt** Applicatiefunctie ("invloed van regelgeving op functie"); Applicatiefunctie **gebruikt**
Applicatie/Applicatie als service. Wijziging/project = nieuw/wijzigt/vervalt. Wet&regelgeving genoteerd bij
bouwblokken (niet altijd compleet).

---

## Implementatie in PR #215 — waar landt wat

De conventies zijn verankerd in **zowel de skill (agent genereert) als de
validator (harde gate)** — belt-and-suspenders.

| Conventie | Landingsplek (geïmplementeerd) |
|-----------|--------------------------------|
| Vast vocabulaire (begrip → ArchiMate-type + stereotype) | `writer.py` → `RIJNLAND_CONCEPTS` (single source of truth); gedocumenteerd in `making-archimate-diagrams/SKILL.md` |
| Stereotype op element | `create_element(stereotype=…)` — opgeslagen als property-marker; afgewezen bij verkeerd type; gerenderd als «stereotype»-label |
| Actief vs. gedrag op eigenaarschap | `SKILL.md` ownership-regel + `RIJNLAND_CONCEPTS["ownership"]` |
| Kleur = laag (al aanwezig) + NORA-uitzondering | `archimateParser.js` + `svg_export.py`: `TRUST_COLORS`; security-zone/Constraint kleurt op trust-niveau |
| Relatie-conventies (flow/access-r-w/associatie/specialisatie/aggregatie/realisatie) | `SKILL.md` relatie-conventietabel |
| WILMA-grounding | sluit aan op bestaande WILMA-reuse in skill |
| Map/view-organisatie (IST/SOLL/doel) | `SKILL.md`; Plateau (Implementation-laag) toegevoegd aan `ELEMENT_TYPE_LAYER` |
| Beveiligingsdomeinen (NORA/IEC-62443) | Grouping + `stereotype=Beveiligingsdomein` + trust-niveau; NORA-kleur; validator-check |
| `validate_view` quality-gate | nieuwe codes `rijnland_stereotype_type` + `security_domain_missing_trust`. Conditioneel — alleen op gestereotypeerde elementen, dus geen ruis op niet-waterschap-platen |

**Tests:** `tests/test_rijnland_conventions.py` (6 checks, backend) +
3 cases in `archimateParser.test.js` (frontend render).

**Bewust nog niet gedaan (voor review/vervolg):**
- Azure/CMDB/Web als kant-en-klare view-builders (generiek vocabulaire dekt ze al).
- Exacte NORA-kleurcodes (huidige hexes volgen de groen-voor-vertrouwd-ordening
  uit de sheets; afstembaar op een exact NORA-palet).
- CMDB-beslismatrix (bewerkt/eigenaar/aannemers/SaaS → type) als geautomatiseerde
  typeer-hulp.
