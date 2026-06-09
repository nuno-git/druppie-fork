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

## Research Template

Create the file as `docs/research/YYYY-MM-DD-topic.md`:

```markdown
# Research: Short Title

**Date**: YYYY-MM-DD
**Author**: Agent name / role
**Status**: draft | complete
**Related PRD**: PRD-XXXX (if applicable)

## Question

What specific question is this research trying to answer?
One clear question, not a vague area of investigation.

## Background

Brief context: why is this question relevant right now?
What triggered the need for this research?

## Options Investigated

### Option A: Name

**Description**: Brief explanation of this approach.

**How it works**: Key technical details.

### Option B: Name

(Same structure)

### Option C: Name

(Same structure)

## Trade-off Analysis

| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| Option A | ... | ... | ... | Low/Med/High |
| Option B | ... | ... | ... | Low/Med/High |
| Option C | ... | ... | ... | Low/Med/High |

## Evaluation Criteria

What dimensions matter for this decision and why:
1. Criterion 1 — why it matters
2. Criterion 2 — why it matters
3. etc.

## Sources

1. [Source title](URL) — relevance note
2. [Source title](URL) — relevance note
3. ...

## Recommendation

**Recommended**: Option X

**Why**: 2-3 sentences tying the recommendation to the evaluation
criteria and trade-off analysis.

**Conditions**: Any conditions under which this recommendation would
change (e.g., "if budget allows", "if latency SLA tightens").

## Next Steps

- [ ] Write ADR-XXX based on this research
- [ ] Validate recommendation with POC / spike
- [ ] Get architect sign-off
```

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

- Every factual claim must trace to a source.
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

After the research is complete and an ADR is written:

1. Add to the research doc's Next Steps: link to the ADR file.
2. In the ADR's Related section, link back to the research doc.
3. Update the research status to `complete`.
