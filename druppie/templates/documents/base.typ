// ============================================================================
// Druppie Document Formatter — Rijnland Corporate Identity Template
// ============================================================================
// Based on: Hoogheemraadschap van Rijnland Huisstijlhandboek (januari 2023)
//
// Corporate identity rules applied:
//   - Primary color: Rijnland Blauw (#0065BD)
//   - Typography: Neusa Next Std (headings) / Lato Light (body)
//   - Logo: bottom-right, 75% for A4
//   - Pay-off: "droge voeten, schoon water"
//   - Footer: title (left) | page number (center) | date (right)
//   - Dijk-en-sloot decorative element above footer
//
// Expected inputs:
//   - content.md   : Agent-written markdown body
//   - metadata.json: Document metadata dict
//   - assets/Logo-hoogheemraadschap-rijnland.png
//   - assets/fonts/Lato-*.ttf
// ============================================================================

#import "@preview/cmarker:0.1.8"

// ---- Load metadata ---------------------------------------------------------
#let meta = json("metadata.json")

#let doc-type      = meta.at("document_type", default: "memo")
#let title         = meta.at("title", default: "Untitled Document")
#let status        = meta.at("status", default: "DRAFT")
#let project-name  = meta.at("project_name", default: "")
#let include-toc   = meta.at("include_toc", default: false)
#let watermark     = meta.at("include_watermark", default: status != "FINAL")
#let breaks        = meta.at("section_breaks", default: true)
#let author        = meta.at("author", default: "")

// ============================================================================
// RIJNLAND COLOR PALETTE
// ============================================================================

// Primary
#let rijnland-blauw       = rgb("#0065BD")
#let rijnland-blauw-10   = rgb("#E9EFFA")

// Secondary
#let zand                 = rgb("#C4B9A7")
#let zand-licht           = rgb("#f0ece6")
#let donkerblauw          = rgb("#002544")
#let mint                 = rgb("#91D0D5")
#let baksteen             = rgb("#EA8A63")

// Functional
#let grijs-tekst          = rgb("#333333")
#let grijs-licht          = rgb("#999999")

// ============================================================================
// FONT SETUP
// ============================================================================

#set text(
  font: ("Neusa Next Std", "Lato", "Libertinus Serif"),
  weight: "light",
  size: 11pt,
  lang: "nl",
  fill: grijs-tekst,
)

#let heading-font = ("Neusa Next Std", "Lato", "Libertinus Serif")

#show raw: set text(
  font: ("DejaVu Sans Mono", "Consolas", "Courier New"),
  size: 9pt,
)

// ============================================================================
// DECORATIVE: DIJK EN SLOOT (dike + water motif)
// ============================================================================
// Horizontal rule: top bar = dijk (sand), lower line = sloot (blue wave).
#let dijk-en-sloot(size: 100%) = {
  block(width: size, height: 6pt)[
    #place(dy: 0pt, line(length: 100%, stroke: 0.8pt + zand))
    #place(dy: 3pt, line(length: 60%, stroke: 0.6pt + rijnland-blauw))
  ]
}

// ============================================================================
// PAGE GEOMETRY
// ============================================================================

#set page(
  paper: "a4",
  margin: (
    top:    25mm,
    right:  25mm,
    bottom: 30mm,
    left:   25mm,
  ),
)

// ============================================================================
// HEADER (content pages only)
// ============================================================================

#set page(
  header: context {
    let page-num = counter(page).get().first()
    if page-num > 1 {
      line(length: 100%, stroke: 0.5pt + rijnland-blauw)
      v(3pt)
      grid(
        columns: (1fr, 1fr),
        gutter: 0pt,
        text(8pt, donkerblauw)[#project-name],
        align(right, text(8pt, donkerblauw)[#doc-type.replace("_", " ")]),
      )
    }
  },
)

// ============================================================================
// FOOTER (every page)
// ============================================================================
// According to Huisstijlhandboek:
//   Left: document title
//   Center: page number
//   Right: date
//   Above: dijk-en-sloot decorative line

#set page(
  footer: context {
    let total   = counter(page).final().first()
    let page-nr = counter(page).display()
    let today   = datetime.today().display("[day]-[month]-[year]")
    // Decorative line
    dijk-en-sloot(size: 100%)
    v(4pt)
    grid(
      columns: (1fr, 1fr, 1fr),
      gutter: 0pt,
      text(8pt, grijs-licht)[#title],
      align(center, text(8pt, grijs-licht)[Pagina #page-nr van #total]),
      align(right, text(8pt, grijs-licht)[#today]),
    )
  },
)

// ============================================================================
// LOGO PATH
// ============================================================================

#let logo-path = "assets/Logo-hoogheemraadschap-rijnland.png"

// ============================================================================
// WATERMARK (draft)
// ============================================================================

#let show-watermark = watermark and status != "FINAL"

// ============================================================================
// BACKGROUND (watermark + logo — every page including title page)
// ============================================================================

#set page(
  background: context {
    // Watermark on every page when draft
    if show-watermark {
      place(
        center + horizon,
        rotate(-30deg, text(52pt, rijnland-blauw.lighten(75%))[
          #strong(upper(status))
        ]),
      )
    }
    // Logo bottom-right
    place(
      bottom + right,
      dx: -20mm,
      dy: -15mm,
      image(logo-path, width: 3cm),
    )
  },
)

// ============================================================================
// TITLE PAGE
// ============================================================================

#block(height: 100%, width: 100%)[
  #v(1fr)

  #align(center)[
    // Logo
    #image(logo-path, width: 5cm)
    #v(1.5cm)

    // Document title
    #text(
      font: heading-font,
      size: 22pt,
      weight: "bold",
      rijnland-blauw,
    )[#title]

    #v(0.5cm)

    // Project name
    #text(size: 12pt, donkerblauw)[#project-name]

    #v(0.3cm)

    // Date
    #text(size: 10pt, grijs-licht)[
      #datetime.today().display("[day]-[month]-[year]")
    ]

    // Draft indicator badge
    #if show-watermark {
      v(0.8cm)
      box(
        fill: rijnland-blauw-10,
        inset: 8pt,
        radius: 4pt,
        text(size: 10pt, rijnland-blauw, weight: "bold")[
          Niet-definitief — ter goedkeuring
        ],
      )
    }
  ]

  #v(2cm)

  // Pay-off
  #align(center)[
    #text(size: 11pt, donkerblauw, weight: "bold")[
      droge voeten, schoon water
    ]
  ]

  #v(1fr)

  // Author
  #if author != "" {
    align(center, text(9pt, grijs-licht)[Auteur: #author])
  }

  // Dijk-en-sloot accent at bottom of title page
  #dijk-en-sloot(size: 60%)
]

#pagebreak()

// ============================================================================
// TABLE OF CONTENTS
// ============================================================================

#if include-toc {
  v(1cm)
  text(
    font: heading-font,
    size: 14pt,
    weight: "bold",
    rijnland-blauw,
  )[Inhoudsopgave]
  v(0.8cm)
  outline(
    indent: auto,
    depth: 3,
    title: none,
  )
  pagebreak()
}

// ============================================================================
// SECTION BREAKS
// ============================================================================

#let breakable-tables = doc-type in ("technical_research", "core_documentation")

// H1
#show heading.where(level: 1): it => {
  if breaks {
    pagebreak(weak: true)
  }
  v(1cm)
  text(
    font: heading-font,
    size: 16pt,
    weight: "bold",
    rijnland-blauw,
  )[#it.body]
  line(length: 100%, stroke: 0.8pt + rijnland-blauw)
  v(0.5cm)
}

// H2
#show heading.where(level: 2): it => {
  v(0.8cm)
  text(
    font: heading-font,
    size: 13pt,
    weight: "bold",
    donkerblauw,
  )[#it.body]
  v(0.3cm)
}

// H3
#show heading.where(level: 3): it => {
  v(0.5cm)
  text(
    font: heading-font,
    size: 11pt,
    weight: "bold",
    grijs-tekst,
  )[#it.body]
  v(0.2cm)
}

// ============================================================================
// TABLE STYLING
// ============================================================================

#show table: it => {
  set text(size: 9.5pt)
  block(
    breakable: breakable-tables,
    inset: 6pt,
    stroke: 0.5pt + zand,
    radius: 2pt,
    it,
  )
}

#show table.header: set table.cell(
  fill: rijnland-blauw,
  inset: 6pt,
)
#show table.header: set text(weight: "bold", fill: white, size: 9pt)
#show table.cell: set text(size: 9pt)

// Striped rows
#show table.cell.where(y: 1): set table.cell(fill: rijnland-blauw-10)
#show table.cell.where(y: 3): set table.cell(fill: rijnland-blauw-10)
#show table.cell.where(y: 5): set table.cell(fill: rijnland-blauw-10)

// ============================================================================
// CODE BLOCKS / BLOCKQUOTES / LISTS
// ============================================================================

#show raw.where(block: true): it => {
  block(
    fill: rijnland-blauw-10,
    inset: 10pt,
    radius: 4pt,
    width: 100%,
    breakable: false,
    it,
  )
}

#show quote: it => {
  block(
    fill: zand-licht,
    inset: 10pt,
    radius: 2pt,
    stroke: (left: 4pt + rijnland-blauw),
    it,
  )
}

#set list(marker: (text(rijnland-blauw)[•], text(rijnland-blauw)[◦], text(rijnland-blauw)[▪]))

// ============================================================================
// MAIN CONTENT
// ============================================================================

#cmarker.render(read("content.md"))

// ============================================================================
// END MATTER
// ============================================================================

#pagebreak()
#align(center + horizon)[
  #text(size: 10pt, grijs-licht)[
    Dit document is gegenereerd met Druppie.
    #linebreak()
    #datetime.today().display("[day]-[month]-[year]")
  ]
]