// ============================================================================
// HHSK Corporate Identity Template Library
// ============================================================================
// Hoogheemraadschap van Schieland en de Krimpenerwaard (HHSK)
// Based on: Huisstijlhandboek HHSK 2026 (v2, juli 2025)
// Palette + gradients verified byte-exact against the vector source logo.ai.
//
// Deliberately mirrors the signature and structure of rijnland.typ so the two
// house styles are interchangeable from the calling agent's point of view.
//
// Usage:
//   #import "druppie/templates/documents/hhsk.typ": hhsk_doc
//   #show: hhsk_doc.with(
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

#import "_shared.typ": (
  ai-generated-notice, ai-trajectory-disclaimer, breakable-table-types,
  document-type-label, draft-badge-text, dutch-date, status-label,
)

// ============================================================================
// COLOR PALETTE — authoritative sRGB values from the logo.ai swatch library
// ============================================================================
// NOTE: these are the .ai swatch values, NOT the printed table in the
// handbook, which is slightly wrong on the two 40% tints. Do not "correct"
// them against the PDF.

#let donkerblauw    = rgb("#293173")
#let donkergroen    = rgb("#015F03")
#let blauw          = rgb("#0067C6")
#let groen          = rgb("#76B900")
#let oranje         = rgb("#F9651F")
#let lichtoranje    = rgb("#FFBC80")
#let lichtblauw     = rgb("#8ED4DA")
#let lichtblauw-40  = rgb("#D2EEF0")
#let lichtgroen     = rgb("#CBDF74")
#let lichtgroen-40  = rgb("#EAF2C7")
#let wit            = rgb("#FFFFFF")

// ============================================================================
// ACCESSIBILITY MATRIX — NORMATIVE. Check every colour choice against this.
// ============================================================================
// Size rules:
//   Large text / heading : >= 18pt regular OR >= 14pt bold, contrast >= 3:1
//   Small text           : <= 17pt regular OR <= 13pt bold, contrast >= 4.5:1
//   Black-on-white and white-on-black are always allowed.
//   ANY combination not listed below is FORBIDDEN.
//
// Legend: K = headings / large text only.  K+T = large AND small text.
// The handbook states every pairing below is ALSO valid reversed (fg <-> bg).
//
//   on WIT #FFFFFF
//     blauw K+T | donkerblauw K+T | donkergroen K+T
//     blauwverloop K+T | groenverloop K+T | oranje K
//
//   on DONKERBLAUW #293173
//     lichtblauw-40 K+T | lichtblauw K+T | lichtgroen-40 K+T
//     lichtgroen K+T | groen K+T | lichtoranje K+T | oranje K
//
//   on BLAUW #0067C6
//     lichtblauw K | lichtgroen-40 K+T | lichtgroen K
//     lichtoranje K | lichtblauw-40 K+T | blauwverloop K+T
//
//   on DONKERGROEN #015F03
//     lichtblauw-40 K+T | lichtblauw K | lichtgroen-40 K+T
//     lichtgroen K+T | groen K | lichtoranje K+T
//
//   on ZWART #000000
//     lichtblauw-40 K+T | lichtblauw K+T | blauw K | lichtgroen-40 K+T
//     lichtgroen K+T | groen K+T | lichtoranje K+T | oranje K+T
//
// Pairings actually used in this template (all present in the matrix above):
//   donkerblauw   on wit            K+T  -> body, headings H2-H4, captions
//   blauwverloop  on wit            K+T  -> H1 / title (large text only)
//   oranje        on wit            K    -> DRAFT watermark (large text)
//   wit           on donkerblauw    K+T  -> table header (reversed pairing)
//   donkerblauw   on lichtblauw-40  K+T  -> striped rows, code blocks (reversed)
//   donkerblauw   on lichtgroen-40  K+T  -> blockquotes (reversed)
// ============================================================================

// ============================================================================
// GRADIENTS — "enkel toegepast in koppen" (headings only!)
// ============================================================================
// The .ai gradients are exponential, not linear: interpolating from C0 the
// colour follows C(t) = C0 + t^N * (C1 - C0). Typst's gradient.linear only
// interpolates linearly between stops, so a naive 2-stop gradient would put
// the midpoint at 50% instead of where the brand actually puts it. We
// therefore sample the exponential curve at 1/8 intervals and hand Typst 9
// positioned stops; the piecewise-linear result is visually indistinguishable
// from the true curve.
//
// blauwverloop: blauw -> donkerblauw, N = 1.26229.
//   Midpoint colour lands 57.75% from the donkerblauw end (= 42.25% from blauw).
// groenverloop: groen -> donkergroen, N = 1.27655.
//   Midpoint colour lands 41.90% from the groen end.
//
// HARD RULE from the handbook: gradients are permitted ONLY in headings,
// specifically large title headings. NEVER as a page or panel background.

#let blauwverloop-stops = (
  (rgb("#0067C6"), 0%),
  (rgb("#065FB9"), 12.5%),
  (rgb("#0C57AD"), 25%),
  (rgb("#124FA1"), 37.5%),
  (rgb("#184896"), 50%),
  (rgb("#1D418B"), 62.5%),
  (rgb("#223A81"), 75%),
  (rgb("#263579"), 87.5%),
  (rgb("#293173"), 100%),
)

#let groenverloop-stops = (
  (rgb("#76B900"), 0%),
  (rgb("#64AB00"), 12.5%),
  (rgb("#529D01"), 25%),
  (rgb("#419001"), 37.5%),
  (rgb("#318402"), 50%),
  (rgb("#227902"), 62.5%),
  (rgb("#156E02"), 75%),
  (rgb("#096503"), 87.5%),
  (rgb("#015F03"), 100%),
)

// CHOICE: horizontal (0deg) gradient direction. The handbook shows the
// gradient running across the width of a heading; it does not fix an angle.
#let blauwverloop = gradient.linear(..blauwverloop-stops, angle: 0deg)
#let groenverloop = gradient.linear(..groenverloop-stops, angle: 0deg)

// ============================================================================
// TYPOGRAPHY
// ============================================================================
// House font is Ruda. Available weights: Regular(400), Medium(500),
// SemiBold(600), Bold(700), ExtraBold(800), Black(900).
//
// !! THERE IS NO RUDA ITALIC AND NO RUDA LIGHT !!
// Never set italic in this template — Typst would synthesise a fake oblique,
// which is off-brand. For emphasis use weight (600/700/900) or a palette
// colour from the accessibility matrix instead. `show emph:` below enforces
// this so that markdown-ish `_emphasis_` in agent output degrades gracefully.
//
// Headings: Ruda Black (900). Body: Ruda Regular (400).
// DejaVu Sans is only a fallback so the template still compiles on a machine
// where the Ruda font-path was not wired up.
#let hhsk-font = ("Ruda", "DejaVu Sans")
#let hhsk-mono = ("DejaVu Sans Mono", "Consolas", "Courier New")

// ============================================================================
// LAYOUT CONSTANTS
// ============================================================================
// Portrait A4 is governed by an 8-part horizontal grid; the logo sits against
// the top or bottom edge inside the outer 1/8 band. (Landscape uses a 6-part
// grid — not needed here.)
#let page-height    = 297mm
#let grid-band      = page-height / 8   // 37.125mm — the outer logo band
#let page-margin    = 15mm              // the only margin figure in the handbook
#let logo-clearance = 7mm               // must stay empty on all sides of the logo
#let corner-radius  = 15mm              // minimum radius on A4 for panels/shapes

// Logo is 90mm x 28.5mm at 100% (aspect 3.158:1). At 100% plus the 15mm
// margin the logo would end 43.5mm down the page, i.e. outside the 1/8 band,
// so the title-page logo is scaled to fit the band.
// CHOICE: 70mm wide (~78%) -> 22.2mm tall; 15mm + 22.2mm = 37.2mm, which lands
// exactly on the 1/8 grid line. The logo ALWAYS sits on a white background.
#let logo-path       = "assets/hhsk/logo.png"
#let logo-width      = 70mm
#let logo-width-full = 90mm  // 100% size, for reference

// LOGO VARIANTS — handbook usage rule
// ------------------------------------------------------------------
// The handbook supplies two full logo lock-ups (mark + wordmark):
//   logo.png       — FC (full-colour). Use ONLY on a WHITE background.
//   logo_white.png — diapositief (all-white). Use ONLY on a COLOURED
//                    background (donkerblauw/blauw/donkergroen) or over
//                    photography.
// CHOICE: the title page uses the FC logo (`logo-path`). Per the grid rules
// the cover logo "always sits on a white background", and it is placed in the
// top-left 1/8 band which is white — the graphic shape element (below) bleeds
// in from the bottom-right and is deliberately kept out of that quadrant, so
// the logo never overlaps a coloured surface. FC-on-white is the matrix's
// baseline pairing, so this is correct and compliant.
//
// CHOICE: the white variant is wired up as an available asset but is NOT
// placed anywhere in the default report layout. The only coloured surface in
// this template is the title-page shape, and that shape is legally restricted
// to the light 40% tints (lichtblauw-40 / lichtgroen-40, see the shape rule
// below). White-on-lichtblauw-40 and white-on-lichtgroen-40 are NOT in the
// accessibility matrix — they fail contrast — so the white logo may not sit on
// the shape. It becomes usable the moment a donkerblauw/blauw/donkergroen
// panel or a photograph is introduced (e.g. a chapter divider or a cover
// photo); render-tested white-on-donkerblauw and it is crisp and legible.
#let logo-white-path = "assets/hhsk/logo_white.png"

// BEELDMERK (mark only, no wordmark) — Beeldmerk.svg, full-colour vector.
// CHOICE: intentionally UNUSED in the document body. The handbook restricts
// the standalone beeldmerk to profile pictures / official channels and states
// it is applied by Communications only; it is explicitly not required in a
// report. Wiring it in would clutter the layout and overreach the usage rule.
// It is also the FC (colour) mark — its donkerblauw wave disappears on a dark
// background, so it too belongs on white; there is no diapositief beeldmerk in
// the asset set. The path is recorded here so a future Communications-approved
// use (e.g. a footer mark on white) can reference it without hunting for it.
#let beeldmerk-path  = "assets/hhsk/Beeldmerk.svg"

#let tagline      = "Droge voeten en schoon water"
#let organisation  = "Hoogheemraadschap van Schieland en de Krimpenerwaard"
#let organisation-short = "HHSK"
#let domain        = "schielandendekrimpenerwaard.nl"

// ============================================================================
// TYPE SCALE
// ============================================================================
// CHOICE: the handbook specifies no point sizes at all. This scale is chosen
// to satisfy the accessibility floors above and to sit comfortably on A4 with
// 15mm margins. Every size is annotated with which accessibility rule it must
// clear. Sign these off before treating them as brand-approved.
//
// CHOICE: H1/title use the gradient and are >= 18pt, so they legitimately
// qualify as "large text" (>= 3:1). Everything smaller is treated as small
// text and only ever uses donkerblauw (>= 4.5:1 on white) or a reversed
// pairing from the matrix.
#let size-title   = 30pt  // title page — large text (gradient allowed)
#let size-h1      = 20pt  // large text (>= 18pt) — gradient allowed
#let size-h2      = 15pt  // large text (>= 14pt at weight 900)
#let size-h3      = 12.5pt // small text -> donkerblauw only (11:1 on white)
#let size-h4      = 11pt  // small text -> donkerblauw only
#let size-body    = 11pt  // small text, <= 17pt regular: OK
#let size-caption = 9pt   // small text
#let size-table   = 9.5pt // small text
#let size-code    = 9pt   // small text
#let size-meta    = 8pt   // header/footer — small text
#let size-watermark = 60pt // large text

// CHOICE: 0.65em leading (~1.5x line height at 11pt) for comfortable Dutch
// prose; Ruda has a large x-height and looks cramped at Typst's default.
#let body-leading = 0.65em

// ============================================================================
// DOCUMENT TEMPLATE
// ============================================================================

#let hhsk_doc(
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
  let show-watermark = include_watermark and status != "FINAL"
  let breakable-tables = document_type in breakable-table-types
  let type-label = document-type-label(document_type)

  // ---- Font & text ---------------------------------------------------------
  // DEFAULT TEXT COLOUR IS donkerblauw, NOT black. This is explicit in the
  // handbook and applies to body copy as well as headings.
  set text(
    font: hhsk-font,
    weight: 400,          // Ruda Regular
    size: size-body,
    lang: "nl",
    fill: donkerblauw,
    hyphenate: true,
  )
  set par(leading: body-leading, justify: false)

  // CHOICE: syntax highlighting is switched OFF (theme: none). Typst's default
  // raw theme paints keywords/strings in reds and greens that are not in the
  // HHSK palette, and the accessibility matrix is normative: any pairing not
  // listed there is forbidden. Monochrome donkerblauw code is the compliant
  // option. Revisit if a brand-palette .tmTheme is ever produced.
  set raw(theme: none)
  show raw: set text(font: hhsk-mono, size: size-code, fill: donkerblauw)

  // No Ruda italic exists — render emphasis as SemiBold instead of a
  // synthesised oblique.
  show emph: it => text(weight: 600, it.body)
  show strong: set text(weight: 700)

  // ---- Page geometry + header + footer + layers ----------------------------
  set page(
    paper: "a4",
    margin: (
      top:    page-margin,
      right:  page-margin,
      bottom: page-margin + 8mm,  // CHOICE: extra room for the footer block
      left:   page-margin,
    ),

    // CHOICE: the handbook gives no header/footer content rules. Running
    // header from page 2 onward carries the project and document type; the
    // title page stays clean so the logo keeps its 7mm clear space.
    header: context {
      if counter(page).get().first() > 1 {
        grid(
          columns: (1fr, auto),
          gutter: 0pt,
          text(size-meta, donkerblauw)[#project_name],
          text(size-meta, donkerblauw)[#type-label],
        )
        v(2pt)
        line(length: 100%, stroke: 0.6pt + blauw)
      }
    },

    // CHOICE: footer carries the full organisation name, the tagline/domain
    // and "page / total". Plain donkerblauw on white — no coloured bar, since
    // large filled panels are reserved for the graphic shape element.
    footer: context {
      if counter(page).get().first() > 1 {
        line(length: 100%, stroke: 0.6pt + blauw)
        v(3pt)
        // Columns are (auto, 1fr, auto): the organisation name is long and
        // must keep its natural width or it wraps into the tagline.
        grid(
          columns: (auto, 1fr, auto),
          gutter: 6mm,
          text(size-meta, donkerblauw)[#organisation],
          align(center, text(size-meta, donkerblauw)[#tagline]),
          align(right, text(size-meta, donkerblauw)[
            #counter(page).display() / #counter(page).final().first()
          ]),
        )
      }
    },

    // Graphic shape element: preferably full page height, ALWAYS bleeding off
    // the page, ONLY in lichtblauw-40 or lichtgroen-40, never filled with
    // imagery. We have no vector shape assets wired up yet, so this is a
    // simple bleeding rounded rect approximation.
    // NOTE: this is a *shape*, not a gradient panel — gradients are headings
    // only. It is kept off the top-left quadrant so the logo keeps its white
    // background and 7mm clear space.
    // CONTRAST NOTE: because this shape is a light 40% tint, it is NOT a valid
    // background for the white (diapositief) logo — white-on-lichtblauw-40
    // fails the matrix. The FC logo therefore stays on the white area above;
    // the white logo (logo-white-path) is reserved for donkerblauw/blauw/
    // donkergroen surfaces, which this layout does not currently contain.
    background: context {
      if counter(page).get().first() == 1 {
        place(
          bottom + right,
          dx: 40mm,   // bleeds off the right edge
          dy: 30mm,   // bleeds off the bottom edge
          rect(
            width: 130mm,
            height: 210mm,   // CHOICE: ~70% of page height, tall but not full
            fill: lichtblauw-40,
            radius: corner-radius,
            stroke: none,
          ),
        )
      }
    },

    foreground: context {
      if show-watermark {
        place(
          center + horizon,
          rotate(-30deg, text(
            size: size-watermark,
            weight: 900,
            // oranje is permitted on wit for large text (K). Transparency is
            // applied because a watermark must sit behind readable body copy;
            // it is decorative and never the only carrier of information.
            fill: oranje.transparentize(80%),
          )[#upper(status)]),
        )
      }
    },
  )

  // ---- Title page ----------------------------------------------------------
  // Logo top-left, against the top edge, inside the outer 1/8 band.
  // (The handbook contradicts itself: p2 says linksboven/linksonder, p3 says
  // linksonder/rechtsboven — but p3's own illustrations show top-left and
  // bottom-left, so p2 is authoritative. Top-left it is.)
  block(height: 100%, width: 100%)[
    #image(logo-path, width: logo-width)

    // 7mm mandatory clear space below the logo before any content.
    #v(logo-clearance)

    #v(1fr)

    // Title — large text, set in the blue gradient (headings only).
    #text(
      font: hhsk-font,
      size: size-title,
      weight: 900,          // Ruda Black
      fill: blauwverloop,
    )[#title]

    #v(8mm)

    #if project_name != "" [
      #text(size: 14pt, weight: 700, fill: donkerblauw)[#project_name]
      #v(3mm)
    ]

    #text(size: 12pt, weight: 500, fill: donkerblauw)[#type-label]

    #v(3mm)

    #text(size: size-body, fill: donkerblauw)[
      #dutch-date(datetime.today())
      #h(1em) · #h(1em)
      #status-label(status)
    ]

    #if author != "" [
      #v(3mm)
      #text(size: 10pt, fill: donkerblauw)[Auteur: #author]
    ]

    #if show-watermark [
      #v(8mm)
      // donkerblauw on lichtgroen-40 — reversed pairing, K+T. Radius kept
      // small: the 15mm minimum applies to page-scale panels/shapes, not to
      // an inline badge.
      #box(
        fill: lichtgroen-40,
        inset: 10pt,
        radius: 4pt,
        text(size: 10pt, weight: 700, fill: donkerblauw)[#draft-badge-text],
      )
    ]

    #v(1fr)

    // AI disclaimer — carried across from the Rijnland template.
    #block(width: 105mm)[
      #text(size: size-caption, fill: donkerblauw)[#ai-generated-notice]
      #v(2mm)
      #text(size: size-caption, fill: donkerblauw)[#ai-trajectory-disclaimer]
    ]

    #v(8mm)

    #text(size: 12pt, weight: 900, fill: donkerblauw)[#tagline]
    #v(2mm)
    #text(size: size-meta, fill: donkerblauw)[#organisation · #domain]
  ]

  pagebreak()

  // ---- Table of contents ---------------------------------------------------
  if include_toc {
    text(
      font: hhsk-font,
      size: size-h1,
      weight: 900,
      fill: blauwverloop,
    )[Inhoudsopgave]
    v(8mm)
    outline(indent: auto, depth: 3, title: none)
    pagebreak()
  }

  // ---- Heading styles ------------------------------------------------------
  // CHOICE: H1 is the only heading that uses the gradient (handbook: gradients
  // in large title headings). H2-H4 are flat donkerblauw so they stay inside
  // the small-text 4.5:1 rule as they shrink.
  show heading.where(level: 1): it => {
    if section_breaks { pagebreak(weak: true) }
    v(6mm)
    text(font: hhsk-font, size: size-h1, weight: 900, fill: blauwverloop)[#it.body]
    v(0.5mm)
    line(length: 100%, stroke: 1pt + blauw)
    v(5mm)
  }

  show heading.where(level: 2): it => {
    v(7mm)
    text(font: hhsk-font, size: size-h2, weight: 900, fill: donkerblauw)[#it.body]
    v(2.5mm)
  }

  show heading.where(level: 3): it => {
    v(5mm)
    text(font: hhsk-font, size: size-h3, weight: 700, fill: donkerblauw)[#it.body]
    v(2mm)
  }

  show heading.where(level: 4): it => {
    v(4mm)
    text(font: hhsk-font, size: size-h4, weight: 700, fill: donkerblauw)[#it.body]
    v(1.5mm)
  }

  // ---- Table styling -------------------------------------------------------
  // CHOICE: no outer box, hairline blauw rules, 6pt cell padding. Header row
  // is wit on donkerblauw (reversed matrix pairing); body rows alternate white
  // and lichtblauw-40, both carrying donkerblauw text — also a reversed
  // matrix pairing, so contrast stays >= 4.5:1 at 9.5pt.
  //
  // IMPLEMENTATION NOTE: row fills are driven by table's `fill` callback, NOT
  // by `show table.cell.where(y: <predicate>)`. `.where()` only matches
  // literal field values — handing it a function produces a selector that
  // silently never matches, so a predicate-based striping rule compiles fine
  // and then does nothing. The callback is the supported mechanism.
  set table(
    stroke: 0.5pt + blauw.transparentize(60%),
    inset: 6pt,
    // y == 0 is the header row (whether declared via table.header or just
    // written as the first row); odd rows below it get the subtle stripe.
    fill: (x, y) => {
      if y == 0 { donkerblauw } else if calc.rem(y, 2) == 1 { lichtblauw-40 }
    },
  )
  show table: it => block(breakable: breakable-tables, it)

  show table.cell: set text(size: size-table, fill: donkerblauw)
  // Header row: wit on donkerblauw — the reversed "donkerblauw on wit" K+T
  // pairing, so contrast holds at 9.5pt bold.
  show table.cell.where(y: 0): set text(weight: 700, fill: wit)

  // ---- Figures / captions --------------------------------------------------
  // CHOICE: captions are small, donkerblauw, SemiBold to separate them from
  // body copy without resorting to italic (which Ruda does not have).
  show figure.caption: it => text(size: size-caption, weight: 600, fill: donkerblauw)[
    #it.supplement #context it.counter.display(it.numbering) — #it.body
  ]

  // ---- Code blocks ---------------------------------------------------------
  // CHOICE: lichtblauw-40 panel, 4pt radius (inline element, not a page-scale
  // shape, so the 15mm minimum does not apply), donkerblauw monospace text.
  show raw.where(block: true): it => block(
    fill: lichtblauw-40,
    inset: 10pt,
    radius: 4pt,
    width: 100%,
    breakable: false,
    text(fill: donkerblauw, it),
  )

  // ---- Blockquotes ---------------------------------------------------------
  // CHOICE: lichtgroen-40 panel with a groen rule on the left. The handbook
  // allows quotes to carry primary palette colours provided contrast holds —
  // donkerblauw on lichtgroen-40 is a permitted (reversed) K+T pairing.
  show quote: it => block(
    fill: lichtgroen-40,
    inset: 10pt,
    radius: 4pt,
    width: 100%,
    stroke: (left: 3pt + groen),
    text(fill: donkerblauw, it),
  )

  // ---- Lists ---------------------------------------------------------------
  // CHOICE: filled/hollow/small square glyph progression in donkerblauw, with
  // a slightly wider indent than Typst's default so nested lists stay legible
  // at 11pt. Markers are donkerblauw on white — a permitted K+T pairing.
  set list(
    marker: (
      text(fill: donkerblauw)[•],
      text(fill: donkerblauw)[◦],
      text(fill: donkerblauw)[▪],
    ),
    indent: 4mm,
    spacing: 0.9em,
  )
  set enum(indent: 4mm, spacing: 0.9em)
  show enum: set text(fill: donkerblauw)

  // ---- Body ----------------------------------------------------------------
  body
}
