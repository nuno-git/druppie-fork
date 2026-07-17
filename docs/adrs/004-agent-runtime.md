---
id: "004"
title: Build native agent runtime with done() enforcement
status: accepted
date: 2026-05-19
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/004-agent-runtime.md
linked_research: docs/research/004-agent-runtime.md
---

# ADR 004: Build native agent runtime with done() enforcement

## Context

Druppie agents build applications through MCP tools with HITL approval and sandboxed execution. External coding-agent frameworks were tried first (see ADRs 021, 032, 033) and all failed to integrate with Druppie's governance model (approval gates, sandbox networking, per-agent tool scoping). The original Python runtime (druppie/agents/runtime.py) was tightly coupled to FastAPI and SQLAlchemy, making it untestable in isolation.

## Decision

Build druppie/agent_runtime/ as a storage-agnostic library (pure dataclasses, no ORM/framework imports). The runtime enforces done() as a mechanical completion gate: an agent CANNOT finish until it calls the done tool with the required output variables. Only two tools are builtin (done and subagents); all other capabilities route through MCP servers. Per-agent sandbox containers are managed by the module-coding MCP server based on the agent's git_scope YAML property. Context compaction (LLM-summarized) prevents context window overflow on long sessions. The AgentV2 facade (druppie/agents/runtime_v2.py) bridges the library to the Druppie backend.

## Consequences

Positive: full control over the execution loop, tight HITL/approval integration, storage-agnostic testability, and a mechanical quality gate via done(). Negative: we maintain our own runtime instead of building on external frameworks, the dual Agent/AgentV2 system persists during migration (legacy Agent is still used in 1 orchestrator path), and the agent_runtime library has no sandbox layer (sandbox is delegated to module-coding, which was planned but descoped).
