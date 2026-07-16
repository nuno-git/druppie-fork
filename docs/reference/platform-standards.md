# Spec: Platform Standards Files

**Status:** in review — PR [#158](https://github.com/nuno-git/druppie-fork/pull/158) (draft)
**Author:** nuno
**Date:** 2026-04-20
**Branch:** `feature/platform-standards` → `colab-dev`

---

## Problem

Every Technical Design the Architect produces and every Functional Design
the BA produces restates the same platform assumptions: stack (Postgres,
FastAPI, React/Vite), Druppie template, module usage via SDK, auth
handled by Druppie, performance targets, accessibility, error UX, and so
on. This bloats FDs and TDs, and when a default changes we have to chase
it through every project.

On top of that, the agents *infer* these defaults from their prompts and
from scanning existing projects. When the LLM guesses wrong we get drift
— one project uses the SDK, the next uses a provider SDK directly; one
project builds its own login screen, the next doesn't.

## Goal

A **Platform Standards** concept, owned by two files seeded into every
new project repo, so that:

1. Platform defaults are captured once, in one place per audience.
2. The files are automatically seeded into `docs/` in every new project
   repo (no new wiring needed — the existing template-push does it).
3. The BA and Architect each read the file that applies to their domain
   before writing their artifact, cite the revision in a visible header,
   and only document *deviations*.
4. The user sees a clickable link to the relevant standards file from
   the FD and TD — transparent about what they're inheriting.
5. Files can be updated later; new projects pick up the new version
   automatically. Existing projects keep their snapshot.

Non-goal: enforcing standards automatically (lint, CI). For now this is
a *checked* reference, not a *generated* contract — the agent checks it,
doesn't generate against it.

## Design

### 1. Two files, owned by the appropriate agent

The content splits along audience:

| File | Read by | Linked from | User sees it? |
|---|---|---|---|
| `docs/platform-functional-standards.md` | BA | every `functional-design.md` | yes — FD header is a markdown link |
| `docs/platform-technical-standards.md` | Architect | every `technical-design.md` | yes — TD header is a markdown link |

The functional file covers language, performance targets, responsiveness,
accessibility, error UX, auth UX, cost-display-hidden, and the functional
out-of-scope list. The technical file covers stack, template-is-the-start,
modules-before-code, DB rules, API/frontend conventions, testing,
technical auth, deployment, git, and the technical out-of-scope list.

### 2. Source of truth — project template

Both files live in the existing project template:

```
druppie/templates/project/docs/platform-functional-standards.md
druppie/templates/project/docs/platform-technical-standards.md
```

The template directory is already pushed verbatim into every new Gitea
repo during `create_project` (see `builtin_tools.py:448` —
`gitea.push_template`). Dropping files under `templates/project/docs/`
is enough for auto-seeding — **no new wiring in the project-creation
code path**.

When the platform team wants to update the standards, they edit the
file(s) in the Druppie repo; the next created project gets the update.
Existing projects keep their snapshot.

### 3. BA integration (`business_analyst.yaml`)

1. **Context gathering, update_project mode**: the BA reads
   `docs/platform-functional-standards.md` from the project repo via
   `coding_read_project_file`. Uses the covered topics (language, perf,
   a11y, error UX, auth UX, cost) as a do-not-elicit list. In
   `create_project` mode the repo is being created, so the file isn't
   yet in the project — the BA falls back to a hard-coded list of
   out-of-scope topics in its own prompt that mirrors the file.
2. **Phase 1 heads-up to the user**: one sentence at the start of
   elicitation: *"A few platform defaults apply automatically — things
   like language, performance, accessibility, error messages, and login
   — so I won't ask about those unless you want anything different. See
   `docs/platform-functional-standards.md` in the project repo for the
   full list."* No per-standard monologue.
3. **FD format**:
   - Mandatory first line — visible markdown link + revision:
     `> Platform standards applied: [docs/platform-functional-standards.md](./platform-functional-standards.md) rev X. Only deviations are listed below.`
   - New §14 **Platform standard deviations** table for intentional
     exceptions (empty row when none).
   - The BA does NOT write FR/NFR entries for topics the standards file
     covers.

### 4. Architect integration (`architect.yaml`)

1. **Context gathering, Level 2**: the Architect reads
   `docs/platform-technical-standards.md` from the project repo before
   writing or updating the TD.
2. **TD format**:
   - Mandatory first line — visible markdown link + revision:
     `> Platform standards: conforms to [docs/platform-technical-standards.md](./platform-technical-standards.md) rev X. Only deviations are documented below.`
   - **Platform standard deviations** section for intentional exceptions
     (empty table when none).
   - Removed from the current TD format anything the standards file
     now covers (stack, deployment framework, chat-template scaffold,
     Druppie auth as its own Security row) so the Architect isn't
     pulled two ways. The TD's Security section now only covers
     project-specific measures (PII handling, data protection) — not
     "Authentication" as a top-level row.

### 5. Chat rendering of the links

The FD and TD are rendered inside the chat (approval-card file preview)
via ReactMarkdown. Relative links like `./platform-functional-standards.md`
would 404 in that view because the browser resolves them against the app
URL, not the source file's directory.

Added:

- `ProjectRepoContext` — set by `SessionDetail` to the session's project
  (`repo_url`, `default_branch`).
- `SourceFileContext` — set per file preview to the path of the file
  being rendered (e.g. `docs/functional-design.md`).
- `MarkdownLink` component registered as the `a` handler in
  `chatMarkdownComponents`. For relative hrefs it resolves against the
  source file's directory (so `./foo.md` from `docs/bar.md` → `docs/foo.md`,
  matching Gitea/GitHub behaviour) and rewrites to
  `${repo_url}/src/branch/${default_branch}/${path}`. Opens in a new tab.
  External links left alone, also opened in a new tab.
- `FilePreviewModal` wraps each file's ReactMarkdown in its own
  `SourceFileContext.Provider` so multiple previewed files resolve their
  own relative links correctly.

**Known gap:** the Tasks page renders `ApprovalCard` outside the session
tree so it has no `ProjectRepoContext`; relative links there fall back
to raw hrefs. Fix later by including `repo_url` on `ApprovalDetail`.

### 6. Versioning

Each standards file carries a manual `Revision:` date header at the top.
The BA and Architect copy that into the document they produce. Updated
manually on each PR. A pre-commit hook to auto-embed a short sha is
possible later.

### 7. Update path

- Platform team edits the file(s) in `druppie/templates/project/docs/`
  via a PR. New projects created after merge pick up the new content.
- Existing projects keep their snapshot. If we want to push an update
  into existing projects later, add a `sync_platform_standards` builtin
  tool that pulls the latest into `docs/`. **Out of scope for this PR**
  — the agent reading the file that is already in the repo is enough
  for v1.

## Implementation plan (shipped)

1. **Template files** — new:
   - `druppie/templates/project/docs/platform-functional-standards.md`
   - `druppie/templates/project/docs/platform-technical-standards.md`
2. **Agent prompt edits**:
   - `druppie/agents/definitions/architect.yaml` — L2 read of the
     technical file; TD format header (markdown link) + deviations
     table; trimmed duplicated defaults from the TD format.
   - `druppie/agents/definitions/business_analyst.yaml` — L2 read of
     the functional file in `update_project`; Phase 1 user heads-up;
     FD format header (markdown link) + new §14 deviations table.
3. **Frontend link rewriting**:
   - `frontend/src/components/chat/ChatHelpers.jsx` — new
     `ProjectRepoContext`, `SourceFileContext`, `MarkdownLink`;
     registered as `a` in `chatMarkdownComponents`; proper relative-path
     resolution against the source file.
   - `frontend/src/components/chat/SessionDetail.jsx` — wraps the
     session tree in `ProjectRepoContext.Provider`.
   - `frontend/src/components/chat/ApprovalCard.jsx` — `FilePreviewModal`
     wraps each file's render in `SourceFileContext.Provider`.
4. **Tests**:
   - `testing/tools/create-project-seeds-platform-standards.yaml` —
     verifies both standards files land in the new Gitea repo after
     `create_project`. **Passing.**
   - `testing/tools/fd-with-platform-standards-link.yaml` —
     deterministic chain that writes an FD containing the mandated
     markdown link to `platform-functional-standards.md`; asserts
     `file_contains`; leaves a session for manual UI verification of
     the link rewriter. **Passing.**
   - `testing/agents/architect-references-platform-standards.yaml` —
     LLM architect test with judge checks for the TD header + deviations
     section + no restatement of covered defaults. Cancelled mid-run
     while iterating on the link rendering; to be re-run before merge.
5. **Design doc** — this file.

## Open questions (resolved)

| # | Question | Decision |
|---|---|---|
| 1 | File name | `platform-functional-standards.md` / `platform-technical-standards.md` under `docs/`. Lowercase-hyphen matching repo convention. |
| 2 | Revision format | Manual date string for v1. Auto-sha via pre-commit hook later if useful. |
| 3 | Dutch vs English | English for both files (engineering reference). Dutch TDs/FDs still reference and link to them — normal for mixed-language docs. |
| 4 | Architect only, or BA too? | **Both.** BA reads the functional file and has a Phase 1 user heads-up. |
| 5 | Sync into existing projects | Deferred. `sync_platform_standards` tool can be added later. |
| 6 | Chat link rendering (not in original spec) | `MarkdownLink` in chat resolves relative paths against the source file's directory and rewrites to Gitea URLs. Session rendering covered; Tasks page still falls back to raw hrefs (known gap). |
