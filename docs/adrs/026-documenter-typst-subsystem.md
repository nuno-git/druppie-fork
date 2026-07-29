---
id: "026"
title: Documenter Typst subsystem for PDF formatting
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/023-document-formatter.md
linked_research: null
---

# ADR 026: Documenter Typst subsystem for PDF formatting

## Context

Druppie needs to produce professionally formatted PDFs from Markdown documents stored in Gitea. The primary consumer is the Hoogheemraadschap (regional water authority), which requires documents in a specific format: title page with logo, table of contents, page numbers, consistent headers and footers, and professional typography.

The original PRD 023 proposed a Markdown-to-HTML-to-PDF pipeline using Puppeteer (headless Chrome) or WeasyPrint (Python-native). Both approaches had drawbacks: Puppeteer adds a heavy browser dependency to the container, and WeasyPrint produces inconsistent output with complex layouts. Neither handles Dutch typographic conventions well out of the box.

The PDF formatting capability is exposed as a tool call available only to the Documenter agent. Business Analyst and Architect agents will get access later.

## Decision

Use Typst as the PDF rendering engine. Build a focused subsystem within the backend with three components: PdfRenderService, DocumentFormatterService, and PdfRenderRepository.

### Typst over Puppeteer/WeasyPrint

Typst produces consistent, professional PDFs without browser dependencies. It offers LaTeX-quality output with a modern, readable syntax. Typst templates are plain text files stored in the repo, version-controlled alongside the code. The Typst CLI compiles `.typ` files to PDF directly, with no Chrome or Node.js dependency in the container.

Key advantages over alternatives:

- **vs Puppeteer**: No headless Chrome. No 300MB+ browser image. No flaky page rendering. No JavaScript execution environment.
- **vs WeasyPrint**: Better CSS support. More predictable page breaking. Native support for custom fonts. Active development community.

### Gitea-based source document fetching

The Documenter agent reads functional and technical design documents directly from the project's Gitea repository. This keeps Gitea as the single source of truth for all project documents. The agent uses the same authentication model as the rest of Druppie (Gitea API token from the session context). No separate document upload or sync step is needed.

### Render cache keyed by Git blob SHA

Each source document in Gitea has a unique Git blob SHA. The PdfRenderRepository stores rendered PDFs keyed by this SHA. When the Documenter agent requests a format:

1. Look up the blob SHA in the cache.
2. If found and the SHA matches, return the cached PDF (no re-render).
3. If not found or SHA differs, compile via Typst, store the result, and return it.

This avoids re-rendering expensive Typst compilations for unchanged documents. The cache lives in the application database (PdfRenderRepository table) with a configurable TTL.

### Hoogheemraadschap formatting via Typst templates

A set of Typst template files in the documenter module implements the Hoogheemraadschap format:

- Title page with the Hoogheemraadschap logo.
- Table of contents.
- Page numbers in the footer.
- Consistent headers with document title and section name.
- Body text in a professional serif font.
- Code blocks with syntax highlighting.
- Table rendering with alternating row colors.
- Mermaid and ArchiMate diagram placeholders (rendered as embedded images).

### Agent-driven access control

Only the Documenter agent has access to the PDF formatting tool. The tool is registered in the agent's MCP tool manifest. Business Analyst and Architect agents will get access in a future iteration (deferred). This limits the blast radius of any rendering issues and lets us validate the subsystem with a single consumer first.

### Font handling

Custom fonts (Hoogheemraadschap brand fonts, professional serif and sans-serif families) are stored in the documenter module's `fonts/` directory. Typst embeds them directly in the PDF output, ensuring consistent rendering regardless of the viewer's installed fonts. Font files add to the container image size but guarantee correct output.

### Subsystem isolation

The PDF formatting capability lives in `druppie/documenter/` as three focused components:

- **PdfRenderService**: Orchestrates the render pipeline. Accepts Markdown content and formatting options. Converts Markdown to Typst markup. Invokes the Typst CLI. Returns the compiled PDF bytes.
- **DocumentFormatterService**: Higher-level service that the Documenter agent calls. Handles Gitea fetching, cache lookup, and coordinates PdfRenderService.
- **PdfRenderRepository**: Database access layer for the render cache. Keyed by Git blob SHA. Stores PDF bytes, source SHA, render timestamp, and document metadata.

## Consequences

### Positive

- Professional PDF output without browser dependencies.
- Cache by blob SHA saves compute on repeated renders.
- Typst templates are version-controlled in the repo alongside the code.
- No Chrome or Node.js in the container reduces image size and attack surface.
- Typst output is deterministic and reproducible.

### Negative

- Typst is a niche tool with a smaller community than LaTeX or browser-based renderers.
- Font embedding adds to the container image size.
- Deferred BA/Architect access limits immediate utility to Documenter agent only.
- Markdown-to-Typst conversion requires a custom translation layer (no off-the-shelf converter).
- Typst CLI must be installed and maintained in the backend Docker image.
