---
id: 007
title: Rolling deployment strategy for generated sandbox apps
status: accepted
date: 2026-05-12
deciders: [nuno, kilian]
supersedes: ADR-003
linked_prd: PRD-014
---

# ADR-007: Rolling deployment strategy for generated sandbox apps

## Context
Sandbox apps were redeployed with a stop-then-start sequence, causing ~30s downtime and dropping active WebSocket sessions.

## Decision
Adopt a rolling deployment: start the new container, run a health check, switch traffic, then drain the old container. Rollout limits: maxSurge=1, maxUnavailable=0.

## Consequences
- (+) Zero-downtime deploys
- (+) Safe automatic rollback when the health check fails
- (-) Requires a /health endpoint on every generated app
- (-) Transient ~2x memory usage during rollout
