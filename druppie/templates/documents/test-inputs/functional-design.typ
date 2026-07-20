#import "../rijnland.typ": rijnland_doc

#show: rijnland_doc.with(
  title: "Functioneel Ontwerp — Vergunningzoeker",
  document_type: "functional_design",
  status: "DRAFT",
  project_name: "Vergunningzoeker",
  include_toc: true,
  include_watermark: true,
  section_breaks: true,
)

= Inleiding

Dit document beschrijft het functioneel ontwerp van de Vergunningzoeker.

= Huidige vs. Gewenste Situatie

== Huidige Situatie

Het zoeken naar vergunningen is gefragmenteerd.

== Gewenste Situatie

Een uniforme zoekinterface.

= Functionele Eisen

#table(
  columns: (auto, 1fr, auto),
  [*ID*], [*Vereiste*], [*Prioriteit*],
  [FR-01], [Uniforme zoekinterface], [Must have],
  [FR-02], [Filters op locatie en datum], [Must have],
  [FR-03], [Export naar PDF], [Should have],
)

= Gebruikersscenario

Gebruiker opent de zoekinterface en voert een zoekterm in.
