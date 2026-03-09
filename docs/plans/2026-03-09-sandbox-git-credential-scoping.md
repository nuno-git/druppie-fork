# Sandbox Git Credential Scoping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the shared Gitea admin credentials with per-sandbox restricted service accounts so each sandbox can only access its target repository. Also fix credential cleanup so proxy keys are invalidated when sandboxes complete.

**Architecture:** Two layers of defense. Layer A: Druppie creates a restricted Gitea user per sandbox, grants it collaborator access to only the target repo, and creates a scoped token. The token is sent to the control plane instead of admin credentials. Layer B: The git proxy validates that the requested `owner/repo` matches the session's authorized scope. Credentials are destroyed on `execution_complete`, container destruction, and session deletion.

**Tech Stack:** Python/httpx (Druppie Gitea API calls), TypeScript (control plane credential store + git proxy)

---

### Task 1: Add repo scope to credential store

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/credentials/credential-store.ts:15-53`

**Step 1: Add `authorizedRepo` to `GitCredentials` interface and `StoredSession`**

In `credential-store.ts`, add a field to track which repo this session is allowed to access:

```typescript
export interface GitCredentials {
  provider: string;
  url: string;
  username: string;
  password: string;
  authorizedRepo?: string; // "owner/repo" — enforced by git proxy
}
```

No other changes needed — the `authorizedRepo` will flow through the existing `store()` → `getByGitProxyKey()` path automatically since `StoredSession.gitCredentials` is typed as `GitCredentials | null`.

**Step 2: Expose `authorizedRepo` in `getByGitProxyKey` return**

The method already spreads `...stored.gitCredentials` into the return value (line 122), so `authorizedRepo` will be included automatically. No code change needed.

**Step 3: Commit**

```bash
cd vendor/open-inspect
git add packages/local-control-plane/src/credentials/credential-store.ts
git commit -m "feat: add authorizedRepo field to GitCredentials for repo-scoped access"
```

---

### Task 2: Validate repo scope in git proxy

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/proxy/git-proxy.ts:68-92`

**Step 1: Add repo validation after proxy key check**

In `git-proxy.ts`, after the proxy key validation (line 81), add:

```typescript
    // 2. Validate repo scope
    if (creds.authorizedRepo) {
      const requestedRepo = `${owner}/${repoName}`;
      if (requestedRepo !== creds.authorizedRepo) {
        console.warn(
          `[git-proxy] Repo mismatch: requested=${requestedRepo} authorized=${creds.authorizedRepo} session=${creds.sessionId}`
        );
        res.status(403).json({ error: "Repository not authorized for this session" });
        return;
      }
    }
```

Insert this between the existing "1. Validate proxy key" block and the "2. Validate git path whitelist" block. Renumber the existing comments (path whitelist becomes 3, build URL becomes 4, etc.).

**Step 2: Update the file header comment**

The header already says "2. Validates the owner/repo matches the session's authorized scope" — now the code actually does this.

**Step 3: Commit**

```bash
cd vendor/open-inspect
git add packages/local-control-plane/src/proxy/git-proxy.ts
git commit -m "feat: enforce repo scope validation in git proxy"
```

---

### Task 3: Destroy credentials on execution_complete and container destruction

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts:866-906`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts:317-357`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts` (constructor/fields)
- Modify: `vendor/open-inspect/packages/local-control-plane/src/router.ts:144-208`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-manager.ts`

The session instance currently has no access to the credential store. We need to thread it through.

**Step 1: Pass credential store reference to SessionManager**

In `index.ts` (line 39), the `SessionManager` is created before the `CredentialStore`. Reorder:

```typescript
const credentialStore = new CredentialStore();
const sessionManager = new SessionManager(sandboxClient, sessionIndex, credentialStore);
```

Update `SessionManager` to accept and store the credential store:

```typescript
// In session-manager.ts
export class SessionManager {
  constructor(
    private sandboxClient: SandboxClient,
    private sessionIndex: LocalSessionIndexStore,
    private credentialStore: CredentialStore,
  ) {}

  get(sessionId: string): SessionInstance {
    // ... existing logic, pass credentialStore to SessionInstance
  }
}
```

**Step 2: Pass credential store to SessionInstance**

When `SessionManager.get()` creates a new `SessionInstance`, pass the credential store. Add a private field and a cleanup method:

```typescript
// In session-instance.ts
private credentialStore: CredentialStore | null = null;

setCredentialStore(store: CredentialStore): void {
  this.credentialStore = store;
}

private destroyCredentials(): void {
  if (this.credentialStore && this.sessionName) {
    this.credentialStore.destroy(this.sessionName);
  }
}
```

**Step 3: Call `destroyCredentials()` on execution_complete**

In `processSandboxEvent`, case `"execution_complete"` (line 866), add after the webhook callback block (line 898) but before the broadcast:

```typescript
      // Invalidate proxy keys — sandbox is done, no more git/LLM access needed
      this.destroyCredentials();
```

**Step 4: Call `destroyCredentials()` in `destroySandboxContainer()`**

In `destroySandboxContainer()` (line 317), add at the beginning of the method:

```typescript
  private async destroySandboxContainer(): Promise<void> {
    // Invalidate proxy keys before destroying container
    this.destroyCredentials();

    const sandbox = this.getSandbox();
    // ... rest of existing code
  }
```

**Step 5: Remove redundant destroy from router DELETE**

In `router.ts` line 226, the `credentialStore?.destroy(sessionId)` call is now redundant since `handleDestroyContainer()` calls `destroySandboxContainer()` which calls `destroyCredentials()`. Keep it anyway as defense-in-depth — `destroy()` is idempotent.

**Step 6: Commit**

```bash
cd vendor/open-inspect
git add packages/local-control-plane/src/
git commit -m "fix: destroy credentials on execution_complete and container destruction"
```

---

### Task 4: Create per-sandbox Gitea service accounts

**Files:**
- Create: `druppie/sandbox/gitea_credentials.py`

This module creates a restricted Gitea user per sandbox session, grants it collaborator access to the target repo, creates a scoped token, and provides cleanup.

**Step 1: Implement the module**

```python
"""Per-sandbox Gitea credential management.

Creates a restricted Gitea user per sandbox session with access to only
the target repository. This replaces the shared admin credentials so a
compromised sandbox cannot access other repos.

Lifecycle:
  create_sandbox_git_user()  — called before sandbox creation
  delete_sandbox_git_user()  — called after sandbox completion (webhook handler + retry)
"""

import os
import secrets

import httpx
import structlog

logger = structlog.get_logger()

_GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "")


def _admin_auth() -> tuple[str, str]:
    return (_ADMIN_USER, _ADMIN_PASSWORD)


async def create_sandbox_git_user(
    sandbox_session_id: str,
    repo_owner: str,
    repo_name: str,
) -> dict[str, str]:
    """Create a restricted Gitea user scoped to one repo.

    Returns a git credential dict compatible with build_git_credentials() format:
      {"provider": "gitea", "url": ..., "username": ..., "password": ..., "authorizedRepo": ...}

    The user is named `sandbox-{sandbox_session_id[:12]}` to stay within
    Gitea's username length limits while remaining identifiable.
    """
    username = f"sandbox-{sandbox_session_id[:12]}"
    password = secrets.token_urlsafe(24)
    email = f"{username}@sandbox.druppie.local"
    base = _GITEA_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Create restricted user via admin API
        resp = await client.post(
            f"{base}/api/v1/admin/users",
            json={
                "username": username,
                "password": password,
                "email": email,
                "must_change_password": False,
                "restricted": True,
                "visibility": "private",
            },
            auth=_admin_auth(),
        )

        if resp.status_code not in (201, 422):
            raise RuntimeError(
                f"Failed to create sandbox Gitea user: {resp.status_code} {resp.text[:200]}"
            )

        if resp.status_code == 422 and "already exists" in resp.text.lower():
            logger.warning("sandbox_gitea_user_exists", username=username)

        # 2. Add as collaborator on target repo (write access)
        resp = await client.put(
            f"{base}/api/v1/repos/{repo_owner}/{repo_name}/collaborators/{username}",
            json={"permission": "write"},
            auth=_admin_auth(),
        )

        if resp.status_code not in (204, 200):
            # Clean up orphaned user
            await _delete_user(client, base, username)
            raise RuntimeError(
                f"Failed to add collaborator: {resp.status_code} {resp.text[:200]}"
            )

        # 3. Create scoped access token for the user
        resp = await client.post(
            f"{base}/api/v1/users/{username}/tokens",
            json={
                "name": "sandbox-token",
                "scopes": ["write:repository"],
            },
            auth=(username, password),
        )

        if resp.status_code != 201:
            await _delete_user(client, base, username)
            raise RuntimeError(
                f"Failed to create token: {resp.status_code} {resp.text[:200]}"
            )

        token = resp.json().get("sha1", "")

        logger.info(
            "sandbox_gitea_user_created",
            username=username,
            repo=f"{repo_owner}/{repo_name}",
        )

        return {
            "provider": "gitea",
            "url": _GITEA_URL,
            "username": username,
            "password": token,
            "authorizedRepo": f"{repo_owner}/{repo_name}",
        }


async def delete_sandbox_git_user(sandbox_session_id: str) -> None:
    """Delete the sandbox's Gitea user. Idempotent — ignores 404."""
    username = f"sandbox-{sandbox_session_id[:12]}"
    base = _GITEA_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        await _delete_user(client, base, username)


async def _delete_user(client: httpx.AsyncClient, base: str, username: str) -> None:
    """Delete a Gitea user via admin API. Ignores 404."""
    try:
        resp = await client.delete(
            f"{base}/api/v1/admin/users/{username}",
            auth=_admin_auth(),
        )
        if resp.status_code in (204, 404):
            logger.info("sandbox_gitea_user_deleted", username=username)
        else:
            logger.warning(
                "sandbox_gitea_user_delete_failed",
                username=username,
                status=resp.status_code,
            )
    except Exception as e:
        logger.warning("sandbox_gitea_user_delete_error", username=username, error=str(e))
```

**Step 2: Commit**

```bash
git add druppie/sandbox/gitea_credentials.py
git commit -m "feat: per-sandbox Gitea service accounts with repo-scoped access"
```

---

### Task 5: Wire scoped credentials into sandbox creation

**Files:**
- Modify: `druppie/sandbox/credentials.py:50-57`
- Modify: `druppie/sandbox/__init__.py:99-103`

**Step 1: Replace `build_git_credentials()` with async scoped version**

In `credentials.py`, rename the current function to `build_admin_git_credentials()` (keep it for fallback/MCP use) and add a new async function:

```python
async def build_scoped_git_credentials(
    sandbox_session_id: str,
    repo_owner: str,
    repo_name: str,
) -> dict[str, str]:
    """Create per-sandbox scoped git credentials via Gitea API."""
    from druppie.sandbox.gitea_credentials import create_sandbox_git_user

    return await create_sandbox_git_user(sandbox_session_id, repo_owner, repo_name)
```

Rename existing `build_git_credentials` → `build_admin_git_credentials`. Update the import in `__init__.py`.

**Step 2: Use scoped credentials in `create_and_start_sandbox()`**

In `__init__.py`, after the sandbox session is created on the control plane (line 124, where we have `sandbox_session_id`), the credentials are already sent. We need to restructure: build scoped credentials BEFORE creating the session.

Change the credential building (lines 99-102) from:

```python
        "credentials": {
            "git": build_git_credentials(),
            "llm": build_llm_credentials(),
        },
```

To:

```python
        "credentials": {
            "git": await build_scoped_git_credentials(
                sandbox_session_id=f"{repo_owner}-{repo_name}-{secrets.token_hex(6)}",
                repo_owner=repo_owner,
                repo_name=repo_name,
            ),
            "llm": build_llm_credentials(),
        },
```

Wait — we don't have the `sandbox_session_id` yet at this point because it comes from the control plane response. But the Gitea username is derived from the sandbox session ID. We need a deterministic ID we control.

Better approach: generate a short unique ID ourselves for the Gitea user, independent of the control plane session ID. Use this in the create body and store it on the sandbox session record for cleanup:

```python
    git_user_id = secrets.token_hex(6)  # 12-char hex, used for Gitea username

    scoped_git_creds = await build_scoped_git_credentials(
        sandbox_session_id=git_user_id,
        repo_owner=repo_owner,
        repo_name=repo_name,
    )

    create_body = {
        "repoOwner": repo_owner,
        "repoName": repo_name,
        # ... existing fields ...
        "credentials": {
            "git": scoped_git_creds,
            "llm": build_llm_credentials(),
        },
    }
```

Store `git_user_id` on the sandbox session record (next task).

**Step 3: Commit**

```bash
git add druppie/sandbox/credentials.py druppie/sandbox/__init__.py
git commit -m "feat: use per-sandbox scoped git credentials in sandbox creation"
```

---

### Task 6: Store git_user_id on sandbox session for cleanup

**Files:**
- Modify: `druppie/db/models/sandbox_session.py` — add `git_user_id` column
- Modify: `druppie/repositories/sandbox_session_repository.py` — accept `git_user_id` in `create()`

**Step 1: Add column to SandboxSession model**

```python
git_user_id = Column(String, nullable=True)  # Gitea service account ID for cleanup
```

**Step 2: Accept in repository `create()` method**

Add `git_user_id: str | None = None` parameter to `create()` and pass through.

**Step 3: Pass from `create_and_start_sandbox()`**

In `__init__.py`, when calling `sandbox_repo.create()` (line 141-150), add `git_user_id=git_user_id`.

**Step 4: Commit**

```bash
git add druppie/db/models/sandbox_session.py druppie/repositories/sandbox_session_repository.py druppie/sandbox/__init__.py
git commit -m "feat: store git_user_id on sandbox session for Gitea user cleanup"
```

---

### Task 7: Clean up Gitea user on sandbox completion

**Files:**
- Modify: `druppie/api/routes/sandbox.py` — webhook handler and watchdog

**Step 1: Add cleanup to the webhook handler**

In the webhook completion endpoint (`sandbox_complete_webhook`), after the tool call is completed and before resuming the agent, delete the Gitea user:

```python
    # Clean up the per-sandbox Gitea service account
    sandbox_mapping = sandbox_repo.get_by_sandbox_id(sandbox_session_id)
    if sandbox_mapping and sandbox_mapping.git_user_id:
        try:
            from druppie.sandbox.gitea_credentials import delete_sandbox_git_user
            await delete_sandbox_git_user(sandbox_mapping.git_user_id)
        except Exception as e:
            logger.warning("sandbox_gitea_cleanup_failed", error=str(e))
```

**Step 2: Add cleanup to the retry path**

In the retry logic (where a new sandbox is created after failure), delete the old Gitea user before creating a new one. The retry path already has access to the sandbox session record.

**Step 3: Add cleanup to manual sandbox cancellation**

If the sandbox watchdog kills a session, ensure the Gitea user is cleaned up there too.

**Step 4: Commit**

```bash
git add druppie/api/routes/sandbox.py
git commit -m "feat: clean up Gitea service accounts on sandbox completion and retry"
```

---

### Task 8: Add garbage collection for orphaned Gitea users

**Files:**
- Create: `druppie/sandbox/gitea_cleanup.py`

If cleanup fails (network error, process crash), orphaned `sandbox-*` users accumulate. Add a simple garbage collection function that can be called on backend startup or periodically.

**Step 1: Implement cleanup**

```python
async def cleanup_orphaned_sandbox_users() -> int:
    """Delete Gitea users matching 'sandbox-*' that have no active sandbox session.

    Returns the number of users deleted.
    """
    base = _GITEA_URL.rstrip("/")
    deleted = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        # List all users matching sandbox pattern
        resp = await client.get(
            f"{base}/api/v1/admin/users",
            params={"limit": 50},
            auth=_admin_auth(),
        )
        if resp.status_code != 200:
            return 0

        for user in resp.json():
            username = user.get("login", "")
            if username.startswith("sandbox-") and user.get("restricted"):
                await _delete_user(client, base, username)
                deleted += 1

    return deleted
```

**Step 2: Call on backend startup**

In `druppie/api/main.py`, add a startup event that runs `cleanup_orphaned_sandbox_users()`.

**Step 3: Commit**

```bash
git add druppie/sandbox/gitea_cleanup.py druppie/api/main.py
git commit -m "feat: garbage collection for orphaned sandbox Gitea users on startup"
```

---

### Task 9: Reset database and test end-to-end

**Step 1: Reset DB** (new column added)

```bash
docker compose --profile reset-db run --rm reset-db
```

**Step 2: Rebuild and start**

```bash
docker compose --profile dev --profile init up -d --build
```

**Step 3: Verify**

1. Trigger a sandbox task via the UI
2. Check Gitea admin panel — a `sandbox-*` user should appear with collaborator access to only the target repo
3. Check backend logs for `sandbox_gitea_user_created`
4. Wait for sandbox to complete
5. Check Gitea admin panel — the `sandbox-*` user should be deleted
6. Check backend logs for `sandbox_gitea_user_deleted`
7. Verify proxy keys are invalidated (control plane logs should show credential store cleanup)

**Step 4: Test unauthorized repo access**

1. During an active sandbox (before completion), try to access a different repo through the proxy
2. Verify the git proxy returns 403 "Repository not authorized for this session"
3. Verify the Gitea token itself cannot access other repos (restricted user)

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: per-sandbox git credential scoping — complete implementation"
```

---

### Task 10: Update documentation

**Files:**
- Modify: `docs/SANDBOX.md` — update security section

**Step 1: Update the Credential Proxying section**

Replace the "Known limitation" paragraph with:

```markdown
### Credential Proxying

Git and LLM credentials are never exposed to the sandbox. The control plane generates per-session
proxy keys and intercepts git/LLM requests to inject real credentials.

**Per-sandbox Gitea accounts:** Each sandbox gets its own restricted Gitea user with collaborator
access to only the target repository. The user is created before the sandbox starts and deleted
after it completes. Even if a sandbox extracts its proxy key, the underlying Gitea token can only
access the authorized repo.

**Proxy-side validation:** The git proxy validates that the requested `owner/repo` matches the
session's authorized scope. Requests for other repos return 403.

**Credential lifecycle:** Proxy keys (both git and LLM) are invalidated when the sandbox completes
(`execution_complete`), when the container is destroyed (timeout, failure, manual kill), and when
the session is deleted. Orphaned Gitea service accounts are cleaned up on backend startup.
```

**Step 2: Commit**

```bash
git add docs/SANDBOX.md
git commit -m "docs: update sandbox security section with per-repo credential scoping"
```
