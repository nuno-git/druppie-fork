# Workflow Development Guide

Workflows in Druppie allowing you to implement rigid, deterministic, or complex logic in **Go code**, while still leveraging LLMs and MCP tools. This is useful for processes that require loops, retries, or precise state management (e.g., Video Production, Release Pipelines).

## 🛠️ Creating a New Workflow

1.  **Create a file**: Add a new `.go` file in `core/internal/workflows/`.
2.  **Implement Interface**: Your struct must satisfy the `Workflow` interface:
    ```go
    type Workflow interface {
        Name() string
        Run(wc *WorkflowContext, initialPrompt string) error
    }
    ```
3.  **Register**: Add your workflow to `RegisterAll` in `core/internal/workflows/registry.go`.

## 🧠 WorkflowContext Helpers

The `WorkflowContext` (`wc`) provides powerful helpers to interact with the system.

### 1. Calling the LLM (`CallLLM`)

Use `CallLLM` to generate text or structure data. It automatically tracks token usage.

**Signature:**
```go
func (wc *WorkflowContext) CallLLM(prompt, systemPrompt string, opts ...string) (string, *model.TokenUsage, error)
```

**Examples:**
```go
// 1. Basic Usage (Default Provider)
resp, usage, err := wc.CallLLM("Generate a title", "You are a creative assistant")

// 2. Select Specific Provider (e.g. "ollama", "gemini")
//    Useful for cost optimization or privacy.
resp, usage, err := wc.CallLLM("Analyze sensitive data", "System", "ollama")

if err != nil {
    return err
}
// Optionally attach usage to a specific step
wc.AppendStep(model.Step{..., Usage: usage})
```

### 2. Calling Tools / MCP (`mcpManager.Call`)

To invoke tools from the registry (e.g. `read_file`, `git_commit`), use the MCP Manager helper found via `wc.Dispatcher`'s underlying manager (requires access) OR typically workflows access **Executors**.

*Correction*: Workflows usually work via `wc.Dispatcher`. However, if you need direct access, you might inject dependencies.
*Current Best Practice*: Use `wc.Dispatcher.GetExecutor(action)` or the newly added `mcpManager.Call` if available in your scope.

**Note**: If you imported the `mcp` package and have access to the manager instance (often passed or available globally if refactored), you can use:
```go
output, err := mcpManager.Call(ctx, "list_directory", "path", ".")
```

### 3. State & Steps

Workflows should report progress to the UI by appending Steps.

```go
// Add a visible step
stepID := wc.AppendStep(model.Step{
    AgentID: "my-agent",
    Action:  "processing",
    Status:  "running",
    Result:  "Starting task...",
})

// ... do work ...

// Update to completed
wc.AppendStep(model.Step{
    ID:     stepID,
    Status: "completed",
    Result: "Done!",
})
```

## 💡 Best Practices

*   **Resumability**: Check `wc.FindCompletedStep(...)` at the start of your logic to skip phases that already finished (in case of restart/crash).
*   **User Feedback**: Use `wc.OutputChan` to send realtime logs to the user console.
*   **Validation loops**: Use `for` loops combined with LLM calls to retry generation until it passes validation.
