---
id: "014"
title: "Cost & Usage Tracking"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 014: Cost & Usage Tracking

## Problem

Token tracking is partially implemented (`LLMCall` has token fields, LiteLLM provides counts) but display per session/project is poor. Cost tracking is essentially non-existent — no calculation of costs based on token usage and provider pricing. Users cannot see what they're spending or set budget limits.

## Goal

Complete cost & usage visibility: accurate token extraction across all providers, cost calculation based on provider pricing tiers, aggregate metrics at session/agent/project levels, cost warnings and budget limits in the UI, and historical cost reporting.

## User Journey

1. User opens a session — system tracks every LLM call's token usage and calculates cost.
2. User views session detail — sees cumulative token count and estimated cost.
3. Admin opens project dashboard — sees aggregate costs across all sessions and agents.
4. Admin sets a monthly budget limit per project.
5. When a project approaches its budget, the UI shows a warning.
6. When the budget is exceeded, new agent runs are blocked with a clear message.

## Constraints

- Token extraction must work consistently across all LiteLLM-supported providers.
- Cost calculation must reflect each provider's pricing model (per-1K-token rates).
- Historical data must be retained for reporting.
- Must not add latency to the agent execution path.

## Out of Scope

- Real-time cost streaming during agent execution (polled updates are sufficient).
- Cross-project cost aggregation (single-project view first).
- Billing integration (Stripe, invoicing).

## Open Questions

- **Q1: Should budget limits hard-stop agents or just warn?**
  - Option A: Hard stop — block new runs when budget exceeded.
  - Option B: Warn only — let users decide.
  - Owner: admin.

## Linked Documents

- Source: `docs/BACKLOG.md` — "Token/Cost Tracking Half Implemented and Buggy"
