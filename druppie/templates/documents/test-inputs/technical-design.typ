#import "../rijnland.typ": rijnland_doc

#show: rijnland_doc.with(
  title: "Technisch Ontwerp — Vergunningzoeker",
  document_type: "technical_design",
  status: "DRAFT",
  project_name: "Vergunningzoeker",
  include_toc: true,
  include_watermark: true,
  section_breaks: true,
)

= Architectuur

Het systeem bestaat uit drie lagen.

= Data Model

#table(
  columns: (auto, auto, 1fr),
  [*Entiteit*], [*Type*], [*Beschrijving*],
  [Permit], [Primair], [Vergunning met metadata],
  [SearchIndex], [Secundair], [Elasticsearch index],
  [Document], [Opslag], [BLOB storage],
)

= Integratie

Verbinding met externe systemen via REST API.
