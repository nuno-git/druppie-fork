#import "../hhsk.typ": hhsk_doc

#show: hhsk_doc.with(
  title: "Functioneel Ontwerp — Vergunningzoeker",
  document_type: "functional_design",
  status: "DRAFT",
  project_name: "Vergunningzoeker",
  include_toc: true,
  include_watermark: true,
  section_breaks: true,
  author: "Team Digitalisering",
)

= Inleiding

Dit document beschrijft het functioneel ontwerp van de Vergunningzoeker voor het
Hoogheemraadschap van Schieland en de Krimpenerwaard. Het _accent_ hier toont dat
nadruk als gewicht wordt gezet, want Ruda kent geen cursief.

== Doel en scope

De Vergunningzoeker ontsluit watervergunningen voor zowel medewerkers als burgers.

#quote(block: true)[
  Iedere inwoner moet binnen drie klikken kunnen zien welke vergunningen op een
  perceel van toepassing zijn.
]

= Huidige vs. Gewenste Situatie

== Huidige Situatie

Het zoeken naar vergunningen is gefragmenteerd over meerdere systemen:

- Archief op netwerkschijf
- Zaaksysteem zonder publieke ontsluiting
  - Losse exports per afdeling
  - Handmatige controle op actualiteit

== Gewenste Situatie

Een uniforme zoekinterface met kaartweergave.

+ Eén zoekindex over alle bronnen
+ Filters op locatie, datum en vergunningtype
+ Export naar PDF

=== Randvoorwaarden

Toegankelijkheid conform WCAG 2.1 AA.

==== Techniek

Zie het technisch ontwerp voor details.

= Functionele Eisen

#table(
  columns: (auto, 1fr, auto),
  table.header([*ID*], [*Vereiste*], [*Prioriteit*]),
  [FR-01], [Uniforme zoekinterface], [Must have],
  [FR-02], [Filters op locatie en datum], [Must have],
  [FR-03], [Export naar PDF], [Should have],
  [FR-04], [Kaartweergave van percelen], [Should have],
  [FR-05], [Abonneren op wijzigingen], [Could have],
)

= Gebruikersscenario

Gebruiker opent de zoekinterface en voert een zoekterm in.

```python
def zoek_vergunningen(term: str, gemeente: str | None = None) -> list[Vergunning]:
    """Zoek vergunningen op vrije tekst, optioneel gefilterd op gemeente."""
    return index.query(term, filters={"gemeente": gemeente})
```

Inline code zoals `zoek_vergunningen()` blijft leesbaar in de lopende tekst.

#figure(
  table(
    columns: 2,
    table.header([*Stap*], [*Resultaat*]),
    [Zoekterm invoeren], [Resultatenlijst],
    [Resultaat openen], [Detailpagina],
  ),
  caption: [Hoofdscenario van de Vergunningzoeker],
)
