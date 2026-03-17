# Dual-Repo Sandbox for update_core_builder — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `update_core_builder` sandbox access to both the Druppie core repo (GitHub, read+write) and the project repo (Gitea, read+write) via `/workspace/core/` and `/workspace/project/`, all proxied through the control plane.

**Architecture:** Extend the credential store to hold two sets of git credentials (core + project) with separate proxy keys. The sandbox entrypoint clones both repos into subdirectories. A new OpenCode agent (`druppie-core-builder.md`) instructs the sandbox agent to only commit/push to `/workspace/core/` and read context from `/workspace/project/`.

**Tech Stack:** TypeScript (control plane), Python (sandbox entrypoint, Druppie backend), Markdown (OpenCode agent definition)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `druppie/sandbox/__init__.py` | Modify | Pass both git credentials (core + project) to control plane |
| `druppie/agents/builtin_tools.py` | Modify | Look up project repo info for `update_core_builder` calls |
| `background-agents/packages/local-control-plane/src/credentials/credential-store.ts` | Modify | Store two git credentials per session, two proxy keys |
| `background-agents/packages/local-control-plane/src/router.ts` | Modify | Pass second git proxy key to session |
| `background-agents/packages/local-control-plane/src/session/session-instance.ts` | Modify | Build `CONTEXT_GIT_URL` env var from second proxy key |
| `background-agents/packages/local-sandbox-manager/src/main.py` | Modify | Pass `CONTEXT_GIT_URL` to sandbox container |
| `background-agents/packages/modal-infra/src/sandbox/entrypoint.py` | Modify | Clone second repo into `/workspace/project/`, main into `/workspace/core/` |
| `druppie/sandbox-config/agents/druppie-core-builder.md` | Create | OpenCode agent for core changes with dual-repo instructions |
| `druppie/agents/definitions/update_core_builder.yaml` | Modify | Use `druppie-core-builder` as sandbox agent name |

---

### Task 1: Extend Credential Store for Dual Git Credentials

**Files:**
- Modify: `background-agents/packages/local-control-plane/src/credentials/credential-store.ts`

- [ ] **Step 1: Add `contextGit` to `SessionCredentials` interface**

Add a second optional git credential field to the interface (around line 34):

```typescript
export interface SessionCredentials {
  git?: GitCredentials;
  contextGit?: GitCredentials;  // Second repo (e.g., project repo for context)
  llm?: LlmCredentials | LlmCredentials[];
  githubApi?: GithubApiCredentials;
}
```

- [ ] **Step 2: Add `contextGitProxyKey` to `ProxyKeys` interface**

```typescript
export interface ProxyKeys {
  gitProxyKey: string | null;
  contextGitProxyKey: string | null;  // Proxy key for context repo
  llmProxyKey: string | null;
  githubApiProxyKey: string | null;
}
```

- [ ] **Step 3: Add fields to `StoredSession` interface**

```typescript
interface StoredSession {
  sessionId: string;
  gitCredentials: GitCredentials | null;
  contextGitCredentials: GitCredentials | null;  // Second repo credentials
  // ... existing fields ...
  contextGitProxyKey: string | null;  // Proxy key for context repo
  // ... rest unchanged ...
}
```

- [ ] **Step 4: Add reverse index for context git proxy keys**

Add to class fields (around line 75):
```typescript
/** contextGitProxyKey -> sessionId (reverse index) */
private contextGitKeyIndex = new Map<string, string>();
```

- [ ] **Step 5: Update `store()` to handle context git credentials**

In the `store()` method, add after the `gitProxyKey` generation (around line 90):
```typescript
const contextGitProxyKey = credentials.contextGit
  ? crypto.randomBytes(32).toString("hex")
  : null;
```

Add to the `stored` object:
```typescript
contextGitCredentials: credentials.contextGit ?? null,
contextGitProxyKey,
```

Add index registration:
```typescript
if (contextGitProxyKey) {
  this.contextGitKeyIndex.set(contextGitProxyKey, sessionId);
}
```

Update return to include `contextGitProxyKey`.

- [ ] **Step 6: Add `getByContextGitProxyKey()` lookup method**

After `getByGitProxyKey()`:
```typescript
/** Look up context git credentials by proxy key. Returns null if key is invalid. */
getByContextGitProxyKey(key: string): (GitCredentials & { sessionId: string }) | null {
  const sessionId = this.contextGitKeyIndex.get(key);
  if (!sessionId) return null;

  const stored = this.sessions.get(sessionId);
  if (!stored?.contextGitCredentials) return null;

  return { ...stored.contextGitCredentials, sessionId };
}
```

- [ ] **Step 7: Update `destroy()` to clean up context git index**

Add before `this.sessions.delete(sessionId)`:
```typescript
if (stored.contextGitProxyKey) {
  this.contextGitKeyIndex.delete(stored.contextGitProxyKey);
}
```

- [ ] **Step 8: Commit**

```bash
cd background-agents && git add packages/local-control-plane/src/credentials/credential-store.ts
cd .. && git commit -m "feat: credential store supports dual git credentials (core + context repo)"
```

---

### Task 2: Add Context Git Proxy Route

**Files:**
- Modify: `background-agents/packages/local-control-plane/src/proxy/git-proxy.ts`

The existing git-proxy uses `getByGitProxyKey()` to look up credentials. The context git uses a separate proxy key but the same proxy logic. We can reuse the same route handler — the proxy key lookup already determines which credentials to use.

- [ ] **Step 1: Update git-proxy to also check `contextGitKeyIndex`**

The simplest approach: make `getByGitProxyKey()` also check the context index. But that conflates the two. Better: the git-proxy route handler should try both lookups.

In `git-proxy.ts`, where it does `credentialStore.getByGitProxyKey(proxyKey)`, update to:

```typescript
const creds = credentialStore.getByGitProxyKey(proxyKey)
  ?? credentialStore.getByContextGitProxyKey(proxyKey);
```

This way both proxy keys work with the same `/git-proxy/` route.

- [ ] **Step 2: Commit**

```bash
cd background-agents && git add packages/local-control-plane/src/proxy/git-proxy.ts
cd .. && git commit -m "feat: git-proxy accepts both primary and context git proxy keys"
```

---

### Task 3: Pass Context Git Proxy Key to Session Instance

**Files:**
- Modify: `background-agents/packages/local-control-plane/src/router.ts`
- Modify: `background-agents/packages/local-control-plane/src/session/session-instance.ts`

- [ ] **Step 1: Update router.ts to pass contextGitProxyKey**

The `proxyKeys` returned by `credentialStore.store()` now includes `contextGitProxyKey`. The router already passes `proxyKeys` to `instance.handleInit()` — no change needed in router.ts if `handleInit` accepts the full `ProxyKeys` type.

Verify that the `handleInit` call at line 183 passes `proxyKeys` and that session-instance reads it.

- [ ] **Step 2: Store `contextGitProxyKey` in session-instance.ts**

In session-instance.ts, where `gitProxyKey` is stored (around line 1366), add:
```typescript
this.contextGitProxyKey = body.proxyKeys?.contextGitProxyKey ?? null;
```

Add the field declaration to the class:
```typescript
private contextGitProxyKey: string | null = null;
```

- [ ] **Step 3: Build `CONTEXT_GIT_URL` env var**

In the sandbox spawning section (around line 1087), after the `GIT_URL` block, add:

```typescript
if (this.contextGitProxyKey) {
  // Context repo info is passed via the credentials body
  // We need repo_owner and repo_name for the context repo
  const contextRepoInfo = this.getContextRepoInfo();
  if (contextRepoInfo) {
    userEnvVars["CONTEXT_GIT_URL"] = `${controlPlaneUrl}/git-proxy/${this.contextGitProxyKey}/${contextRepoInfo.owner}/${contextRepoInfo.name}.git`;
  }
}
```

For `getContextRepoInfo()`, we need to store the context repo owner/name. The simplest way: pass them in `handleInit` alongside the proxy keys. Add `contextRepoOwner` and `contextRepoName` to the init body.

- [ ] **Step 4: Update `handleInit` to accept context repo info**

Add to the handleInit params:
```typescript
contextRepoOwner?: string;
contextRepoName?: string;
```

Store them:
```typescript
this.contextRepoOwner = body.contextRepoOwner ?? null;
this.contextRepoName = body.contextRepoName ?? null;
```

Use them in the `CONTEXT_GIT_URL` construction:
```typescript
if (this.contextGitProxyKey && this.contextRepoOwner && this.contextRepoName) {
  userEnvVars["CONTEXT_GIT_URL"] = `${controlPlaneUrl}/git-proxy/${this.contextGitProxyKey}/${this.contextRepoOwner}/${this.contextRepoName}.git`;
}
```

- [ ] **Step 5: Update `destroyCredentials` to clear context proxy key**

Ensure the `contextGitProxyKey` is nulled on destroy.

- [ ] **Step 6: Update router.ts to pass context repo info**

In router.ts POST /sessions handler, after credential store call, pass context repo info to handleInit:

```typescript
const initResult = await instance.handleInit({
  // ... existing fields ...
  contextRepoOwner: body.contextRepoOwner ?? null,
  contextRepoName: body.contextRepoName ?? null,
});
```

- [ ] **Step 7: Commit**

```bash
cd background-agents && git add packages/local-control-plane/src/router.ts packages/local-control-plane/src/session/session-instance.ts
cd .. && git commit -m "feat: session-instance passes CONTEXT_GIT_URL to sandbox for dual-repo"
```

---

### Task 4: Update Sandbox Manager to Pass Context Git URL

**Files:**
- Modify: `background-agents/packages/local-sandbox-manager/src/main.py`

- [ ] **Step 1: Pass CONTEXT_GIT_URL through**

The `CONTEXT_GIT_URL` is already in `user_env_vars` (set by session-instance). The sandbox manager passes `user_env_vars` at line 82-84, so it flows through automatically. Verify this by checking that `user_env_vars` are applied before system overrides (they are — line 82-84 vs 86-93).

No code change needed — `CONTEXT_GIT_URL` will flow through `user_env_vars` automatically.

- [ ] **Step 2: Verify and commit (no-op if no changes needed)**

---

### Task 5: Update Sandbox Entrypoint for Dual Clone

**Files:**
- Modify: `background-agents/packages/modal-infra/src/sandbox/entrypoint.py`

- [ ] **Step 1: Read `CONTEXT_GIT_URL` env var**

In `__init__` (around line 64), add:
```python
self.context_git_url = os.environ.get("CONTEXT_GIT_URL", "")
```

- [ ] **Step 2: Change workspace layout when context repo is present**

When `CONTEXT_GIT_URL` is set, use `/workspace/core/` and `/workspace/project/` instead of `/workspace/<repo_name>`.

Update `self.repo_path` logic (around line 78):
```python
if self.context_git_url:
    # Dual-repo mode: /workspace/core/ and /workspace/project/
    self.repo_path = self.workspace_path / "core"
    self.context_repo_path = self.workspace_path / "project"
else:
    # Single-repo mode: /workspace/<repo_name> (existing behavior)
    self.repo_path = self.workspace_path / self.repo_name if self.repo_name else self.workspace_path
    self.context_repo_path = None
```

- [ ] **Step 3: Clone context repo after main clone**

In `perform_git_sync()`, after the main clone succeeds, add the context repo clone:

```python
# Clone context repo if configured (dual-repo mode)
if self.context_git_url and self.context_repo_path and not self.context_repo_path.exists():
    self.log.info("git.context_clone_start", context_url="[proxied]")
    result = await asyncio.create_subprocess_exec(
        "git", "clone", self.context_git_url, str(self.context_repo_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await result.communicate()
    if result.returncode != 0:
        self.log.error("git.context_clone_error", stderr=stderr.decode())
        # Non-fatal — core repo is the priority
    else:
        self.log.info("git.context_clone_complete", path=str(self.context_repo_path))

        # Configure credential helper for context repo too
        await asyncio.create_subprocess_exec(
            "git", "config", "credential.helper",
            "!f() { echo username=x; echo password=x; }; f",
            cwd=self.context_repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
```

- [ ] **Step 4: Strip `CONTEXT_GIT_URL` from OpenCode env**

In the credential stripping section (around line 507), add:
```python
for secret_var in ("GIT_URL", "GITHUB_APP_TOKEN", "GITHUB_TOKEN", "CONTEXT_GIT_URL"):
    env.pop(secret_var, None)
```

- [ ] **Step 5: Set OpenCode working directory to core repo**

Ensure that when dual-repo mode is active, OpenCode starts in `/workspace/core/` (the main repo the agent should modify). Check where `cwd` or `workdir` is set for the OpenCode process.

- [ ] **Step 6: Commit**

```bash
cd background-agents && git add packages/modal-infra/src/sandbox/entrypoint.py
cd .. && git commit -m "feat: sandbox entrypoint clones dual repos into /workspace/core/ and /workspace/project/"
```

---

### Task 6: Create `druppie-core-builder` OpenCode Agent

**Files:**
- Create: `druppie/sandbox-config/agents/druppie-core-builder.md`

- [ ] **Step 1: Write the agent definition**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add druppie/sandbox-config/agents/druppie-core-builder.md
git commit -m "feat: add druppie-core-builder OpenCode agent for dual-repo sandbox"
```

---

### Task 7: Update `update_core_builder` to Use New Sandbox Agent

**Files:**
- Modify: `druppie/agents/definitions/update_core_builder.yaml`

- [ ] **Step 1: Update the agent prompt to specify `druppie-core-builder` agent**

In the system prompt, update the `execute_coding_task` instructions to specify the agent:

```yaml
  2. Call execute_coding_task with agent="druppie-core-builder" and a prompt that:
```

Also in `extra_builtin_tools`, the agent name parameter defaults to the global default. The `update_core_builder` should pass `agent="druppie-core-builder"` explicitly.

- [ ] **Step 2: Commit**

```bash
git add druppie/agents/definitions/update_core_builder.yaml
git commit -m "feat: update_core_builder uses druppie-core-builder sandbox agent"
```

---

### Task 8: Pass Dual Git Credentials from Druppie Backend

**Files:**
- Modify: `druppie/sandbox/__init__.py`
- Modify: `druppie/agents/builtin_tools.py`

- [ ] **Step 1: Update `create_and_start_sandbox` to accept context repo params**

Add optional parameters to `create_and_start_sandbox`:
```python
async def create_and_start_sandbox(
    *,
    # ... existing params ...
    context_repo_owner: str | None = None,
    context_repo_name: str | None = None,
    context_git_provider: str | None = None,
) -> dict:
```

- [ ] **Step 2: Build context git credentials when provided**

After the main git credentials are built (around line 132), add:

```python
# Build context repo credentials if provided (dual-repo mode)
context_git_user_id = None
if context_repo_owner and context_repo_name and context_git_provider:
    if context_git_provider == "github":
        context_git_creds = await _build_github_git_credentials(context_repo_owner, context_repo_name)
    else:
        from druppie.sandbox.gitea_credentials import create_sandbox_git_user
        context_git_user_id = secrets.token_hex(6)
        context_git_creds = await create_sandbox_git_user(
            sandbox_session_id=context_git_user_id,
            repo_owner=context_repo_owner,
            repo_name=context_repo_name,
        )
    credentials["contextGit"] = context_git_creds
```

- [ ] **Step 3: Pass context repo info in the create body**

Add to `create_body`:
```python
if context_repo_owner and context_repo_name:
    create_body["contextRepoOwner"] = context_repo_owner
    create_body["contextRepoName"] = context_repo_name
```

- [ ] **Step 4: Update `execute_sandbox_coding_task` in builtin_tools.py**

For the `update_core_builder` agent, look up the project repo info and pass it:

```python
if calling_agent_id == "update_core_builder":
    repo_owner = os.getenv("DRUPPIE_REPO_OWNER", "nuno-git")
    repo_name = os.getenv("DRUPPIE_REPO_NAME", "druppie-fork")
    git_provider = "github"

    # Also pass the project repo as context
    context_repo_owner = os.getenv("GITEA_ORG", "druppie")
    context_repo_name = ""
    context_git_provider = "gitea"
    if session.project_id:
        project_repo = ProjectRepository(db)
        project = project_repo.get_by_id(session.project_id)
        if project:
            context_repo_owner = project.repo_owner or context_repo_owner
            context_repo_name = project.repo_name or ""
else:
    # Regular flow — single repo
    context_repo_owner = None
    context_repo_name = None
    context_git_provider = None
```

Then pass to `create_and_start_sandbox`:
```python
result = await create_and_start_sandbox(
    # ... existing params ...
    context_repo_owner=context_repo_owner,
    context_repo_name=context_repo_name,
    context_git_provider=context_git_provider,
)
```

- [ ] **Step 5: Handle context git user cleanup**

If a Gitea user was created for the context repo, store the `context_git_user_id` on the `SandboxSession` for cleanup. This may require adding a `context_git_user_id` column or combining it with the existing `git_user_id` field.

Simplest approach: store it as a comma-separated value in the existing `git_user_id` field, or add a new nullable column.

- [ ] **Step 6: Commit**

```bash
git add druppie/sandbox/__init__.py druppie/agents/builtin_tools.py
git commit -m "feat: pass dual git credentials (core + project) for update_core_builder sandbox"
```

---

### Task 9: Rebuild and Test

- [ ] **Step 1: Rebuild all services**

```bash
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile dev --profile init up -d --build
```

- [ ] **Step 2: Verify agent loads**

```bash
docker exec druppie-new-backend python3 -c "
from druppie.agents.definition_loader import AgentDefinitionLoader
d = AgentDefinitionLoader().load('update_core_builder')
print(f'Agent: {d.id}, tools: {d.extra_builtin_tools}')
"
```

- [ ] **Step 3: Verify OpenCode agent file exists**

```bash
ls druppie/sandbox-config/agents/druppie-core-builder.md
```

- [ ] **Step 4: E2E test — send "add smiley.md to Druppie codebase" via chat**

Use Playwright MCP to:
1. Login as admin
2. Send message
3. Answer BA questions
4. Approve FD
5. Verify Architect signals `DESIGN_APPROVED_CORE_UPDATE`
6. Verify Planner routes to `update_core_builder`
7. Verify sandbox clones both repos
8. Verify PR is created targeting `colab-dev`
9. Verify `done()` pauses for developer approval
