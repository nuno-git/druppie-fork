---
id: "004"
title: "Native Agent Runtime"
status: implemented
author: nuno
date: 2026-05-19
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/004-agent-runtime.md"]
linked_research: ["docs/research/004-agent-runtime.md"]
linked_specs: ["docs/specs/004-agent-runtime.feature"]
---

# PRD 004: Native Agent Runtime

## Problem

External coding-agent frameworks (OpenCode, TypeScript prototype) could not integrate with Druppie's governance model. Agents must operate exclusively through MCP tools with human-in-the-loop approval, per-agent sandboxed execution, and tool scoping based on agent role. Testing individual agents in isolation was impossible with the coupled runtime.

## Goal

A storage-agnostic agent runtime that powers the full Druppie agent pipeline (router through deployer). Agents complete only when they produce required output via done(). Subagents can be spawned for delegation. Context is compacted to prevent overflow. The runtime works identically whether called from the orchestrator, the developer test page, or a retry flow.

## User Journey

1. Agent is defined in YAML (system_prompt, mcps, done_variables, skills)
2. Orchestrator creates a pending agent_run and calls execute_pending_runs
3. AgentV2 loads the YAML definition and enters the LLM<->tool loop
4. Each tool call routes through the ToolExecutor to the appropriate MCP server
5. When the agent calls done() with required variables, the run completes
6. If context grows too large, compaction summarizes prior turns
7. On pause (HITL, approval, sandbox, user stop), the run suspends and can be resumed

## Constraints

Storage-agnostic (no SQLAlchemy/FastAPI imports in agent_runtime/). Only done() and subagents are builtin tools. All other tools are MCP-based. done() is mechanically enforced: no agent can complete without it.

## Out of Scope

Multi-agent parallel execution (subagents are sequential). Direct file I/O by agents (all I/O goes through MCP tools). Sandbox management inside agent_runtime (delegated to module-coding).

## Open Questions

None: feature is implemented.

## Linked Documents

ADR 004, Research 004, Spec.
