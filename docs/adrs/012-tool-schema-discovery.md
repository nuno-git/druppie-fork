---
id: "012"
title: Discover Tool Schemas Dynamically via MCP tools/list
status: accepted
date: 2026-07-16
deciders:
  - Nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: docs/TECHNICAL.md
---

## Context

Druppie agents call tools hosted on MCP microservices (`module-coding`, `module-docker`,
`module-web`, …). Each tool has a name, description, and JSON-schema parameter definition that must
be conveyed to the LLM so it can call the tool correctly. The question is where that schema lives.

The forces at play:

- **Drift.** If a tool schema is declared in two places (the MCP server's `@mcp.tool()` decorator
  *and* a copy in the backend), they inevitably diverge. The backend would describe a parameter the
  server no longer accepts, or omit one it now requires, and the LLM would call the tool wrongly.
- **Discoverability vs. duplication.** MCP defines a `tools/list` endpoint precisely so a client can
  learn what a server offers. Hard-coding the same schemas on the client side negates that.
- **OpenAI strict mode.** The LLM tool definitions must follow OpenAI strict-mode rules
  (`additionalProperties: false`, all properties in `required`, nullable optionals). Whatever the
  source of truth, the emitted schema must comply.
- **Operational reality.** Tool sets evolve: new tools are added, parameters renamed. The backend
  should never need a hand edit to stay in sync with a server it already talks to.

Historically the backend carried hand-maintained Pydantic models per tool under `druppie/tools/params/`,
duplicating the decorator-level schemas and routinely drifting from them.

## Decision

Tool schemas are discovered **dynamically via MCP `tools/list`** calls. The MCP server's
`@mcp.tool()` decorator is the **single source of truth** for every tool's name, description, and
parameter schema. The backend holds **no** hardcoded tool schemas.

Concretely:

- At startup, `ToolRegistry` (`druppie/core/tool_registry.py`) calls each configured MCP server's
  `tools/list` endpoint and builds `ToolDefinition` objects (`druppie/domain/tool.py`) from the live
  responses. It merges in approval requirements read from `mcp_config.yaml`.
- `mcp_config.yaml` contains **only** server URLs, approval rules, and parameter-injection rules —
  never tool schemas.
- The old `druppie/tools/params/` directory (hand-maintained Pydantic models per tool) no longer
  exists; schemas come exclusively from the modules.
- `registry.to_openai_format()` converts the discovered definitions into OpenAI function schemas,
  following strict mode (`strict: true`, `additionalProperties: false`, all properties in
  `required`, nullable optionals via the `anyOf: [{type}, {type: null}]` pattern).
- `registry.get_tools_for_agent(...)` scopes an agent's tool set by its declared MCP permissions and
  builtin tools.

## Consequences

Positive:

- **Single source of truth.** A tool's schema exists in exactly one place — the `@mcp.tool()`
  decorator. Adding or changing a tool means editing the server only; the backend picks it up
  automatically on next startup.
- **No drift.** Because there is no second copy, the backend can never disagree with the server about
  a tool's contract.
- **Conservative failure.** If a server is unreachable at startup, its tools are simply absent rather
  than described wrongly.

Negative:

- **Startup dependency on live servers.** Schema discovery requires every MCP server to be reachable
  at startup. An unreachable server means its tools are unavailable until the backend restarts.
- **No offline introspection.** You cannot read the tool schemas from the backend source alone — you
  must run the servers (or read their `v1/tools.py`).
- **Implicit contract changes.** A server-side schema change silently changes what the LLM is told on
  the next restart, with no diff review on the backend side.

## Alternatives Considered

- **Hand-maintained Pydantic models per tool (the former `druppie/tools/params/` approach).**
  Rejected: it is a second copy of the schema and drifts from the decorator in practice. This ADR
  formalises its removal.
- **Tool schemas duplicated in `mcp_config.yaml`.** Rejected for the same duplication/drift reason;
  `mcp_config.yaml` is restricted to URLs, approval rules, and injection rules only.
- **Static schema files generated at build time from the servers.** Rejected: it adds a build step
  and a generation+commit+deploy loop, reintroducing a stale-copy risk that live `tools/list`
  avoids.
