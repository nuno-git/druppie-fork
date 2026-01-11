# Agent Definition Guide

In Druppie, Agents are defined as Markdown files in the `agents/` directory (e.g. `agents/my-agent.md`).

## 📄 File Format

Agents use a YAML Frontmatter block followed by the System Instructions.

```markdown
---
id: my-custom-agent
name: "My Custom Agent"
description: "Handles specialized tasks for the domain."
type: exec-agent
sub_agents: []  # Optional: List of agents this agent manages (for hierarchies)
native: false   # Set to 'true' if backed by Go workflow
skills: ["read_file", "write_file", "git_commit"]
priority: 100.0 # Selection priority (higher = more likely to be picked by planner)
prompts:        # Optional: Custom prompts used by Go logic
  custom_task: |
    Perform task X...
workflow: |     # Optional: Mermaid diagram for logic documentation
  stateDiagram
    [*] --> TaskA
    TaskA --> [*]
---

# System Instructions

You are the My Custom Agent. Your role is to...

## Capabilities
- You can read and write files.
- You understand Git concepts.

## Rules
1. Always verify file existence before reading.
2. ...
```

## 🔑 Key Fields

*   **id**: Unique identifier (used in Planner and code).
*   **type**:
    *   `spec-agent`: High-level planning/architecture.
    *   `exec-agent`: Task execution (tools).
    *   `system`: Internal logic.
*   **native**:
    *   `false` (Default): The agent is "Virtual". The Planner generates steps, and the LLM executes them generically using the defined Instructions.
    *   `true`: The agent maps to a **Native Go Workflow**. The Instructions are still used for context, but the execution logic is hardcoded in Go.

## 🔗 Linking to Native Workflows

If you set `native: true`, you MUST implement a corresponding Workflow in Go (see [Workflow Development](./workflows.md)).

1.  **Go Workflow Name**: Your Go struct `Name()` must match the agent's `id`.
    ```go
    func (w *MyWorkflow) Name() string { return "my-custom-agent" }
    ```
2.  **Behavior**: When the Planner selects this agent, instead of decomposing the task deeply itself, it hands off control to your `Run(wc, ...)` method.

## 📝 Custom Prompts

For Native Agents, you often need specific prompts for internal steps (e.g. "Refine Intent", "Draft Script"). Instead of hardcoding them in Go strings, define them in the Markdown frontmatter under `prompts:`.

**Usage in Go:**
```go
agent, _ := wc.GetAgent("my-custom-agent")
sysPrompt := agent.Prompts["custom_task"]
```

## 🛠️ Skills & Tools

List the MCP tools or internal skills the agent is allowed to use.
*   `read_file`, `write_file` (Standard File System)
*   `git_clone`, `git_commit` (Git MCP)
*   `ask_questions`, `content-review` (Internal Skills)
