# Sandbox Architecture

Each coding agent runs in an isolated sandbox. In production (Kubernetes) the
sandbox is a **gVisor**-isolated pod managed by the [agent-sandbox controller][as]
(`kubernetes-sigs/agent-sandbox`); for local development it is a Docker
container. The backend is selected at runtime by `DRUPPIE_SANDBOX_MODE`
(`k8s` | `docker`).

The critical property is the same in both modes: **the sandbox never holds git
credentials**. The `module-coding` MCP server clones the repo, ships it into the
sandbox, the agent works, and changes are extracted via `git bundle` and pushed
from the host — credentials only ever live on the host side.

> **Note on this document.** Earlier revisions described a Docker/Sysbox/Kata
> setup. That is now only the *local dev* mode. The production path is
> gVisor + Kubernetes, described below. Some sibling docs
> (`docs/stories/coding-agent-supplement.md`, `sprint-overview-coding-agent.md`)
> still use the older Docker vocabulary — treat this file as the source of truth
> for the runtime.

[as]: https://github.com/kubernetes-sigs/agent-sandbox

---

## Why gVisor changes everything: no ClusterIP reachability

gVisor (`runsc`) gives the sandbox its own userspace network stack. That stack
**cannot reach in-cluster `ClusterIP` services or cluster DNS (CoreDNS)**. This
single fact drives most of the design below:

- **Gitea** is a `ClusterIP` service → the sandbox cannot clone/fetch/push
  against it directly. All git traffic is handled **host-side** in the
  `module-coding` pod, and code moves in/out of the sandbox as **git bundles**.
- The sandbox pod uses `dnsPolicy: Default` (the node resolver), **not**
  `ClusterFirst`, so it does not get cluster service discovery either.
- Outbound **internet** (e.g. `pip`/`npm` over `:443`) *does* work — that egress
  is allowed on the SandboxTemplate.

See **Network reachability** below for the full picture.

---

## Architecture (k8s mode)

```
Druppie backend (agent loop)
    |
    v
module-coding MCP server (host pod, port 9001)   ── has git credentials, reaches Gitea ClusterIP
    |
    |  create_sandbox() via agent-sandbox SDK (claims from a warm pool)
    v
gVisor sandbox pod  (namespace: {instance}-sandbox, runtimeClass: gvisor)
    |  NO git credentials · NO ClusterIP reachability · /workspace on a PVC
    |
    |  <-- host-side clone: git clone on host → tar → upload → extract in /workspace
    |  --> push_changes: git bundle in sandbox → copy to host → push to Gitea (host)
    v
Gitea (ClusterIP, reached only from the host)
```

### Key components

| Component | Location | Role |
|-----------|----------|------|
| **K8sSandboxManager** | `druppie/mcp-servers/module-coding/k8s_sandbox.py` | Wraps the agent-sandbox async SDK: claim/exec/read/write/destroy + host-side clone + orphan reaper |
| **MCP tools (orchestrator)** | `druppie/mcp-servers/module-coding/v1/tools.py` | The agent-facing tools; dual-mode dispatch (`SANDBOX_MODE`) between k8s and docker |
| **MCP server + watchdog** | `druppie/mcp-servers/module-coding/server.py` | Lifespan startup cleanup + 60s watchdog (dead/idle reap + orphan sweep) |
| **SandboxTemplate** | `helm/druppie/templates/agent-sandbox/sandboxtemplate-agent-coding.yaml` | Pod spec for the sandbox: `runtimeClassName: gvisor`, image, `/workspace` PVC, egress rules |
| **SandboxWarmPool** | `helm/druppie/templates/agent-sandbox/warmpool.yaml` | Pre-warmed pool (default 5) so claims are instant (no ~10s cold start) |
| **RBAC / namespace** | `helm/druppie/templates/agent-sandbox/rbac.yaml`, `namespace.yaml` | Per-instance sandbox namespace + rights on sandbox CRDs and `pods/exec` |
| **Sandbox image** | `druppie/mcp-servers/module-coding/Dockerfile.sandbox.k8s` | Runner image (agent-sandbox runtime server + Python/Node/git/tools) |

---

## The clone → edit → push flow (in detail)

This is the flow the E2E test (`testing/tools/sandbox-gvisor-push-e2e.yaml`)
exercises end to end.

1. **Host-side clone** (`k8s_sandbox._host_side_clone`)
   - `git clone --depth 50 --branch <b>` runs **on the module-coding host**
     (which can reach Gitea's ClusterIP), into a temp dir.
   - The tree (incl. `.git`) is tarred in memory and uploaded to the sandbox as
     `repo.tar` (relative name → `/app/repo.tar`; the SDK upload endpoint 500s
     on absolute paths).
   - `/workspace` is wiped (a recycled warm-pool pod may hold a previous
     session's files) and the tar is extracted there.
   - The `origin` URL is rewritten to a **credential-stripped** form, so no token
     remains in `/workspace/.git/config`.

2. **Edit** — the agent uses `read_file` / `write_file` / `edit_file` / `bash`.
   In k8s mode file writes stage the content via the SDK upload endpoint under a
   relative temp name and `mv` it into place (absolute paths 500 on that
   endpoint; the older base64-through-`bash -c` approach failed with execve
   `E2BIG` for files larger than ~96 KB). Binary reads (e.g. git bundles) still round-trip
   via `base64` in the shell.

3. **`push_changes`** (`tools.py`)
   - Auto-commits any uncommitted changes **inside** the sandbox.
   - `git bundle create` inside the sandbox (no credentials needed).
   - The bundle is copied to the host (base64 read via the SDK).
   - On the host: fetch the base branch from Gitea **with credentials**, import
     the bundle, and `git push` to Gitea. A PR can be opened via the Gitea REST
     API (also host-side).

`git_fetch` / `git_pull` are the mirror image: host fetches with credentials,
bundles, and imports into the sandbox.

**Credential isolation:** the `bash` tool blocks `git push`, `git remote`, and
`git config credential.*`. The sandbox holds no token; every authenticated git
operation happens on the host.

---

## Network reachability

What a gVisor sandbox pod can and cannot reach (from the SandboxTemplate egress
rules + the gVisor netstack limitation):

| Destination | Reachable from sandbox? | How / notes |
|-------------|-------------------------|-------------|
| **Gitea** (code) | ❌ No | `ClusterIP` — unreachable by gVisor. Handled host-side; code moves via git bundles. |
| **Internet** (pip, npm, docs, public APIs) | ✅ Yes | Egress to `0.0.0.0/0:443` is allowed on the SandboxTemplate. |
| **LLM** | ⚠️ Allowed, not verified | Egress rule permits the release-namespace backend pods on `:8000`. Not confirmed end-to-end from a gVisor sandbox — see `docs/sandbox-network-findings.md`. |
| **Other modules** (filesearch, registry, …) | ❌ Not wired | These are `ClusterIP` services. The per-tier "modules gateway" that would bridge this was reverted (see `docs/specs/sandbox-modules-gateway-proposal.md`); the current tree has no path from the sandbox to module ClusterIPs. |
| **Cluster DNS (CoreDNS)** | ❌ No | Pod uses `dnsPolicy: Default` (node resolver), not `ClusterFirst`. |

To (re-)establish the actual state on a live cluster, run the probe in
**`scripts/sandbox_network_probe.sh`** and record the outcome in
`docs/sandbox-network-findings.md`.

---

## Lifecycle, cleanup & cancellation

Leaked sandboxes and wedged sessions used to pin cluster capacity. These are the
mechanisms that address it (all in `server.py` + `k8s_sandbox.py` + `tools.py`):

- **Watchdog (60s)** — `_sandbox_watchdog` in `server.py`. Destroys dead
  sandboxes and **idle-reaps** any sandbox with no tool activity for
  `> DRUPPIE_SANDBOX_MAX_IDLE` (default 900s). `last_activity` is touched on every
  resolve.
- **Orphan-claim reaper** — `K8sSandboxManager.cleanup_orphan_claims`. Lists
  `SandboxClaim`s in the sandbox namespace and deletes any whose
  `session::scope` label isn't tracked in-memory and that is older than
  `min_age_seconds` (default 300). Runs at startup and every watchdog cycle.
  Relies on `replicas=1` for module-coding.
- **Destroy-before-recreate** — `_resolve_container` destroys the old sandbox
  before recreating on a flaky liveness check (a prior bare `del` leaked claims).
- **Cancel** — session cancel hard-cancels the wedged tool call and
  `_destroy_all_for_session` terminates the gVisor sandbox (k8s branch).

---

## Known limitations / technical debt

These are deliberate work-arounds. They work today but are fragile; each is a
candidate for hardening.

| # | Item | Where | Risk |
|---|------|-------|------|
| 1 | **SDK monkeypatch** — `wait_for_sandbox_ready` is replaced with a no-op to dodge a warm-pool adoption race in the agent-sandbox SDK. | `k8s_sandbox.py` `__init__` | Breaks on an SDK upgrade; must be re-verified when bumping `k8s-agent-sandbox`. |
| 2 | **base64 shell pipe for binary reads** — the SDK's `files.write` 500s on absolute paths, so `read_file_bytes` (git bundles) reads via `base64` in the shell. `write_file` no longer uses base64: it stages via the SDK upload endpoint under a relative temp name + `mv`, which also fixed a silent ~96 KB `MAX_ARG_STRLEN` truncation. | `k8s_sandbox.read_file_bytes` | Slower/larger than a native binary download; an upstream SDK fix should replace it. |
| 3 | **Namespace / warmpool fallbacks** — code defaults (`sandbox-runtime` / `agent-coding-warmpool`) match no chart resource; the Helm ConfigMap injects the real per-instance values. `__init__` now warns loudly if the fallback is ever used. | `k8s_sandbox.py` top + `__init__` | Only bites if run in k8s mode without the ConfigMap; then create/reap target a non-existent namespace. |
| 4 | **`/management/sandbox/warmup` is a noop** — warming is declarative via the `SandboxWarmPool` CRD, so there is nothing imperative to trigger. Endpoint kept for API compatibility. | `server.py` `warmup_pool` | None functionally; was previously mislabelled "not implemented". |
| 5 | **No module-tier egress** — the sandbox cannot reach in-cluster module services; the per-tier gateway was reverted. | Helm agent-sandbox templates | Agents that need real module APIs from inside the sandbox cannot; see the gateway proposal. |
| 6 | **Two things named "sandbox"** — the gVisor orchestrator (this doc) is separate from a `sandbox_session` "control plane" (`druppie/api/routes/sandbox.py`) that talks to an external `sandbox-control-plane:8787` service not shipped in this chart. Don't conflate them. | `api/routes/sandbox.py` | Confusing; unrelated to the gVisor runtime. |
| 7 | **`_get_death_reason` is static in k8s mode** — always returns `"sandbox terminated (k8s mode)"`. | `tools.py` | Crash diagnostics are poorer than docker mode. |

---

## Local dev mode (Docker)

When `DRUPPIE_SANDBOX_MODE=docker` (the default outside the cluster), the
orchestrator spawns Docker containers via the Docker socket instead of gVisor
pods. Runtime is `sysbox-runc` (hardened, nested containers) or `kata-runtime`
(VM-level). The tool surface and the clone/bundle/push flow are identical; only
the container lifecycle differs. This mode is what the Python tests
(`druppie/tests/mcp_servers/test_sandbox*.py`) cover.

---

## Configuration reference

### Environment variables (k8s mode)

| Variable | Source | Description |
|----------|--------|-------------|
| `DRUPPIE_SANDBOX_MODE` | ConfigMap | `k8s` when `agentSandbox.enabled`, else `docker` |
| `SANDBOX_NAMESPACE` | ConfigMap | `{instance}-sandbox` — where sandboxes live (see debt #3) |
| `SANDBOX_WARMPOOL` | ConfigMap | `{instance}-warmpool` — warm pool to claim from (see debt #3) |
| `DRUPPIE_SANDBOX_MAX_IDLE` | env/default | Idle seconds before the watchdog reaps a sandbox (default 900) |

### MCP tools exposed to the agent

`read_file`, `write_file`, `edit_file`, `bash`, `grep`, `find`, `ls`/`list_dir`,
`batch_write_files`, `delete_file`, `search_files`, `get_file_info`,
`get_git_status`, `push_changes`, `git_fetch`, `git_pull`, `create_pr`.

### Key files

| File | Purpose |
|------|---------|
| `druppie/mcp-servers/module-coding/k8s_sandbox.py` | K8sSandboxManager (SDK wrapper, host-side clone, orphan reaper) |
| `druppie/mcp-servers/module-coding/v1/tools.py` | MCP tool implementations, dual-mode dispatch |
| `druppie/mcp-servers/module-coding/server.py` | MCP server, watchdog, management routes |
| `helm/druppie/templates/agent-sandbox/` | SandboxTemplate, WarmPool, RBAC, namespace |
| `helm/druppie/templates/configmap.yaml` | Injects the sandbox env vars |
| `testing/tools/sandbox-gvisor-push-e2e.yaml` | End-to-end clone→edit→push→verify test |
| `scripts/sandbox_network_probe.sh` | Determines module/LLM/internet reachability from a sandbox |
| `docs/sandbox-network-findings.md` | Record of the network-reachability determination |
| `docs/specs/sandbox-modules-gateway-proposal.md` | Gateway history + recommendation |
</content>
