# Document Templates

This directory contains Typst document templates for PDF generation.

## Structure

```
base.typ                                       # Master template with Rijnland corporate identity
assets/
  Logo-hoogheemraadschap-rijnland.png         # Rijnland corporate logo
  fonts/
    Lato-Light.ttf                             # Body text (weight: "light")
    Lato-Regular.ttf                           # Fallback regular weight
    Lato-Bold.ttf                              # Headings (weight: "bold")
  style-guide.pdf                              # Reference: Huisstijlhandboek (januari 2023)
test-inputs/
  fo-test.md / fo-metadata.json                # FO test fixture
  to-test.md / to-metadata.json                # TO test fixture
```

## Corporate Identity

The template applies the Rijnland brand identity (from `style-guide.pdf`):

- **Primary color**: `#0065BD` (PMS 300)
- **Secondary palette**: sand (`#C4B9A7`), dark-blue (`#002544`), mint (`#91D0D5`), brick (`#EA8A63`)
- **Typography**: Neusa Next Std (brand headings) → Lato (free substitute). Body uses **Lato Light** via Typst `weight: "light"`; headings use **Lato Bold** via `weight: "bold"`.
- **Logo placement**: title page centered at 12cm wide (not shown on content pages)
- **Pay-off**: "droge voeten, schoon water" on title page
- **Grid-based margins**: 25mm sides, 32mm bottom
- **Watermark**: "DRAFT" in foreground layer when `status != "FINAL"`
- **Footer**: Full-bleed dijk-en-sloot shape above Rijnland-blue bar, right-aligned project/page info (excluded from title page)
- **Diagram rendering**: Mermaid → PNG via `mmdc`; ArchiMate → SVG via Node.js SSR (`/app/scripts/archimate-ssr/`)

### Font Setup Note

Typst identifies fonts by internal family name. The Google Fonts Lato `.ttf` files register as family **"Lato"** with weight encoded in metadata. We reference `"Lato"` in `base.typ` and control weight via Typst's `weight` parameter. If you add custom fonts, verify the family name recognised by Typst with:

```bash
typst fonts --font-path assets/fonts
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

The template is compiled by the backend `DocumentFormatterService`.
It expects two inputs in the working directory:

- `content.md` — Markdown body produced by the agent
- `metadata.json` — Structured metadata dict

## Template Variables (metadata)

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

1. Place `.ttf` or `.otf` files in `assets/fonts/`
2. Run `typst fonts --font-path assets/fonts` to discover the exact family name
3. Reference them in `base.typ` via `#set text(font: "Your Font")`
4. Ensure `TYPST_FONT_PATHS` env var points to this directory (already set in Dockerfile)
