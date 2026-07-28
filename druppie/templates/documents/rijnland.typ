// ============================================================================
// Rijnland Corporate Identity Template Library
// ============================================================================
// Based on: Hoogheemraadschap van Rijnland Huisstijlhandboek (januari 2023)
//
// Usage:
//   #import "druppie/templates/documents/rijnland.typ": rijnland_doc
//   #show: document.with(
//     title: "Document Title",
//     document_type: "functional_design",
//     status: "DRAFT",
//     project_name: "Project Name",
//     include_toc: true,
//     include_watermark: true,
//     section_breaks: true,
//     author: "",
//   )
//   = Heading 1
//   Your native Typst content here.
// ============================================================================

// ============================================================================
// COLOR PALETTE
// ============================================================================

// Primary
#let rijnland-blauw     = rgb("#0065BD")
#let rijnland-blauw-10  = rgb("#E9EFFA")

// Secondary
#let zand               = rgb("#C4B9A7")
#let zand-licht         = rgb("#f0ece6")
#let donkerblauw        = rgb("#002544")
#let mint               = rgb("#91D0D5")
#let baksteen           = rgb("#EA8A63")

// Functional
#let grijs-tekst        = rgb("#333333")
#let grijs-licht        = rgb("#999999")

// ============================================================================
// UTILITIES
// ============================================================================

#let dutch-month-name(m) = {
  let names = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december"
  )
  names.at(m - 1)
}

// ============================================================================
// DOCUMENT TEMPLATE
// ============================================================================

#let rijnland_doc(
  body,
  title: "Untitled Document",
  document_type: "memo",
  status: "DRAFT",
  project_name: "",
  include_toc: false,
  include_watermark: true,
  section_breaks: true,
  author: "",
) = {
  let heading-font = ("Neusa Next Pro", "Lato", "Libertinus Serif")
  let show-watermark = include_watermark and status != "FINAL"
  let logo-path = "assets/Logo-hoogheemraadschap-rijnland.png"
  let breakable-tables = true

  // ---- Font & text ---------------------------------------------------------
  set text(
    font: ("Lato", "Libertinus Serif"),
    weight: "light",
    size: 11pt,
    lang: "nl",
    fill: grijs-tekst,
    hyphenate: true,
  )

  show raw: set text(
    font: ("DejaVu Sans Mono", "Consolas", "Courier New"),
    size: 9pt,
  )

  // ---- Page geometry + header + footer + layers ----------------------------
  set page(
    paper: "a4",
    margin: (
      top:    25mm,
      right:  25mm,
      bottom: 32mm,
      left:   25mm,
    ),
    header: context {
      let page-num = counter(page).get().first()
      if page-num > 1 {
        line(length: 100%, stroke: 0.5pt + rijnland-blauw)
        v(3pt)
        grid(
          columns: (1fr, 1fr),
          gutter: 0pt,
          text(8pt, donkerblauw)[#project_name],
          align(right, text(8pt, donkerblauw)[#document_type.replace("_", " ")]),
        )
      }
    },
    footer: context {
      let total   = counter(page).final().first()
      let page-nr = counter(page).display()
      let month   = dutch-month-name(datetime.today().month())
      let year    = str(datetime.today().year())
      let page-idx = counter(page).get().first()

      if page-idx > 1 {
        place(
          bottom + left,
          dx: -25mm,
          block(
            width: 210mm,
            inset: (bottom: 6pt),
            fill: rijnland-blauw,
          )[
            #place(top + left, dy: -22pt)[
              #image("assets/dijkEnSloot.png", width: 210mm, height: 24pt)
            ]
            #align(horizon)[
              #pad(left: 25mm, right: 25mm)[
                #align(right)[
                  #box(width: 100%)[
                    #text(7.5pt, white, weight: "regular")[Hoogheemraadschap van Rijnland]
                    #h(2em)
                    #text(7.5pt, white.transparentize(35%), weight: "regular")[#project_name - versie #month #year]
                    #h(2em)
                    #text(7.5pt, white, weight: "regular")[#page-nr / #total]
                  ]
                ]
              ]
            ]
          ]
        )
      }
    },
    background: context {},
    foreground: context {
      if show-watermark {
        place(
          center + horizon,
          rotate(-30deg, text(52pt, fill: rijnland-blauw.lighten(75%).transparentize(50%))[
            #strong(upper(status))
          ]),
        )
      }
    },
  )

  // ---- Title page ----------------------------------------------------------
  block(height: 100%, width: 100%)[
    #v(1fr)

    #align(center)[
      #image(logo-path, width: 12cm)
      #v(1.5cm)

      #text(
        font: heading-font,
        size: 22pt,
        weight: "bold",
        rijnland-blauw,
      )[#title]

      #v(0.5cm)

      #text(size: 12pt, donkerblauw)[#project_name]

      #v(0.3cm)

      #text(size: 10pt, grijs-licht)[
        #datetime.today().display("[day]-[month]-[year]")
      ]

      #v(0.4cm)

      #text(size: 8pt, grijs-licht)[
        Dit document is gegenereerd met behulp van AI.
      ]

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

      #v(0.6cm)

      #text(size: 9pt, grijs-licht)[
        Dit traject dient om het AI-platform te leren en verbeteren.
        Geen garantie op een volledige oplossing, vaste planning of maatwerkontwikkeling.
      ]
    ]

    #v(2cm)

    #align(center)[
      #text(size: 11pt, donkerblauw, weight: "bold")[
        droge voeten, schoon water
      ]
    ]

    #v(1fr)

    #if author != "" [
      #align(center)[#text(9pt, grijs-licht)[Auteur: #author]]
    ]

    #v(0.8cm)
  ]

  pagebreak()

  // ---- Table of contents -----------------------------------------------------
  if include_toc {
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

  // ---- Heading styles ------------------------------------------------------
  show heading.where(level: 1): it => {
    if section_breaks {
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

  show heading.where(level: 2): it => {
    v(0.8cm)
    text(
      font: heading-font,
      size: 13pt,
      weight: "bold",
      donkerblauw,
    )[#it.body]
    v(0.3cm)
  }

  show heading.where(level: 3): it => {
    v(0.5cm)
    text(
      font: heading-font,
      size: 11pt,
      weight: "bold",
      grijs-tekst,
    )[#it.body]
    v(0.2cm)
  }

  // ---- Table styling --------------------------------------------------------
  show table: it => {
    set text(size: 9.5pt)
    block(
      breakable: breakable-tables,
      inset: 6pt,
      stroke: 0.5pt + zand,
      radius: 2pt,
      it,
    )
  }

  show table.header: set table.cell(
    fill: rijnland-blauw,
    inset: 6pt,
  )
  show table.header: set text(weight: "bold", fill: white, size: 9pt)
  show table.cell: set text(size: 9pt)

  // Striped rows — every odd row (excluding header at y=0)
  show table.cell.where(y: y => calc.rem(y, 2) == 1): set table.cell(fill: rijnland-blauw-10)

  // ---- Code blocks ---------------------------------------------------------
  show raw.where(block: true): it => {
    block(
      fill: rijnland-blauw-10,
      inset: 10pt,
      radius: 4pt,
      width: 100%,
      breakable: false,
      it,
    )
  }

  // ---- Blockquotes ---------------------------------------------------------
  show quote: it => {
    block(
      fill: zand-licht,
      inset: 10pt,
      radius: 2pt,
      stroke: (left: 4pt + rijnland-blauw),
      it,
    )
  }

  // ---- Lists ---------------------------------------------------------------
  set list(marker: (text(rijnland-blauw)[•], text(rijnland-blauw)[◦], text(rijnland-blauw)[▪]))

  // ---- Body ----------------------------------------------------------------
  body
}
