---
id: "030"
title: Sticky LLM fallback per session
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 030: Sticky LLM fallback per session

## Context

ADR 009 introduced cross-provider fallback for LLM calls. When the primary
provider fails, the request is retried on a fallback provider. This works, but
it has a cost: every LLM call pays the latency of the primary's full retry
cycle before the fallback runs. If the primary is down for minutes or hours,
every single call in that window is slow.

PR #235 (issue #76) addresses this by making the fallback behavior
session-aware. Once the primary fails in a session, subsequent calls should
skip the primary and go directly to the fallback. When the primary recovers,
the system should detect that and return to normal operation.

The forces at play:

- **Latency on repeated failure.** ADR 009's negative section explicitly calls
  out: "Fallback adds latency when the primary fails (primary exhausts its
  retries before fallback runs)." A multi-minute outage means every agent call
  is slow.
- **Recovery detection.** The system must detect when the primary comes back
  online without adding a separate health-check mechanism.
- **Session isolation.** Degraded state from one session must not leak into
  another. A failing primary in session A should not cause session B to skip
  the primary.
- **Minimal complexity.** The fix should be a thin wrapper around the existing
  `FallbackLLM`, not a new subsystem.

## Decision

Introduce a **sticky degraded mode** in `FallbackLLM`
(`druppie/llm/fallback.py`) with three rules:

1. **Session-aware degraded mode.** After the first primary provider failure
   in a session, all subsequent LLM calls within the same agent run skip the
   primary entirely and go directly to the fallback. This avoids paying the
   primary failure latency on every call.

2. **Per-session isolation.** Degraded state does not leak across sessions.
   Each session maintains its own degraded flag independently via a class-level
   `_degraded_sessions: set[str]`. A `clear_session()` class method removes the
   flag when a session ends.

3. **Retry-free probe on new agent runs.** When a new agent run starts within
   the same session, the first LLM call probes the primary provider with zero
   retries. If it works, the session exits degraded mode. If it fails, degraded
   mode continues. Zero retries minimizes latency: if the primary is still down,
   we learn that quickly rather than waiting through 3 retries with exponential
   backoff.

The implementation lives in `FallbackLLM` and tracks two booleans:

- `_degraded` — set when the primary first fails in a session. Persists across
  agent runs within the same session.
- `_primary_failed_this_run` — set when the primary fails during the current
  agent run. Resets on each new agent run (the orchestrator creates a fresh
  `FallbackLLM` instance per run).

The probe logic: when `_degraded` is true but `_primary_failed_this_run` is
false (new agent run), the primary is called with `max_retries=0`. A success
clears `_degraded`. A failure sets `_primary_failed_this_run` and falls back.

## Consequences

Positive:

- Eliminates repeated primary-failure latency within a session. After the
  first failure, calls go directly to the fallback.
- Zero-retry probe minimizes recovery latency. A recovered primary is detected
  on the first call of the next agent run.
- Per-session isolation prevents cross-session state leakage. A failing primary
  in one session does not affect others.
- Minimal code change: ~100 lines added to the existing `FallbackLLM` class,
  no new dependencies.

Negative:

- If the primary recovers mid-agent-run, the session stays degraded until the
  next agent run. This is an acceptable trade-off: agent runs are typically
  short (seconds to minutes), and the alternative (probing on every call) would
  reintroduce latency.
- Degraded state is in-memory only. A process restart clears all degraded
  flags, meaning every session probes the primary again. This is acceptable:
  a restart implies the system was down anyway, and probing is cheap.
- Zero-retry probe may miss intermittent failures. A transient blip during the
  probe call could trigger a false degraded state. In practice, the probe
  follows a full retry cycle that already failed, so the primary is likely
  genuinely down.

## Alternatives Considered

- **Health-check endpoint.** A separate periodic health check against the
  primary provider. Rejected: adds complexity, requires a background task, and
  duplicates the real signal (actual LLM calls).
- **Exponential backoff on primary retries.** Reduce retry count over time
  rather than skipping the primary entirely. Rejected: still pays some latency
  on every call, and the complexity of tuning backoff parameters is not worth
  the marginal gain.
- **Circuit breaker pattern.** Track failure rate over a sliding window and
  open the circuit when a threshold is exceeded. Rejected: over-engineered for
  this use case. The primary either works or it does not; a binary degraded
  flag is sufficient.
- **No change (status quo).** Every call retries the primary with full
  backoff. Rejected: directly contradicts the latency concern documented in
  ADR 009.
