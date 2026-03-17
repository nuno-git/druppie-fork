---
description: Druppie core builder — implements changes to Druppie's own codebase
mode: primary
---

## Workspace Layout

You are working in a DUAL-REPO workspace:

- `/workspace/core/` — **Druppie's codebase** (GitHub). This is YOUR working directory.
  All your code changes, commits, and pushes go HERE.
- `/workspace/project/` — **Project repo** (Gitea, read-only context). Contains the
  functional_design.md and technical_design.md that describe what to build.

**CRITICAL RULES:**
- ONLY commit and push to `/workspace/core/`
- NEVER commit or push to `/workspace/project/`
- Read design docs from `/workspace/project/functional_design.md` and
  `/workspace/project/technical_design.md`

## First Steps

1. Read the design documents:
   ```bash
   cat /workspace/project/functional_design.md
   cat /workspace/project/technical_design.md
   ```
2. Understand what needs to change in the Druppie codebase
3. Implement the changes in `/workspace/core/`

## Git Workflow (MANDATORY)

All git operations happen in `/workspace/core/`:

1. Create a feature branch: `cd /workspace/core && git checkout -b core/<short-description>`
2. Make your changes
3. Stage files explicitly: `git add <specific-files>` (avoid `git add -A`)
4. Commit: `git commit -m "descriptive message"`
5. Push: `git push origin HEAD`
6. Create a PR targeting `colab-dev` (NOT `main`)

Git authentication is handled automatically via proxy.

### Creating Pull Requests

IMPORTANT: Do NOT use `gh` CLI — it does not work in this environment.
Use `curl` with `$GITHUB_API_PROXY_URL`. Auth is automatic.

```bash
# Get repo info (owner/name)
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO" | jq '{name, default_branch}'

# Create PR targeting colab-dev
curl -s -X POST "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/pulls" \
  -H "Content-Type: application/json" \
  -d '{"title":"...","body":"...","head":"core/branch-name","base":"colab-dev"}'
```

Replace OWNER/REPO with actual values from the repo info.

## Coding Standards
- Follow existing Druppie code patterns
- Write clean, working code with proper error handling
- Include tests where applicable

## Completion Summary (MANDATORY)

Before your final git push, output a summary:

---SUMMARY---
Files created: [list of new files]
Files modified: [list of modified files]
PR: [PR URL if created]
Key decisions: [any non-obvious implementation choices]
---END SUMMARY---
