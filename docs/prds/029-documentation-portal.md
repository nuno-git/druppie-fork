---
id: "029"
title: "Documentation Portal"
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs:
  - docs/adrs/028-documentation-portal-architecture.md
linked_research: []
linked_specs: []
linked_workitem: null
---

# PRD 029: Documentation Portal

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD -> Research (optional, only when unclear) -> ADR (decision) -> Spec (verification)
> -> Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

## Problem

Generated applications have no documentation. When Druppie creates an app, it produces working code but nothing that explains what the app does, how it works, or how to use it. A user or another agent who encounters a generated app has to read the source code to understand its purpose and capabilities.

This breaks the self-service model. A developer who deploys an app through Druppie cannot share it with a colleague and say "read the docs." An agent that needs to integrate with an existing app cannot discover its API or data model without scanning files. The platform generates applications but leaves them undocumented, which limits reuse, slows onboarding, and forces everyone to reverse-engineer every app.

## Goal

Every generated app has a `docs/documentation.md` file in its Gitea repository that describes what the app does, how it works, and how to use it. A browsable portal at `/documentation/apps` lists all apps and renders their documentation in a readable layout.

**Definition of done:** A user can open `/documentation/apps`, see a card grid of all generated apps, click any card to view its full documentation rendered from Markdown, and the documentation was written by an agent (not a human) as part of the app generation pipeline.

## User Journey

1. User navigates to `/documentation/apps`.
2. System displays a grid of app cards. Each card shows the app name, a short description, and a status indicator (documented / undocumented).
3. User clicks a card for an app.
4. System fetches the app's `docs/documentation.md` from Gitea and renders it as formatted Markdown.
5. User reads the documentation: purpose, architecture, API endpoints, data model, configuration, and usage examples.
6. User clicks the "View in Gitea" link to open the raw file in Gitea.
7. User navigates back to the portal grid to browse another app.

## Constraints

- Documentation is written by the documentation agent, not by humans. No manual editing workflow.
- Documentation lives in the app's own Gitea repository as `docs/documentation.md`. No separate storage.
- Portal fetches docs via the Gitea file API. No direct filesystem access.
- Portal must handle missing docs gracefully (show "No documentation yet" instead of breaking).
- Documentation is Markdown only. No HTML, no PDF, no rich text.
- Cache layer (`documentation_cache` DB table) prevents hitting Gitea on every page load.
- Cache TTL must be configurable. Default: 5 minutes.
- Portal is scoped to generated apps only. No platform documentation, no external repos.

## Out of Scope

- Live documentation editing from the portal. Docs are written by agents, edited in Gitea.
- Version history or diff view in the portal. Gitea handles versioning.
- Full-text search across documentation. Users browse, not search.
- Documentation for non-Druppie apps or external services.
- PDF or HTML export of documentation.
- Documentation quality scoring or review workflow.
- The `/documentation` page redesign (platform docs). This portal is app-specific only.

## Open Questions

None. Scope is well-defined and the implementation path is straightforward.

## Linked Documents

- **ADRs:** docs/adrs/028-documentation-portal-architecture.md
- **Research:** none
- **Specs / Feature files:** none
