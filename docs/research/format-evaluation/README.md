# Format evaluation — empirical AI-extraction experiment

## Purpose
Test, per documentation format, whether a fresh AI agent can:

- **(a) extract named fields** — pull specific values (id, status, deciders, ...) out of a document,
- **(b) infer cross-document relationships** — connect a decision to the work it constrains across two documents,
- **(c) detect changes between versions** — diff two revisions of the same document and report what changed.

These three capabilities mirror the user story: an agent picking up existing
documentation must be able to read fields, follow links between documents, and
notice when a decision has evolved.

## Method
The **same** decision — **ADR-007 "Rolling deployment strategy for generated sandbox apps"** —
was rendered in **4 formats** (see files `01-frontmatter.md`, `02-xml.md`,
`03-json-schema.md`, `04-classic-adr.md`).

For each format, a **fresh agent that saw ONLY the relevant document(s)** performed 3 tasks:

1. **Field extraction** — read the 9 named fields out of the single ADR document.
2. **Cross-doc linking** — combine **ADR-007 + PRD-014** and report how the decision constrains the work.
3. **Change detection** — compare **V1 vs V2** of the document and list what changed.

Each task was run with a **strong model (Opus-class)**. Field extraction was
**additionally repeated with a weak model (Haiku)** to surface format
sensitivity. All answers were graded against a **fixed ground truth**.

## Results
See [RESULTS.md](./RESULTS.md) for the scored outcome and findings.
