# Scheduled PR Review Agent

Automated review of open PRs on the GitOps Gitea (`aigit.waterschap.org`),
running centrally on the AI platform as a cron job — replacing the ad-hoc
local setup. One agent (`pr_reviewer`) reviews only PRs that changed since
their last review, strictly within the PR diff, on local (in-cluster) models
only.

## Architecture

```
JobScheduler (backend, every minute)
  └─ pr_review_job (cron, default */20) ── creates session + agent run
       └─ pr_reviewer agent (llm_profile: llmkube — local models only)
            └─ coding MCP module
                 ├─ list_prs_needing_review   (dedup decided in code)
                 ├─ get_pr_diff               (size-guarded)
                 ├─ post_pr_review            (one sticky comment per PR)
                 └─ read_file/grep/find/...   (read-only ai/druppie checkout)
```

Everything that must not depend on LLM discipline is enforced in code, not
in the prompt:

- **Repo allowlist** — `PRREVIEW_REPOS` is server-side config of the coding
  module, never a tool argument. The agent cannot review or comment outside
  it.
- **Dedup / no stacked reviews** — review state lives in Gitea itself: each
  reviewed PR carries exactly one sticky comment starting with a marker
  (`<!-- druppie-pr-review sha:<head_sha> verdict:<verdict> -->`). A PR needs
  review only when its head SHA differs from the marker SHA; posting again
  edits the same comment. Draft PRs are skipped.
- **Cost caps** — `PRREVIEW_MAX_PRS_PER_RUN` (default 5) caps work per run;
  diffs over `PRREVIEW_MAX_DIFF_LINES` (default 3000) are not reviewed but
  marked `SKIPPED_TOO_LARGE` with a request to split the PR, so they are not
  retried (and re-paid for) every run.

## Enabling it in an environment

The job ships **disabled** (`enabled: false` in
`druppie/jobs/definitions/pr_review_job.yaml`). Because the job YAML is baked
into the image, enabling is done **per environment** through env overrides
that the backend's job loader applies on top of the YAML:

| Env var | Effect |
|---|---|
| `JOB_PR_REVIEW_JOB_ENABLED` | `true`/`false` — overrides the YAML `enabled` flag |
| `JOB_PR_REVIEW_JOB_SCHEDULE` | cron expression — overrides the YAML schedule |

(The mechanism is generic: `JOB_<ID_UPPERCASED>_ENABLED` / `_SCHEDULE` works
for any job definition.)

### Kubernetes (the real deployment)

Set the Helm values in the environment's HelmRelease in **ai/k8s** — IaC,
no kubectl:

```yaml
values:
  prReview:
    repos: ai/druppie          # comma-separated <owner>/<repo> allowlist
    jobEnabled: true           # -> JOB_PR_REVIEW_JOB_ENABLED
    # jobSchedule: "*/30 * * * *"   # optional cron override
    # maxPrsPerRun: 5
    # maxDiffLines: 3000
```

With `repos` empty (the chart default) no `PRREVIEW_*` config is emitted and
the feature is fully off.

**Secrets come from Vault.** With `externalSecrets.managed=true` the chart
Secret is owned by ESO (`ai/k8s` vault-eso layer); `EXTERNAL_GITEA_TOKEN` —
and optionally a dedicated `PRREVIEW_GITEA_TOKEN` — are Vault entries synced
into that Secret, which module-coding consumes via `envFrom`. Nothing
token-related goes into values or the configmap. For unmanaged installs the
chart accepts `secrets.externalGiteaToken` / `secrets.prreviewGiteaToken`.

**Use a bot account.** The reviewer only needs *read + PR-comment* rights on
the allowlisted repos. `PRREVIEW_GITEA_TOKEN` exists so the reviewer does not
have to run on the broader `EXTERNAL_GITEA_TOKEN`; prefer a dedicated
`druppie-reviewer` bot account and store its token in Vault.

### Local development / manual pilot

Set the same env vars on the backend and module-coding containers of your
dev deployment (see `.env.example`):

```bash
PRREVIEW_REPOS=ai/druppie
EXTERNAL_GITEA_TOKEN=...        # or PRREVIEW_GITEA_TOKEN for a bot account
JOB_PR_REVIEW_JOB_ENABLED=true
```

A manual pilot works without enabling the cron:
`POST /api/jobs/{definition_id}/trigger` (admin).

## Cost per run

Cost is visible on the job run itself: `GET /api/jobs/runs/{run_id}` (admin)
returns a `usage` block aggregated from the run's session:

```json
"usage": {
  "llm_calls": 12,
  "prompt_tokens": 84213,
  "completion_tokens": 6120,
  "total_tokens": 90333,
  "duration_ms": 421337,
  "fallback_calls": 0,
  "models": ["llmkube/Qwen/Qwen3.6-27B"]
}
```

Local models have no per-token price, so cost is expressed in what drives it:
calls, tokens and wall time. `fallback_calls > 0` is the signal that an
external (paid) provider was involved after all — by design that can only
happen with explicit approval, which an unattended cron run never gives.

Expensive patterns are avoided structurally: one agent per run (no fan-out),
capped PR count, capped diff size, `max_iterations: 45`, `temperature: 0.1`.

## Design decisions

### Platform cron job, not the Gitea Action Runner (CI/CD)

Considered: running the review as a Gitea Actions workflow on PR events
(runner already exists in the `gitea-runner` namespace).

Chosen: **cron job on the AI platform**, because:

- The reviewer needs the platform anyway — agent runtime, coding MCP module,
  the in-cluster LLMKube/vLLM endpoint, and session/llm_calls bookkeeping all
  live there. A CI job would call back into the platform and add a network
  path plus a second set of credentials.
- Cost control is central here: one queue, `max PRs per run`, shared caps.
  Per-PR CI triggers fan out with push frequency and are much harder to cap.
- Event-driven CI reviews on every push would re-review with every commit;
  the cron + head-SHA dedup batches naturally.
- CI stays available as a *trigger* later: a small workflow step can simply
  call `POST /api/jobs/{definition_id}/trigger` for instant feedback on a PR,
  without moving the review itself into the runner. That is the recommended
  hybrid if the 20-minute latency turns out to be too slow.

Open follow-ups (owned outside this repo):

- **Nuno**: validate the decision above / the hybrid trigger option from the
  CI side (Gitea Action Runner).
- **Azure backlog**: this implementation belongs to the existing "PR review
  agent" PBI; scope alignment happens on that PBI.

### Sticky issue comment instead of a native Gitea review

The verdict (`APPROVE` / `REQUEST_CHANGES` / `COMMENT` /
`SKIPPED_TOO_LARGE`) is recorded in one editable issue comment, **not** as a
native Gitea PR review. Native reviews cannot be edited in place, so every
run would add a new review and reviews would stack — exactly what the dedup
design must prevent. Consequence: a `REQUEST_CHANGES` verdict does not block
merging in Gitea; it is advisory. If blocking is ever wanted, that is a
branch-protection rule, not a change to this agent.

### Review scope

Findings must be about lines the PR changes. The agent has a read-only
checkout of `ai/druppie` at `colab-dev` for *context* (callers, config,
surrounding code) — the checkout is the base side and only valid for PRs on
that repo/base; for anything else the diff is the sole source and unverified
findings are capped at MINOR. Severity gate: `REQUEST_CHANGES` only on
BLOCKER/MAJOR; when unsure, the finding is dropped.

## Configuration reference

| Env var (module-coding) | Default | Meaning |
|---|---|---|
| `PRREVIEW_REPOS` | *(empty = off)* | Comma-separated `<owner>/<repo>` allowlist |
| `PRREVIEW_GITEA_URL` | `EXTERNAL_GITEA_URL` | Gitea instance |
| `PRREVIEW_GITEA_TOKEN` | `EXTERNAL_GITEA_TOKEN` | Bot token (Vault) |
| `PRREVIEW_MAX_PRS_PER_RUN` | `5` | PR cap per cron run |
| `PRREVIEW_MAX_DIFF_LINES` | `3000` | Diff size guard |
| `PRREVIEW_SSL_CA_BUNDLE` | *(system CAs)* | Private CA bundle path; TLS verification has no off-switch |

| Env var (backend) | Default | Meaning |
|---|---|---|
| `JOB_PR_REVIEW_JOB_ENABLED` | YAML (`false`) | Enable the cron per environment |
| `JOB_PR_REVIEW_JOB_SCHEDULE` | YAML (`*/20 * * * *`) | Cron override per environment |
