---
name: research-writer
description: >
  Guides creation of research documents that investigate alternatives
  before architectural decisions. Covers the template, trade-off tables,
  source citation, and linking to resulting ADRs.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
  web:
    - search_web
    - fetch_url
---

# Research Writer

Research documents investigate alternatives and provide evidence-based
recommendations *before* an Architectural Decision Record is written.
They are the input to ADRs — research explores, ADRs decide.

## Where Research Fits in the Flow

Research comes AFTER the PRD (we know what we want) but BEFORE the ADR (we haven't decided yet).

**PRD** (we want something) → **Research** (what are the options?) → **ADR** (we decided X)

Research is OPTIONAL — only needed when there are genuinely multiple viable options and the
choice isn't obvious. If the decision is straightforward, skip research and go straight to ADR.

Research = "We're figuring this out"
ADR = "We've decided"

## When Research Is Needed

Write a research document when:

- An ADR is needed but the options are unclear or contested.
- Multiple technologies, patterns, or approaches are viable and need
  comparison.
- The team needs evidence to make an informed architectural choice.
- A new domain or technology is being introduced that no one on the team
  has deep experience with.

Do **not** write research when:

- The choice is obvious and uncontested (just write the ADR).
- An existing research doc already covers the topic.
- The decision is a minor implementation detail, not an architectural choice.

## Research Template — YAML Frontmatter Format (MANDATORY)

The canonical format is defined by `docs/research/TEMPLATE.md`. Every research
doc is a Markdown file with **YAML frontmatter between `---` delimiters**,
followed by a fixed set of body sections.

Create the file as `docs/research/NNN-short-kebab-title.md` (3-digit id matching
the frontmatter `id`):

```markdown
---
id: 000                              # Sequential research number (e.g. 001, 002)
title: Research topic                # Short, descriptive name
status: draft                        # draft | complete
author: role name                    # Who conducted this research
date: 2026-06-09                     # Date of research (YYYY-MM-DD)
outcome: null                        # "adr-NNN" if research led to an ADR, or null
---

# Research: {title}

## Question

What specific question is this research trying to answer?
One clear question, not a vague area of investigation.

## Background

Brief context: why is this question relevant right now?
What triggered the need for this research?

## Approach

How we researched (sources, experiments, benchmarks):

- Source or experiment 1
- Source or experiment 2

## Findings

### Option Comparison

| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| Option A | ... | ... | low/med/high | S/M/L |
| Option B | ... | ... | ... | ... |

### Additional Notes

Details beyond the comparison table (benchmarks, bundle sizes, etc.).

## Trade-off Analysis

Weighted comparison of the top options against relevant criteria:

| Criterion | Weight | Option A | Option B |
|-----------|--------|----------|----------|
| Criterion 1 | 1-5 | Score (weighted) | Score (weighted) |
| Criterion 2 | 1-5 | Score | Score |
| **Total** | | **Sum** | **Sum** |

## Recommendation

Recommended option and why (2-3 sentences tying back to the criteria).

## Open Items

- Open item 1
- Open item 2

## Resulting ADR

<!-- Auto-populated from the `outcome` frontmatter field. -->
```

### Required frontmatter fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | integer | Sequential research number (e.g. `001`). |
| `title` | string | Short, descriptive name. |
| `status` | string | One of `draft`, `complete`. |
| `author` | string | Role or name of the researcher. |
| `date` | string | `YYYY-MM-DD`. |
| `outcome` | string or null | `"adr-NNN"` once an ADR results from this research, else `null`. |

### Body sections (fixed order)

**Question**, **Background**, **Approach**, **Findings** (with **Option
Comparison** table and **Additional Notes**), **Trade-off Analysis**,
**Recommendation**, **Open Items**, **Resulting ADR** — matching
`docs/research/TEMPLATE.md`. There is no prose "Next Steps" section for the ADR
link — that information lives in the `outcome` frontmatter field and is rendered
into the **Resulting ADR** section.

## Trade-off Table Format

The trade-off table is the core of the research document. Fill every cell:

- **Pros** — Concrete advantages, not vague praise.
  Good: "Sub-10ms p95 latency at 10k RPS". Bad: "Fast".
- **Cons** — Concrete disadvantages, not hedging.
  Good: "Requires dedicated GPU for inference". Bad: "Might be slow".
- **Risk** — What could go wrong if we choose this option.
  Include likelihood (low/med/high) and impact.
- **Effort** — Implementation and maintenance effort.
  Low = days, Med = weeks, High = months.

## Sources Must Be Cited

- Every factual claim must trace to a source, listed in the **Approach** section.
- Prefer primary sources (official docs, benchmarks, spec papers) over
  blog posts or second-hand summaries.
- Use the `web` tools (`search_web`, `fetch_url`) to find and read sources.
- Include the URL and a brief note on why the source is relevant.
- If a claim cannot be sourced, mark it explicitly: `[unsourced claim]`.

## Recommendation Must Be Clear

- State exactly one recommended option (no "Option A or B depending on...").
- If the recommendation truly depends on an unknown, state the decision
  tree: "Choose Option A if X, Option B if Y."
- The recommendation should follow directly from the trade-off analysis —
  no surprises.

## Linking to the Resulting ADR

After the research is complete and an ADR is written, the link is tracked in
frontmatter on both sides — there is no prose "Next Steps" or "Related" section:

1. In the research doc's frontmatter, set `outcome: "adr-NNN"` (the resulting
   ADR's id). This renders into the **Resulting ADR** body section automatically.
2. In the ADR's frontmatter, set `linked_research` to this research doc's path
   (e.g. `"docs/research/001-state-mgmt.md"`).
3. Update the research doc's frontmatter `status` to `complete`.
