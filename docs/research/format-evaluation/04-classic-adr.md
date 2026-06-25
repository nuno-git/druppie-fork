# 7. Rolling deployment strategy for generated sandbox apps

Status: accepted
Date: 2026-05-12
Deciders: nuno, kilian
Supersedes: ADR-003
Linked PRD: PRD-014

## Context
Sandbox apps were redeployed with a stop-then-start sequence, causing ~30s downtime and dropping active WebSocket sessions.

## Decision
Adopt a rolling deployment: start the new container, run a health check, switch traffic, then drain the old container. Rollout limits: maxSurge=1, maxUnavailable=0.

## Consequences
Positive: Zero-downtime deploys.
Positive: Safe automatic rollback when the health check fails.
Negative: Requires a /health endpoint on every generated app.
Negative: Transient ~2x memory usage during rollout.
