# Extending Druppie Core

This guide explains how to extend the core functionality by adding **Executors** or **Workflows**.

---

## 🏗️ Adding a New Executor

Executors are responsible for performing specific actions (steps) defined in a plan. If you need to handle a new type of action (e.g. `send_slack_message`) natively in Go, you create an Executor.

### 1. Create the Executor

Create a new file in `core/internal/executor/`, e.g. `slack_executor.go`.

```go
package executor

import (
	"context"
	"fmt"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

type SlackExecutor struct {
    // Inject dependencies here if needed (e.g. Config, API Client)
    WebHookURL string
}

// CanHandle determines if this executor owns the action
func (e *SlackExecutor) CanHandle(action string) bool {
    return action == "send_slack_message"
}

// Execute runs the logic
func (e *SlackExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
    outputChan <- "[Slack] Sending message..."
    
    msg, _ := step.Params["message"].(string)
    if msg == "" {
        return fmt.Errorf("missing message param")
    }

    // ... Logic to send message ...
    
    outputChan <- fmt.Sprintf("Message sent: %s", msg)
    return nil
}
```

### 2. Register the Executor

Open `core/internal/executor/dispatcher.go`.
Add your executor to the `NewDispatcher` list.

```go
func NewDispatcher(...) *Dispatcher {
    return &Dispatcher{
        executors: []Executor{
            // ... existing ...
            &SlackExecutor{WebHookURL: "https://..."}, // Register here
            &MCPExecutor{...},
        },
    }
}
```
**Note**: The order matters. Executors are checked sequentially.

---

## 🔄 Adding a New Workflow

Workflows are high-level processes that orchestrate multiple steps and agents.

### 1. Create the Workflow

Create a new file in `core/internal/workflows/`, e.g. `release_flow.go`.

```go
package workflows

import (
	"fmt"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

type ReleaseWorkflow struct{}

func (w *ReleaseWorkflow) Name() string { 
    return "release-pipeline" 
}

func (w *ReleaseWorkflow) Run(wc *WorkflowContext, initialPrompt string) error {
    wc.OutputChan <- "🚀 Starting Release Workflow..."

    // 1. Call LLM for prep
    resp, usage, err := wc.CallLLM("Generate release notes based on...", "System")
    if err != nil {
        return err
    }
    // Attach usage to a step if desired
    wc.AppendStep(model.Step{
        AgentID: "release-bot",
        Action:  "generate_notes",
        Status:  "completed",
        Result:  resp,
        Usage:   usage,
    })

    // 2. Execute a Tool Step
    // ...
    
    return nil
}
```

### 2. Register the Workflow

Open `core/internal/workflows/registry.go`. (Note: You may need to create a manual registration hook if `RegisterAll` doesn't pick it up automatically or if there isn't a central registry file yet. Currently `RegisterAll` in `manager.go` or individual `init()` functions are used).

*Check Implementation*: Druppie uses a `Manager` with a `Register` method.
Usually `core/druppie/main.go` or `workflows` package has an `init` pattern.

If `core/internal/workflows/registry.go` exists, add it there.
If not, look for `RegisterAll`.

*Example:*
```go
func RegisterAll(m *Manager) {
    m.Register(&VideoCreationWorkflow{})
    m.Register(&ReleaseWorkflow{}) // Add this
}
```
