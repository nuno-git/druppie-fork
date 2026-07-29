---
id: "020"
title: "Kubernetes Production Hardening"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/005-dev-prod-infrastructure.md"]
linked_research: ["docs/research/007-kubernetes-as-built-analysis.md"]
linked_specs: []
---

# PRD 020: Kubernetes Production Hardening

## Problem

The K8s deployment has three gaps: (1) the sandbox image builder job is a placeholder, (2) there is no Helm chart test suite, and (3) production hardening (TLS termination, external secrets management, HPA autoscaling tuning) is incomplete. The CNPG backup posture (barman-cloud/PITR) is not configured — a production gap flagged in Research 007.

## Goal

Production-ready K8s: working sandbox image builder, comprehensive Helm chart tests, TLS via cert-manager, external secrets via External Secrets Operator, HPA tuning validated against real load, and CNPG backup/PITR configured.

## User Journey

1. Operator deploys to production — TLS certificates auto-provisioned via cert-manager.
2. Secrets pulled from external secret store (no Kubernetes secrets in git).
3. Sandbox image builder creates container images on demand.
4. Helm chart tests run in CI — regression caught before deployment.
5. HPA scales backend pods based on queue depth + CPU.
6. CNPG backups run on schedule — PITR recovery tested quarterly.

## Constraints

- Must not break the dev environment (dev uses local secrets, no TLS).
- Helm chart tests must run in CI without a live cluster (kind-based).
- External Secrets Operator must support the chosen secret backend.
- CNPG backup requires object storage (S3-compatible).

## Out of Scope

- Multi-cluster federation.
- Service mesh (Istio/Linkerd).
- Custom admission controllers beyond OPA/Gatekeeper defaults.

## Open Questions

None blocking — items are well-defined engineering tasks.

## Linked Documents

- ADR: ADR 005 (`docs/adrs/005-dev-prod-infrastructure.md`)
- Research: Research 007 (`docs/research/007-kubernetes-as-built-analysis.md`) — tech debt items
- Source: `docs/BACKLOG.md` — "Kubernetes" section
