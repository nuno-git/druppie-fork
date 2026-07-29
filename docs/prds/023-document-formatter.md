---
id: "023"
title: "Document Formatter (PDF Generation)"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/026-documenter-typst-subsystem.md"]
linked_research: []
linked_specs: ["docs/specs/024-document-formatter.feature"]
---

# PRD 023: Document Formatter (PDF Generation)

## Problem

Functional designs, technical designs, and other project documents are stored as Markdown in Gitea. Users cannot download polished, formatted PDF versions of these documents for sharing, printing, or archival. The only option is raw Markdown.

A hoogheemraadschap (regional water authority) requires documents in its own house style: title page with logo, table of contents, page numbers, consistent headers and footers, and professional typography. Manual formatting in Word or LaTeX is time-consuming and inconsistent.

Druppie is not tied to a single water authority. Different hoogheemraadschappen have distinct corporate identities — palette, fonts, logo, and layout — that a project's documents must comply with. A single hardcoded identity cannot serve projects belonging to different authorities, so the formatter must support more than one house style and let each project choose the one it needs.

## Goal

A document formatter service that converts Markdown documents from Gitea to professionally formatted PDF using Typst templates. The service produces house-style-compliant output with title page, TOC, page numbers, headers, footers, code blocks, tables, and inline diagrams. Accessible through the Documenter agent via a tool call.

Two house styles are supported, selectable per project:

- **Rijnland** (Hoogheemraadschap van Rijnland) — the default, pre-existing.
- **HHSK** (Hoogheemraadschap van Schieland en de Krimpenerwaard) — new.

Both house styles implement the *same* document types, title page, watermark, TOC, tables, code blocks, blockquotes, and diagram embedding. Only the visual identity — palette, fonts, logo, and layout — differs, so a project renders identically-structured documents regardless of brand. HHSK is built from the official Huisstijlhandboek HHSK: the Ruda house font (weights 400–900, no italic — emphasis maps to a heavier weight), a donkerblauw/blauw/groen/oranje palette with light 40% tints, donkerblauw default text colour, a brand gradient reserved for large headings, a full-colour logo top-left with 7mm clear space, and the pay-off "Droge voeten en schoon water".

The house style is a per-project setting that defaults to Rijnland. It is set through the API (owner/admin gated) and exposed on the project's detail. At render time the Documenter agent resolves the style by precedence — an explicit request in the task, then the project setting, then the default — and automatically loads the matching Typst template; the author never hand-picks the module.

## User Journey

1. Documenter agent receives a request to format a functional or technical design document. The orchestrator publishes the project's `document_house_style` into the agent's context.
2. Agent fetches the source Markdown from Gitea using the document's repository path and blob SHA.
3. Agent resolves the house style by precedence — an explicit style in the task request, otherwise the project setting, otherwise the default Rijnland — and selects the matching Typst template.
4. Agent calls the PDF formatting tool with the document content and formatting options.
5. PdfRenderService compiles the Markdown through the selected house-style Typst template into a PDF.
6. Rendered PDF is cached keyed by the source document's Git blob SHA.
7. Agent returns the PDF to the user for download.

## Constraints

- Must handle Dutch and English text correctly.
- Must render code blocks, tables, Mermaid diagrams, and ArchiMate diagrams.
- Must be fast enough for interactive use (<5s for typical document).
- PDF styling must match the selected house style's formatting requirements (logo, title page, TOC, headers, footers).
- The formatter must support multiple house styles (currently Rijnland and HHSK) selectable per project, defaulting to Rijnland. The selection is stored on the project and set through an owner/admin-gated API endpoint.
- All house styles must produce identically-structured documents (same document types, title page, watermark, TOC, tables, code blocks, blockquotes, and diagram embedding); only the visual identity may differ between styles.
- House-style-agnostic helpers (Dutch date formatting, document-type/status labels, breakable-table types, AI disclaimer copy) must be shared across styles; colours, fonts, logos, and grids belong to the per-style template only.
- Each house style must comply with its authority's brand guidelines — for HHSK, the Huisstijlhandboek's palette, contrast matrix, font (Ruda, no italic), logo placement, and clear space.
- Custom fonts must be embedded in the PDF output and auto-registered from `assets/fonts/` (Lato + Neusa Next Pro for Rijnland, Ruda for HHSK).
- No browser dependency (no Chrome, no Puppeteer, no Playwright).
- Typst CLI must be available in the backend container.

## Out of Scope

- DOCX generation (PDF only for now).
- Collaborative real-time editing.
- Version diff visualization.
- Frontend "Download PDF" button (agent-driven only for now).
- Frontend UI for selecting a project's house style (API-only for now; a project setting / dropdown is tracked in the backlog under "HHSK house style — follow-ups").
- BA/Architect agent access to the formatting tool (deferred).

## Open Questions

None resolved. The rendering engine decision is captured in ADR 026.

## Linked Documents

- ADR 026: docs/adrs/026-documenter-typst-subsystem.md
- Spec: docs/specs/024-document-formatter.feature
