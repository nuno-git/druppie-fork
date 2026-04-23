# Running oneshot-tdd-agent

How to actually run it, from zero to "PR opened against druppie-fork".

## Prerequisites

### Host

- **Linux** (macOS untested).
- **Node.js 22+** — the orchestrator.
- **Docker Engine** — 24+. Used for both the main sandbox and the push-sandbox.
- **A sandbox runtime** registered with Docker:
  - `kata-runtime` for production (microVM per container, needs `/dev/kvm`
    exposed). Hetzner Cloud VMs don't expose this — you'd need
    Hetzner Robot bare metal or any provider with nested virt (GCP n2 with
    `enable-nested-virtualization`, Azure Dv3+, AWS `*.metal`).
  - `sysbox-runc` for dev on hosts without nested virt. Install via
    [`scripts/install-sysbox.sh`](../scripts/install-sysbox.sh).

### Credentials

- **Z.AI / GLM API key** — REQUIRED. The default agent configs all use
  `zai/glm-5.1`. Set `ZAI_API_KEY` (or `GLM_API_KEY`) in your env.
- **GitHub App credentials** — if pushing from a CI/production context.
  Set `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`,
  `GITHUB_APP_PRIVATE_KEY_PATH`. Tokens minted fresh per run, valid ~1h.
- **GitHub PAT fallback** — if not using an App, set `GITHUB_TOKEN` with
  Contents + Pull requests write permissions on the target repo.

Anthropic API key is **not** required unless you edit an agent to use a
Claude model.

## First-time setup

```bash
# 1. Install Node deps
cd /path/to/dev_agent
npm install

# 2. Build TS
npm run build

# 3. Build the sandbox images (one-time, ~2 minutes)
./scripts/build-sandboxes.sh
# → oneshot-sandbox:latest (1.46 GB, includes dockerd, node, python, git)
# → oneshot-push-sandbox:latest (32 MB, alpine + git)

# 4. Install your sandbox runtime (dev)
sudo ./scripts/install-sysbox.sh

# Or install Kata for production:
#   https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker/
```

## Running a task

### Minimal task spec

`task.json`:

```json
{
  "description": "Append a single line '<!-- oneshot-tdd-agent test -->' at the end of README.md",
  "language": "none",
  "testCommand": "grep -q 'oneshot-tdd-agent test' README.md",
  "buildCommand": "true",
  "sourceRepoUrl": "https://github.com/nuno-git/druppie-fork",
  "pushOnComplete": true
}
```

Fields:

- `description` — the task the agents will work on. The analyst
  restates this as the goal.
- `language` — free-form, passed into agent prompts. Use `"none"` for
  non-code tasks like doc edits.
- `testCommand` — shell command the verifier runs. Must return exit 0 on
  success.
- `buildCommand` — shell command the verifier runs after tests. Use `"true"`
  if there's no build step.
- `sourceRepoUrl` — the repo to clone into the sandbox. Agents work on a
  new branch derived from this.
- `sourceBranch` — defaults to `"colab-dev"`. Override for other base branches.
- `pushOnComplete` — whether to push + create a PR when done.
- `branch` — pin the working branch name instead of letting the analyst
  choose. Rarely needed.

### Invoking

```bash
set -a && . /path/to/.env && set +a        # loads ZAI_API_KEY + GITHUB_APP_*
export ONESHOT_SANDBOX_RUNTIME=sysbox-runc  # or kata-runtime

node dist/cli.js \
  --task task.json \
  --push-remote https://github.com/nuno-git/druppie-fork
```

That's the whole invocation. At end of run you get stdout summary, a journal
directory, and (if everything worked) a PR on GitHub.

### Key CLI flags

| Flag | Purpose |
|---|---|
| `--task <file\|desc>` | Task JSON file or inline description |
| `--lang <lang>` | Language (inline task only; default: typescript) |
| `--model <id>` | Default model override |
| `--push` | Equivalent to `pushOnComplete: true` in the spec |
| `--push-remote <url>` | Target repo for the push |
| `--push-token <tok>` | Override (normally env vars) |
| `--pr-base <branch>` | PR target branch (default: sourceBranch) |
| `--pr-title <str>` | Override agent-authored title |
| `--source-repo <url>` | Override `sourceRepoUrl` from CLI |
| `--source-branch <b>` | Override `sourceBranch` from CLI (default: colab-dev) |
| `--workdir <path>` | Host scratch dir (default: tmpdir) |

### Environment variables

| Var | Default | Purpose |
|---|---|---|
| `ZAI_API_KEY` / `GLM_API_KEY` | — | Z.AI API key (required) |
| `GITHUB_TOKEN` | — | PAT fallback for push/PR if no App |
| `GITHUB_APP_ID` | — | GitHub App ID |
| `GITHUB_APP_INSTALLATION_ID` | — | App installation on target repo |
| `GITHUB_APP_PRIVATE_KEY_PATH` | — | filesystem path to App private key .pem |
| `ONESHOT_SANDBOX_RUNTIME` | `kata-runtime` | `kata-runtime` or `sysbox-runc` |
| `ONESHOT_SANDBOX_IMAGE` | `oneshot-sandbox:latest` | Sandbox image tag |
| `ONESHOT_SANDBOX_MEMORY` | `4g` | Container memory cap |
| `ONESHOT_SANDBOX_CPUS` | `2` | Container cpu cap |
| `ONESHOT_SANDBOX_PIDS` | `8192` | Container pid-limit |
| `ONESHOT_SANDBOX_TIMEOUT` | `86400` | Wall-clock max (24h) |
| `ONESHOT_SANDBOX_NETWORK` | `1` | `0` = `--network=none` in the sandbox |
| `ONESHOT_SIM_FAILURES` | `0` | `1` = enable the failure-injection proxy |
| `ONESHOT_SIM_FAILURE_RATE` | `0.5` | 0-1 probability of injecting failures |

## Typical smoke-test sequence

```bash
# 1. Verify the environment is sane
./scripts/build-sandboxes.sh
docker info --format '{{json .Runtimes}}' | jq keys   # should include your chosen runtime
node -e 'require("./dist/github/app.js").mintInstallationToken(require("./dist/github/app.js").loadAppCredentialsFromEnv()).then(t=>console.log("token ok, expires", t.expiresAt))'

# 2. Run a trivial task against a throwaway branch
cat > /tmp/smoke.json <<'EOF'
{
  "description": "...",
  "language": "none",
  "testCommand": "grep -q 'marker' README.md",
  "buildCommand": "true",
  "sourceRepoUrl": "https://github.com/<you>/<test-repo>",
  "pushOnComplete": true
}
EOF

node dist/cli.js --task /tmp/smoke.json --push-remote https://github.com/<you>/<test-repo>

# 3. Check the resulting PR
# 4. Inspect the journal in sessions/runs/<timestamp>/
```

## Troubleshooting

**"Runtime sysbox-runc is not registered with Docker."** You've set
`ONESHOT_SANDBOX_RUNTIME` to a runtime that isn't installed. Either install
it (see prereqs) or set the env var to something actually available.

**"No commit found for SHA"** — a GitHub 422 when looking up a commit.
Means the commit doesn't exist on the remote yet. Fine during a run — the
push step creates it.

**Run hangs in ANALYZE for minutes.** Probably retries. Check
`sessions/runs/<latest>/journal.jsonl` for `llm_retry_start` events. At
90% upstream failure each LLM call needs ~10 attempts with exponential
backoff. Lower `ONESHOT_SIM_FAILURE_RATE` if you weren't trying to stress-test.

**"Author identity unknown" in agent bash output.** The orchestrator didn't
call `git.init()` after the clone — bug, file an issue. Should be set
automatically.

**"Push failed: Invalid username or token"** on a long run. App
installation tokens expire in ~1h. Current code mints fresh per call —
older versions cached and hit this. If seeing this again, check
`resolvePushToken()` isn't re-caching.

**Sandbox fails to boot / `docker run` error.** Make sure the image was
built (`docker image inspect oneshot-sandbox:latest`). `./scripts/build-sandboxes.sh`
rebuilds both.

**PR #N already exists and we claim `action: exists`.** That's normal —
re-running the same task reuses the existing PR. The push updates the
branch to the new commits.

**The agent committed but `commits: []` in summary.** `listNewCommits`
got nothing. Either the branch didn't advance (commit actually failed)
or `baseSha` is wrong (git log baseSha..HEAD is empty). Inspect session
files in `sessions/runs/<timestamp>/<agent>.jsonl`.
