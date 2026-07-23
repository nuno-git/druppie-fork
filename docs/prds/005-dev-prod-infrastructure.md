---
id: "005"
title: "Dev and Prod Infrastructure"
status: implemented
author: nuno
date: 2026-06-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/005-dev-prod-infrastructure.md", "docs/adrs/002-kubernetes-migration.md"]
linked_research: ["docs/research/006-kubernetes-strategy.md"]
linked_specs: ["docs/specs/005-dev-prod-infrastructure.feature"]
---

# PRD 005: Dev and Prod Infrastructure

## Problem

Developers need fast local iteration with hot reload and realistic
infrastructure (Keycloak, Gitea, PostgreSQL, MCP servers). Production needs high
availability, TLS termination, monitoring, and horizontal scaling. The sandbox
(per-agent Docker containers) must behave identically in both environments.

Without dev/prod parity, a sandbox that runs locally can fail in production, and
a sandbox that works in production can't be reproduced cheaply on a developer
laptop.

## Goal

A single-VM dev environment that starts in under 60 seconds with hot reload,
and a multi-VM prod environment with 3-node etcd HA, automatic failover,
KEDA-based autoscaling, and Prometheus/Grafana monitoring. The same agent
sandbox behavior in both.

## User Journey

1. Developer runs `docker compose --profile dev --profile init up -d` to start
   the full dev stack.
2. Backend and frontend hot-reload on code changes.
3. MCP servers, Keycloak, Gitea, and PostgreSQL run as infrastructure.
4. For production, the cluster is provisioned via the hetzner-k3s CLI using
   `iac/cluster.yaml`.
5. Workloads are deployed via `helm template | kubectl apply` (helm upgrade is
   broken).
6. ARC runners in the cluster build and deploy images on push.
7. Traefik ingress and cert-manager provide TLS at `druppie.rijnland.dev`.

## Constraints

- The sandbox uses the Docker-socket pattern, not native K8s pods.
- Docker must be installed on K8s app nodes via a DaemonSet.
- Three ADR-002 decisions are pending the local-Rancher migration.
- Helm upgrade is broken, so use `helm template | kubectl apply`.

## Out of Scope

- Native K8s sandbox (deferred to Phase 2 per ADR-002).
- Sealed Secrets (using a gitignored values overlay instead).
- Multi-region deployment.

## Open Questions

- Local-Rancher migration timeline. Three ADR-002 decisions are flagged for
  supersession until this lands.

## Linked Documents

- ADR 005: `docs/adrs/005-dev-prod-infrastructure.md`
- ADR 002: `docs/adrs/002-kubernetes-migration.md`
- Research 006: `docs/research/006-kubernetes-strategy.md`
- Spec: `docs/specs/005-dev-prod-infrastructure.feature`
