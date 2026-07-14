<!--
ADR template (MADR-style).

File naming: NNN-kebab-title.md  (e.g. 007-rolling-deployment-strategy.md).
The NNN prefix is a 3-digit, zero-padded id that matches the `id` frontmatter field.

ADRs are IMMUTABLE: once accepted, do not edit the decision. If a decision
changes, create a NEW ADR and use the `supersedes` / `superseded_by` fields to
link them — never rewrite history.

Status promotion: only an architect may promote `status` to `accepted`.
-->
---
id: 007                       # 3-digit, zero-padded; matches the filename prefix
title: Short decision title
status: proposed              # one of: proposed | accepted | deprecated | superseded
date: 2026-05-12             # YYYY-MM-DD
deciders:                     # who made the call
  - nuno
  - kilian
supersedes: null             # ADR id this replaces (e.g. ADR-003), or null
superseded_by: null          # set when a later ADR replaces this one
linked_prd: null             # related PRD id (e.g. PRD-014), or null
tags:
  - deployment
  - infrastructure
---

# ADR-007: Short decision title

## Context
*State the problem and the forces at play that make a decision necessary.*

## Decision
*State the choice in active voice, e.g. "We will ...".*

## Consequences
*List the outcomes; mark each (+) positive or (-) negative.*

- (+) Positive outcome
- (-) Negative trade-off

## Compliance
*Optional: how is adherence to this decision checked or enforced (tests, CI checks, reviews)?*
