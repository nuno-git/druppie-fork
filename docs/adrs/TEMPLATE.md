---
# ADR Frontmatter — every field is required.
# Copy this template to NNN-short-kebab-title.md and fill in the values.

id: "001"                         # 3-digit zero-padded STRING (quote it!) — e.g. "001", "012". Must match filename prefix.
title: Short imperative title     # Imperative mood, e.g. "Use layered architecture"
status: proposed                  # One of: proposed | accepted | deprecated | superseded
date: YYYY-MM-DD                  # Date the decision was made
deciders:                         # Roles/people who made the decision
  - role_or_name

# Supersession tracking — only relevant when a decision is replaced
supersedes: null                  # ADR id string this replaces (e.g. "003") or null
superseded_by: null               # ADR id string that replaces this (e.g. "005") or null

# Traceability — link to product requirements or research that motivated this ADR
linked_prd: null                  # Path or URL to a PRD section (e.g. "docs/FEATURES.md#section")
linked_research: null             # Path or URL to research/spike document
---

> **Where this fits:** ADRs come AFTER the PRD (we know what we want) and AFTER research
> (if needed — we investigated the options). An ADR is a COMMITTED decision — it records
> what was chosen, why, and how it's enforced. It does NOT contain the user journey (that's
> the PRD) or the investigation (that's the research doc).

## Context

What is the issue that we're seeing that is motivating this decision or change? Describe the forces at play, including technical, social, and project constraints. Include any assumptions about the current state of the system.

## Decision

What is the change that we're proposing and/or doing? State the decision clearly and unambiguously. Use imperative mood. Explain *what* was decided, not *why* (the why belongs in Context and Consequences).

## Consequences

What becomes easier or more difficult to do because of this change? Cover both positive and negative effects. Include impacts on performance, developer experience, testing, deployment, and future evolution.

<!-- LATER (PBI 9744 — afdwingen): hoe deze beslissing wordt afgedwongen (welke frontmatter-velden
     en CI-/lint-checks daarvoor nodig zijn) wordt in PBI 9744 onderzocht en hier toegevoegd.
     Bewust nog niet opgenomen zodat we het afdwing-mechanisme eerst goed uitzoeken. -->
