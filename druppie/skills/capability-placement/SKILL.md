---
name: capability-placement
description: >
  This skill should be used by the architect when a design requires a
  capability that is not yet covered by an existing module — to decide
  WHERE that capability should live: in the generated project, in the
  shared project template, in an existing module (extended), or in a new
  module. It is a generic reuse/placement decision that applies to any
  building block (LLM, OCR, RAG, data-access, …), not a technology choice.
  It replaces the inline "reuse decision framework" summary and is the
  single place to extend placement rules over time.
---

# Capability Placement (Architect — where does it live?)

When the design needs a capability, first check whether it already exists
as a module tool → if so, **REUSE** it (reference it in the TD, no new
code). Only when new code is genuinely needed do you decide *where* it
should live, using the four paths below.

## Decision order

1. **Reuse first.** Exists as a module tool → reuse, stop here.
2. **Does it recur across projects?** No → keep it in the project. Yes →
   continue.
3. **How much per-project adaptability does it need, and does it benefit
   from central governance?** High adaptability / lives best close to the
   app → template. Benefits from centralisation/governance → module.

## The four placement paths

1. **In the project (project-local).**
   The capability is project-specific and unlikely to recur. Keep it
   inside the generated app. Every project is already generated from the
   project template, so adding code to your own project is this path — not
   a template change. *(No platform change.)*

2. **Extend the project template** (`druppie/templates/project`).
   This means editing the **shared** template repository itself so that
   **every future generated project inherits the change by default** — a
   platform change, not project-local code. Choose this only for a default
   pattern that recurs across projects but still needs high per-project
   adaptability and is most efficient living close to the application
   (added as a pre-defined, reusable example under `app/` or `frontend/`).
   *(Template change — affects all new projects.)*

   > Do not confuse this with the template you start from: every project
   > is generated from the shared template, so adding code to *your own
   > project* is path 1. Path 2 means changing the **shared template
   > itself**.

3. **Evolve an existing module.**
   The capability recurs across projects and benefits from
   centralisation/governance. Grow an existing module so apps stay on
   `druppie.call(...)` instead of each app importing its own stack.
   *(Module change → CORE_UPDATE; a platform-roadmap item. Flag the need;
   do not design module internals here.)*

4. **New module.**
   The functionality is fundamentally distinct or broadly reusable across
   projects (and possibly apps). *(New module → CORE_UPDATE; platform-
   roadmap item. Flag the need; do not design internals here.)*

State which path applies and why, in one sentence. For paths 3–4 the
architect only flags the platform need — the module's internals are a
separate core-update design.

## What to record in the TD

One line: the chosen path (project / template / module / new module) and a
one-sentence reason. For paths 3–4, add what platform capability is needed.
