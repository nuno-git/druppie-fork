---
id: "033"
title: Markdown to Typst PDF pipeline
status: draft
author: architect
date: 2026-07-29
supersedes: null
superseded_by: null
linked_adrs:
  - docs/adrs/026-documenter-typst-subsystem.md
  - docs/adrs/039-markdown-to-typst-conversion.md
linked_research: []
linked_specs:
  - docs/specs/031-markdown-to-typst-pdf.feature
linked_workitem: null
---

# PRD: Markdown to Typst PDF pipeline

## Problem

The documenter agent produces design documents in Markdown and stores them in Gitea, but users need professionally formatted PDF output with corporate branding for review, approval, and distribution. There is currently no way to convert these Markdown documents into branded PDFs. Users must manually copy content into Word or another tool to produce presentable output, which is slow and error-prone.

## Goal

Provide a server-side pipeline that converts Markdown documents stored in Gitea into branded PDF files via Typst. The pipeline handles the full conversion chain: fetching Markdown from Gitea, converting it to Typst markup, wrapping it in a corporate house-style template, compiling via the Typst binary, caching by Git blob SHA, and serving the result as a downloadable PDF. The frontend gains a "Download PDF" button on design documents.

## User Journey

1. A user opens a project's design document view in the frontend.
2. The user clicks the "Download PDF" button on a design document.
3. The frontend calls `GET /api/projects/{id}/design-pdf?path=...` with the document path.
4. The backend fetches the Markdown file from Gitea and resolves the Git blob SHA.
5. The backend checks the render cache keyed by `(project_id, typ_path, file_sha)`. If a cached PDF exists, it is returned immediately.
6. On cache miss, the backend converts Markdown to Typst markup, handling headings, tables, code blocks, Mermaid diagrams, ArchiMate SVGs, links, and images.
7. The converted markup is wrapped in the applicable house-style template (Rijnland or HHSK).
8. The Typst binary compiles the markup to PDF.
9. The PDF is stored in the render cache and returned to the user as a download.

## Constraints

- The Markdown-to-Typst conversion must handle all content types produced by the documenter agent: headings, paragraphs, bullet/numbered lists, tables, fenced code blocks, Mermaid diagram blocks, inline/referenced images, ArchiMate SVG embeds, and hyperlinks.
- Two house styles must be supported: Rijnland (default) and HHSK. The style is determined by project configuration.
- The render cache must be keyed by `(project_id, typ_path, file_sha)` so that identical content is never recompiled, and stale cache entries are automatically invalidated when the source file changes.
- The Typst binary must be available in the backend container. Compilation must be synchronous within the request lifecycle.
- The API endpoint must stream the PDF response with appropriate `Content-Type` and `Content-Disposition` headers for browser download.

## Out of Scope

- Client-side rendering or preview of Typst markup.
- Editing Typst templates through the UI.
- Batch export of multiple documents into a single PDF.
- Print-style CSS or alternative PDF engines (wkhtmltopdf, Playwright PDF, etc.).
- Automatic regeneration of cached PDFs on Gitea webhook events.

## Open Questions

- Should the cache have a TTL or size limit, or is SHA-based invalidation sufficient?
- Should the endpoint support selecting a house style via query parameter, or is project-level configuration the only mechanism?

## Linked Documents

- **ADRs:** [026 -- Documenter Typst subsystem](../adrs/026-documenter-typst-subsystem.md), [039 -- Markdown to Typst conversion](../adrs/039-markdown-to-typst-conversion.md)
- **Research:** none
- **Specs / Feature files:** [031 -- Markdown to Typst PDF](../specs/031-markdown-to-typst-pdf.feature)
