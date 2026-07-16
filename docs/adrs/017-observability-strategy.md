---
id: "017"
title: Adopt a structured observability strategy for agent executions
status: proposed
date: 2026-07-16
deciders:
  - Nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

## Context

The platform has no real observability infrastructure. Per `docs/BACKLOG.md`
("No Observability Infrastructure"):

- No Prometheus metrics, no OpenTelemetry tracing, no structured log
  aggregation.
- Debugging relies on database records (`LLMCall`, tool calls) and the debug
  pages in the frontend — i.e. you can only see what was persisted to a row,
  after the fact.
- Logging is inconsistent: `print()` statements sit alongside `structlog`
  calls throughout the LLM providers, so log output is a mix of structured and
  unstructured text that cannot be cleanly aggregated or queried.

There has been partial progress in the *audit-trail* direction — the
`llm_retries` and `tool_call_normalizations` tables now record retry attempts
and tool-argument normalizations, and the `LLMCallDetail` domain model was
consolidated (duplicate `raw_request`/`raw_response` wrappers removed). But
these are persistence-based breadcrumbs, not live observability: there are no
live metrics, no distributed tracing, and no centralized logs.

This gaps the two operational needs that matter most for an agent-execution
platform: understanding *what is happening right now* during a long multi-agent
run, and understanding *why* a run degraded (latency, token/cost burn, retry
storms, tool failures). The related "Token/Cost Tracking Half Implemented and
Buggy" backlog item shows that even the persisted signals (token usage, cost)
are not aggregated at session/agent/project level — observability of cost is
part of the same gap.

## Decision

Adopt a three-pillar observability strategy — structured logs, metrics, and
distributed tracing — built on an open-source, self-hostable stack, and make
agent executions first-class subjects of all three.

- **Structured logging (single standard).** Standardize on `structlog`
  everywhere and remove the remaining `print()` calls in the LLM providers.
  Emit structured, JSON-formatted logs with consistent fields (session id, agent
  id, agent run id, tool call id, LLM call id) so logs join cleanly to traces
  and to the existing DB audit rows.
- **Metrics (Prometheus).** Expose Prometheus metrics for agent execution:
  active/pending agent runs, agent run duration histograms, tool-call counts and
  latencies, LLM call counts/latencies, token usage and cost gauges
  (session/agent/project), retry counts (backed by the existing `llm_retries`
  data), and sandbox/queue depth.
- **Distributed tracing (OpenTelemetry).** Trace the full path
  `API request → orchestrator → agent run → MCP tool call → LLM call` as a
  single trace with spans, so a slow or failing multi-agent run can be followed
  end-to-end across process boundaries (backend, MCP servers, sandbox).
- **Backend & aggregation.** Use an open-source stack (Prometheus + Grafana for
  metrics; Loki or equivalent for structured-log aggregation; Tempo/Jaeger for
  traces), integrated with the existing Docker Compose dev profile so it is
  usable locally, not just in production.
- **Extend, don't replace, the audit trail.** Keep and extend the persistence
  pattern already started (`llm_retries`, `tool_call_normalizations`); live
  observability complements it rather than replacing the durable record.

The specific metric names, retention windows, and sampling rates are to be
settled when this ADR moves to `accepted`; the commitment here is the
three-pillar shape and an open-source, self-hosted implementation.

## Consequences

Positive:
- Live, end-to-end visibility into agent runs — see what is happening now and
  reconstruct why a run failed or degraded.
- Cost/token burn becomes observable (complements the half-implemented
  token/cost tracking), enabling budgets, alerts, and SLI/SLO definitions.
- Structured logs become queryable and joinable to traces and DB rows, ending
  the `print()`-vs-`structlog` inconsistency.
- Self-hosted stack avoids vendor lock-in and data-residency concerns (relevant
  given the project's local-LLM posture).

Negative:
- Instrumentation overhead in the hot path and the operational cost of running
  Prometheus/Grafana/Loki/Tempo alongside the existing services.
- Learning curve and new infra to maintain; must be wired into the Docker
  Compose profiles (and later the Helm chart) carefully.
- Risk of noisy/high-cardinality metrics (e.g. per-session labels) if label
  discipline is not enforced up front.

Before this ADR can move to `accepted`:
- Pick the concrete stack versions and confirm they run in the dev Docker
  Compose profile.
- Define the initial metric set and label cardinality rules (avoid per-session
  labels on histograms).
- Prototype instrumentation on one full agent flow (API → orchestrator → agent
  → MCP tool → LLM call) and prove a single end-to-end trace renders.

## Alternatives Considered

- **Status quo (DB rows + frontend debug pages only).** Rejected — only shows
  persisted state after the fact; no live view, no tracing, no metrics, no log
  aggregation. This is the gap being closed.
- **Structured logging only (no metrics or tracing).** Cheapest, but cannot
  answer aggregate questions (rates, latencies, cost burn) and cannot follow a
  request across process boundaries. Insufficient on its own.
- **Third-party APM (Datadog / New Relic).** Fastest to value, but introduces
  cost, vendor lock-in, and data-residency concerns that conflict with the
  project's self-hosted / local-LLM direction. Rejected.
- **Open-source stack (Prometheus + Grafana + Loki + Tempo).** More setup and
  maintenance, but self-hosted, no lock-in, and consistent with the existing
  Docker-Compose / Helm approach. **Selected.**
