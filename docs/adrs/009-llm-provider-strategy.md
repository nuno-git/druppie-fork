---
id: "009"
title: LLM provider strategy with LiteLLM and cross-provider fallback
status: accepted
date: 2026-07-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 009: LLM provider strategy with LiteLLM and cross-provider fallback

## Context

Druppie's agents are powered by external LLMs, and the platform must not be
hard-coded to a single vendor. Providers differ in cost, quality, rate limits, and
uptime; some agents (e.g. router/summarizer) are cheap and routine, while others
need a stronger model. Providers also fail — auth keys expire, services have
outages, and rate limits get hit — so a single-provider dependency would make the
whole platform brittle.

The forces at play:

- Need to support multiple OpenAI-compatible providers (zai, deepinfra, and
  potentially openai/anthropic-style providers) without writing per-vendor parsing
  or tool-calling code.
- Need per-agent model selection so a router can use a cheap model while an
  architect uses a stronger one.
- Need resilience: if the primary provider is unavailable, the request should
  still succeed on a fallback provider.
- Need observability into which provider/model was chosen for a given run.

## Decision

Use **LiteLLM** as the single abstraction layer over all LLM providers, and add
cross-provider fallback via per-agent **LLM profiles**.

- **Unified abstraction.** All providers go through LiteLLM
  (`druppie/llm/litellm_provider.py`), which standardizes tool calling and
  response parsing across 100+ providers. There is one `LLMService` singleton and
  one `LLMResponse` shape regardless of provider.
- **Provider profiles.** Agents reference a named profile in
  `druppie/agents/definitions/llm_profiles.yaml`. Each profile is an ordered list
  of `{provider, model}` pairs (e.g. `standard`, `cheap`). Agent YAMLs set
  `llm_profile: standard`.
- **3-step model resolution** (`druppie/llm/resolver.py`):
  1. **Override** — `LLM_FORCE_PROVIDER` / `LLM_FORCE_MODEL` env vars force all
     agents to one provider (for testing/debugging).
  2. **Profile** — filter the profile's provider list by API-key availability;
     the first available entry becomes the primary, the second the fallback. The
     global `LLM_PROVIDER` is appended as a last-resort if not already present.
  3. **Global default** — if no profile is set, fall back to `LLM_PROVIDER`.
- **Graceful fallback** (`druppie/llm/fallback.py`). When a profile has multiple
  available providers, `FallbackLLM` wraps primary + fallback. Any `LLMError` from
  the primary — including `AuthenticationError` — triggers the fallback provider.
  This is correct for cross-provider fallback: a bad key for provider A does not
  mean provider B is broken.
- **Observability.** Every resolution decision is logged as a structured
  `model_resolved` event, and the `/api/status` endpoint exposes the loaded
  profiles and their provider chains.

## Consequences

Positive:

- Provider-agnostic code: adding a vendor is a config change, not new parsing
  logic.
- Per-agent cost/quality tuning via named profiles.
- Resilience to provider outages and expired keys through automatic fallback.
- Easy A/B testing and forced-provider debugging via env override.

Negative:

- A dependency on LiteLLM and on its correctness across providers.
- Fallback adds latency when the primary fails (primary exhausts its retries
  before fallback runs).
- Provider feature differences (context windows, tool-calling quirks) are masked
  by the abstraction and can surface as subtle behavior differences.
- Profile management overhead: profiles and key availability must be kept
  consistent.

## Alternatives Considered

- **Per-provider integrations (hand-written client per vendor).** Rejected:
  duplicated parsing/tool-calling code, high cost to add providers, no shared
  response model.
- **Single-provider lock-in.** Rejected: no resilience to outages, no
  cost/quality flexibility, full dependency on one vendor's pricing and uptime.
- **Heavier framework abstraction (e.g. LangChain).** Rejected: more opinionated
  and heavier than needed; LiteLLM gives the standardized tool calling and
  response parsing without the surrounding framework.
