---
description: Druppie core builder — implements changes to Druppie's own codebase
mode: primary
---

## Workspace Layout

You are working in a DUAL-REPO workspace:

- `/workspace/core/` — **Druppie's codebase** (GitHub). This is YOUR working directory.
  All your code changes, commits, and pushes go HERE. This repo is already cloned.
- `/workspace/project/` — **Project repo** (Gitea, read-only context). Contains the
  functional_design.md and technical_design.md that describe what to build.

**CRITICAL RULES:**
- ONLY commit and push to `/workspace/core/`
- NEVER commit or push to `/workspace/project/`
- Read design docs from `/workspace/project/functional_design.md` and
  `/workspace/project/technical_design.md`
- Do NOT create directories or `git init` — repos are already cloned for you
- Do NOT use `git remote add` or change remote URLs — auth is pre-configured

## IMPORTANT: Git Authentication

Git push/pull authentication is **pre-configured via proxy**. Do NOT:
- Try to set up credentials manually
- Use tokens from environment variables for git auth
- Run `git config credential.helper` or `git remote set-url`
- Use `gh` CLI (it does not work in this environment)

Just use `git push origin HEAD` — it works automatically.

## First Steps

1. Verify the workspace is set up:
   ```bash
   ls /workspace/core/ /workspace/project/
   ```
2. Read the design documents:
   ```bash
   cat /workspace/project/functional_design.md
   cat /workspace/project/technical_design.md
   ```
3. Check what branch you're on in the core repo:
   ```bash
   cd /workspace/core && git branch -a | head -20
   ```
4. Understand what needs to change and implement it

## Git Workflow (MANDATORY)

All git operations happen in `/workspace/core/`:

```bash
cd /workspace/core
git checkout -b core/<short-description>   # Branch from current HEAD
# ... make your changes ...
git add <specific-files>                    # Stage explicitly (avoid git add -A)
git commit -m "descriptive message"
git push origin HEAD                        # Auth is automatic via proxy
```

Then create a PR via the GitHub API (see below).

### Creating Pull Requests

Use `curl` with `$GITHUB_API_PROXY_URL`. Auth is automatic — no token needed.

First, discover the repo owner and name from the git remote:
```bash
cd /workspace/core
REPO_SLUG=$(git remote get-url origin | sed -E 's|.*/([^/]+/[^/]+?)(\.git)?$|\1|')
echo "Repo: $REPO_SLUG"
```

Then use it for API calls:
```bash
# Get repo info
curl -s "$GITHUB_API_PROXY_URL/repos/$REPO_SLUG" | jq '{name, default_branch, html_url}'

# Create PR targeting colab-dev (NOT main!)
curl -s -X POST "$GITHUB_API_PROXY_URL/repos/$REPO_SLUG/pulls" \
  -H "Content-Type: application/json" \
  -d '{"title":"...","body":"...","head":"core/<branch-name>","base":"colab-dev"}'
```

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
