# Document Templates

This directory contains Typst document templates for PDF generation.

## Structure

```
rijnland.typ                                     # Rijnland corporate identity template library
hhsk.typ                                         # HHSK corporate identity template library
_shared.typ                                      # House-style-agnostic helpers: Dutch date formatting,
                                                 #   document-type/status labels, the breakable-table-type
                                                 #   set, and the standard AI notice/disclaimer strings
assets/
  Logo-hoogheemraadschap-rijnland.png            # Rijnland corporate logo (title page)
  dijkEnSloot.png                                # Full-bleed dijk-en-sloot footer shape
  hhsk/
    logo.png                                     # HHSK logo raster, full-colour (RGBA 1063x337)
    logo_white.png                               # HHSK logo raster, diapositief (RGBA 436x90)
    logo.ai                                      # HHSK logo vector — authoritative colour source
    Beeldmerk.svg                                # HHSK beeldmerk (mark only) vector
  fonts/                                         # TYPST_FONT_PATHS root, scanned recursively
    lato/                                        # Lato (18 TTFs) — Rijnland body/heading substitute
    NeuasaNextPro/                               # Neusa Next Pro (41 OTFs) — Rijnland brand font
    neusaNextCompact/                            # Neusa Next Pro Compact (OTF + TTF pairs)
    ruda/                                        # Ruda (6 TTFs) — HHSK house font
test-inputs/                                     # pytest fixtures
  functional-design.typ                          # FO Typst source
  functional-design.md                           # FO Markdown source (legacy fixture)
  functional-design-metadata.json
  technical-design.typ                           # TO Typst source
  technical-design.md                            # TO Markdown source (legacy fixture)
  technical-design-metadata.json
  technical-design-metadata-final.json           # status = FINAL variant
  technical-design-metadata-veryLongProjectName.json   # header overflow variant
  hhsk-functional-design.typ                     # FO in the HHSK house style
```

There is **no `assets/style-guide.pdf`**. Brand manuals are reference-only material
and are not kept in this repository at all — see [Asset layout](#asset-layout)
below.

## Asset layout

The Dockerfile does `COPY druppie/ /app/druppie/`, so **everything under this
directory ships in the image**. Keep that in mind when adding files:

- **Runtime assets** (logos, fonts, shapes actually referenced by a `.typ`) belong
  under `assets/`.
- **Reference-only material** (brand manuals, source `.ai` shape libraries, unused
  font families) does not belong in this repository at all — not under `assets/`,
  where the `COPY` would ship it, and not elsewhere in the tree either. It has no
  runtime use; keep it in the brand owner's asset pack and request it again when
  it is needed.

Filenames under `assets/` must contain **no spaces** — they are referenced from
Typst `#image()` paths.

Fonts are discovered **recursively** from `assets/fonts/`, so a new family only
needs its own subdirectory; no configuration change is required. `TYPST_FONT_PATHS`
is set to `/app/druppie/templates/documents/assets/fonts` in the Dockerfile, and
`DocumentFormatterService` additionally passes `<template_dir>/assets/fonts` as
`--font-path`.

## House styles

| Brand | Template | Status |
|-------|----------|--------|
| Hoogheemraadschap van Rijnland | `rijnland.typ` | Live |
| Hoogheemraadschap van Schieland en de Krimpenerwaard (HHSK) | `hhsk.typ` | Live |

The **HHSK** style is live alongside Rijnland and is selectable per project via
`PUT /api/projects/{id}/house-style`. Its runtime assets live in
`assets/hhsk/` and `assets/fonts/ruda/`; the house-style-agnostic helpers shared
with `rijnland.typ` live in `_shared.typ`. Remaining gaps are tracked in
`docs/BACKLOG.md` under "HHSK house style — follow-ups".

HHSK notes:

- **House font**: Ruda — Typst family name **`Ruda`**, weights 400, 500, 600, 700,
  800, 900 (no italics ship with the family). Verdana is the handbook's Office
  fallback.
- **Colour**: sample from `assets/hhsk/logo.ai` (RGB vector). Do not sample from the
  raster logo or from the CMYK `Vormelementen-2024.ai`.
- **Reference material** (**not in this repo** — re-request it from HHSK):
  - *Huisstijlhandboek HHSK 2026* (v2, juli 2025) — the brand manual, and the
    authority for typography, logo clear space and layout. It is the source cited
    by the `// Based on:` line in the `hhsk.typ` file header, and the document the
    `// CHOICE:` comments weigh their decisions against wherever the handbook is
    silent. The palette, gradients and page grid in `hhsk.typ` derive from it.
  - `Vormelementen-2024.ai` — the CMYK vector shape library holding the
    decorative wave/band elements the title page still lacks (see
    `docs/BACKLOG.md`, "Title-page shape is a placeholder"). Shapes only: it is
    CMYK, so the colour rule above applies to it.

## Corporate Identity (Rijnland)

The template applies the Rijnland brand identity:

- **Primary color**: `#0065BD` (PMS 300)
- **Secondary palette**: sand (`#C4B9A7`), dark-blue (`#002544`), mint (`#91D0D5`), brick (`#EA8A63`)
- **Typography**: Neusa Next Std (brand headings) → Lato (free substitute). Body uses **Lato Light** via Typst `weight: "light"`; headings use **Lato Bold** via `weight: "bold"`.
- **Logo placement**: title page centered at 12cm wide (not shown on content pages)
- **Pay-off**: "droge voeten, schoon water" on title page
- **Grid-based margins**: 25mm sides, 32mm bottom
- **Watermark**: "DRAFT" in foreground layer when `status != "FINAL"`
- **Footer**: Full-bleed dijk-en-sloot shape above Rijnland-blue bar, right-aligned project/page info (excluded from title page)
- **Diagram rendering**: Mermaid is rendered inline by the pure-Typst package `@preview/mmdr:0.2.2` (no Chromium, no `mmdc`). ArchiMate diagrams are exported to SVG by the pure-Python `module-archimate/v1/svg_export.py` (via the `archimate:save_model` MCP tool) and embedded with `#image()`.

### Font Setup Note

Typst identifies fonts by internal family name, not by filename. The Google Fonts Lato `.ttf` files register as family **"Lato"** with weight encoded in metadata; we reference `"Lato"` in `rijnland.typ` and control weight via Typst's `weight` parameter. Neusa Next Pro registers as **"Neusa Next Pro"**, and Ruda as **"Ruda"**. Always verify the family name a new font actually exposes:

```bash
typst fonts --variants --font-path assets/fonts
```

## Built-in Fonts (always available in Typst CLI)

- **Libertinus Serif** (system fallback) — body text
- **New Computer Modern** — alternative serif
- **New Computer Modern Math** — math/equations
- **DejaVu Sans Mono** — code / monospace

## Document Types Supported

| Type | Description |
|------|-------------|
| `functional_design` | Functioneel Ontwerp (FO) |
| `technical_design` | Technisch Ontwerp (TO) |
| `technical_research` | Technisch Onderzoek |
| `core_documentation` | Platform documentation |

## Usage

Agents author **native Typst** (`.typ`) directly and compile it through the
`make_pdf_document` / `verify_typst` builtin tools, which call
`DocumentFormatterService.compile_typ()` / `verify_typ()`.

The older Markdown→PDF pipeline — which expected a `content.md` plus a
`metadata.json` in the working directory — has been **removed** (see
`docs/BACKLOG.md`, "Document Formatter (PDF Generation)"). Do not write new code
against it.

The `.md` files in `test-inputs/` are retained fixtures from that era; the `.typ`
files are the ones exercised by the current tests.

## Template Variables (metadata)

Values passed into the template by the calling agent:

| Field | Type | Description |
|-------|------|-------------|
| `document_type` | string | One of the types above |
| `title` | string | Document title (header) |
| `status` | string | `"DRAFT"` or `"FINAL"` |
| `project_name` | string | Project name (header) |
| `include_toc` | boolean | Generate table of contents |
| `include_watermark` | boolean | Show draft watermark |
| `section_breaks` | boolean | Page break before h1 |
| `author` | string | Document author (optional) |

## Adding Custom Fonts

1. Create a subdirectory under `assets/fonts/` and place the `.ttf` / `.otf` files in it
2. Run `typst fonts --variants --font-path assets/fonts` to discover the exact family name and the weights it resolves
3. Reference the family in the template via `#set text(font: "Your Font")`
4. No config change needed — `TYPST_FONT_PATHS` already points at `assets/fonts` and scanning is recursive
