---
id: "003"
title: Require tool-only agent communication
status: accepted
date: 2026-06-09
deciders:
  - architect
  - developer
superseded_by: null
enforcement:
  lint_rules: []
  ci_checks:
    - runtime-agent-loop
linked_prd: docs/FEATURES.md#core-philosophy
linked_research: null
---

## Context

Druppie is a governance platform for AI agents. Agents operate within the platform by interacting with external systems through MCP (Model Context Protocol) tools. The core philosophy is that every agent action must be observable, auditable, and governable.

When agents respond with raw text instead of tool calls, several problems arise:

- **Ungovernable actions**: Text output bypasses the approval workflow entirely. There is no tool call to intercept, approve, or deny.
- **No audit trail**: Freeform text cannot be structured into the tool call audit log that the platform maintains.
- **Unpredictable runtime behavior**: The agent orchestration loop expects tool calls to drive state transitions. Raw text responses leave the loop in an undefined state.
- **Security risk**: An agent that avoids tool calls can circumvent permission boundaries and approval gates.

## Decision

Agents must communicate exclusively through MCP tool calls. They must never produce raw text output as their primary response.

**Rules:**

1. Every agent response must contain at least one tool call.
2. If an agent needs to communicate information to the user, it must use a designated communication tool (e.g., a messaging or response tool) rather than raw text.
3. The LLM runtime (`AgentLoop` in `druppie/execution/loop.py`) sends correction messages when an agent responds without tool calls, instructing it to use tools instead.
4. After a configurable number of consecutive non-tool responses, the agent run is terminated with an error status.

**Runtime enforcement flow:**

```
Agent responds → Check for tool calls →
  Yes: process tool calls, continue loop
  No:  send correction message, increment counter →
    Counter < max: retry
    Counter >= max: terminate run with error
```

## Consequences

**Positive:**

- Every agent action flows through the governance layer and is subject to approval workflows.
- Complete audit trail of all agent actions via structured tool call records.
- Permission boundaries are enforced consistently — no bypass vectors through raw text.
- The agent runtime remains in a well-defined state machine with predictable transitions.

**Negative:**

- Agents that naturally want to "explain" before acting must use a tool call for that explanation, adding latency.
- The correction-and-retry mechanism consumes LLM tokens on non-productive turns.
- Agents designed outside Druppie must be adapted to use tool-only communication.

## Compliance

Compliance is enforced at runtime:

1. **AgentLoop runtime check**: The execution loop in `druppie/execution/loop.py` inspects every LLM response for tool calls. Non-tool responses trigger the correction flow.
2. **Run termination**: Runs that exceed the maximum consecutive non-tool responses are terminated and logged.
3. **Monitoring**: Terminated runs due to non-tool responses are tracked as a metric for agent quality assessment.

## Enforcement

When an agent responds without tool calls:

1. **Runtime correction**: The `AgentLoop` sends a system message instructing the agent to use tools.
2. **Retry**: The agent is given another opportunity to respond with tool calls.
3. **Termination**: If the agent repeatedly fails to use tools (exceeding the configured threshold), the run is terminated with an `AgentRunStatus` indicating the failure reason.
4. **Logging**: The correction attempts and termination are recorded in the agent run detail for debugging.
