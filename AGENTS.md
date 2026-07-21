# CLAUDE.md

Guidance for AI coding assistants working in this repository.

## Where you are running: the branch-environment workspace

You are (almost always) running **inside a per-branch developer workspace pod**
in the Kubernetes cluster — namespace `druppie-<slug>`, built from
`Dockerfile.dev-workspace` and seeded from this repo. What this means for you:

- **This repo is checked out at `/workspace/druppie`** (default branch:
  `colab-dev`). `/workspace` is a PVC that may also hold sibling checkouts of
  `ai/k8s` and `systeembeheer/rancher-gitops`.
- **Everything is hot-reload.** The backend runs under `uvicorn --reload`
  (:8000) and the frontend under Vite HMR (:5173). Just edit files on the
  checkout — the running services pick the change up automatically. You do
  **not** need to restart anything to see local edits.
- **`kubectl` is available**, wired in from a **read-only** kubeconfig. Use it
  to inspect the cluster and your branch environment; do not expect write
  access to production resources.
- Editor is code-server (:8080) opened on `/workspace`; an XFCE/noVNC desktop
  is on :6080. Auth is handled by the oauth2-proxy sidecar.

## Repos & Responsibilities (3 Gitea repos)

All three live on `aigit.waterschap.org`. You have **push** access to two of
them; the third is read-only.

| Repo | Gitea URL | Push? | Purpose |
|------|-----------|-------|---------|
| `ai/druppie` | `aigit.waterschap.org/ai/druppie` | ✅ **yes** | Application code + Helm chart (`helm/druppie/`) + CI workflow (`.gitea/workflows/build.yaml`) + this dev-workspace image |
| `ai/k8s` | `aigit.waterschap.org/ai/k8s` | ✅ **yes** | GitOps: HelmReleases, infra (Harbor, Gitea Runner, GPU), ExternalSecrets, FluxCD kustomizations |
| `systeembeheer/rancher-gitops` | `aigit.waterschap.org/systeembeheer/rancher-gitops` | ❌ **no** | Base infra: RKE2, Cilium, Traefik, cert-manager, Longhorn, FluxCD itself. Read-only context (view online); **never change** — the Infra team owns this. If changes are needed, tell me. |

### How they connect (CI/CD — a push rebuilds everything)

```
ai/druppie push → Gitea Actions CI (.gitea/workflows/build.yaml, runs on
                  every branch) → builds images → pushes to Harbor
                → updates imageTag in ai/k8s HelmRelease
ai/k8s push     → FluxCD detects change → Helm upgrade → pods restart
```

FluxCD watches the `ai/k8s` main branch every ~5 min, applies everything under
`clusters/ka-k8s-ai/`, and prunes removed objects. The chart source for
HelmReleases comes from `ai/druppie` (FluxCD GitRepository `ai-druppie`).

**Consequence:** every `git push` triggers a full rebuild + redeploy through
the pipeline. Push deliberately — it is not a substitute for the local
hot-reload loop above.

## Pushing to Gitea

The Gitea remotes are **reachable directly from the workspace pod** — no WSL
relay, no `NO_PROXY` workaround. Credentials/tokens are baked into the remote
URLs or `~/.git-credentials`, so no password prompts.

```bash
git push origin colab-dev   # ai/druppie
git push origin main        # ai/k8s
```

> Never push to `systeembeheer/rancher-gitops` — read-only, Infra-owned.

> Historical note: earlier docs described a WSL + `gsa-relay.ps1` Windows proxy
> relay with a `NO_PROXY` gotcha. That was for developing from WSL on a laptop.
> Inside the branch-environment pod it no longer applies.
