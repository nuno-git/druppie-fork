// ============================================================================
// Shared helpers for the document house-style templates
// ============================================================================
// Small, house-style-agnostic utilities used by the corporate identity
// templates in this directory (rijnland.typ, hhsk.typ, ...).
//
// RULE OF THUMB: only put something here if it is genuinely independent of a
// single house style. Colours, fonts, logos, layout grids and any styling
// decision belong in the per-house-style template, NOT here.
//
// Usage:
//   #import "_shared.typ": dutch-month-name, dutch-date, document-type-label
// ============================================================================

// ----------------------------------------------------------------------------
// Dates (all templates are Dutch-language: lang: "nl")
// ----------------------------------------------------------------------------

/// Dutch name of a month number (1 = januari ... 12 = december).
#let dutch-month-name(m) = {
  let names = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
  )
  names.at(m - 1)
}

/// Long-form Dutch date, e.g. "20 juli 2026".
#let dutch-date(d) = {
  str(d.day()) + " " + dutch-month-name(d.month()) + " " + str(d.year())
}

/// Short numeric date, e.g. "20-07-2026".
#let short-date(d) = d.display("[day]-[month]-[year]")

// ----------------------------------------------------------------------------
// Document metadata vocabulary
// ----------------------------------------------------------------------------
// The `document_type` values below are the closed set defined by
// druppie/domain/document_formatter.py :: DocumentMetadata.document_type.
// Keep this map in sync with that Literal.

/// Human-readable Dutch label for a DocumentMetadata.document_type value.
/// Falls back to the raw value with underscores turned into spaces so an
/// unknown type never breaks a compile.
#let document-type-label(document_type) = {
  let labels = (
    memo:               "Memo",
    functional_design:  "Functioneel Ontwerp",
    technical_design:   "Technisch Ontwerp",
    technical_research: "Technisch Onderzoek",
    core_documentation: "Kerndocumentatie",
  )
  if document_type in labels {
    labels.at(document_type)
  } else {
    document_type.replace("_", " ")
  }
}

/// Human-readable Dutch label for a DocumentMetadata.status value.
/// Mirrors DocumentMetadata.display_status in the Python domain model.
#let status-label(status) = {
  if status == "FINAL" { "Definitief" } else { "Niet-definitief" }
}

/// Document types whose tables are allowed to break across pages. Long
/// technical documents need it; short memos and designs read better with
/// tables kept whole.
#let breakable-table-types = (
  "technical_design", "technical_research", "core_documentation",
)

// ----------------------------------------------------------------------------
// Standard disclaimer copy
// ----------------------------------------------------------------------------
// Identical wording across house styles — only the styling differs, so the
// strings live here and each template decides how to set them.

/// Short notice that the document was machine-generated.
#let ai-generated-notice = "Dit document is gegenereerd met behulp van AI."

/// Longer expectation-management disclaimer shown on the title page.
#let ai-trajectory-disclaimer = (
  "Dit traject dient om het AI-platform te leren en verbeteren. "
  + "Geen garantie op een volledige oplossing, vaste planning of "
  + "maatwerkontwikkeling."
)

/// Badge text shown on the title page while a document is not yet final.
#let draft-badge-text = "Niet-definitief — ter goedkeuring"
