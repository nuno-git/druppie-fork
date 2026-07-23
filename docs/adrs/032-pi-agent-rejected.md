---
id: "032"
title: "Reject vendored TypeScript pi_agent due to MCP and coupling incompatibility"
status: deprecated
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: "004"
linked_prd: null
linked_research: null
---

# ADR 032: Reject vendored TypeScript pi_agent due to MCP and coupling incompatibility

## Context

After rejecting OpenCode, the dev_agent orchestrator (TypeScript, containerized
sandboxes, analyze→plan→build→verify→PR flow) was evaluated as a potential
replacement. It was vendored into the repo as `pi_agent/`.

Key commits: `61c6fe5a` (vendor), `b8dfe533` (TDD+explore flows), `c0a8bf26`
(Gitea provider). It used the `@mariozechner/pi-coding-agent` SDK and
communicated via raw HTTP, not MCP.

## Decision

**Reject the vendored pi_agent.** Two blockers made it incompatible with
Druppie's architecture:

1. **No MCP integration.** pi_agent used raw HTTP calls to communicate with
tools, while Druppie had already standardized on MCP for all tool
communication. Adapting pi_agent to use MCP would require rewriting its tool
dispatch layer — effectively building a new runtime.

2. **Tight coupling to FastAPI and SQLAlchemy.** pi_agent was designed as an
application-level module, not a library. It could not be tested in isolation
without a full FastAPI stack and database. Druppie needed a storage-agnostic
runtime that could be tested independently.

The vendored code was a dead end: Druppie's architecture had already evolved
past the assumptions pi_agent was built on.

## Consequences

**Positive.** The pi_agent evaluation confirmed that MCP-native tool
communication is a non-negotiable requirement for the agent runtime. The
tight-coupling failure reinforced the need for a storage-agnostic library
design.

**Negative.** More engineering time spent on an external approach that was
ultimately incompatible. The vendored code path was a distraction from
building the right solution.
