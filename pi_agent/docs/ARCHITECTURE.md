# Architecture

## The two-world model

Everything in this codebase splits cleanly into two places:

- **Host** — the Node.js process running `oneshot-tdd-agent`. Holds all
  credentials (Anthropic / Z.AI key, GitHub App private key). Runs the
  orchestrator logic and hosts each agent's pi session.
- **Sandbox** — a Kata microVM (production) or Sysbox container (dev). Holds
  the source code, runs every bash/write/edit operation. Holds no credentials.

Every LLM call originates from the host. Every effect on the source code
(file writes, commits, `npm install`, `docker compose up`) happens in the
sandbox. The boundary is a loopback-TCP RPC between the orchestrator
process and a Python daemon inside the container.

This is LangChain's "agent-out, sandbox-as-tool" pattern. See e.g.
<https://www.langchain.com/blog/the-two-patterns-by-which-agents-connect-sandboxes>.

## End-to-end flow

One `oneshot --task task.json` invocation walks through:

```
  host                                  sandbox
  ────                                  ───────
  1. launch sandbox container           boot ~2s
     (sysbox/kata, --privileged if kata)
     dockerd starts inside
     daemon starts on TCP 8000
  2. mint GitHub App installation token
     (1h-valid, cheap to remint)
  3. host clones source repo with token
     → bundle (--all, opaque packfile)
  4. send bundle bytes to daemon  ──▶   /import-bundle
                                        git init + git fetch bundle
                                        → all refs local
                                        checkout source branch (e.g. colab-dev)
  5. init() via daemon          ──▶    git config user.email/name
                                        (so agents can commit)
  6. snapshot baseSha = git rev-parse HEAD
  7. createBranch(oneshot-run-<ts>)
     (temp name — analyst renames later)

  PHASE LOOP BEGINS
  ─────────────────

  ANALYZE
  8. spawn pi session for analyst agent
     LLM thinks → tool calls
       → remote-ops route bash/read → daemon /exec, /read
     analyst outputs JSON with branchName
  9. renameCurrentBranch(branchName) ──▶ git branch -m

  PLAN (iteration N, retry on invalid JSON)
 10. spawn pi session for planner agent
     LLM outputs BuildPlan (waves × steps)

  EXECUTE
 11. for each wave:
       spawn builder agent(s) — parallel if wave has >1 step
       each builder commits via bash ──▶ /exec 'git commit'

  VERIFY
 12. spawn verifier agent
     runs tests + build via bash
     may commit fixes

 13. if testsPassed && buildPassed → break
     else → loop to PLAN with failure context

  PHASE LOOP ENDS
  ───────────────

 14. git.getCurrentBranch()         ──▶ /exec 'git branch --show-current'
     push-branch = that
 15. listNewCommits(baseSha)        ──▶ /exec 'git log <baseSha>..HEAD'

 16. bundle = git bundle create     ──▶ /bundle
     → /out/run.bundle (host-visible via mount)

 17. spawn push-sandbox container
     mount bundle (read-only) + GITHUB_TOKEN in env
     fresh bare clone of remote
     fetch bundle → push branch to origin
     container exits

 18. spawn pr-author agent (retry ×3 if invalid JSON)
     LLM reads git log/diff → outputs {title, body}

 19. POST /repos/:owner/:repo/pulls (ensurePullRequest)
     idempotent — skips if open PR exists

 20. tear down sandbox
     write summary.json, close journal
     print ascii table
```

Every step that writes to disk, executes code, or touches git state happens
inside the sandbox. Every step involving credentials happens on the host.

## Who decides what

This is a deliberate split between **plain code** and **LLM-agent** concerns.

| Decision | Who decides |
|---|---|
| Sequence of phases (analyze → plan → build → verify) | orchestrator (hardcoded) |
| Retry count for each iteration | orchestrator (`maxIterations`, default 3) |
| Which agent to run for each phase | orchestrator (`getAgent("analyst")` etc.) |
| Branch name | analyst (outputs `branchName` in JSON) |
| Number of waves, steps in build plan | planner |
| Which files get modified + commit messages | builder |
| Whether tests pass / what remaining issues are | verifier |
| PR title + body | pr-author |
| Whether a PR already exists (idempotency) | GitHub API + `ensurePullRequest` |

The orchestrator is a dumb state machine. It makes no creative decisions —
every `if`/`for`/`switch` is over parsed JSON or boolean checks. See
[`src/orchestrator.ts`](../src/orchestrator.ts) top-of-file comment.

## Where credentials live

```
ANTHROPIC_API_KEY / ZAI_API_KEY
  ├── host env (process.env)
  └── authStorage.setRuntimeApiKey (in-memory, per-run)
  NOT in sandbox. Not in push-sandbox. Never serialized.

GITHUB_APP_ID / INSTALLATION_ID / PRIVATE_KEY_PATH
  ├── host env
  └── used on host to mint short-lived installation tokens
  NOT in sandbox. Not even the installation tokens enter the sandbox —
  only the host-side clone step (source-clone.ts) and the push-sandbox
  container use them.

GITHUB_TOKEN (fallback PAT)
  ├── host env
  └── same treatment as App tokens

INSTALLATION TOKEN (minted)
  ├── host process memory (short-lived, ~1h)
  ├── embedded in host-side git clone URL (authedUrl in source-clone.ts)
  └── passed to push-sandbox container via -e GITHUB_TOKEN
  Main sandbox never sees these either.
```

## Sandbox security posture

Under Kata (production):
- Each container is its own microVM with its own Linux kernel
- `--privileged` is VM-scoped, not host-scoped
- dockerd inside the sandbox can run arbitrary containers (`docker compose up`) without touching host
- Kernel exploit in the guest doesn't reach the host

Under Sysbox (dev):
- User-namespace isolation + seccomp + procfs virtualization
- No microVM, but rootless-docker-in-docker works natively
- Good enough for development on hosts without nested virt (e.g. Hetzner Cloud)

Both satisfy the same invariant: the sandbox cannot reach host files, host
processes, or host credentials. The sandbox's network is wide open (so the
agent can `npm install`, `apt install`, `curl public-apis`), which is
safe-by-construction since no credentials are present to exfiltrate.

## Why agent-out, not agent-in

An alternative design (see druppie/background-agents) is to put the coding
agent *inside* the sandbox, and have it talk to external services through
proxies. That's better for multi-tenant hosted deployments: the user never
runs the orchestrator process, a tenant's LLM/git creds are scoped to their
sandbox via a proxy, sessions can survive host restarts, etc.

This codebase is agent-out because it's single-tenant (one dev running
`oneshot --task ...`). That's strictly simpler:

- No LLM proxy infrastructure needed — the orchestrator calls LLM directly
- No git proxy — the push-sandbox uses the credential directly
- pi SDK stays identical to its default usage
- Debugging is local: journal, traces, a single Node process

If you ever need to scale to a hosted, multi-user product, you'd flip to the
agent-in pattern. Nothing in the current design precludes that.
