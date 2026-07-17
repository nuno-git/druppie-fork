---
id: "028"
title: "Documentation Portal Architecture"
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/029-documentation-portal.md
linked_research: null
---

# ADR 028: Documentation Portal Architecture

## Context

Generated applications in Druppie have no documentation. When the platform creates an app, it produces working code but nothing that explains the app's purpose, architecture, API, or usage. Users and agents alike must read source code to understand what an app does.

PRD 029 defines the goal: auto-generate `docs/documentation.md` for every app and provide a browsable portal to discover them. The architectural questions are:

- **Who writes the docs?** A human? An agent? A CI pipeline?
- **Where do docs live?** In the app's repo? In a central store? In the platform database?
- **How does the portal find docs?** Direct Gitea API calls on every load? Cached? Pre-rendered?
- **What format?** Markdown? HTML? PDF? Rich text?
- **When are docs generated?** At app creation? On demand? On a schedule?

## Decision

### Documentation Agent

A dedicated documentation agent writes `docs/documentation.md` for each generated app. The agent reads the app's source code from Gitea, analyzes its structure (routes, models, config, entry points), and produces a Markdown document covering purpose, architecture, API endpoints, data model, configuration, and usage examples.

The agent is wired into the planner sequence as a post-deploy step. After the deployer agent finishes deploying an app, the planner triggers the documentation agent to write the docs. This ensures every deployed app gets documentation automatically, with no manual step.

The agent uses the same Gitea API credentials as the rest of Druppie. It reads the app repo, writes `docs/documentation.md`, and commits the file through Gitea's file API. No sandbox or shell access is needed.

### Gitea as Documentation Store

Documentation lives in the app's own Gitea repository as `docs/documentation.md`. This is the single source of truth. Rationale:

- **Single source of truth.** The docs travel with the code. No sync step, no drift between code and docs.
- **Same access control.** Gitea permissions apply. If you can see the repo, you can see the docs.
- **Version-controlled.** Every doc change is a commit. History, blame, diff all work naturally.
- **Gitea renders it natively.** The raw Markdown file renders in Gitea's UI without any portal. The portal is an additional convenience, not the only way to read docs.

### documentation_cache DB Table with TTL

A `documentation_cache` database table stores fetched documentation to avoid hitting the Gitea file API on every portal load. The table schema:

- `app_id` (UUID, PK) — the generated app's identifier.
- `repo_path` (string) — Gitea repo path (e.g., `druppie/apps/my-app`).
- `content` (text) — the Markdown content of `docs/documentation.md`.
- `cached_at` (timestamp) — when this cache entry was written.
- `ttl_seconds` (integer) — how long the entry is valid (default: 300).

On portal load:

1. Look up `app_id` in `documentation_cache`.
2. If found and `cached_at + ttl_seconds > now`, return cached content.
3. If not found or expired, fetch from Gitea file API, update cache, return content.

Cache invalidation is TTL-based only. No webhook-based invalidation. This keeps the architecture simple and avoids coupling the portal to Gitea webhook delivery guarantees.

### Frontend Portal

A new frontend page at `/documentation/apps` displays all generated apps and their documentation. The page has two views:

- **Grid view:** A card grid of all apps. Each card shows the app name, a short description (first paragraph of the doc), and a status chip (documented / undocumented).
- **Detail view:** A full-page render of the app's `docs/documentation.md` with a sidebar table of contents generated from Markdown headings.

The portal is a separate page from the existing `/documentation` route (platform documentation). The two are distinct: platform docs cover Druppie itself, while the portal covers generated apps. They may be linked from a common navigation element, but they are not the same page.

### Markdown-Only Format

Documentation is plain Markdown. No HTML, no PDF, no rich text. Rationale:

- **Simplicity.** Markdown is easy for agents to write reliably. No HTML escaping, no broken tags, no malformed structures.
- **Gitea renders it natively.** The raw file looks good in Gitea's UI without any processing.
- **Portal renders it easily.** Markdown-to-HTML is a solved problem. Any Markdown library works.
- **Agents produce it reliably.** LLMs generate Markdown more consistently than HTML or structured formats.

The trade-off is limited formatting. No tables of contents with page numbers, no embedded diagrams (beyond Markdown-compatible image links), no custom styling. If richer formatting is needed later, it can be layered on top of the Markdown foundation.

### Planner Integration

The documentation agent runs as a step in the planner sequence, after the deployer agent. The planner:

1. Runs the builder agent to generate app code.
2. Runs the deployer agent to deploy the app.
3. Runs the documentation agent to write `docs/documentation.md`.
4. Marks the project as complete.

This ordering ensures documentation is always written for deployed apps. If the deployer fails, the documentation agent does not run (no point documenting a failed deployment). If the documentation agent fails, the project is still marked complete but with a warning — missing docs do not block the deployment.

## Consequences

### Positive

- Every generated app gets documentation automatically, with no human effort.
- Documentation is browsable from a single portal, making app discovery easy.
- Cache reduces Gitea API load on the portal. Frequent page loads hit the DB, not Gitea.
- Docs live alongside code in Gitea, keeping a single source of truth with version control and access control.
- Markdown is simple for agents to write and for the portal to render.
- The documentation agent slots naturally into the existing planner sequence.

### Negative

- Documentation quality depends on the agent's output. A weak agent produces weak docs. Quality is not guaranteed.
- Cache TTL means stale docs can appear briefly after an update. The portal may show outdated content for up to 5 minutes.
- Markdown-only limits formatting options. No diagrams, no custom layouts, no rich media.
- New agent to maintain. The documentation agent adds to the agent catalog and requires ongoing maintenance.
- No webhook-based cache invalidation. Stale docs are resolved by TTL expiry, not by immediate update.
- The portal is a separate page from platform docs, which may confuse users who expect a single documentation entry point.
