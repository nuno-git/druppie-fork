# oneshot-tdd-agent — documentation

An orchestrated multi-agent system that runs a full TDD cycle (analyze →
plan → build → verify → PR) against a source repository, inside an isolated
Kata/Sysbox sandbox, with no credentials ever entering the sandbox.

## Reading order

Start here, then drill into whichever section matches what you're working on.

| Doc | What it covers |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The big picture — two-world model (host orchestrator + sandboxed workspace), end-to-end flow, which component owns which decision. |
| **[SANDBOX.md](SANDBOX.md)** | Everything about the sandbox: Kata vs Sysbox runtimes, the container image, the daemon API, how pi's tool calls are re-routed to hit the daemon, security properties. |
| **[AGENTS.md](AGENTS.md)** | What an "agent" is in this codebase, the five agents, the pi runtime, frontmatter contract, retry handling, commit expectations. |
| **[GIT_AND_PR.md](GIT_AND_PR.md)** | Bundle-based source-clone, commits inside the sandbox, the isolated push-sandbox, PR creation, GitHub App token minting. |
| **[OBSERVABILITY.md](OBSERVABILITY.md)** | The per-run journal + summary, the pretty end-of-run table, the sim provider for testing resilience, retry caps. |
| **[RUNNING.md](RUNNING.md)** | Quickstart + env vars + prerequisites + common debugging. |

## Quick mental model

```
              HOST                                    SANDBOX (Kata or Sysbox)
              ────                                    ────────────────────────
  node dist/cli.js                                    docker container
                                                       ├── dockerd running inside
  orchestrator.ts                                      ├── Python exec daemon
    │                                                  │      unix RPC from host
    │  spawns pi agent session                         │         │
    │   (LLM calls → GLM / Anthropic)                  │         ▼
    │                                                  ├── /workspace
    │   LLM emits tool call ──── RPC ──── ▶             │      git repo, real
    │                           cwd='/workspace'        │      source code, real
    │                                                  │      commits
    │   ◀────── tool result ───────                   │
    │                                                  └── no credentials
    ▼
  at end:
    - get bundle from sandbox                         bundle file (pack of git objects)
    - spawn push-sandbox container                       ↓
      with GitHub token                                 push → GitHub
    - pr-author agent → PR title+body                     
    - call GitHub API to create PR
```

**LLM key lives on host. Git token lives in host + push-sandbox. Neither ever
enters the main sandbox. Code execution, file writes, git commits all happen
inside the sandbox.**

## Key source files

| File | Role |
|---|---|
| `src/cli.ts` | Argv parsing, config construction, `oneshot --task ...` entry |
| `src/orchestrator.ts` | Plain-code coordinator (not an agent) that sequences the phases |
| `src/agents/runner.ts` | Spawns a pi session for one subagent, wires remote tools |
| `.pi/agents/*.md` | The five agent definitions (frontmatter + system prompt) |
| `src/sandbox/lifecycle.ts` | Launch/tear down the sandbox container |
| `src/sandbox/client.ts` | HTTP client for the sandbox daemon |
| `src/sandbox/remote-ops.ts` | Pi tool `operations` impls that RPC to the daemon |
| `src/sandbox/tools-factory.ts` | Builds `customTools` + `activationTools` for pi |
| `src/sandbox/source-clone.ts` | Host-side clone → bundle → import into sandbox |
| `src/sandbox/bundle-push.ts` | Spawn isolated push-sandbox to push to GitHub |
| `src/sandbox/sandbox-git.ts` | `SandboxGitOps` — git commands routed through daemon |
| `src/github/app.ts` | GitHub App JWT signing + installation-token minting |
| `src/github/pr.ts` | `ensurePullRequest` — idempotent PR create-or-find |
| `src/providers/sim.ts` | Failure-injecting HTTP proxy in front of Z.AI |
| `src/journal.ts` | Run journal (JSONL) + summary (JSON) + pretty print |
| `sandbox/daemon.py` | The daemon that runs inside the sandbox container |
| `sandbox/Dockerfile` | Sandbox image (debian + node + python + docker-ce) |
| `sandbox/entrypoint.sh` | Starts dockerd then execs the daemon |
| `push-sandbox/entrypoint.sh` | Fresh bare clone + fetch bundle + push |
