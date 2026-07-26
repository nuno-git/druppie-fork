# Scheduled PR Review Agent

Automated review of open PRs on the GitOps Gitea (`aigit.waterschap.org`),
running centrally on the AI platform as a cron job — replacing the ad-hoc
local setup. The `pr_reviewer` agent reviews only PRs that changed since their
last review, strictly within the PR diff. For each changed PR it **fans out**
one reviewer per lens (correctness / security / architecture / tests-docs),
**adversarially verifies** their findings, then publishes one sticky verdict
plus line-anchored inline comments.

> **Data egress / cost.** The reviewer runs on `llm_profile: standard`
> (hosted providers — zai glm-5, glm-4.7, DeepSeek, gpt-oss, GPT-5-MINI; the
> resolver picks the first with a key). The local-only `llmkube` endpoint did
> not reliably serve this unattended run. **Consequence:** every scheduled run
> sends the PR diff of an allowlisted repo to an external hosted LLM, and runs
> are billed per token. Keep the allowlist to repos whose code may leave the
> cluster, or switch the agent back to a local profile if that is unacceptable.

## Architecture

```
JobScheduler (backend, every minute)
  └─ pr_review_job (cron, default */20) ── creates session + agent run
       └─ pr_reviewer agent  (role: primary, llm_profile: standard)
            ├─ subagents(): 4× pr_review_dimension  (parallel, one per lens)
            │                 └─ get_pr_diff + read-only ai/druppie checkout
            ├─ subagents(): 1× pr_review_verifier    (adversarial filter)
            └─ coding MCP module
                 ├─ list_prs_needing_review   (dedup decided in code)
                 ├─ get_pr_diff               (size-guarded)
                 └─ post_pr_review            (sticky verdict + inline review)
```

The dimension and verifier subagents inherit the orchestrator's read-only
`update_core` checkout (subagents share the parent's sandbox scope). The
orchestrator itself only calls the three Gitea tools plus `subagents()`.

Everything that must not depend on LLM discipline is enforced in code, not
in the prompt:

- **Repo allowlist** — `PRREVIEW_REPOS` is server-side config of the coding
  module, never a tool argument. The agent cannot review or comment outside
  it.
- **Dedup / no stacked reviews** — review state lives in Gitea itself: each
  reviewed PR carries exactly one sticky comment starting with a marker
  (`<!-- druppie-pr-review sha:<head_sha> verdict:<verdict> -->`). A PR needs
  review only when its head SHA differs from the marker SHA; posting again
  edits the same comment. Draft PRs are skipped. The inline comments do not
  stack either: each run deletes the bot's previous PR review before posting
  the fresh one (the marker comment is the durable dedup record; the review
  just carries the line-anchored notes).
- **Inline anchoring in code, not the LLM** — the LLM only names `file` + a
  NEW-file `line` per finding; `post_pr_review` parses the diff, maps each to
  an anchorable hunk line (snapping a near miss), and folds anything outside a
  changed hunk into the summary body — so a wrong line never makes Gitea reject
  the whole review. Inline count is capped by `PRREVIEW_MAX_INLINE_COMMENTS`.
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
  "llm_calls": 47,
  "prompt_tokens": 512480,
  "completion_tokens": 21840,
  "total_tokens": 534320,
  "duration_ms": 620145,
  "fallback_calls": 3,
  "models": ["zai/glm-5", "zai/glm-4.7"]
}
```

The usage aggregates the orchestrator **and all its subagents** (the fan-out
runs many LLM calls per PR), so tokens are the real cost driver — these are
hosted, per-token-billed providers. `fallback_calls > 0` means the resolver
dropped to a later provider in the `standard` chain.

The fan-out trades cost for depth. It is bounded structurally so a run cannot
run away: the per-run PR cap, the diff-size guard, exactly **4 lenses + 1
verifier per PR** (no verifier loop, no extra rounds), `temperature: 0.1`, and
the per-agent `max_iterations`. Tune `PRREVIEW_MAX_PRS_PER_RUN` and the cron
interval down first if a run is too expensive.

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

### Sticky verdict comment + a non-blocking inline review

The verdict (`APPROVE` / `REQUEST_CHANGES` / `COMMENT` / `SKIPPED_TOO_LARGE`)
lives in one editable **issue comment** carrying the dedup marker — the
durable record, edited in place so it never stacks. The per-line findings are
posted as a native Gitea **PR review**, which is what allows line-anchored
inline comments. Native reviews cannot be edited, so instead of editing, each
run **deletes the bot's previous review** before creating the new one — that
keeps the "never stack" guarantee for inline comments too.

The inline review is always submitted with `event: COMMENT`, never
`APPROVED`/`REQUEST_CHANGES`, so the bot never changes the PR's merge or
approval state — even a `REQUEST_CHANGES` *verdict* stays advisory (it is text
in the sticky comment). If blocking is ever wanted, that is a
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
| `PRREVIEW_MAX_INLINE_COMMENTS` | `30` | Inline comments per review; overflow folds into the summary |
| `PRREVIEW_SSL_CA_BUNDLE` | *(system CAs)* | Private CA bundle path; TLS verification has no off-switch |

| Env var (backend) | Default | Meaning |
|---|---|---|
| `JOB_PR_REVIEW_JOB_ENABLED` | YAML (`false`) | Enable the cron per environment |
| `JOB_PR_REVIEW_JOB_SCHEDULE` | YAML (`*/20 * * * *`) | Cron override per environment |
