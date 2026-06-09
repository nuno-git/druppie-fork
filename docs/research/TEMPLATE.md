---
id: 000                              # Sequential research number (e.g. 001, 002)
title: Research topic                  # Short, descriptive name
status: draft                         # draft | complete
author: role name                     # Who conducted this research
date: 2026-06-09                      # Date of research (YYYY-MM-DD)
outcome: null                         # "adr-NNN" if research led to an ADR, or null
---

# Research: {title}

## Question

<!-- What are we investigating?
     - State the research question in one clear sentence.
     - Frame it as a decision to be made or a knowledge gap to fill.
     Example: "Which state management library should we use for the Druppie frontend?" -->

_One-sentence research question._

## Background

<!-- Why this investigation matters.
     - What triggered this research? (performance issue, new feature need, tech debt)
     - What happens if we make the wrong choice or delay the decision?
     - Who are the stakeholders affected by this decision?
     Example: "The frontend currently uses React Context for all state, causing unnecessary re-renders on the Chat page with 500+ messages." -->

_Context and motivation._

## Approach

<!-- How we researched (sources, experiments, benchmarks).
     - List all sources consulted: documentation, benchmarks, proof-of-concept code, team interviews.
     - Describe any experiments or prototypes built.
     - Note time-box constraints (e.g. "1 day spike").
     Example:
     - Reviewed official docs for Zustand, Jotai, and Redux Toolkit.
     - Built a prototype chat page with each library (see `/spikes/state-mgmt/`).
     - Benchmarked re-render count with React DevTools Profiler.
     - Interviewed 2 team members with prior Redux experience._-->

- _Source or experiment 1._
- _Source or experiment 2._

## Findings

<!-- Organized as a comparison table when comparing options.
     Use the table format below for option comparisons.
     For non-comparative research, use free-form sections with headings. -->

### Option Comparison

| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| _Option A_ | _Pro 1, Pro 2_ | _Con 1, Con 2_ | _Risk level (low/med/high)_ | _Effort estimate (S/M/L)_ |
| _Option B_ | _Pro 1, Pro 2_ | _Con 1, Con 2_ | _Risk level_ | _Effort estimate_ |
| _Option C_ | _Pro 1, Pro 2_ | _Con 1, Con 2_ | _Risk level_ | _Effort estimate_ |

### Additional Notes

<!-- Any extra observations, benchmarks, or data points that don't fit the table.
     Example: "Option A's bundle size is 2.1KB gzipped vs Option B's 11.4KB." -->

_Details beyond the comparison table._

## Trade-off Analysis

<!-- Weighted comparison of top options.
     - Score each option against criteria relevant to the decision.
     - Weight criteria by project priorities.
     - Show the math so others can verify or adjust weights.
     Example:
     | Criterion | Weight | Option A | Option B |
     |-----------|--------|----------|----------|
     | Bundle size | 3 | 5 (15) | 3 (9) |
     | DX simplicity | 2 | 4 (8) | 5 (10) |
     | Ecosystem | 1 | 3 (3) | 5 (5) |
     | **Total** | | **26** | **24** |_

| Criterion | Weight | _Option A_ | _Option B_ |
|-----------|--------|------------|------------|
| _Criterion 1_ | _1-5_ | _Score (weighted)_ | _Score (weighted)_ |
| _Criterion 2_ | _1-5_ | _Score_ | _Score_ |
| **Total** | | **_Sum_** | **_Sum_** |

## Recommendation

<!-- Clear recommendation with rationale.
     - State the recommended option explicitly.
     - Explain why it wins on the criteria that matter most for this project.
     - Note any conditions or prerequisites.
     Example: "We recommend Zustand. It scored highest on bundle size and DX simplicity, which are our top priorities. The smaller ecosystem is acceptable given our limited state complexity." -->

_Recommended option and why._

## Open Items

<!-- What still needs investigation.
     - List follow-up questions or unknowns that surfaced during research.
     - These may become separate research documents.
     Example: "How does Zustand handle time-travel debugging? Need to verify before final decision."_

- _Open item 1._
- _Open item 2._

## Resulting ADR

<!-- Link to ADR if one was created from this research.
     Auto-populated from the `outcome` frontmatter field. -->

<!-- {% if outcome %}This research led to [ADR {{ outcome }}](../adrs/{{ outcome }}.md).{% else %}No ADR created yet.{% endif %} -->
