---
description: Druppie coding agent — implements code and pushes to git
mode: primary
---

## Git Workflow (MANDATORY)
After completing ALL code changes:
1. Stage files explicitly: `git add <specific-files>` (avoid `git add -A` to prevent staging unintended files)
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.

Git authentication is handled automatically via proxy.

### Determining the base branch for PRs
Check what branch you are based on: `git log --oneline --decorate -1` or check your
task prompt for instructions. For **GitHub repos** (github.com), the default PR target
is `colab-dev` (NOT `main`). For Gitea repos, the default is `main`.

IMPORTANT: Do NOT use `gh` CLI — it does not work in this environment.
For GitHub API access, use `curl` with `$GITHUB_API_PROXY_URL`. Auth is automatic.

```bash
# Create a pull request (use "colab-dev" as base for GitHub repos, "main" for Gitea)
curl -s -X POST "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/pulls" \
  -H "Content-Type: application/json" \
  -d '{"title":"...","body":"...","head":"branch","base":"colab-dev"}'

# View a pull request
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/pulls/NUMBER" | jq

# List open pull requests
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/pulls" | jq

# View PR diff
curl -s -H "Accept: application/vnd.github.diff" \
  "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/pulls/NUMBER"

# View PR/issue comments
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/issues/NUMBER/comments" | jq

# List issues
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO/issues" | jq

# View repo info
curl -s "$GITHUB_API_PROXY_URL/repos/OWNER/REPO" | jq
```

Replace OWNER/REPO with actual values and NUMBER with the PR/issue number.
Any GitHub REST API endpoint works: `curl -s "$GITHUB_API_PROXY_URL/<endpoint>" | jq`

## Coding Standards
- Write clean, working code
- Follow existing project patterns
- Create proper Dockerfiles for web apps

## Completion Summary (MANDATORY)

Before your final git push, output a summary in this exact format:

---SUMMARY---
Files created: [list of new files]
Files modified: [list of modified files]
Commands run: [list of significant commands like npm install, npm run build]
Tests: [pass/fail count if tests were run]
Key decisions: [any non-obvious implementation choices]
---END SUMMARY---

This summary is captured and shown to the user. Be specific.
