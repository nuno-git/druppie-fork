---
id: "012"
title: "LLM Provider Management"
status: approved
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/009-llm-provider-strategy.md"]
linked_research: []
linked_specs: []
---

# PRD: LLM Provider Management

## Problem

Druppie's agents are powered by external LLMs, and the platform runs many of them
simultaneously — a cheap router that classifies intent, a strong architect that
designs systems, a summarizer, a builder, and so on. A single hard-coded vendor
creates three concrete pain points for operators and product owners:

1. **Fragility.** Providers fail in ordinary ways: auth keys expire, services
   have outages, and rate limits get hit. With one vendor, any of these halts the
   entire platform. There is no recovery path that does not involve a human
   editing configuration under pressure.
2. **Cost rigidity.** Different agents have very different needs — a router is
   cheap and routine, an architect needs a stronger model. A single global model
   either over-pays for the cheap agents or under-powers the demanding ones.
   There is no way to tune cost vs. quality per agent.
3. **No visibility.** When something goes wrong, the operator cannot easily tell
   which provider and model a given run actually used, or whether a fallback
   fired. Debugging an unexpected result means guessing at the resolution path.

On top of this, the platform must not be hard-coded to a single vendor's API
shape — providers differ in tool-calling format, response structure, and
authentication, and writing per-vendor integration code makes every new vendor
expensive to add.

## Goal

Operators can configure the LLM layer **once** and then tune it per agent, with
resilience and observability built in. Concretely, success looks like:

1. **Multi-provider support.** Two or more OpenAI-compatible providers (e.g. zai,
   deepinfra, azure_foundry) can be configured simultaneously via API keys in the
   environment. Adding a vendor is a configuration change, not new integration
   code.
2. **Per-agent model assignment.** Each agent references a named **profile**
   (e.g. `standard`, `cheap`), so a router can use a cheap model while an
   architect uses a stronger one. Cost and quality are tunable per role.
3. **Provider profiles with fallback chains.** A profile is an ordered list of
   `{provider, model}` pairs. The resolver picks the first provider with a valid
   API key as primary and the next as fallback.
4. **Automatic cross-provider fallback.** When the primary provider fails for any
   reason — including an invalid auth key — the request still succeeds on the
   fallback provider, transparently. A bad key for provider A does not mean
   provider B is broken.
5. **Environment-based overrides.** An operator can force ALL agents to a single
   provider/model (`LLM_FORCE_PROVIDER` / `LLM_FORCE_MODEL`) for testing,
   debugging, or A/B comparison.
6. **Provider status visibility.** The `/api/status` endpoint exposes the loaded
   profiles and their provider chains, so operators can see exactly what is
   configured and what would be used.
7. **Observable resolution.** Every resolution decision is logged as a structured
   `model_resolved` event, so a run's chosen provider/model is always
   reconstructable.

**Definition of done:** Multiple providers can coexist, each agent resolves to a
sensible primary+fallback chain based on configured profiles and key
availability, a failing primary transparently fails over without user-visible
error, the `/api/status` endpoint reports the active profiles/chains, and the
resolver's decisions are queryable in logs. An agent run succeeds end-to-end even
when its primary provider's key is deliberately invalid.

## User Journey

1. An operator adds one or more provider API keys to the environment (e.g.
   `ZAI_API_KEY`, `DEEPINFRA_API_KEY`) and sets a global `LLM_PROVIDER` default.
2. The operator authors/edits **profiles** in `llm_profiles.yaml` — named,
   ordered `{provider, model}` lists (e.g. `standard` and `cheap`).
3. An agent author assigns `llm_profile: standard` (or `cheap`) in each agent's
   YAML definition, choosing cost/quality for that role.
4. On startup, the system loads the profiles and filters each profile's provider
   list by API-key availability; the first available entry becomes the primary,
   the second the fallback. The global default is appended as a last resort.
5. When an agent runs, the resolver determines primary + fallback and emits a
   structured `model_resolved` event recording the decision.
6. If the primary provider errors (outage, expired key, rate limit), the request
   transparently retries on the fallback provider; the user/agent sees a normal
   result, not an error.
7. The operator opens `/api/status` to inspect the loaded profiles and their
   provider chains — confirming, for example, that the fallback is wired up
   correctly before relying on it.
8. To debug or A/B-test, the operator sets `LLM_FORCE_PROVIDER` /
   `LLM_FORCE_MODEL`; on the next run every agent uses that provider regardless
   of its profile.
9. When reviewing an unexpected agent result, the operator correlates the run
   with the logged `model_resolved` event to see exactly which provider/model
   produced it.

## Constraints

- **Config, not code.** Adding a provider must be a configuration change, not new
  parsing or tool-calling code per vendor.
- **Cross-provider fallback semantics.** A failure on provider A (including an
  authentication error) must still attempt provider B, because a bad key for one
  service says nothing about a different service.
- **Keys via environment only.** API keys are supplied through env vars and are
  never committed or surfaced in responses.
- **Deterministic, logged resolution.** The provider/model chosen for any run
  must be reproducible from configuration and recorded in logs.
- **Single global override.** The force-provider override is platform-wide
  (affects all agents), not per-agent — it exists for testing/debugging.
- **Cost awareness.** Model choice has direct cost implications, so profiles
  exist to let operators trade cost vs. quality deliberately per role.

## Out of Scope

- **In-app LLM orchestration.** How the *built application* (the product a Druppie
  project produces) calls LLMs is a separate capability handled by the Architect
  and Builder — this PRD is about how *Druppie's own agents* are powered.
- **Billing/cost dashboards.** Aggregating spend per provider/model across runs
  is a future analytics concern, not part of provider management.
- **Runtime UI to edit profiles.** Profiles are YAML configuration owned by
  operators; there is no in-app editor in this scope.
- **Active provider health-checking and alerting.** `/api/status` reports
  configuration; it does not actively probe provider endpoints or raise alerts.

## Open Questions

- **Q1: Should profile changes apply without a restart?**
  - Option A: Require a restart — simpler, matches current behaviour, no race
    between file state and running requests.
  - Option B: Hot-reload profiles via a file watcher — more operator-friendly,
    adds concurrency considerations.
  - Owner: architect, deadline: 2026-08-30

- **Q2: How much should `/api/status` reveal about each provider's key?**
  - Option A: Present/absent only — safe, makes no external calls.
  - Option B: Active validation (a lightweight probe) — richer, costs an API call
    per provider per status fetch.
  - Owner: architect, deadline: 2026-08-30

## Linked Documents

- **ADRs:** `docs/adrs/009-llm-provider-strategy.md`
- **Research:** _(none)_
- **Specs / Feature files:** _(none yet)_
