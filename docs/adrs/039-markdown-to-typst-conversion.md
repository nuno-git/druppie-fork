---
id: "039"
title: Server-side markdown to Typst conversion
status: proposed
date: 2026-07-29
deciders:
  - architect
supersedes: null
superseded_by: null
linked_prd: docs/prds/033-markdown-to-typst-pdf.md
linked_research: null
---

## Context

Druppie's documenter agent writes documentation as Markdown and stores it in Gitea. Users need branded PDF exports of these documents with corporate house-style templates (Rijnland, HHSK). ADR 026 decided to use Typst as the PDF engine. This ADR covers the conversion layer that bridges Markdown content to the Typst compilation step, so that agents write plain Markdown and never need to produce native Typst markup.

## Decision

Implement server-side conversion from Markdown to Typst markup on the backend.

1. **Backend conversion** -- the Markdown-to-Typst transformation runs on the backend, not in-browser. The backend already hosts the Typst binary and has access to Gitea content; keeping conversion server-side avoids shipping a Typst toolchain to the frontend and keeps rendering deterministic.

2. **Mermaid diagrams via `@preview/mmdr`** -- Mermaid code blocks in Markdown are converted to `mmdr` calls in the generated Typst markup, delegating diagram rendering to Typst's own package ecosystem rather than a separate Node-based Mermaid CLI.

3. **ArchiMate via pre-rendered SVG** -- ArchiMate diagrams are stored as SVG images in Gitea. The converter embeds these as Typst `image()` calls referencing the SVG content fetched from Gitea at render time.

4. **Render cache keyed by Git blob SHA** -- compiled PDF output is cached using the Git blob SHA of the source Markdown file as the cache key. When the content has not changed (same SHA), the cached PDF is returned without recompilation.

5. **House-style template wrapping** -- the converter wraps the generated Typst content in a configurable house-style template. Template selection is driven by the organization associated with the session, supporting Rijnland and HHSK branding.

## Consequences

**Positive:**
- Users get branded PDFs from plain Markdown without learning or touching Typst.
- The Git blob SHA cache avoids redundant compilation when documents have not changed.
- Mermaid and ArchiMate diagrams render consistently across all exports via standardized paths.

**Negative:**
- The backend must maintain a Markdown-to-Typst converter with correct escaping rules for Typst's syntax (hash, asterisk, underscore).
- The render cache adds database state that must be invalidated when templates change independently of content.
- The Typst binary must be available on the server, adding a system dependency to the backend container.
