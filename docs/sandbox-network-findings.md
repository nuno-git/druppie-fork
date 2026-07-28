# Sandbox network reachability — findings

**Purpose:** answer AC2 of the coding-sandbox story — *determine and document
whether the gVisor sandbox has network access to other modules/services in the
cluster (Gitea, LLM, etc.), and if so, that it works.*

This document has two parts:
1. **Expected** — derived from the code + Helm config (what the design says).
2. **Observed** — to be filled in after running the probe on a live cluster.

---

## How to determine it

Run the probe from inside a live sandbox pod and paste its output into the
"Observed" section below:

```bash
kubectl -n <instance>-sandbox get pods            # find a running sandbox pod
kubectl -n <instance>-sandbox exec -it <pod> -- bash -c "$(cat scripts/sandbox_network_probe.sh)"
```

(or paste `scripts/sandbox_network_probe.sh` as a `coding:bash` command during a
session.) Override `LLM_PROBE_URL` / `FILESEARCH_URL` / `REGISTRY_URL` /
`GITEA_URL` env vars if your instance's service names differ.

---

## Expected (from code + config)

Sources: `helm/druppie/templates/agent-sandbox/sandboxtemplate-agent-coding.yaml`
(egress rules), `helm/druppie/templates/configmap.yaml` (service URLs),
`druppie/mcp-servers/module-coding/k8s_sandbox.py` (host-side clone rationale),
and `docs/specs/sandbox-modules-gateway-proposal.md` (the per-tier gateway
decision).

Expectations now depend on the **tier** and on whether the gateway feature flag
is enabled:

- **Flag `agentSandbox.gateway.enabled = false`** (default; `hetzner`): a single
  template/warmpool, no per-tier resources, no gateway. Behaves as the historic
  single sandbox — the `airgapped`/`internet` rows below still describe egress,
  but there is no `modules` path.
- **Flag `agentSandbox.gateway.enabled = true`** (`rijnland`/prod): 3 per-tier
  templates (`agent-coding-template-{airgapped|internet|modules}`) + the
  `hostNetwork` gateway DaemonSet on `:3128`. Probe **each tier** separately.

| Destination | airgapped | internet | modules | Why |
|-------------|-----------|----------|---------|-----|
| **Internet HTTPS** (`:443`, e.g. pypi.org, github.com) | ⛔ default-deny | ✅ reachable | ✅ reachable **direct** | `airgapped` egress is `[]`. `internet`/`modules` allow `0.0.0.0/0:443`; `modules` keeps these in `NO_PROXY` so packages/git go direct, not via the proxy. |
| **Internet HTTP** (`:80`) | ⛔ | ⛔ (by design) | ⛔ (by design) | Only `:443` is allowed out (plus Harbor namespace `:80` for image pulls). |
| **Cluster DNS** (`*.svc.cluster.local`, short names) | ⛔ no-resolve | ⛔ no-resolve | ⛔ no-resolve | Sandbox pods use the node resolver, not CoreDNS. In-cluster names resolve **only** inside the gateway (which is `hostNetwork` + `ClusterFirstWithHostNet`). |
| **Gitea** (`aigit.waterschap.org` / `10.23.0.101:443`) | ⛔ (default-deny) | ✅ network path | ✅ network path (direct, in `NO_PROXY`) | External for real instances. `hostAliases` map the name → `10.23.0.101`; egress to `:443` is allowed. Git still runs **host-side via bundles** — the sandbox holds NO credentials; this is a network path only. |
| **LLM** | ⛔ | ⛔ | ⛔ (by design) | **Intentionally unreachable.** The agent loop (LLM calls) runs pod-side in module-coding; the sandbox runtime is exec/file primitives only, so in-sandbox code has no need to call the LLM. Two paths are deliberately closed: (1) the Druppie backend (`:8000`) has **no egress rule**; (2) the model server (ClusterIP in the `llm` namespace) is excluded by prod `ALLOW_HOSTS=.druppie.svc.cluster.local` and by `ALLOW_PORTS` (which omits `:8000`). The probe should **confirm it stays blocked** (negative test). |
| **Other modules** (`module-filesearch`, `module-registry`) | ⛔ | ⛔ | ✅ via gateway (if in `ALLOW_HOSTS`) | In-cluster ClusterIPs. Only the `modules` tier routes in-cluster hostnames through the `:3128` gateway proxy; reachability requires the host to be in `.Values.agentSandbox.gateway.allowHosts`. |

### Bottom line (expected)

- **Gitea:** no in-sandbox git *credentials*; bridged host-side via bundles. A
  **network path** to `10.23.0.101:443` exists on `internet`/`modules` tiers.
- **Internet:** **yes** over HTTPS on `internet`/`modules` (direct on `modules`
  via `NO_PROXY`); **no** on `airgapped`.
- **LLM:** **intentionally unreachable on every tier** — by design, not a gap.
  The agent loop runs pod-side; the sandbox needs no LLM path. Backend `:8000`
  has no egress rule, and the model server (`llm` namespace) is excluded by prod
  `ALLOW_HOSTS`/`ALLOW_PORTS`. The probe confirms the block (negative test).
- **Modules:** now **wired on the `modules` tier** via the gateway proxy (when
  the flag is on and the host is in `ALLOW_HOSTS`); **no** path on the other
  tiers.

---

## Observed (fill in after running)

> **TODO — not yet observed.** Run `scripts/sandbox_network_probe.sh` **once per
> tier** (claim an `airgapped`, an `internet`, and a `modules` sandbox) on a
> live `rijnland`/prod cluster with `agentSandbox.gateway.enabled = true`, and
> paste each run below.

> _Run date:_ `TODO`
> _Cluster / instance:_ `TODO`
> _Sandbox image tag:_ `TODO`

```
airgapped tier — <paste scripts/sandbox_network_probe.sh output here>
```

```
internet tier — <paste scripts/sandbox_network_probe.sh output here>
```

```
modules tier — <paste scripts/sandbox_network_probe.sh output here>
```

### Conclusion

> _Fill in once observed:_ Does each tier's observed behaviour match "Expected"?
> Any surprises (e.g. internet blocked on a tier that should allow it, a module
> host missing from `ALLOW_HOSTS`)? The **LLM must stay unreachable on every
> tier** — that is the designed posture (see the LLM row). If the probe finds it
> *reachable*, that is a regression to fix, not a feature.
</content>
