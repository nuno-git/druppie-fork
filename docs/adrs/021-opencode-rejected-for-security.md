---
id: "021"
title: "Reject OpenCode as agent runtime due to sandbox credential risk"
status: deprecated
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: "004"
linked_prd: null
linked_research: docs/research/005-sandbox-network-isolation.md
---

# ADR 021: Reject OpenCode as agent runtime due to sandbox credential risk

## Context

Druppie needed an agent runtime that could enforce its governance model:
approval gates, sandbox networking, and per-agent tool scoping. The first
external coding-agent framework evaluated was OpenCode.

OpenCode was integrated as a TypeScript control plane **inside** sandbox
containers — the agent process itself lived within the sandbox. Key commits:
`4df3da35` (config), `e8c59a3e` (TDD flow), `f5aaeadf` (timeout fix).

## Decision

**Reject OpenCode.** The architectural decision is: the agent with LLM
access must run outside the sandbox, and the sandbox is a credential-free
tool accessed through MCP.

The critical failure: because OpenCode ran inside the sandbox, it needed a
credential (LLM API key) to call external LLM providers. This credential
lived inside the sandbox container and was reachable by any command
OpenCode executed. An agent that can execute arbitrary shell commands inside
a container that also holds API credentials is fundamentally unsafe.
Druppie's compliance model (BIO, NIS2) requires zero credentials in the
sandbox.

The resulting architecture inversion: git access from inside the sandbox is
blocked; code changes flow through a bundle extraction mechanism operated
by tools running outside the sandbox. The sandbox has no network access and
no credentials — it is a pure execution environment for build, test, and
verify.

Remaining artifacts: `druppie/opencode/config/` (config files survived the
purge), `.git/opencode` (git directory leftover). Removal commit: `62c2f19a`
(2026-05-21).

## Consequences

**Positive.** The credential-leakage risk is eliminated by design. The agent
outside / sandbox as tool pattern is now a core platform invariant. The
OpenCode failure directly informed the "verify, don't assume" principle:
agents run in real sandbox environments to test their output, but the sandbox
itself holds nothing of value.

**Negative.** A working external framework was discarded. The work invested in
OpenCode integration (config, TDD flow, timeout handling) was lost.
