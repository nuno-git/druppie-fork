# Git flow, auth, and PR creation

How source code enters and leaves the sandbox, how we authenticate to
GitHub, and how PRs get created — all while keeping credentials out of the
main sandbox.

## High-level flow

```
      HOST                                 MAIN SANDBOX
      ────                                 ────────────
  1.  mint App installation token
  2.  git clone --bare <authed-url>
      git bundle create --all  ──────▶   POST /import-bundle (bytes)
                                           git init /workspace
                                           git fetch bundle +refs/heads/*:refs/heads/*
                                           git checkout <sourceBranch>
  3.  mint token again
      POST /init  ─────────────────────▶   git config user.email / user.name
                                           git remote add origin <url>
  4.  snapshot baseSha
  5.  createBranch(oneshot-run-<ts>)
                                          agents run, agents commit, agents diff
  6.  renameCurrentBranch(analyst.branchName)

  7.  verifier passes →
      listNewCommits(baseSha)  ───────▶   git log <baseSha>..HEAD

  8.  POST /bundle --all  ────────────▶   git bundle create /out/run.bundle
      ◀───── bundle bytes (via bind mount)

                PUSH-SANDBOX
                ────────────
  9.  docker run push-sandbox \
        -v <bundle-path>:/in/run.bundle:ro \
        -e GITHUB_TOKEN=<fresh token> \
        -e REMOTE_URL=... -e BRANCH=...
      ───▶  git clone --bare <remote> → fresh bare clone with NO hooks
            git bundle verify /in/run.bundle
            git fetch /in/run.bundle refs/heads/$BRANCH:refs/heads/$BRANCH
            git push --no-verify origin $BRANCH

  10. pr-author agent → {title, body} JSON
  11. POST /repos/:owner/:repo/pulls (idempotent)
```

## Source clone (step 2)

[`src/sandbox/source-clone.ts`](../src/sandbox/source-clone.ts):

```
cloneSourceIntoSandbox(client, endpoint, { remoteUrl, branch, token }):
  mkdtemp on host
  injectTokenIntoHttpsUrl(remoteUrl, token)
    → https://x-access-token:<token>@github.com/owner/repo
  git clone --bare <authed-url> <work>/src.git
  git -C src.git bundle create <work>/src.bundle --all
  POST /import-bundle?branch=<branch> with bundle bytes as body
  rm -rf <work>
```

Three properties worth calling out:

1. **Token is on host only.** The authed URL is used for `git clone` on the
   host, then discarded. It never appears in any sandbox-bound request,
   environment variable, or file.
2. **Bundle is opaque data.** `git bundle` produces a packfile. The sandbox
   `/import-bundle` handler treats it as bytes fed to `git fetch`. There's
   no code execution possible here — fetch only brings in objects, never
   populates hooks, never runs scripts.
3. **Full clone (no `--single-branch`).** Agents get all branches locally
   and can checkout, inspect, diff against any of them. Enables `git branch
   -a` to show everything.

## Git config on init (step 3)

Without `user.email` / `user.name`, `git commit` fails inside the sandbox
with "Author identity unknown". The daemon's `/init` endpoint handles this:

[`sandbox/daemon.py`](../sandbox/daemon.py) `init_workspace`:

```python
await (await asyncio.create_subprocess_exec(
    "git", "-C", WORKSPACE, "config", "user.name", user_name
)).wait()
await (await asyncio.create_subprocess_exec(
    "git", "-C", WORKSPACE, "config", "user.email", user_email
)).wait()
if remote_url:
    await (await asyncio.create_subprocess_exec(
        "git", "-C", WORKSPACE, "remote", "add", "origin", remote_url
    )).wait()
```

Idempotent — `git init` is skipped if `.git` already exists, `git config`
always runs. The orchestrator calls `git.init()` unconditionally after the
clone for exactly this reason.

## Commits inside the sandbox (step 6)

Builders commit via their own bash tool calls (`git add -A && git commit -m
"..."`). See [AGENTS.md](AGENTS.md) §Commit expectations.

The orchestrator itself **does not commit** anything. Earlier revisions
used to emit `chore: goal analysis complete` etc. between phases — those
were all no-ops (nothing staged) and have been removed.

## Capturing what the agents did (step 7)

Right after clone + init, the orchestrator captures `baseSha = git rev-parse
HEAD`. At push time:

```ts
const newCommits = await git.listNewCommits(baseSha);  // git log baseSha..HEAD
for (const c of newCommits.reverse()) {
  commits.push(c.sha);
  journal.commit("agent", c.sha, c.message);
}
```

Every commit the agents actually made appears in `commits[]` and in the
journal. If no agent committed, `commits` is empty and the summary reports
`Commits: 0` — a clear signal something went wrong during the build phase.

**Gotcha this design avoids**: don't diff against a named branch like
`colab-dev`. If `task.sourceBranch` is undefined at some point in the code
path, `colab-dev..HEAD` becomes `HEAD..HEAD` (empty). Always capture the
explicit SHA at start.

## Creating the bundle (step 8)

The sandbox creates one final bundle:

```
POST /bundle { refs: ["--all"], name: "run.bundle" }
→ git bundle create /out/run.bundle --all
```

`/out` is the only shared path between host and sandbox (bind mount
`<host-tmpdir>/out` ↔ `/workspace/out`... no wait, `/out`). The host reads
the bundle bytes directly from its tmpdir.

## Push via isolated push-sandbox (step 9)

**The main sandbox never pushes.** The push happens in a separate,
single-use alpine container. [`push-sandbox/Dockerfile`](../push-sandbox/Dockerfile)
+ [`push-sandbox/entrypoint.sh`](../push-sandbox/entrypoint.sh):

```bash
set -eu
: "${REMOTE_URL:?}"; : "${BRANCH:?}"; : "${GITHUB_TOKEN:?}"
BUNDLE="${BUNDLE_PATH:-/in/run.bundle}"

cd /tmp
# Fresh bare clone — no hooks, no working tree, nothing executable.
git -c core.hooksPath=/dev/null clone --bare --filter=blob:none "$REMOTE_URL" /tmp/remote.git
cd /tmp/remote.git

# Verify is a pure data check (self-consistency of the pack).
git bundle verify "$BUNDLE"

# Fetch objects + the one branch from the bundle.
git -c core.hooksPath=/dev/null fetch "$BUNDLE" "refs/heads/${BRANCH}:refs/heads/${BRANCH}"

# Push only that branch.
git -c core.hooksPath=/dev/null push --no-verify origin "refs/heads/${BRANCH}:refs/heads/${BRANCH}"
```

Security properties:

- **Read-only rootfs**, tmpfs for /tmp (see [`pushBundleIsolated`](../src/sandbox/bundle-push.ts)).
- `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root user.
- `core.hooksPath=/dev/null` on every git command → hooks can't execute.
- `--no-verify` on push → pre-push hooks can't execute.
- `--filter=blob:none` on clone → small download, no content-layer execution
  surface. We only need refs + trees to push.
- Bundle is mounted **read-only**. The container can read it but can't
  modify it or escape to host.
- Container lifetime is seconds: clone + verify + fetch + push + exit.

The container sees nothing except the bundle file and the token. If the
bundle triggered a git parsing CVE, it'd land in this throwaway container —
not in the main sandbox, not in the host, not in anything with long-term
credentials.

## PR creation (steps 10-11)

### pr-author agent

After push succeeds, the orchestrator spawns pr-author (see [AGENTS.md](AGENTS.md)):

```ts
for (let attempt = 1; attempt <= 3; attempt++) {
  const result = await runSubagent(getAgent("pr-author"), prPrompt, baseOpts);
  const parsed = extractJson<{ title?: string; body?: string }>(result.output);
  if (parsed?.title && parsed?.body) {
    authoredTitle = parsed.title;
    authoredBody  = parsed.body;
    break;
  }
}
if (!authoredTitle || !authoredBody) {
  throw new Error("pr-author failed to produce a valid title+body after 3 attempts");
}
```

Overrides: if `config.sandbox.prTitle` or `config.sandbox.prBody` was set
explicitly, the agent is skipped and the override wins.

### ensurePullRequest

[`src/github/pr.ts`](../src/github/pr.ts) — idempotent:

```
GET /repos/:owner/:repo/pulls?state=open&head=OWNER:BRANCH&base=PR_BASE
  ─────────────────────────────────────────────────────────────────
  any results?   →  return { action: "exists", number, url }
  empty?         →  POST /repos/:owner/:repo/pulls { title, body, head, base }
                    return { action: "created", number, url }
```

Base branch defaults to `task.sourceBranch ?? "colab-dev"` — so PR targets
the same branch the agent started from. Overridable via `sandbox.prBase` /
`--pr-base`.

## GitHub App token minting

[`src/github/app.ts`](../src/github/app.ts):

```
mintInstallationToken({ appId, installationId, privateKey }):
  1. sign a short-lived JWT (9 min lifetime) with the App's RSA private key (RS256)
     payload = { iat: now-60, exp: now+9*60, iss: appId }
  2. POST https://api.github.com/app/installations/:id/access_tokens
     Authorization: Bearer <JWT>
  3. response.token is a ~1h installation token (ghs_...)
```

Tokens are minted fresh on every call. No caching — a long-running session
(tests taking hours) would outlast a cached token, and push/PR would fail
with `Invalid username or token`. Minting is cheap: one JWT sign + one
API call, both local-CPU or sub-second.

Env vars mirror druppie's convention:

- `GITHUB_APP_ID`
- `GITHUB_APP_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY_PATH` (filesystem path to the .pem)

If any are missing, `loadAppCredentialsFromEnv()` returns `null` and we fall
back to `GITHUB_TOKEN` (a PAT). Either path produces the same shape of
credential downstream.

## PAT fallback

If you don't want to set up an App, a fine-grained personal access token
works. Required permissions:

- **Contents: Read and write** (for push)
- **Pull requests: Read and write** (for ensure-or-create)

Scope the PAT to the single target repo. Set via `GITHUB_TOKEN` env or
`--push-token`.

## What never crosses to the main sandbox

Neither `GITHUB_APP_*` env vars, nor the PAT, nor any minted installation
token, ever enter the main sandbox container. The clone step uses the
token on the host (runs `git clone` in a host tmpdir) and only ships an
opaque bundle. The push step runs in its own throwaway container with the
token.

The main sandbox only sees commit outputs (branches, commits, working
tree). If an agent there were to be prompt-injected into exfiltrating, the
worst it could leak is the source code — which is going to the remote
anyway.
