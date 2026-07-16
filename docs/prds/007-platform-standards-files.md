---
id: "007"
title: "Platform Standards Files"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: ["testing/specs/features/platform-standards-files.feature"]
---

# PRD: Platform Standards Files

## Problem

Every Technical Design the Architect produces and every Functional Design the
Business Analyst produces restates the same platform assumptions: stack
(Postgres, FastAPI, React/Vite), the Druppie template, module usage via SDK,
auth handled by Druppie, performance targets, accessibility, error UX, and so
on. This bloats FDs and TDs with boilerplate that is identical across every
project. When a platform default changes, the team must chase it through every
project's design documents.

On top of that, the agents *infer* these defaults from their prompts and from
scanning existing projects. When the LLM guesses wrong, projects drift — one
project uses the SDK while the next talks to the provider directly; one project
builds its own login screen while the next does not. There is no single source
of truth that the agents are required to read before producing a design.

## Goal

A **Platform Standards** concept, owned by two files seeded into every new
project repo, so that:

1. Platform defaults are captured once, in one place per audience (functional
   vs. technical).
2. The files are automatically seeded into `docs/` in every new project repo
   via the existing template-push — no new wiring in the project-creation code
   path.
3. The BA and Architect each read the file that applies to their domain before
   writing their artifact, cite the revision in a visible header, and only
   document *deviations*.
4. The user sees a clickable link to the relevant standards file from the FD
   and TD — transparent about what they are inheriting.
5. Files can be updated later; new projects pick up the new version
   automatically. Existing projects keep their snapshot.

**Definition of done:** Both standards files exist in the project template,
every newly created project repo contains them in `docs/`, the BA and Architect
agents read and link them in their design artifacts, deviations are tracked in
a dedicated table, and the chat file preview renders relative standards links
as clickable Gitea URLs.

## User Journey

1. A user creates a new project through Druppie (`create_project`).
2. The system seeds the project Gitea repo from the project template, which
   includes `docs/platform-functional-standards.md` and
   `docs/platform-technical-standards.md`.
3. The Business Analyst agent runs. In `update_project` mode it reads
   `docs/platform-functional-standards.md` via `coding_read_project_file`,
   gives the user a one-sentence heads-up about which platform defaults apply
   automatically, and elicits only what is NOT covered by the standards.
4. The BA produces `docs/functional-design.md`. Its first line is a visible
   markdown link to the functional standards file with its revision. A
   "Platform standard deviations" table records any intentional exceptions.
5. The Architect agent runs. It reads
   `docs/platform-technical-standards.md` before writing the TD, does not
   restate covered defaults, and produces `docs/technical-design.md` whose
   first line is a visible markdown link to the technical standards file with
   its revision and a deviations table.
6. The user reviews the FD and TD in the chat file preview. The relative link
   to the standards file is rewritten to a clickable Gitea source URL and opens
   in a new tab, so the user can see exactly what platform defaults are
   inherited.
7. When the platform team updates the standards files in
   `druppie/templates/project/docs/`, the next created project picks up the
   new content; existing projects keep their snapshot.

## Constraints

- Seeding must use the existing template-push mechanism — no new wiring in the
  project-creation code path.
- Each standards file carries a manual `Revision:` date header; the BA and
  Architect copy that revision into the document they produce.
- The standards are a *checked* reference, not a *generated* contract — the
  agent checks them; there is no lint/CI enforcement (non-goal).
- Both standards files are written in English (engineering reference). Dutch
  FDs/TDs still reference and link to them.
- Chat rendering must resolve relative links against the source file's
  directory (matching Gitea/GitHub behaviour) and rewrite to Gitea source URLs,
  because the browser resolves them against the app URL inside the chat preview.
- The Tasks page renders `ApprovalCard` outside the session tree and has no
  `ProjectRepoContext`; relative links there fall back to raw hrefs (known gap).

## Out of Scope

- Enforcing standards automatically via lint or CI. This is a checked
  reference, not a generated contract.
- Pushing standards updates into existing project repos
  (`sync_platform_standards` tool). Deferred to a later PR.
- Auto-embedding a short SHA in the revision header via a pre-commit hook.
  Manual date string for v1.
- Fixing the Tasks-page link rendering gap (requires `repo_url` on
  `ApprovalDetail`).

## Open Questions

- **Q1: How should standards updates reach existing projects?**
  - Option A: Deferred `sync_platform_standards` builtin tool that pulls the
    latest into `docs/`.
  - Option B: Manual — the team copies updated files into projects that want
    them.
  - Owner: architect, deadline: 2026-08-15

## Linked Documents

- ADRs: _(none — this is a product requirement, not an architectural decision)_
- Research: _(none)_
- Specs: `testing/specs/features/platform-standards-files.feature`
- Source reference: `docs/reference/platform-standards.md` (superseded by this PRD)
