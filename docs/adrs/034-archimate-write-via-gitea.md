---
id: "034"
title: Write ArchiMate models and diagrams directly to Gitea
status: proposed
date: 2026-07-23
deciders:
  - mk2023-land

supersedes: null
superseded_by: null

linked_prd: null
linked_research: null
---

> **Where this fits:** ADRs come AFTER the PRD (we know what we want) and AFTER research
> (if needed — we investigated the options). An ADR is a COMMITTED decision — it records
> ONLY the final decision and its consequences (Context / Decision / Consequences).

## Context

The ArchiMate MCP module reads and writes the model file (`docs/architecture.archimate`)
and exports its views as SVGs. Historically this happened on a **shared-volume workspace**
that the coding MCP cloned per session: the archimate module and the coding module saw the
same working copy on disk.

When the coding MCP became a **sandbox orchestrator**, that shared-volume workspace
disappeared — coding now runs in ephemeral sandboxes that push their results to Gitea rather
than to a persistent shared volume. This left the archimate write tools with no durable place
to read the current model from or persist changes to: the on-disk workspace they assumed no
longer exists. Gitea is already the durable source of truth that the coding sandboxes push to
and that the frontend renderer reads from.

## Decision

Route the ArchiMate write path **directly against Gitea** via its Contents API, instead of a
shared-volume workspace:

- The archimate module reads and writes the model file (`docs/architecture.archimate`) and
  writes exported SVGs (to `docs/diagrams/`) directly to the project's Gitea repository.
- Introduce a self-contained minimal async Gitea client inside the module
  (`druppie/mcp-servers/module-archimate/v1/gitea_io.py`, `GiteaFileStore`), because the module
  container does not ship `druppie.core`. Its admin basic-auth mirrors `druppie.core.gitea`.
- SVG export gains an in-memory counterpart (`svg_export.render_all_views`) that returns
  `{filename: svg_string}` for pushing to the repo via the API, instead of writing files to a
  workspace directory.
- The write tools receive the project repo coordinates (`repo_name`, `repo_owner`) as hidden
  injected parameters via `mcp_config.yaml`, from the same source as the coding MCP, so they
  know which repository to target.
- The write buffer is scoped by **repo** (not just session + path).

## Consequences

**Positive**

- The model and its diagrams persist to the durable source of truth (Gitea); the archimate
  module, the coding sandboxes, and the frontend renderer now all agree on one place.
- No dependency on the removed shared-volume workspace; the module keeps working after the
  coding MCP became a sandbox orchestrator.
- Read paths (`api/routes/projects.py`) now pass `owner=project.repo_owner` explicitly and use
  `status_code` for 404 detection, and the cooperation-view rendering is fixed.
- Behaviour is covered by a new test suite (`tests/test_all_write_tools_gitea.py`) exercising
  every write tool against Gitea.

**Negative / trade-offs**

- A minimal Gitea client is **duplicated** inside the module container because it cannot import
  `druppie.core`; the two clients must be kept in sync by hand.
- Write tools now perform **network I/O to Gitea** per operation instead of local file writes,
  adding latency and a new failure mode (Gitea unavailable) to the write path.
- Access uses Gitea **admin basic-auth** from within the module, consistent with the existing
  `druppie.core.gitea` approach.
