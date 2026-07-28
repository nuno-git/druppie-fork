# Sandbox → in-cluster modules: gateway proposal

**Status:** proposal (investigation + recommendation — no code change yet)
**Date:** 2026-07-28
**Context:** AC2 of the "coding sandbox reliability" story — *"determine and
document whether the sandbox has network access to other modules/services in
the cluster (Gitea, LLM, etc.), and if so, that it works."*

---

## Problem statement

gVisor sandboxes cannot reach in-cluster `ClusterIP` services (their userspace
netstack does not route to the cluster service VIPs, and they use the node
resolver rather than CoreDNS). That is fine for **Gitea** — it is bridged
host-side via git bundles (see `docs/SANDBOX.md`). But some agents are supposed
to talk to **other module MCP servers** (e.g. `module-filesearch`,
`module-registry`) from *inside* the sandbox — the `modules` network tier in the
network-isolation design (`docs/specs/sandbox-network-isolation-v2.md`). Today
there is **no path** for that: the current tree has a single sandbox template
with no module egress and no bridge.

## History: it was built, then reverted 26 minutes later

| Commit | When | What |
|--------|------|------|
| `0fe1509c` "feat: per-tier agent-sandbox networking via internal gateway" | 2026-07-06 10:14 | Introduced three gVisor SandboxTemplates/WarmPools (airgapped / internet / modules), selected per agent from `coding.networks`. The **modules tier reached in-cluster services through a `hostNetwork` gateway DaemonSet** (a CONNECT proxy with a host allowlist), "since gVisor can't reach ClusterIPs". Also moved the repo clone host-side. Touched `k8s_sandbox.py`, `tools.py`, `sandboxtemplate-agent-coding.yaml`, `warmpool.yaml`, `values.yaml`, and added `gateway.yaml` (227 lines). |
| `079052f4` `Revert "feat: per-tier agent-sandbox networking via internal gateway"` | 2026-07-06 10:40 | Full revert, **no stated reason**, no intervening commits. |

**Read of the situation:** a 26-minute lifespan with a bare revert message
strongly suggests the gateway did not work on first deploy (or broke something)
and was backed out to unblock, not a considered architectural rejection. The
*host-side clone* idea from the same commit was later re-landed on its own
(`b9090e56`), which is why clone/push work today while the modules gateway does
not. **The reason it was reverted is not recorded** — that gap is itself worth
closing before deciding.

## What the gateway did (reconstructed from `0fe1509c`)

- A **`hostNetwork` DaemonSet** ran on nodes and acted as an HTTP `CONNECT`
  proxy. Because it was on the host network, it *could* reach ClusterIPs.
- Sandbox pods on the `modules` tier were pointed at this proxy (via env /
  `HTTP(S)_PROXY` or explicit client config) with a **host allowlist** limiting
  which in-cluster destinations were reachable.
- Per-tier **templates + warm pools** meant an agent's `coding.networks`
  declaration selected which sandbox flavour it got (airgapped / internet /
  modules) — aligning the runtime with the isolation model in the v2 spec.

## Options

### Option A — Keep the status quo (host-side only), document it
Do not reintroduce a modules path from inside the sandbox. Agents that need
module data get it via the pipeline/filesystem pattern already described in
`sandbox-network-isolation-v2.md` (internet agents fetch, module agents read
from the workspace), and any host-mediated calls stay host-side like Gitea.

- **Pro:** simplest; nothing new to run or secure; matches what actually ships.
- **Con:** the `modules` network tier in the isolation spec has no runtime
  backing — it is aspirational. Agents cannot call module MCP servers directly.

### Option B — Reintroduce the gateway DaemonSet (revive `0fe1509c`)
Bring back the per-tier templates + `hostNetwork` CONNECT proxy, but first find
out *why* it was reverted and fix that.

- **Pro:** realises the intended `modules` tier; agents can reach module
  services with a host allowlist enforcing least privilege.
- **Con:** a `hostNetwork` DaemonSet is a privileged, cluster-wide component —
  higher security/ops burden; needs its own NetworkPolicy, allowlist review, and
  monitoring. Reintroducing reverted code without the root cause risks the same
  failure.

### Option C — Host-side module proxy in `module-coding` (no new DaemonSet)
Mirror the Gitea pattern: the `module-coding` pod (which *can* reach ClusterIPs)
proxies specific, allowlisted module calls on the sandbox's behalf, exposed as
an explicit MCP tool rather than raw network access.

- **Pro:** no privileged DaemonSet; reuses the trust boundary that already
  handles credentials; calls are explicit and auditable.
- **Con:** only supports call patterns we expose as tools (not arbitrary
  sandbox→module traffic); more work in `tools.py`.

## Recommendation

1. **Short term — Option A + honesty.** Ship the documented status quo: Gitea is
   host-side, internet works, and the `modules` tier is **not currently wired**.
   `docs/SANDBOX.md` and `sandbox-network-isolation-v2.md` should say so plainly
   so nobody assumes an agent can reach module ClusterIPs from the sandbox.
2. **Decide with data.** Run `scripts/sandbox_network_probe.sh` on a live cluster
   and record results in `docs/sandbox-network-findings.md`. This confirms
   (rather than assumes) internet=yes, Gitea=no, LLM=?, modules=no.
3. **If the `modules` tier is actually required**, prefer **Option C** (host-side
   proxy tool) over reviving the DaemonSet — it keeps the privileged surface
   small and reuses the existing host trust boundary. Only pursue **Option B**
   if agents genuinely need arbitrary sandbox→module traffic that a tool cannot
   express, and only after the `0fe1509c` revert root cause is understood.

## Open questions

- **Why was `0fe1509c` reverted?** (deploy failure? gVisor+proxy incompat?
  scheduling? security review?) — ask the author (nscholten) or check deploy
  logs from 2026-07-06. This should be answered before Option B is considered.
- Which agents/tools actually need direct module access from inside the sandbox
  today, versus getting module data via the filesystem/pipeline pattern?
</content>
