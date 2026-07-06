// ============================================================================
// Druppie Document Formatter — Backward-compatible entry point
// ============================================================================
// Reads metadata.json + content.md and applies the Rijnland corporate identity
// template.
//
// For native Typst authoring, agents should import rijnland.typ directly:
//   #import "rijnland.typ": rijnland_doc
//   #show: rijnland_doc.with(title: "...", ...)
// ============================================================================

#import "rijnland.typ": rijnland_doc
#import "@preview/cmarker:0.1.8"

#let meta = json("metadata.json")

#let status-val = meta.at("status", default: "DRAFT")
#let include-watermark-val = meta.at("include_watermark", default: status-val != "FINAL")

#show: rijnland_doc.with(
  title: meta.at("title", default: "Untitled Document"),
  document_type: meta.at("document_type", default: "memo"),
  status: status-val,
  project_name: meta.at("project_name", default: ""),
  include_toc: meta.at("include_toc", default: false),
  include_watermark: include-watermark-val,
  section_breaks: meta.at("section_breaks", default: true),
  author: meta.at("author", default: ""),
)

#cmarker.render(read("content.md"))

// ============================================================================
// END MATTER
// ============================================================================
