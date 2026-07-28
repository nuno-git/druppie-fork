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
`druppie/mcp-servers/module-coding/k8s_sandbox.py` (host-side clone rationale).

| Destination | Expected | Why |
|-------------|----------|-----|
| **Internet HTTPS** (`:443`, e.g. pypi.org, github.com) | ✅ reachable | SandboxTemplate egress allows `0.0.0.0/0:443`. |
| **Internet HTTP** (`:80`) | ⛔ blocked (by design) | Only `:443` is allowed out (plus Harbor namespace `:80` for image pulls). |
| **Cluster DNS** (`*.svc.cluster.local`, short names) | ⛔ no-resolve (by design) | Pod uses `dnsPolicy: Default` (node resolver), not CoreDNS. |
| **Gitea** (`ClusterIP`) | ⛔ unreachable (by design) | gVisor userspace netstack can't reach ClusterIPs; git is host-side via bundles. No egress rule. |
| **LLM** | ⚠️ **uncertain** | Egress *policy* allows release-namespace `backend` pods on `:8000`. BUT the model server is `model-server.llm.svc.cluster.local:8001` (a ClusterIP in another namespace, not in the allowlist), and cluster DNS won't resolve from the node resolver. So even the allowed `backend:8000` hop is likely blocked by ClusterIP+DNS. **Must be confirmed by the probe.** |
| **Other modules** (`module-filesearch:9004`, `module-registry:9007`) | ⛔ unreachable | No egress rule for them + ClusterIP + DNS. The per-tier "modules gateway" that would bridge this was reverted (`docs/specs/sandbox-modules-gateway-proposal.md`). |

### Bottom line (expected)

- **Gitea:** answered — **no** direct access; bridged host-side. Working (that's
  what the E2E push test proves).
- **Internet:** answered — **yes** over HTTPS.
- **LLM:** **open** — allowed by NetworkPolicy but probably not actually
  reachable from a gVisor pod; needs the probe to confirm.
- **Modules:** answered — **no** path today.

---

## Observed (fill in after running)

> _Run date:_ `TODO`
> _Cluster / instance:_ `TODO`
> _Sandbox image tag:_ `TODO`

```
<paste scripts/sandbox_network_probe.sh output here>
```

### Conclusion

> _Fill in once observed:_ Does the observed behaviour match "Expected"? Any
> surprises (e.g. LLM reachable, or internet blocked)? If LLM is unreachable and
> agents need it from the sandbox, that becomes a follow-up (mirror the
> host-side pattern, or revisit the gateway proposal).
</content>
