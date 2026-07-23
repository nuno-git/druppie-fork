---
id: "022"
title: "Kubernetes Phase 2"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/005-dev-prod-infrastructure.md"]
linked_research: ["docs/research/007-kubernetes-as-built-analysis.md"]
linked_specs: []
---

# PRD 022: Kubernetes Phase 2

## Problem

Phase 1 K8s migration is complete (kind → Hetzner K3s) but several capabilities remain uncontainerized or need Kubernetes-native reimplementation: dependency cache (remote/distributed), pre-populated common packages, automated periodic vulnerability scanning, and general multi-instance operational maturity.

## Goal

Phase 2 K8s: distributed dependency caching (shared across sandbox instances), pre-populated package caches for common stacks, automated OSV vulnerability scanning of cached dependencies, and validated multi-instance operational patterns.

## User Journey

1. Developer agent builds an app — sandbox pulls dependencies from a shared remote cache instead of re-downloading.
2. Common packages (React, FastAPI, etc.) are pre-populated — cold start is fast.
3. Scheduled vulnerability scan runs — finds a CVE in a cached package → alert.
4. Multiple backend instances run simultaneously — cron jobs, session execution, and scheduling all work without duplication.

## Constraints

- Dependency cache must be shared across all sandbox containers (not per-container).
- Cache must support npm, pnpm, bun, uv, pip.
- Vulnerability scanning uses OSV database.
- Multi-instance patterns must leverage existing atomic-claim cron (ADR 014).

## Out of Scope

- Private package registry hosting.
- Custom vulnerability remediation (scan + alert only).
- Cluster autoscaler tuning (covered in PRD 020).

## Open Questions

None blocking — items are well-defined engineering tasks.

## Linked Documents

- ADR: ADR 005, ADR 014 (atomic-claim cron)
- Research: Research 007 (K8s as-built analysis)
- Source: `docs/BACKLOG.md` — "Dependency Cache" items, "Kubernetes Phase 2" section
