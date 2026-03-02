# Update Core Flow & GitHub App Integration — Design

Date: 2026-03-02

## Goal

Enable Druppie to improve itself by modifying its own codebase (`nuno-git/druppie-fork`) through a PR flow. Agents work on GitHub via a GitHub App with short-lived tokens. PRs target `colab-dev` and are always merged by humans.

## Two Stories

### Story 1: GitHub App Integration

**Done when:**
- GitHub App exists, installed on `nuno-git/druppie-fork`
- Backend generates short-lived installation tokens
- Opencode (execute_coding_task) can clone, branch, push, and create PRs on GitHub
- Tokens injected via existing hidden parameter mechanism
- Existing Gitea flows remain unchanged

### Story 2: Update Core Flow

**Done when:**
- Router recognizes `update_core` intent
- Planner follows the update_core workflow (no deploy, ends with PR)
- Planner decides simple vs complex pipeline per request
- `set_intent` handles `update_core` without creating a DB project or Gitea repo
- PR is created targeting `colab-dev`, never auto-merged
- Existing `create_project` and `update_project` flows are unaffected

---

## Design

### 1. GitHub App Setup (Manual, One-Time)

Create at `github.com/settings/apps/new`:
- **Name:** `druppie-core-bot`
- **Permissions:**
  - Contents: Read & Write (clone, push)
  - Pull Requests: Read & Write (create PRs)
  - Metadata: Read (required baseline)
- **Install on:** `nuno-git/druppie-fork` (single repo only)
- **Download** the private key (`.pem` file)

Store credentials:
```
GITHUB_APP_ID=<app-id>
GITHUB_APP_PRIVATE_KEY_PATH=/path/to/private-key.pem
GITHUB_APP_INSTALLATION_ID=<installation-id>
```

### 2. Backend Token Service

New service: `druppie/services/github_app_service.py`

- Reads `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_APP_INSTALLATION_ID` from env
- Generates JWT from private key (RS256, 10-min expiry)
- Exchanges JWT for installation access token via `POST /app/installations/{id}/access_tokens`
- Caches token until near-expiry (~55 min), regenerates automatically
- Single public method: `get_installation_token() -> str`
- If env vars are not set, the service is disabled (no error, just not available)

### 3. Token Injection into Opencode

The backend decides which repo URL and git token to inject based on session intent:

| Intent | repo_url | git_token |
|--------|----------|-----------|
| `create_project` / `update_project` | Gitea URL from project DB | Gitea token from env |
| `update_core` | `https://github.com/nuno-git/druppie-fork.git` | GitHub installation token |

Opencode stays generic — it receives a URL and token, uses `https://x-access-token:{token}@{host}/{owner}/{repo}.git` for clone/push. No GitHub-specific logic in opencode.

Injection rules in `mcp_config.yaml`:
```yaml
execute_coding_task:
  inject:
    repo_url:
      from: resolved.repo_url      # backend resolves based on intent
      hidden: true
    git_token:
      from: resolved.git_token     # backend resolves based on intent
      hidden: true
    base_branch:
      from: resolved.base_branch   # "main" for projects, "colab-dev" for core
      hidden: true
```

The tool executor resolves these dynamically:
- For `update_core`: calls `GitHubAppService.get_installation_token()`, uses hardcoded druppie-fork URL, base branch = `colab-dev`
- For other intents: uses project's Gitea URL and Gitea token, base branch = `main`

### 4. PR Creation on GitHub

Opencode needs to support creating PRs on GitHub (currently only Gitea):

- Detect host from `repo_url` (github.com vs gitea host)
- For GitHub: `POST https://api.github.com/repos/{owner}/{repo}/pulls` with installation token
- For Gitea: existing API call (unchanged)
- Returns PR number + URL in both cases

### 5. Router Changes

`router.yaml` — add fourth intent:

```
update_core — User wants to CHANGE or IMPROVE Druppie itself.
Keywords: "change how you work", "update your prompt", "modify the agent",
"improve yourself", "fix the router", "add a new skill", "change the planner"
```

Router calls `set_intent(intent="update_core")`. No `project_name` or `project_id` parameter.

### 6. `set_intent` Changes

`builtin_tools.py` — handle `update_core`:

- Does NOT create a project in the DB
- Does NOT create a Gitea repo
- Sets `session.intent = "update_core"` on the session
- Stores repo context for the session:
  - `repo_url = https://github.com/nuno-git/druppie-fork.git`
  - `repo_owner = nuno-git`
  - `repo_name = druppie-fork`
  - `base_branch = colab-dev`
- These are stored either on the session model (new fields) or in a session-level config mechanism

### 7. Planner Changes

`planner.yaml` — new `UPDATE_CORE` section:

The planner decides pipeline complexity based on the user's request:

**Simple changes** (prompt tweaks, YAML config, single-file edits, docs):
1. Developer → Planner (create feature branch, implement, commit, push, create PR)
2. Summarizer (report PR link to user)

**Complex changes** (new features, multi-file code, architecture impact):
1. BA → Planner (gather requirements, understand impact on existing flows)
2. Architect → Planner (design the change)
3. Developer → Planner (branch, implement, commit, push, create PR)
4. Summarizer (report PR link to user)

**Decision criteria in planner prompt:**
- Specific, small, clear-scope change → simple
- Vague, large, multi-component, unclear impact → complex
- When in doubt → complex

**Key differences from `update_project`:**
- No deploy step
- No merge step (PR only)
- Branch naming: `core/{description}-{short-hash}` instead of `feature/{description}`
- PR targets `colab-dev` instead of `main`

### 8. What Stays Unchanged

- `create_project` flow — unmodified
- `update_project` flow — unmodified
- `general_chat` flow — unmodified
- Existing Gitea integration — unmodified
- Frontend — no changes needed (sessions with `update_core` intent render normally)
- Approval workflow — works as-is (tool approvals still apply)
- HITL questions — work as-is

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Agent writes breaking changes to core | PR requires human review, never auto-merged |
| GitHub App token leaked to agent | Token is short-lived (1 hour), scoped to single repo |
| Agent modifies sensitive files (secrets, auth) | Humans review every PR before merge |
| Planner enters infinite loop on complex core changes | Existing max-30-iterations safety net applies |
| GitHub API rate limits | Installation tokens get 5000 req/hour, sufficient for single-repo operations |

## Dependencies

- GitHub App creation (manual, one-time)
- `PyJWT` library for RS256 JWT generation (or `cryptography` for manual signing)
- Feature branch `feature/execute-coding-task` should be merged first (opencode integration)
