---
id: "029"
title: Ask-first fallback pattern for runtime model management
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 029: Ask-first fallback pattern for runtime model management

## Context

ADR 009 introduced cross-provider fallback with a silent switch: when the
primary LLM provider failed, `FallbackLLM` transparently retried on the
fallback provider without the user ever knowing. This was a deliberate
choice for resilience — a failing provider should not halt the platform.

Experience showed a UX problem. Users did not know their agent was running
on a different (potentially lower-quality) model. An architect agent that
silently fell back from Claude Sonnet to a cheap model produced noticeably
worse designs, and users had no way to tell why. The silent fallback also
meant operators could not distinguish between "everything is fine" and
"the primary has been down for hours and every agent is running on
fallback."

PR #281 introduced runtime model management with an ask-first fallback
pattern. The forces at play:

- Users need transparency when the model serving their agent changes.
- Users need control — they should decide whether to accept degraded
  quality or cancel the request.
- Operators need a way to override provider/model per agent at runtime
  without redeploying YAML profiles.
- Error messages from LLM providers contain sensitive data (API keys,
  IPs, JWTs) that must not leak to users.
- Translation has its own model requirements, separate from agent models.

## Decision

Replace the silent fallback with an ask-first pattern and add runtime
model management. The following decisions are made together:

**Ask-first fallback.** When the primary provider fails, `FallbackLLM`
raises `FallbackAvailableError` instead of silently switching. The agent
loop catches this error and creates a HITL question with three choices:
"Switch this agent", "Switch all agents", or "Cancel". The frontend shows
a `FallbackModal` with the primary and fallback models side by side. The
agent only continues on the fallback after the user explicitly approves.

**Session-level approval tracking.** Once a user approves fallback for a
session+agent combination, subsequent failures in the same session do not
re-prompt for that agent. But a new agent run in the same session (a
different agent type) does re-prompt. Two approval levels exist:
session-wide (`approve_fallback`) and per-agent
(`approve_fallback_for_agent`). Both are stored in process-local dicts
with 24-hour TTL eviction.

**Per-agent model overrides.** A `model_overrides` DB table stores
admin-set provider/model pairs per agent and for the translation service.
On startup and after admin changes, the `ModelManagementService` loads
overrides into an in-memory cache in the resolver. The resolution chain
becomes: env override → DB override → profile → global default.

**Pre-save validation.** Before persisting a model override, the API
tests the provider/model combination with a lightweight LiteLLM call.
This catches bad API keys, undeployed models, and misconfigured
providers before they affect running agents.

**`clean_llm_error()` utility.** A shared function strips API keys,
Bearer tokens, JWTs, UUIDs, and other sensitive patterns from error
messages before exposing them to users. Also normalises common error
types (deployment not found, auth failure, rate limit, timeout) into
short user-facing messages.

**Provider status dashboard.** An admin page (`/admin/models`) shows API
key availability and model connectivity per provider. The
`/admin/models/providers` endpoint returns per-provider status including
whether the key is configured, the default model, and the base URL.

**Translation model override.** Separate from agent model overrides. The
translation service has its own `model_overrides` row (target_type =
"translation") and its own API endpoints. This lets operators tune the
translation model independently of agent models.

## Consequences

Positive:

- Users see exactly when and why their agent switches models, with
  explicit consent before quality degrades.
- Operators can override provider/model per agent at runtime without
  editing YAML or redeploying.
- Pre-save validation prevents misconfiguration from reaching production.
- Error messages are safe to show to users — no leaked credentials.
- Translation model can be tuned independently of agent models.
- Provider status dashboard gives operators visibility into which
  providers are actually usable.

Negative:

- Adds latency: the agent pauses and waits for user approval before
  continuing on the fallback. During an outage every active session
  triggers a modal.
- Modal UX can be confusing for non-technical users who do not
  understand provider/model concepts.
- Session approval state is process-local (in-memory dicts with TTL
  eviction). Lost on worker restart. Requires single-worker deployment
  (already enforced by the Dockerfile).
- DB override cache is also process-local. Multi-worker deployments
  would need cross-worker invalidation (e.g. polling a DB timestamp).
- Override bypasses the reviewed provider chain — an admin can set a
  provider/model that was never tested in the profile.
