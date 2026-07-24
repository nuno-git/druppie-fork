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

The Hoogheemraadschap (regional water authority) requires documents in a specific format: title page with logo, table of contents, page numbers, consistent headers and footers, and professional typography. Manual formatting in Word or LaTeX is time-consuming and inconsistent.

## Goal

A document formatter service that converts Markdown documents from Gitea to professionally formatted PDF using Typst templates. The service produces Hoogheemraadschap-compliant output with title page, TOC, page numbers, headers, footers, code blocks, tables, and inline diagrams. Accessible through the Documenter agent via a tool call.

## User Journey

1. Documenter agent receives a request to format a functional or technical design document.
2. Agent fetches the source Markdown from Gitea using the document's repository path and blob SHA.
3. Agent calls the PDF formatting tool with the document content and formatting options.
4. PdfRenderService compiles the Markdown through Typst templates into a PDF.
5. Rendered PDF is cached keyed by the source document's Git blob SHA.
6. Agent returns the PDF to the user for download.

## Constraints

- Must handle Dutch and English text correctly.
- Must render code blocks, tables, Mermaid diagrams, and ArchiMate diagrams.
- Must be fast enough for interactive use (<5s for typical document).
- PDF styling must match Hoogheemraadschap formatting requirements (logo, title page, TOC, headers, footers).
- Custom fonts must be embedded in the PDF output.
- No browser dependency (no Chrome, no Puppeteer, no Playwright).
- Typst CLI must be available in the backend container.

## Out of Scope

- DOCX generation (PDF only for now).
- Collaborative real-time editing.
- Version diff visualization.
- Frontend "Download PDF" button (agent-driven only for now).
- BA/Architect agent access to the formatting tool (deferred).

## Open Questions

None resolved. The rendering engine decision is captured in ADR 026.

## Linked Documents

- ADR 026: docs/adrs/026-documenter-typst-subsystem.md
- Spec: docs/specs/024-document-formatter.feature
