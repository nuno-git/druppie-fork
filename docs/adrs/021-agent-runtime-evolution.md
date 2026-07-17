---
id: "021"
title: "Agent Runtime Evolution: From External Frameworks to Native Python Runtime"
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/004-agent-runtime.md
linked_research: docs/research/004-agent-runtime.md, docs/research/002-llm-orchestration-in-apps.md, docs/research/005-sandbox-network-isolation.md
---

# ADR 021: Agent Runtime Evolution: From External Frameworks to Native Python Runtime

## Context

Druppie needed an agent runtime that could enforce governance: approval gates, sandbox networking, per-agent tool scoping. External coding-agent frameworks were evaluated and rejected across five phases. Each rejection taught us something about what we actually needed.

### Phase 1: OpenCode (TypeScript) — March-April 2026

OpenCode was the first external coding-agent framework integrated into Druppie. It ran as a TypeScript control plane **inside** sandbox containers — the agent process itself lived within the sandbox. Key commits: `4df3da35` (config), `e8c59a3e` (TDD flow), `f5aaeadf` (timeout fix).

**Why rejected:** Because OpenCode ran inside the sandbox, it needed a credential (LLM API key) to call external LLM providers. This credential lived inside the sandbox container and was therefore reachable by any command OpenCode executed — a critical security risk. An agent that can execute arbitrary shell commands inside a container that also holds API credentials is fundamentally unsafe. Druppie's compliance model (BIO, NIS2, zero-credentials-in-sandbox) could not accommodate this.

The fix inverts the architecture: **the agent with LLM access runs outside the sandbox and uses the sandbox as a tool.** Git access from inside the sandbox is blocked; instead, code changes flow through a git bundle extraction mechanism operated by a tool running outside the sandbox. The sandbox has no network access and no credentials — it is a pure execution environment.

Remaining artifacts: `druppie/opencode/config/` (config files survived the purge), `.git/opencode` (git directory leftover). OpenCode removal commit: `62c2f19a` (2026-05-21).

### Phase 2: TypeScript pi_agent (Vendored) — April 2026

The dev_agent orchestrator (TypeScript, containerized sandboxes, analyze-plan-build-verify-PR flow) was vendored as `pi_agent/`. Key commits: `61c6fe5a` (vendor), `b8dfe533` (TDD+explore flows), `c0a8bf26` (Gitea provider). It used the `@mariozechner/pi-coding-agent` SDK and communicated via raw HTTP, not MCP.

**Why rejected:** Tight coupling to FastAPI and SQLAlchemy made it impossible to test in isolation. Raw HTTP instead of MCP meant it could not integrate with Druppie's MCP-based tool model and per-agent tool scoping. The vendored code was a dead end: too much of Druppie's architecture had evolved past it.

### Phase 3: LangGraph — January-May 2026

LangGraph was used for roughly four months as the main agent flow. Key commits: `ba9c84b4` (StateGraph), `0db781c5` (HITL via `interrupt()`).

**Why rejected:** Druppie needed so many customizations that the LangGraph layer became more of a hindrance than a help. The team rewired `done()` enforcement, summary relay, subagents, context compaction, sandbox lifecycle, and HITL pause/resume. At that point the LangGraph abstraction was a thin wrapper over custom code. The decision was made to drop the abstraction and build the runtime ourselves.

### Phase 4: LiteLLM Provider — February 2026

Commit `314f3ae7` replaced direct provider SDKs with LiteLLM abstraction. This is the one external integration that stuck. It provides cross-provider fallback without vendor lock-in and remains in use today.

### Phase 5: Native agent_runtime Library — May-July 2026

PR #190 squash-rebased the entire `feature/agent-runtime` branch into `colab-dev` (commit `ec636782`). The `druppie/agent_runtime/` library is storage-agnostic: pure dataclasses, no ORM or framework imports. Key components include AgentLoop, ToolProvider, EventEmitter, AgentDefinition, SubagentsMCP, and MessageCompactor.

The `done()` enforcement is a mechanical gate, not prompt-only. It uses schema constraints, precondition validation, and auto-done fallbacks. Per-agent sandbox containers are managed by the module-coding MCP server based on the `git_scope` YAML property. Context compaction uses LLM summarization with character-to-token ratio calibration via EMA. Subagents support recursive spawning with a depth limit of 10, running in parallel via `asyncio.gather`.

### Framework Survey Context

Research 002 (LLM Orchestration in Apps) surveyed 12 frameworks — LangGraph, Pydantic-AI, DSPy, CrewAI, MAF, Claude Agent SDK, LlamaIndex Workflows, and plain Python — and concluded that "Plain Python (core-stijl)" is the standard. External agent libraries bring version churn, abstraction lock-in, harder debugging, and a larger supply chain.

Research 005 (Sandbox Network Isolation) documented the sandbox security model that our native runtime enforces: per-agent containers, network isolation tiers, and the zero-credentials-in-sandbox constraint that OpenCode could not satisfy.

### Current Dual System

Two runtimes coexist during migration. The legacy Agent (`druppie/agents/runtime.py`) is still used in one orchestrator path and remains coupled to FastAPI and SQLAlchemy. AgentV2 (`druppie/agents/runtime_v2.py`) bridges the storage-agnostic `agent_runtime/` library to the Druppie backend.

### Key Design Principle: Verify, Don't Assume

The OpenCode failure taught us a core principle: agents must verify their output, not assume it works. The sandbox provides a truthful execution environment (real OS, real dependencies, real runtime) where the agent can build, run, and test its code. But the agent itself stays **outside** the sandbox — it has LLM access and tool access, while the sandbox is a credential-free execution environment reached through MCP tool calls. Git access from inside the sandbox is blocked; code flows in and out through a bundle extraction mechanism controlled by tools running outside the sandbox.

This avoids the credential-leakage risk that doomed OpenCode while still giving agents a real environment to verify their work in.

## Decision

Build and maintain `druppie/agent_runtime/` as a native Python library. The runtime is storage-agnostic (pure dataclasses, no ORM or framework imports) and enforces `done()` as a mechanical completion gate. Only two tools are built in (`done` and `subagents`); all other capabilities route through MCP servers. Per-agent sandbox containers are managed by the module-coding MCP server based on the agent's `git_scope` YAML property. Context compaction uses LLM summarization. The AgentV2 facade bridges the library to the Druppie backend.

Keep LiteLLM as the sole external integration for cross-provider LLM access. Retain the legacy Agent (`druppie/agents/runtime.py`) during migration but do not extend it.

## Consequences

**Positive.** Full control over the execution loop means we can implement governance rules (approval gates, sandbox isolation, tool scoping) at the runtime level instead of working around an external framework. HITL and approval integration is tight because the runtime owns the pause and resume lifecycle. The MCP-native tool model lets us scope tools per agent without framework workarounds. Storage-agnostic design makes the library testable in isolation without a database. The `done()` tool acts as a mechanical quality gate: agents cannot finish without declaring their output. The inverted sandbox model — agent outside, sandbox as a credential-free tool — eliminates the credential-leakage risk that OpenCode suffered from while still giving agents a real execution environment to build, test, and verify in.

**Negative.** We maintain our own runtime instead of building on external frameworks. There is no ecosystem leverage: every new runtime feature (context compaction, subagent orchestration, tool routing) is ours to build and maintain. The dual Agent and AgentV2 system persists during migration, with the legacy Agent still used in one orchestrator path. The `agent_runtime` library has no sandbox layer of its own; sandbox lifecycle is delegated to the module-coding MCP server, which was planned but descoped from the initial library. The `open-code-openagent` provider config dependency remains for backward compatibility.
