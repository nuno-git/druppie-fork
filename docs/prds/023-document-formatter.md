---
id: "023"
title: "Document Formatter (PDF Generation)"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 023: Document Formatter (PDF Generation)

## Problem

Functional designs, technical designs, and other project documents are stored as Markdown in Gitea. Users cannot download polished, formatted PDF versions of these documents for sharing, printing, or archival. The only option is raw Markdown.

## Goal

A document formatter service that converts Markdown documents to professionally formatted PDF with consistent styling (headers, footers, page numbers, TOC, code blocks, tables, diagrams). Accessible from the frontend document viewer with a "Download PDF" button.

## User Journey

1. User opens a functional design document in the frontend.
2. User clicks "Download PDF".
3. Backend sends the Markdown to the formatter service.
4. Formatter renders Markdown → styled HTML → PDF (with TOC, page numbers, code highlighting).
5. User receives the PDF download in the browser.

## Constraints

- Must handle Dutch and English text correctly.
- Must render code blocks, tables, Mermaid/ArchiMate diagrams.
- Must be fast enough for interactive use (<5s for typical document).
- PDF styling must match Druppie branding (logo, colors, fonts).

## Out of Scope

- DOCX generation (PDF only for now).
- Collaborative real-time editing.
- Version diff visualization.

## Open Questions

- **Q1: Which rendering engine?**
  - Option A: Puppeteer/Playwright (headless Chrome) — best CSS/render fidelity.
  - Option B: WeasyPrint (Python-native) — lighter, no browser dependency.
  - Owner: architect.

## Linked Documents

- Source: `docs/BACKLOG.md` — "Document Formatter (PDF Generation)" section
