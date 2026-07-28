# Sandbox → in-cluster modules: decision record

**Status:** DECIDED — Option B (hostNetwork CONNECT-proxy DaemonSet), revived and
hardened, shipped behind a feature flag.
**Date:** 2026-07-28 (supersedes the 2026-07-06 proposal draft below the fold)
**Decision owner:** coding-sandbox reliability story, AC2.
**Confirm with:** nscholten (author of the reverted `0fe1509c`).

> This file began as an investigation + recommendation ("no code change yet").
> It is now a **decision record**: the gateway was chosen, the root cause of the
> earlier revert was analysed, and the fixes are documented so the same failure
> cannot recur.

---

## Decision

Reintroduce the per-tier gVisor sandbox networking with an **in-cluster HTTP
`CONNECT`-proxy DaemonSet on `hostNetwork`** (the shape of the reverted
`0fe1509c`), but hardened against the five defects that caused that revert, and
gated behind a feature flag so the blast radius is controlled:

- **Flag:** `agentSandbox.gateway.enabled` (bool, **default `false`**).
  - `false` → render EXACTLY the current single SandboxTemplate + single
    SandboxWarmPool, no gateway, no per-tier resources. Current behaviour is
    preserved bit-for-bit.
  - `true` → render 3 per-tier SandboxTemplates + 3 SandboxWarmPools + the
    gateway DaemonSet/namespace.
- **Enabled on:** `rijnland` / prod.
- **Excluded:** `hetzner` — it runs its **own in-cluster Gitea** and a different
  network posture, so it stays on the flag-off path.

### Why Option B over A / C

The 2026-07-06 draft (preserved below) recommended short-term Option A (status
quo) and, if a modules path was truly needed, Option C (host-side proxy tool)
over reviving the DaemonSet. That recommendation is **overturned**: agents on
the `modules` tier need to reach in-cluster module MCP servers as ordinary
network destinations (arbitrary host:port), which a per-call host-mediated tool
(Option C) cannot express without re-implementing a proxy anyway. Option B, once
hardened, gives the `modules` tier a real runtime backing while keeping the
privileged surface to a single, allowlisted, auditable component.

---

## Root-cause analysis of the `0fe1509c` revert

`0fe1509c` ("feat: per-tier agent-sandbox networking via internal gateway",
nscholten, 2026-07-06 10:14) was fully reverted by `079052f4` at 10:40 — a
**26-minute lifespan**, **no revert message**, no intervening commits. Live
deploy logs from that window were not retrievable offline, so the precise
first-failure is confirmed by code inspection rather than logs. The reconstructed
code shows five concrete defects; **defect 1 is deterministically fatal on
deploy regardless of what the logs would have said.**

| # | Defect (as shipped in `0fe1509c`) | Consequence | Severity |
|---|-----------------------------------|-------------|----------|
| 1 | `sandbox-gateway` namespace was labelled `pod-security.kubernetes.io/enforce: baseline`, but the DaemonSet runs `hostNetwork: true`. | PSA **rejects** every gateway pod at admission — `hostNetwork` requires the `privileged` level. The DaemonSet never starts. | **Certain-fatal** |
| 2 | Gateway container image was `python:3.12-slim` from Docker Hub, with **no `imagePullSecret`**. | `ImagePullBackOff` on air-gapped/Harbor-only clusters (Docker Hub is not reachable / not the pull source). | Fatal |
| 3 | The `modules` tier forced **ALL** HTTPS through the gateway, whose allowlist defaulted to only `.rijnland.dev` (`ALLOW_HOSTS` default `.rijnland.dev`). | `pip` / `npm` / external git got **403** from the proxy — external package + git traffic that should go direct was funnelled into an allowlist that excluded it. | Fatal to `modules` tier |
| 4 | Gateway DaemonSet hard-required `nodeSelector: node-role.kubernetes.io/worker=true`. | On clusters where no node carries that label, the DaemonSet matches **zero nodes** → no proxy anywhere. | Latent-fatal |
| 5 | Per-tier warmpool naming collided with the later env-based `SANDBOX_WARMPOOL = "{instance}-warmpool"` scheme. | Warmpool names the code claims from no longer matched the rendered CRDs → claims target non-existent pools. | Fatal (post-merge) |

**Read of the situation:** a 26-minute lifespan with a bare revert message means
the gateway did not survive first deploy. Defect 1 alone guarantees that — the
pods cannot be admitted — so the revert was an unblock, not a considered
architectural rejection. (The host-side clone idea from the same commit was
re-landed independently as `b9090e56`, which is why clone/push work today.)

---

## The fixes (what "hardened" means)

Each fix maps to a defect above.

1. **PSA `privileged` (fix 1).** The `sandbox-gateway` namespace is labelled
   `pod-security.kubernetes.io/enforce: privileged` (NOT `baseline`), because the
   DaemonSet legitimately needs `hostNetwork: true`.
2. **Harbor image + regcred (fix 2).** The gateway container uses the Harbor
   sandbox image
   `{{ .Values.global.imageRegistry }}/druppie-sandbox-k8s:{{ .Values.global.imageTag }}`,
   overridable via `.Values.agentSandbox.gateway.image`, with
   `imagePullSecrets: [harbor-regcred]`. No Docker Hub image.
3. **NO_PROXY-direct-external design (fix 3).** The `modules` tier does **not**
   force all HTTPS through the gateway. External package/git traffic goes
   **direct** (egress `0.0.0.0/0:443` is already allowed). Only in-cluster
   hostnames route via the proxy, expressed with `HTTPS_PROXY` / `https_proxy`
   pointing at the node proxy plus a `NO_PROXY` that lists the external hosts:
   `pypi.org, files.pythonhosted.org, github.com, codeload.github.com, aigit.waterschap.org, 10.23.0.101, 127.0.0.1, localhost`.
   The proxy allowlist (`ALLOW_HOSTS`, from `.Values.agentSandbox.gateway.allowHosts`)
   then only ever sees in-cluster destinations, so a too-narrow allowlist can no
   longer 403 `pip`/`npm`.
4. **Drop the worker nodeSelector + add probes (fix 4).** The DaemonSet runs on
   **all schedulable nodes** (no `node-role.kubernetes.io/worker=true`
   requirement) and gains a `readinessProbe` **and** `livenessProbe` (TCP `:3128`)
   so unhealthy proxies are detected and traffic is not routed to a dead pod.
5. **Reconciled naming (fix 5).** Warmpool names are `{base}-{tier}` where
   `{base}` is the **same value the code claims from** — the current
   `SANDBOX_WARMPOOL = "{instance}-warmpool"` scheme — i.e.
   `{instance}-warmpool-{tier}`. With the flag **off**, the single pool remains
   exactly `{instance}-warmpool` (`{base}`), so nothing changes for existing
   instances.

---

## Contract (as shipped)

| Item | Value |
|------|-------|
| Feature flag | `agentSandbox.gateway.enabled` (bool, default `false`) |
| Tiers | `airgapped` \| `internet` \| `modules` |
| Tier selection | no networks / `[]` → `airgapped` (default, egress `[]` default-deny); `"modules"` in networks → `modules`; else non-empty → `internet` |
| SandboxTemplate names | `agent-coding-template-{tier}` (namespace `sandbox-runtime`) |
| SandboxWarmPool names | `{base}-{tier}` = `{instance}-warmpool-{tier}` (base = current `SANDBOX_WARMPOOL`) |
| Gateway namespace | `sandbox-gateway`, PSA `enforce: privileged` |
| Gateway workload | DaemonSet, `hostNetwork: true`, `dnsPolicy: ClusterFirstWithHostNet`, listens `:3128` |
| Gateway image | `{{ .Values.global.imageRegistry }}/druppie-sandbox-k8s:{{ .Values.global.imageTag }}` (override: `.Values.agentSandbox.gateway.image`), `imagePullSecrets: [harbor-regcred]` |
| Gateway allowlist | `ALLOW_HOSTS` from `.Values.agentSandbox.gateway.allowHosts` (in-cluster hostnames only) |
| Modules-tier proxy | `HTTPS_PROXY`/`https_proxy` → node proxy `:3128`; `NO_PROXY` = `pypi.org, files.pythonhosted.org, github.com, codeload.github.com, aigit.waterschap.org, 10.23.0.101, 127.0.0.1, localhost` |
| Probes | `readinessProbe` + `livenessProbe`, TCP `:3128` |

### The tiers

| Tier | When selected | Network posture |
|------|---------------|-----------------|
| **airgapped** | no `networks` declared / `[]` (default) | egress `[]` — default-deny. No internet, no modules. |
| **internet** | non-empty `networks` without `"modules"` | External DNS + HTTP/HTTPS egress (`0.0.0.0/0:443`). No in-cluster reach. |
| **modules** | `"modules"` in `networks` | Internet egress **direct** (packages/git), PLUS in-cluster hostnames via the gateway proxy (`HTTPS_PROXY` + `NO_PROXY`). |

### Gitea-from-sandbox path

Gitea is **external** for real instances: `gitea.external.url =
https://aigit.waterschap.org`, `gitea.external.ip = 10.23.0.101`, port `443`
(`hetzner` runs its own in-cluster Gitea and is out of scope for this feature).
The sandbox reaches Gitea as an ordinary external `:443` destination:

- **`hostAliases`** map `aigit.waterschap.org` → `10.23.0.101` in the sandbox
  pod (cluster DNS does not resolve — the pod uses the node resolver), and
- egress to `10.23.0.101:443` is permitted (it is one of the already-allowed
  external `:443` destinations, and it is in `NO_PROXY`, so it goes **direct**,
  not via the proxy).

**Credential invariant (hard):** the sandbox holds **NO git credentials**. Push
stays host-side via `git bundle`. The hostAliases + egress give a **network
path** only (useful for the reachability probe and for read-only fetches the
host cannot bridge); no token, secret mount, or `git config credential.*` is
ever added to any sandbox template, env, or secret. Gitea reachability from the
sandbox = network path only, never credentials.

---

## Verification

Run `scripts/sandbox_network_probe.sh` **per tier** on a live `rijnland`/prod
cluster and record results in `docs/sandbox-network-findings.md`:

- `airgapped`: expect internet ⛔, modules ⛔, Gitea ⛔.
- `internet`: expect internet ✅ (`:443`), modules ⛔, Gitea network-path ✅.
- `modules`: expect internet ✅ (direct, via `NO_PROXY`), modules ✅ (via proxy),
  Gitea network-path ✅.

---
---

## Historical appendix — the original 2026-07-06 proposal (superseded)

> Everything below is the pre-decision investigation, kept for provenance. Its
> recommendation (Option A short-term, Option C if needed) was **superseded** by
> the decision above once the revert root cause was understood and the five
> defects were fixed.

### Problem statement

gVisor sandboxes cannot reach in-cluster `ClusterIP` services (their userspace
netstack does not route to the cluster service VIPs, and they use the node
resolver rather than CoreDNS). That is fine for **Gitea** — it is bridged
host-side via git bundles (see `docs/SANDBOX.md`). But some agents are supposed
to talk to **other module MCP servers** (e.g. `module-filesearch`,
`module-registry`) from *inside* the sandbox — the `modules` network tier in the
network-isolation design (`docs/specs/sandbox-network-isolation-v2.md`).

### History: it was built, then reverted 26 minutes later

| Commit | When | What |
|--------|------|------|
| `0fe1509c` "feat: per-tier agent-sandbox networking via internal gateway" | 2026-07-06 10:14 | Introduced three gVisor SandboxTemplates/WarmPools (airgapped / internet / modules), selected per agent from `coding.networks`. The **modules tier reached in-cluster services through a `hostNetwork` gateway DaemonSet** (a CONNECT proxy with a host allowlist). Also moved the repo clone host-side. |
| `079052f4` `Revert "feat: per-tier agent-sandbox networking via internal gateway"` | 2026-07-06 10:40 | Full revert, **no stated reason**, no intervening commits. |

### Options (as originally framed)

- **Option A — status quo (host-side only), document it.** Simplest; but the
  `modules` tier has no runtime backing.
- **Option B — reintroduce the gateway DaemonSet.** Realises the `modules` tier;
  higher privileged surface. **← the decision above chose this, hardened.**
- **Option C — host-side module proxy in `module-coding`.** No new DaemonSet, but
  only supports call patterns exposed as tools.

### Original recommendation (superseded)

The draft recommended shipping Option A short-term and preferring Option C over
reviving the DaemonSet "only after the `0fe1509c` revert root cause is
understood." That root cause is now understood (see the RCA above), the fatal
defects are fixable, and arbitrary sandbox→module traffic is genuinely required —
so Option B was chosen instead.
