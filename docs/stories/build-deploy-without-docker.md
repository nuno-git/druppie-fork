# Refinement & Implementation Plan: Build & Deploy Without Docker Daemon

> **Branch:** `feature/k8s-native-build-deploy` (branched from `colab-dev` in `ai/druppie`)
> **Status:** IMPLEMENTED locally (uncommitted) — Phases 0–4 coded; build mechanism superseded (see below); cluster validation blocked on Longhorn outage
> **Type:** Refinement + Implementation Plan
> **Spans two repos:** `ai/druppie` (app/chart/template/MCP) **and** `ai/k8s` (GitOps footprint)
> **Related:** [ADR-KUBERNETES.md](../ADR-KUBERNETES.md) §"Out of Scope (Phase 2)", [dev-environment-architecture.md](../dev-environment-architecture.md) v2, [BACKLOG.md](../BACKLOG.md) §"Kubernetes Phase 2"
> **Last updated:** 2026-07-30

> **⚠️ SUPERSEDING DECISION (2026-07-30): build now runs as a git-driven kaniko Job, NOT the DinD Actions runner.**
> The original plan (D2/§3) mandated building on the shared DinD Gitea-Actions
> runner and said "No Kaniko". During implementation the runner proved unusable
> for a k8s-native build: a `docker://` executor needs a Docker daemon (absent on
> containerd), and kaniko can't run under a host executor (it owns `/` and would
> corrupt the persistent runner FS). **Resolution:** module-deploy commits a
> daemonless **kaniko Job** (plus its build namespace + Harbor-push/git-auth
> ExternalSecrets) to `ai/k8s`; **Flux creates it**; module-deploy only polls
> status. This keeps the GitOps invariant intact (module-deploy stays read-only —
> no imperative cluster writes) and the internal Actions runner is disabled
> (`internalRunner.enabled=false`), the app template's `build.yaml` kept but
> neutered. See **§3 "Superseded build mechanism"** below and
> `module-deploy/v1/k8s_deploy.py`. Everything else in this doc (GitOps footprint,
> per-app namespace, teardown/prune, health gate, storage class, §5.1 token
> hardening) stands.

> **Implementation status (2026-07-30, local — nothing pushed):**
> - ✅ Phase 0a — `ai/k8s` `user-apps` Flux Kustomization (`clusters/ka-k8s-ai/infra/user-apps/user-apps-kustomization.yaml`) + machine-managed `clusters/user-apps/` dir
> - ✅ Phase 1 — app template ships a Helm chart (`chart/`) + per-app CI (`.gitea/workflows/build.yaml`, now **disabled/reference-only**); `docker-compose.yaml` removed; template Dockerfile/SDK made buildable (`druppie-sdk` optional). `helm lint`+`template` green.
> - ✅ Phase 2/3 — `module-deploy/v1/k8s_deploy.py`: GitOps commit (namespace+gitrepository+helmrelease) **+ git-driven kaniko build Job** (build ns + ESOs + Job committed, Flux creates, module-deploy polls), Flux rollout wait, 300s ingress health-gate, teardown incl. build/, read-only logs/list/inspect. `tools.py` dispatch rewired; `httpx` added.
> - ✅ Phase 4 — socket mount + `docker-installer` forced off in K8s mode (AC7); module-deploy GitOps env + **read-only** RBAC (jobs/externalsecrets get+list); `deployer.yaml` prompt rewritten for GitOps; unit tests green.
> - ⏳ **Not done:** live cluster validation (blocked — Longhorn down on `ka-k8s-ai`, see §8); ADR/BACKLOG status bump (on merge). *(TLS needs no new cert — `<slug>-apps.rijnland.dev` is a single label, covered by the existing `*.rijnland.dev` wildcard.)*


---

## 1. User Story (original, verbatim)

> Het bouwen en uitrollen van applicaties vanuit Druppie werkt momenteel **niet**
> op het RKE2-cluster. Het huidige proces is gebouwd rond een Docker daemon
> (`docker build` / `docker run` / `docker compose`) die op dit cluster (containerd)
> niet bestaat. Dit moet werken op Kubernetes — zónder afhankelijkheid van Docker.

**Acceptatiecriteria (origineel):**

- [ ] Het bouwen en deployen van een applicatie werkt end-to-end op het RKE2-cluster, zonder Docker daemon.
- [ ] Gebouwde images landen in Harbor en zijn bruikbaar vanuit het cluster.
- [ ] Een uitgerolde applicatie is bereikbaar via een cluster-URL (`*.rijnland.dev`) en wordt healthy.
- [ ] Er is een applicatie-template/startpunt die agents (of het proces) kunnen gebruiken.
- [ ] Alle afhankelijkheden van de Docker daemon / docker-compose zijn verwijderd.

---

## 2. Refined User Story

**Als** Druppie-gebruiker (developer rol)
**wil ik** dat een door Druppie gegenereerde applicatie end-to-end bouwt en uitrolt op het RKE2-cluster via dezelfde CI + GitOps-pipeline als Druppie zelf,
**zodat** er geen Docker daemon op het cluster nodig is, apps bereikbaar zijn op een stabiele `*-apps.rijnland.dev` URL, en elke deployment traceerbaar + drift-bestendig is in git.

### Refined Acceptance Criteria

| # | Criterium | Verifieerbaar door | Status |
|---|-----------|--------------------|--------|
| AC1 | De app-template levert een **eigen Helm chart** (`chart/`: Deployment, Service, Ingress, PVC, ExternalSecret) **en een eigen Gitea Actions CI workflow** — **zonder** `docker-compose.yaml` | `templates/project/chart/Chart.yaml` + `templates/project/.gitea/workflows/build.yaml` aanwezig; geen compose | ☐ |
| AC2 | Build via de **per-app Gitea Actions CI** (gedeelde DinD runner) → image in Harbor project `druppie`; tag = `<branch>-<ts>-<sha>` | Gitea Actions run `success`; image in Harbor UI | ☐ |
| AC3 | Deploy commit een `GitRepository`+`HelmRelease` naar `ai/k8s`; **Flux** trekt de chart uit het app-repo en rolt hem uit | `kubectl get hr -n <app>` → `Ready` | ☐ |
| AC4 | De app draait met **peristente volumes** (Postgres-data overleeft pod-restart) via chart-PVC | `kubectl delete pod` → data nog aanwezig | ☐ |
| AC5 | De app is bereikbaar op een **`<app>-apps.rijnland.dev` URL** (Ingress uit de chart) en wordt **healthy binnen 300s** | `curl https://<app>-apps.rijnland.dev/health` → `200` | ☐ |
| AC6 | **Teardown** = subdir uit `ai/k8s` verwijderen → `prune:true` verwijdert de per-app namespace + alles erin | `kubectl get ns <app>` weg na reconcile | ☐ |
| AC7 | `DRUPPIE_SANDBOX_MODE=k8s` vereist **geen** `/var/run/docker.sock` mount en geen `docker-installer` DaemonSet | `kubectl get ds` (geen docker-installer); geen socket-mount op prod waardes | ☐ |
| AC8 | Frontend "Projects"/"Deployments" tonen K8s-apps (HelmRelease-gebaseerd) met status/URL/logs | UI toont `Ready` + `*-apps.rijnland.dev` URL | ☐ |

### Out of Scope

- **Coding-sandbox migratie** (`module-coding` / gVisor) — al volledig geïmplementeerd via `k8s_sandbox.py` + agent-sandbox CRD.
- **CI/CD voor Druppie's ÉIGEN 13 images** (het bouwen van Druppie zelf) — apart backlog-item. (De per-app CI workflow voor user-apps is wél in scope — zie D2.)
- Multi-replica/HA voor user-apps, autoscaling, per-app Network Policies, Harbor image scanning/signing.

### Definition of Done

- [ ] AC1–AC8 groen op `colab-dev` (dev-cluster) én gedemonstreerd op `ka-k8s-ai`.
- [ ] Cross-repo: `ai/druppie` (template + chart + CI workflow + module-deploy) **en** `ai/k8s` (`user-apps` kustomization) geleverd.
- [ ] Socket-mount + `docker-installer` DaemonSet gated-off voor K8s-mode; lokale dev (`docker`) blijft werken.
- [ ] Deployer-agent prompt bijgewerkt voor GitOps/Helm/CI-realiteit.
- [ ] Tests voor CI-dispatch/-poll-pad + GitOps-commit-pad.
- [ ] ADR + dev-environment-architecture status bijgewerkt.

---

## 3. Architecture Decision (the core of this story)

**Druppie's user apps deploy exactly like Druppie deploys itself:** a Helm chart lives in the app's
own repo; a `GitRepository` + `HelmRelease` in `ai/k8s` points at it; Flux reconciles; and each app
repo ships its **own Gitea Actions CI** that builds → pushes Harbor → bumps the `imageTag`. Full
symmetry with Druppie's own pipeline (`.gitea/workflows/build.yaml`).

```
   ai/<app>  (generated app repo)                  ai/k8s  (GitOps — the only thing Flux watches)
   ┌────────────────────────────────────┐         ┌─────────────────────────────────────────────┐
   │ Dockerfile        (build contract) │         │ clusters/ka-k8s-ai/infra/user-apps/         │
   │ chart/            (deploy contract)│         │   user-apps-kustomization.yaml              │ ◀─ one-time bootstrap
   │ .gitea/workflows/ ◀── CI pipeline  │         │   (Flux Kustomization, path=./clusters/      │   (prune:true, isolated)
   │   build.yaml                       │         │    user-apps, prune:true)                   │
   │ app/ frontend/     (code)          │         │ ...                                         │
   └──────────────┬─────────────────────┘         │ clusters/user-apps/<app-slug>/  ◀ MACHINE-   │
                  │                                 │   gitrepository.yaml  ─┐                    │
                  │ ① push / workflow_dispatch      │   helmrelease.yaml    ─┤ per-app namespace  │
                  ▼                                 │   externalsecrets.yaml ┘ (committed by       │
        Gitea Actions (shared DinD runner):         │                         module-deploy)     │
          docker build → harbor…/druppie/<app>:<tag>└──────────────┬──────────────────────────────┘
          CI bumps imageTag in ai/k8s HelmRelease ──────────────────▶
                                                                   │
                                                    ② Flux reconciles:
                                                       pulls chart from ai/<app> ─► Helm install
                                                       Ingress <app>-apps.rijnland.dev, PVC, ExternalSecret
                                                                   │
   module-deploy (Druppie backend) ────────────────────────────────┘ ③ health-gate polls
     • create_project: scaffold repo (incl. chart + workflow) +          https://<app>-apps.rijnland.dev/health (300s)
       provision Harbor creds/Gitea API
     • deploy: commit the ai/k8s footprint, dispatch build, watch rollout
```

**Why this design (and not direct `kubectl apply`):**
- **GitOps invariant** — AGENTS.md: *"FluxCD will revert manual `kubectl apply` changes."* Committing to `ai/k8s` is the only durable path.
- **Audit + drift correction** — every user-app deployment is a git commit; Flux self-heals drift.
- **Symmetry** — identical mechanism to Druppie's own prod/dev/branch-env deploys. Reuses the **proven `branch-envs` machine-managed Kustomization pattern** (`clusters/ka-k8s-ai/infra/branch-envs/branch-envs-kustomization.yaml`).
- **No docker.sock in the backend** — `module-deploy` never runs Docker; both deploy AND build go through git → Flux.
- **Eliminates the hardest risk** — no compose→K8s translator; the app ships a real Helm chart.

### Superseded build mechanism (2026-07-30): git-driven kaniko Job

> This replaces the original D2/G1/G2 (build on the shared DinD Actions runner).
> The historical text is kept below with ~~strikethrough-in-prose~~ notes for the
> audit trail; the current behaviour is what this subsection describes.

**What changed.** The build no longer runs on a Gitea Actions runner. Instead
`module-deploy` commits — into `clusters/user-apps/<slug>/build/` — a per-app
**build namespace**, a **Harbor-push ExternalSecret** (dockerconfigjson from Vault
`ci/harbor`, the `druppie-ci` robot), a **git-auth ExternalSecret** (clone token
from Vault `ci/gitea`), and a **kaniko Job** (`job.yaml`, whose object name carries
the image tag). Flux creates all four; `module-deploy` only polls status
(namespace exists → ExternalSecrets Ready → Job succeeded), then commits the app
HelmRelease pinned to the exact tag kaniko just pushed.

**Why kaniko-Job-via-git and not the DinD runner:**
- The DinD runner can't build k8s-natively here: a `docker://` executor needs a
  Docker daemon (absent on containerd), and kaniko can't run *under* a host
  executor — kaniko takes over `/` to extract the base image and would corrupt
  the runner's persistent filesystem. kaniko must run in **its own pod**.
- Committing the Job to git (rather than `kubectl create`-ing it) keeps
  `module-deploy` **read-only** — the branch-env invariant the whole design rests
  on. No imperative cluster writes; Flux owns the Job's lifecycle and prunes a
  superseded Job when a new tag is committed (Job names carry the tag).
- kaniko is **daemonless** and runs unprivileged (no `privileged`, no extra caps),
  so the build namespace gets `pod-security.kubernetes.io/enforce: baseline` —
  deliberately NOT the `privileged` profile the old DinD runner namespace needed.

**Ordering / safety.** Build infra is committed first and gated on the namespace
existing + both ExternalSecrets reporting `Ready` (a fast, clear failure if Vault
is missing a declared key) *before* the Job manifest is committed, so the kaniko
pod never starts against an unsynced secret. The git token is mounted ONLY into
the clone init-container, never the kaniko container that runs the untrusted
Dockerfile. §5.1's token-hardening backlog still applies.

**Retired pieces.** The in-cluster Actions runner is disabled
(`internalRunner.enabled=false`); the app template's `.gitea/workflows/build.yaml`
is kept but neutered to `workflow_dispatch`-only as reference/fallback.

### Precedent we copy verbatim

The existing `branch-envs` flow is the template. Concretely (`ai/k8s`):

`clusters/ka-k8s-ai/infra/branch-envs/branch-envs-kustomization.yaml` — separate Kustomization, `prune: true`, machine-managed, isolated so a bad commit can't block prod:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: branch-envs
  namespace: flux-system
spec:
  interval: 1m
  path: ./clusters/branch-envs
  prune: true
  sourceRef: { kind: GitRepository, name: ai-k8s, namespace: flux-system }
```

`clusters/branch-envs/<env>/gitrepository.yaml` + `helmrelease.yaml` — one dir per deployed thing; Druppie commits via Gitea API, deletes on teardown. We replicate this 1:1 for `clusters/user-apps/<app-slug>/`.

### ⚠️ Critical read: what to copy vs what to rethink

`branch-envs` is **not 100% working yet**. The user's read — *"probably not a Flux/CI-CD issue"* — is confirmed by the evidence below. So we copy the GitOps mechanism, but design around its known breakages.

| Area | Status | Copy? | Implication for user-apps |
|------|--------|-------|---------------------------|
| **Flux commit→reconcile loop** | ✅ Reliable (listed under *"wat al werkt"* in `dev-envs.md.txt`) | ✅ **Copy** | Core of D4/D5 is sound |
| **Longhorn storage** | ❌ **Down today** (`docs/infra-longhorn-issue.md`, 2026-07-16): rebuild wiped `longhorn-distributed` SC, nodes `Ready=False`, volumes faulted | 🚫 **Rethink** | AC4 **blocked on infra**. User-app PVCs must use `longhorn-local` (Delete) — see D6 |
| **Orphan-volume trap** | ❌ Ephemeral ns + Retain-policy SC leaked ~135 orphaned volumes → `storageScheduled` exhausted (`docs/longhorn-storage-issue.md`) | 🚫 **Avoid** | Same risk for user-apps (also ephemeral). `Delete`-reclaim class is mandatory |
| **ESO sync race** | ⚠️ `fix(init-job): wait for ESO sync before creating workspace client` | ⚠️ **Gate** | Chart's DB ExternalSecret can race the app Deployment — must wait for `Synced` |
| **imageTag auto-resolve** | ⚠️ Was empty → `ImagePullBackOff` (`fix(branch-env): use correct HR name`) | ✅ **Avoided by design** | The per-app CI sets the exact tag it just built; no parent-HR auto-resolve |
| **Node pinning** | ⚠️ Stale node pin blocked all branch-env deploys (`fix: remove stale node pinning`) | 🚫 **Don't pin** | User-app chart must not hardcode `nodeSelector`/affinity to specific nodes |
| **Traefik LB** | ⚠️ `SyncLoadBalancerFailed: no address pools` (infra outage) | — (infra) | AC5 reachability depends on Traefik being healthy |
| **CI_GIT_TOKEN blast radius** | ⚠️ Druppie's own CI note (`.gitea/workflows/build.yaml:216`) admits the token is exfiltrable from feature branches | 🚫 **Amplified** | User apps run AI-generated/untrusted code → see **§5.1** |
| **Keycloak ↔ dynamic backend** | ❌ Open problem A — not wired for dynamically started backends | 🛑 **Out of scope** | Only if user-apps need Druppie's OIDC; base template stays auth-agnostic |
| **Hot reload** | ❌ docker-compose only, not K8s (open problem B) | 🛑 **Out of scope** | User-apps ship built images, not hot-reload — separate story |

**Net:** the *GitOps plumbing* is the reliable spine. The *storage layer* is both today's outage and a design trap we avoid by class choice. ESO timing we handle explicitly. The *CI token* is a new security fork (§5.1).

---

## 4. Current State (Research Findings)

### 4.1 Where the Docker dependency lives

| Component | File | What it does |
|-----------|------|--------------|
| **Socket mount** | `helm/druppie/templates/{module-deploy,module-coding,backend}-deployment.yaml` | Mounts `/var/run/docker.sock` (hostPath), gated by `.Values.backend.dockerSocket.enabled` |
| **DaemonSet** | `helm/druppie/templates/docker-installer-daemonset.yaml` | Installs Docker Engine on every `pool=app` node via `nsenter` (privileged) — self-described *"Phase 1 workaround"* |
| **Mode toggle** | `helm/druppie/templates/configmap.yaml:85` | `DRUPPIE_SANDBOX_MODE: docker` \| `k8s` (driven by `agentSandbox.enabled`) |
| **Docker tools** | `druppie/mcp-servers/module-deploy/v1/tools.py` (~1565 lines) | `build`, `run`, `compose_up`, `compose_down`, `logs`, … — each dispatches on `DEPLOY_MODE` |

### 4.2 Current build→deploy flow (Docker mode)

```
orchestrator → tool_executor → mcp_http → module-deploy:9002
  → tools.compose_up()  (tools.py:663)
      git clone gitea repo
      write docker-compose.override.yaml (ownership labels + DOCKER_NETWORK)
      docker compose up -d --build
      poll docker inspect {{.State.Health.Status}} up to 300s
```

The deploy contract today is **`templates/project/docker-compose.yaml`** (app + `pgvector/pgvector:pg16`), authored into every new Gitea repo by `create_project` (`agents/builtin_tools.py:418` → `core/gitea.py:519`). **It is docker-compose only — no Helm chart, no CI workflow, no Traefik/Ingress.** This is the gap AC1 closes.

### 4.3 What is ALREADY done (infra + partial code)

Prior architecture decision (dev-environment-architecture.md v2): gVisor + agent-sandbox CRD + dual-mode dispatch. Infra already live on `ka-k8s-ai`: gVisor on 4 nodes, agent-sandbox controller v0.5.0, 4 CRDs, PriorityClasses/Quotas. *(The v2 doc said "Kaniko for builds"; we supersede that with the existing DinD runner — parity with Druppie's own CI, no new build component.)*

Partial code on `colab-dev`:

| File | State | After this story |
|------|-------|------------------|
| `druppie/core/k8s_sandbox.py` | ✅ Complete (coding-sandbox reference) | untouched |
| `druppie/mcp-servers/module-coding/v1/tools.py` | ✅ Dual-mode done | untouched |
| `druppie/mcp-servers/module-deploy/v1/k8s_deploy.py` (490 lines) | ⚠️ Partial, **wrong direction** (imperative K8s API + Kaniko) | **rewritten** to: CI dispatch/watch + GitOps commit (no Kaniko) |
| `druppie/mcp-servers/module-deploy/v1/tools.py` | ⚠️ Partial dispatch | route `compose_up/down/build` → CI + GitOps path |
| `helm/druppie/templates/agent-sandbox/` | ✅ SandboxTemplate for coding; ❌ none for module-deploy | (not needed — GitOps replaces it) |
| `templates/project/` | docker-compose only | **ship chart + CI workflow, drop compose** |

### 4.4 Gaps → how the design resolves them

| Gap (old) | Resolution |
|-----------|------------|
| G1 Kaniko doesn't wait / stream logs | **GONE** — no Kaniko; build runs in the existing DinD runner via per-app CI (D2) |
| G2 No Harbor push secret | **GONE** — CI uses Harbor creds from repo/org secrets (D3) |
| G3 compose→K8s translator drops PVCs/depends_on | **GONE** — app ships a real chart; no translator |
| G4 health-check one-shot | **Fix** — poll `<app>-apps.rijnland.dev/health` to 300s |
| G5 `inspect`/`exec`/`volumes` have no K8s equiv | **Reduce** — most become "read HelmRelease/pods" (read-only) |
| G6 no Ingress/`*.rijnland.dev` | **GONE** — chart renders Ingress; host from HelmRelease values |
| G7 deployer prompt Docker-worded | **Fix** — rewrite for GitOps/Helm/CI |

---

## 5. Design Decisions (your choices applied)

- **D1 — Template ships a per-app Helm chart + CI workflow, drops compose.** `templates/project/chart/` (Chart.yaml, values.yaml, templates: Deployment, Service, Ingress, PVC, ExternalSecret) **and** `templates/project/.gitea/workflows/build.yaml`. `docker-compose.yaml` removed. *(AC1)*
- **D2 — Build = per-app Gitea Actions CI (not Kaniko).** ⚠️ **SUPERSEDED 2026-07-30 — see §3 "Superseded build mechanism".** Build now runs as a git-driven **kaniko Job** (module-deploy commits build ns + ESOs + Job to `ai/k8s`, Flux creates them, module-deploy polls); the DinD Actions runner is disabled. Tag scheme (`<branch>-<ts>-<sha>`) and Harbor destination are unchanged. *Original plan:* the template workflow (trimmed copy of Druppie's own) had the shared DinD runner `docker build` → push → bump `imageTag`. *(AC2)*
- **D3 — Credentials.** Push: Harbor robot creds (`HARBOR_USERNAME/PASSWORD`) provisioned into each app repo by `create_project` via the Gitea API (or org-level secrets). Pull: deployed Deployments get `imagePullSecrets: harbor-regcred`. *(AC2)*
- **D4 — Deploy = GitOps commit to `ai/k8s`.** `module-deploy` commits `clusters/user-apps/<app-slug>/{gitrepository,helmrelease}.yaml` via the Gitea API (same code path `branch_environment_service.py:870` already uses). `HelmRelease.values` sets `imageTag`, ingress `host`, DB secret ref. Flux reconciles. **No `kubectl apply`.** *(AC3)*
- **D5 — Per-app namespace + a `user-apps` Kustomization.** Each app gets its **own namespace** (clean teardown/isolation, matches branch-env precedent); a separate Flux Kustomization watches `./clusters/user-apps`, `prune:true`, machine-managed, isolated from prod. One-time infra commit. *(AC3, AC6)*
- **D6 — PVC from the chart using `longhorn-local` (Delete, 1 replica).** User-apps are ephemeral (teardown = namespace delete) → **same orphan-volume risk** as branch-envs. `Delete`-reclaim class is **mandatory** — `longhorn-distributed` (Retain) leaked ~135 orphaned volumes and exhausted scheduling (`docs/longhorn-storage-issue.md`). *(AC4)*
- **D7 — Reachability via chart Ingress on `<app>-apps.rijnland.dev`** — a single DNS label, so covered by the **existing `*.rijnland.dev` wildcard cert** (secret `druppie-tls`, mirrored into each app namespace via the cluster-wide `druppie-tls-mirror` store). No new cert. *(AC5)*
- **D8 — Health gate** polls the Ingress URL to 300s (parity with the Docker path's helper). *(AC5)*
- **D9 — Teardown = delete the `ai/k8s` subdir**; `prune:true` removes the per-app namespace + all resources (and `Delete`-reclaim PVCs auto-cleanup — no orphans). *(AC6)*
- **D10 — Prod drops the Docker dependency; local dev keeps it.** `dockerSocket.enabled` + `docker-installer` DaemonSet emit only when `agentSandbox.enabled=false`. Local `DRUPPIE_SANDBOX_MODE=docker` still works. *(AC7)*
- **D11 — ESO-sync gating.** The chart's DB `ExternalSecret` must be `Synced` before the app Deployment starts (init-container or ESO `target` readiness), avoiding the race that hit branch-envs (`fix(init-job): wait for ESO sync`). *(AC5)*

### 5.1 Security: the `CI_GIT_TOKEN` — **Option A chosen**

Druppie's own CI bumps `imageTag` by cloning `ai/k8s` with `CI_GIT_TOKEN` (`.gitea/workflows/build.yaml:215-289`). The in-file note admits: on push events the workflow runs from the *pushed branch*, so anyone with push rights can exfiltrate `CI_GIT_TOKEN` (full write to `ai/k8s`). **For user apps this is amplified** — the code is AI-generated and runs untrusted logic in CI.

**Decision: Option A — mirror Druppie.** Each app CI gets a `CI_GIT_TOKEN` and bumps its own HelmRelease in `ai/k8s`, exactly like Druppie's own CI. Chosen for simplicity + symmetry. Accepted trade-off: an app branch *can* in principle push to `ai/k8s`. To make this safe, this hardening is **required** (tracked in Phase 2):

- [ ] **Scoped robot account** — dedicated Gitea robot with **write to `ai/k8s` only** (no admin, no other repos), reused across app CIs.
- [ ] **Gitea "environments"** — tie `CI_GIT_TOKEN` + Harbor secrets to deploy branches (`main`/deploy env) so feature-branch workflows **cannot reference them** (the durable fix Druppie's own note at `build.yaml:216-224` recommends).
- [ ] **Branch protection** on `.gitea/workflows/build.yaml` in every app repo (no direct edit on protected branches).
- [ ] **Path convention** — app CIs only ever write `clusters/user-apps/<own-slug>/helmrelease.yaml`; enforced by convention + review. (If insufficient, revisit Option B — the Harbor-webhook path — where the token lives only in Druppie's backend.)

> Safety valve: if the hardening proves inadequate or an incident occurs, switch to **Option B** (app CI builds+pushes Harbor only; Druppie backend updates the tag via `registry_webhook.py`).

### Decisions confirmed (were open questions)

1. ✅ **Hostname** → `<app>-apps.rijnland.dev` (single label — uses the existing `*.rijnland.dev` cert, no new cert). *(D7)*
2. ✅ **Namespace** → per-app namespace (matches branch-env precedent). *(D5)*
3. ✅ **Build** → per-app Gitea Actions CI/CD pipeline (build + push + bump imageTag), mirroring Druppie's own `.gitea/workflows/build.yaml`. *(D2)*
4. ✅ **CI→GitOps write** → **Option A**: each app CI bumps its own HelmRelease with a scoped `CI_GIT_TOKEN` (with mandatory hardening, §5.1).

---

## 6. Implementation Plan (phased, cross-repo)

> **Nothing below is executed yet.** Each phase ends with a 🛑 review checkpoint.
> I will not start Phase 1 until you approve this plan.

### Phase 0 — Scaffolding & bootstrap  *(no behavior change)*
**ai/druppie:** test scaffold for `k8s_deploy.py` (mock Gitea + kubernetes clients).
**ai/k8s:** add `clusters/ka-k8s-ai/infra/user-apps/user-apps-kustomization.yaml` (copy of `branch-envs-kustomization.yaml` → `path: ./clusters/user-apps`, `prune: true`). Create empty `clusters/user-apps/.gitkeep`.
🛑 **Review checkpoint**

### Phase 1 — Template: chart + CI workflow  *(AC1)*
**ai/druppie:** replace `templates/project/docker-compose.yaml` with:
- `templates/project/chart/` — `Chart.yaml`, `values.yaml` (defaults: image, port 8000, `/health`, pgvector); `templates/{deployment,service,ingress,pvc,externalsecret}.yaml` (**PVC storageClass `longhorn-local`**, no node pinning, ESO-sync gating D11)
- `templates/project/.gitea/workflows/build.yaml` — trimmed from Druppie's own: build 1 image → Harbor → bump imageTag in `clusters/user-apps/<slug>/helmrelease.yaml` (per §5.1 choice). Triggers: `on: push` + `workflow_dispatch`
- `helm lint` + `helm template` green; workflow `act`-dry or syntax-check
🛑 **Review checkpoint**

### Phase 2 — Build dispatch, credentials & CI hardening  *(AC2, D3, §5.1-A)*
**ai/druppie:** `create_project` provisions `HARBOR_USERNAME`, `HARBOR_PASSWORD`, and the scoped `CI_GIT_TOKEN` into each new app repo via the Gitea API (tied to a deploy-branch "environment"). The app CI workflow (Phase 1) builds → pushes Harbor → bumps its own `imageTag` in `ai/k8s` (Option A). In `k8s_deploy.py` implement build-dispatch (`workflow_dispatch`) + run-poll (status/logs) via the Gitea API. Land the §5.1-A hardening (scoped robot account, Gitea environments, branch protection).
🛑 **Review checkpoint**

### Phase 3 — GitOps deploy path  *(AC3, AC4, AC5, AC6)*
**ai/druppie** (`k8s_deploy.py`): `k8s_compose_up` → commit `gitrepository.yaml` + `helmrelease.yaml` to `ai/k8s` `clusters/user-apps/<app-slug>/` (per-app namespace) via Gitea API (reuse `branch_environment_service` helpers). `k8s_compose_down` → delete the subdir. 300s health-gate polling the Ingress URL. End-to-end: `create_project` → push → CI build → deploy → `https://<app>-apps.rijnland.dev/health` 200; DB survives pod delete.
> 🔴 **Dependency:** full AC4/AC5 validation requires Longhorn + Traefik healthy on `ka-k8s-ai` (the existing `*.rijnland.dev` cert is already present). GitOps-commit logic (AC3/AC6) is developable independently of the storage outage.
🛑 **Review checkpoint**

### Phase 4 — Remaining tools, agent, frontend, prod gating  *(AC7, AC8)*
**ai/druppie:** K8s `logs`/`list_containers`/`stop` read HelmRelease+pods; stub `inspect`/`exec`/`volumes` with clear errors. Rewrite `deployer.yaml` prompt (GitOps/Helm/CI/URL/health). Update frontend `Projects`/`Deployments` to show HelmRelease status + `*-apps.rijnland.dev` URL. Gate `dockerSocket` + `docker-installer` off when `agentSandbox.enabled`. Update ADR + dev-environment-architecture status; move BACKLOG item to done.
🛑 **Final review → PR(s) to `colab-dev` (druppie) and `main` (ai/k8s)**

---

## 7. Key Files

### `ai/druppie` (this branch)
| Concern | Path |
|---------|------|
| App template (deploy + build contract) | `druppie/templates/project/chart/` + `druppie/templates/project/.gitea/workflows/build.yaml` (new) — drop `docker-compose.yaml` |
| Docker MCP dispatch | `druppie/mcp-servers/module-deploy/v1/tools.py` |
| K8s impl (CI dispatch + GitOps) | `druppie/mcp-servers/module-deploy/v1/k8s_deploy.py` |
| Project scaffolding | `druppie/agents/builtin_tools.py:418` (`create_project`), `druppie/core/gitea.py` (repo + secret provisioning) |
| GitOps commit helper (reuse) | `druppie/services/branch_environment_service.py:870` |
| Harbor webhook (fallback for §5.1-B) | `druppie/api/routes/registry_webhook.py`, `druppie/services/deploy_service.py` (only if A is revisited) |
| Mode toggle | `helm/druppie/templates/configmap.yaml:85` |
| Socket mounts / DaemonSet (gate off) | `helm/druppie/templates/{module-deploy,module-coding,backend}-deployment.yaml`, `docker-installer-daemonset.yaml` |
| Deployer agent prompt | `druppie/agents/definitions/coding/project/deployer.yaml` |
| Frontend | `frontend/src/pages/{Projects,Platform}.jsx`, `frontend/src/services/api.js` |
| Reference CI (copy from) | `.gitea/workflows/build.yaml` (Druppie's own) |

### `ai/k8s` (separate branch → `main`)
| Concern | Path |
|---------|------|
| Flux Kustomization (bootstrap) | `clusters/ka-k8s-ai/infra/user-apps/user-apps-kustomization.yaml` (new) |
| Machine-managed per-app dirs | `clusters/user-apps/<app-slug>/{gitrepository,helmrelease}.yaml` (committed by Druppie) |
| Existing precedent | `clusters/ka-k8s-ai/infra/branch-envs/branch-envs-kustomization.yaml`, `clusters/branch-envs/<env>/` |

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **CI_GIT_TOKEN exfiltration** (untrusted AI code in app branches) | 🔴 High | §5.1-A hardening: scoped robot (ai/k8s-write only), Gitea environments tied to deploy branches, branch protection on workflow files; safety-valve → Option B |
| **Longhorn currently down on `ka-k8s-ai`** (infra rebuild, 2026-07-16) | 🔴 External blocker | AC4 can't validate until infra re-registers Longhorn SCs/nodes. Dev-track on `colab-dev`; flag to Infra. SC choice (D6) is independent of this outage |
| **Orphan-volume accumulation** (ephemeral ns + Retain SC) | High | Mandatory `longhorn-local` (Delete, 1 replica) for all user-app PVCs (D6) |
| **ESO sync race** | Medium | Chart gates app start on ExternalSecret `Synced` (D11) |
| DinD runner cold builds slow | Low | Runner has 50Gi layer-cache PVC (cached build ~30s); accept slower first build |
| Flux `GitRepository` auth to **user app repos** | Medium | Reuse `flux-git-auth` secret; verify it can read arbitrary `ai/*` app repos |
| **Traefik LB health** (`SyncLoadBalancerFailed` seen in outage) | Medium | AC5 depends on Traefik; verify LB/address-pool before Ingress validation |
| Per-app namespace sprawl / leaked namespaces | Medium | `prune:true` + reuse `branch_environment_service` teardown; orphan reaper job |
| Removing socket-mount breaks something in prod | Medium | Gate by `agentSandbox.enabled`; keep Docker for local dev; dry-run on dev cluster |
| Chart features an app needs that the template doesn't cover | Medium | Ship a minimal-but-complete chart; iterate; agents edit the chart in-repo |

### External dependencies / blockers
- **Infra team (rancher-gitops):** Longhorn must be healthy (`longhorn-distributed`/`longhorn-local` SCs applied, nodes `Ready`, `longhorn-local` present) before AC4/AC5 fully validate. Not in our control — track separately.
- **TLS:** no new cert — `<slug>-apps.rijnland.dev` is covered by the existing `*.rijnland.dev` wildcard (`druppie-tls`, mirrored via the `druppie-tls-mirror` store).
- **Traefik LB:** must be healthy (address pools configured) for AC5 reachability.
- **`flux-git-auth` secret:** must authorize Flux to read the per-app Gitea repos, not just `ai/druppie`.
- **Gitea DinD runner:** must be registered at org/instance scope so workflows in arbitrary `ai/<app>` repos are picked up.
