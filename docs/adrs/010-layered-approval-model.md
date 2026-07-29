---
id: "010"
title: Layered approval model for agent tool calls
status: accepted
date: 2026-07-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 010: Layered approval model for agent tool calls

## Context

Agents act through MCP tools, and those tools carry very different risk profiles.
A `read_file` or `list_dir` is safe to run autonomously, while `build`, `run`,
`merge_pull_request`, or `remove` are destructive and need a human to authorize
them. Hard-coding the approval rule for every tool inside the `ToolExecutor` would
be rigid: adding a tool or changing which agent needs approval would require code
changes. Different agents also legitimately need different rules for the same tool
— e.g. one agent may write files freely while another must get an architect's sign
off first.

The forces at play:

- A single, predictable place for the default approval rule of every tool.
- Per-agent flexibility to tighten or loosen that rule without code changes.
- A clear authorization model: not just "needs approval", but "needs approval by a
  specific role".
- Config lives in YAML (`mcp_config.yaml`, agent definitions), not in the database
  or the executor code.

## Decision

Adopt a **two-layer approval model** resolved per tool call by the `ToolExecutor`:

1. **Global defaults** in `druppie/core/mcp_config.yaml` define, for each tool, the
   default approval requirement and (when approval is required) the `required_role`
   that may approve it. This is the baseline rule for every agent.
2. **Per-agent overrides** in agent YAML files via `approval_overrides`. An agent
   can tighten a tool (turn a freely-running tool into one that requires approval)
   or loosen it, and can set its own `required_role`. The override is keyed by
   `<server>:<tool>`:

   ```yaml
   approval_overrides:
     coding:write_file:
       requires_approval: true
       required_role: architect
   ```

**Enforcement in the `ToolExecutor`:** before a tool runs, the executor computes
the effective approval rule (global default, then overridden by any matching agent
override). If the effective rule requires approval, it creates an `Approval`
record and pauses the agent run (status `waiting_approval`) until a human with the
`required_role` approves. Only then does the tool execute. The `ToolCall` database
record is the source of truth; `Approval` records link back to it via
`tool_call_id`.

## Consequences

Positive:

- Centralized defaults make the baseline safety posture easy to audit and change
  in one file.
- Per-agent overrides give legitimate flexibility (tighten sensitive agents,
  loosen trusted ones) without touching executor code.
- Role-based authorization (`required_role`) maps approval authority to real team
  roles (admin, architect, developer, etc.).
- Adding a new tool or agent needs no code change — only YAML.

Negative:

- Override misconfiguration is a risk: an agent could accidentally loosen a
  critical gate, so overrides need review discipline.
- Two config locations (global YAML + per-agent YAML) must be reconciled when
  auditing who can approve what.
- The override layer is resolved at runtime, so the effective rule for a given
  agent/tool is not obvious without tracing global + override together.

## Alternatives Considered

- **Per-tool approval hardcoded in the `ToolExecutor`.** Rejected: rigid — every
  new tool or per-agent exception would need a code change and a redeploy.
- **Single global policy with no overrides.** Rejected: too coarse; agents that
  legitimately need tighter or looser rules for the same tool would have no way to
  express it.
- **Database-driven approval rules.** Rejected: it would make security-sensitive
  rules runtime-mutable and violate the project's config-in-YAML policy; YAML
  keeps rules version-controlled and reviewable.
