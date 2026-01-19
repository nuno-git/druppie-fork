# Druppie

**AI-Powered Task Orchestration Platform**

Druppie is a sophisticated autonomous workflow execution system written in Go. It combines LLM-based planning with step-by-step execution, enabling multi-agent coordination for complex tasks like code generation, content creation, and infrastructure management.

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Technical Deep Dive](#technical-deep-dive)
- [API Reference](#api-reference)
- [Extensibility](#extensibility)

---

## Features

- **Multi-LLM Support**: Gemini, Ollama, OpenRouter, Z.AI providers with cost tracking
- **Autonomous Planning**: Natural language input converted to executable step-by-step plans
- **Multi-Agent Orchestration**: Specialized agents (Developer, Architect, Content Creator, etc.)
- **Parallel Execution**: Independent steps run concurrently with dependency resolution
- **Interactive Workflows**: Approval gates, user questions, and content review steps
- **Cost Safety**: Configurable spending limits with automatic pause on threshold
- **MCP Integration**: Model Context Protocol for external tool providers
- **Native Workflows**: Optimized execution paths for specific agent types
- **Enterprise IAM**: Local, Keycloak, and demo identity providers
- **Web UI & CLI**: Both browser-based and terminal interfaces

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│                   (Web UI / CLI / Chat)                          │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API Server (chi/v5)                         │
│              POST /chat/completions, GET /plans, etc.            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌─────────────────┐     ┌─────────────────────┐
│     Router      │     │      Registry       │
│ (Intent Analysis)│     │ (Blocks/Skills/    │
└────────┬────────┘     │  Agents/MCP)        │
         │              └─────────────────────┘
         ▼
┌─────────────────┐     ┌─────────────────────┐
│     Planner     │────▶│   ExecutionPlan     │
│ (Step Generation)│     │   (Steps, Status)   │
└─────────────────┘     └──────────┬──────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Task Manager                                │
│        (Async Execution, Dependency Resolution, I/O)             │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Dispatcher                                 │
│   ┌──────────┬──────────┬──────────┬──────────┬──────────┐      │
│   │Developer │  Build   │   MCP    │ Content  │ Standard │      │
│   │ Executor │ Executor │ Executor │ Executor │ Executor │      │
│   └──────────┴──────────┴──────────┴──────────┴──────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites

- Go 1.24+
- Docker (optional, for containerized execution)
- An LLM provider (Ollama for local, or API key for Gemini/OpenRouter/Z.AI)

### Build from Source

```bash
cd core
go build -o druppie ./druppie
```

### Docker

```bash
docker-compose up -d
```

### First Run

On first startup, Druppie creates a `.druppie/` directory with default configuration:

```bash
./druppie serve
# or
./druppie chat
```

---

## Configuration

Configuration is stored in `.druppie/config.yaml`. A default template is generated on first run.

### LLM Providers

```yaml
llm:
  default_provider: ollama
  providers:
    ollama:
      type: ollama
      model: qwen3:8b
      url: http://localhost:11434
      price_per_prompt_token: 0.0
      price_per_completion_token: 0.0

    gemini:
      type: gemini
      model: gemini-2.0-flash
      api_key: ${GEMINI_API_KEY}
      price_per_prompt_token: 0.075
      price_per_completion_token: 0.30

    openrouter:
      type: openrouter
      model: anthropic/claude-3.5-sonnet
      api_key: ${OPENROUTER_API_KEY}
```

### Build Engines

```yaml
build:
  default_provider: docker
  providers:
    docker:
      type: docker
      working_dir: .
    local:
      type: local
      working_dir: .
```

### IAM

```yaml
iam:
  provider: local  # local, keycloak, demo
  local:
    users:
      admin:
        password_hash: $2a$10$...
        groups: [admin, developers]
```

### Cost Safety

```yaml
general:
  max_unattended_cost: 1.0  # EUR - pauses execution if exceeded without user interaction
```

---

## Usage

### CLI Commands

```bash
# Start the API server (default port 8080)
druppie serve

# Interactive chat mode
druppie chat

# Execute a single task
druppie run "Create a REST API for user management"

# Execute with auto-approval (no prompts)
druppie run --auto-pilot "Build a hello world app"

# Resume a paused plan
druppie resume <plan-id>

# Show loaded registry
druppie registry

# Login/logout
druppie login
druppie logout

# Manage MCP servers
druppie mcp list
druppie mcp add <name> <url>
```

### Web Interface

After starting the server, access:
- Main UI: `http://localhost:8080/`
- Admin: `http://localhost:8080/admin.html`
- Chat: `http://localhost:8080/chat/`

---

## Technical Deep Dive

### Request Processing Pipeline

1. **Intent Analysis (Router)**
   - User input is sent to the LLM with a classification prompt
   - Returns an `Intent` with: action, category, language, content type
   - Actions: `general_chat`, `create_project`, `update_project`, `orchestrate_complex`

2. **Plan Generation (Planner)**
   - Selects relevant agents based on intent
   - Generates `ExecutionPlan` with ordered steps
   - Each step has: action, parameters, dependencies, assigned agent

3. **Async Execution (TaskManager)**
   - Spawns goroutine per plan
   - Resolves step dependencies
   - Executes independent steps in parallel batches
   - Handles interactive steps (questions, approvals)

4. **Step Execution (Dispatcher → Executor)**
   - Routes steps to specialized executors
   - Captures output via channel protocol
   - Tracks token usage and costs

### Core Data Types

```go
// Intent represents analyzed user input
type Intent struct {
    InitialPrompt string
    Prompt        string
    Action        string    // create_project, general_chat, etc.
    Category      string    // infrastructure, service, content
    ContentType   string    // video, code, image
    Language      string    // en, nl, fr
}

// ExecutionPlan represents a complete task plan
type ExecutionPlan struct {
    ID             string
    CreatorID      string
    Intent         Intent
    Status         string      // pending, running, completed, stopped
    Steps          []Step
    SelectedAgents []string
    TotalUsage     TokenUsage
    TotalCost      float64
}

// Step represents a single execution unit
type Step struct {
    ID            int
    AgentID       string
    Action        string
    Params        map[string]interface{}
    Result        string
    Status        string      // pending, running, completed, waiting_input, failed
    DependsOn     []int       // Step IDs this depends on
    AssignedGroup string      // For approval routing
}
```

### Execution Loop Algorithm

```go
func runTaskLoop(task *Task) {
    for {
        // Find steps ready to execute (dependencies met)
        batch := identifyRunnableSteps(task.Plan)

        if len(batch) == 0 {
            if allStepsCompleted(task.Plan) {
                task.Status = Completed
                return
            }
            handleStuckState(task)
            continue
        }

        // Check for native workflow override
        if workflow := getWorkflow(currentAgent); workflow != nil {
            workflow.Run(context, prompt)
            return
        }

        // Execute batch in parallel
        var wg sync.WaitGroup
        for _, stepIdx := range batch {
            wg.Add(1)
            go func(idx int) {
                defer wg.Done()
                executeStep(task, idx)
            }(stepIdx)
        }
        wg.Wait()

        // Handle interactive steps
        if task.Status == WaitingInput {
            answer := <-task.InputChan
            applyUserInput(task, answer)
        }
    }
}
```

### Executor Pattern

Executors implement a common interface:

```go
type Executor interface {
    Execute(ctx context.Context, step model.Step, outputChan chan<- string) error
    CanHandle(action string) bool
}
```

The `Dispatcher` routes steps to executors in priority order:
1. MCPExecutor - External MCP tools
2. AudioCreatorExecutor - TTS/audio generation
3. VideoCreatorExecutor - Video generation
4. DeveloperExecutor - Code creation/modification
5. BuildExecutor - Compilation
6. RunExecutor - Execution
7. ComplianceExecutor - Approvals
8. StandardExecutor - Infrastructure (fallback)

### Output Channel Protocol

Executors communicate results via a channel with special prefixes:

```
RESULT_CONSOLE_OUTPUT=<visible output>
RESULT_TOKEN_USAGE=<prompt>,<completion>,<total>,<cost>
<any other text> → logged output
```

### Token Usage & Cost Tracking

```go
type TokenUsage struct {
    PromptTokens     int
    CompletionTokens int
    TotalTokens      int
    EstimatedCost    float64  // EUR
}

// Cost calculation
cost := (promptTokens * pricePerPromptToken +
         completionTokens * pricePerCompletionToken) / 1_000_000
```

Costs are tracked at three levels:
- **Step level**: `Step.Usage`
- **Plan level**: `Plan.TotalUsage` (accumulated)
- **Interaction level**: `Plan.LastInteractionTotalCost` (checkpoint for safety)

### File-Based Persistence

```
.druppie/
├── config.yaml              # Runtime configuration
├── plans/
│   └── plan-<id>/
│       ├── plan.json        # Serialized ExecutionPlan
│       ├── interactions.jsonl # Audit trail
│       ├── logs.txt         # Execution logs
│       ├── memory.json      # Chat context
│       └── files/           # Uploaded/generated files
└── iam/
    └── users.json           # Local user store
```

### MCP (Model Context Protocol) Integration

Druppie supports MCP servers for external tool integration:

```go
type MCPServer struct {
    Name        string
    Description string
    URL         string      // SSE endpoint
    Command     string      // Or stdio command
    Args        []string
    Env         map[string]string
}
```

The MCP Manager:
- Discovers tools from connected servers
- Routes tool calls to appropriate servers
- Merges static registry tools with dynamic MCP tools

---

## API Reference

### Authentication

Protected endpoints require a session token in the `Authorization` header:
```
Authorization: Bearer <session-token>
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/version` | Version info |
| POST | `/chat/completions` | Submit task (returns plan) |
| GET | `/registry` | List building blocks |
| GET | `/plans` | List user's plans |
| GET | `/plans/{id}` | Get plan details |
| POST | `/plans/{id}/resume` | Resume paused plan |
| POST | `/plans/{id}/stop` | Stop execution |
| DELETE | `/plans/{id}` | Delete plan |
| POST | `/plans/{id}/files` | Upload file |
| GET | `/plans/{id}/files` | List plan files |
| GET | `/logs/{id}` | Get execution logs |
| GET | `/agents` | List available agents |
| GET | `/skills` | List available skills |
| GET | `/tasks` | Get pending approval tasks |
| POST | `/tasks/{id}/message` | Send user input |

### Example: Submit Task

```bash
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "messages": [
      {"role": "user", "content": "Create a Python Flask API with user authentication"}
    ]
  }'
```

Response:
```json
{
  "plan": {
    "id": "plan-1705678901234",
    "status": "running",
    "steps": [...]
  },
  "intent": {
    "action": "create_project",
    "category": "service"
  }
}
```

---

## Extensibility

### Adding a New Executor

1. Create executor in `core/internal/executor/`:

```go
type MyExecutor struct {
    logger *slog.Logger
}

func NewMyExecutor(logger *slog.Logger) *MyExecutor {
    return &MyExecutor{logger: logger}
}

func (e *MyExecutor) CanHandle(action string) bool {
    return action == "my_action"
}

func (e *MyExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
    // Implementation
    outputChan <- "RESULT_CONSOLE_OUTPUT=" + result
    return nil
}
```

2. Register in `dispatcher.go`:

```go
func NewDispatcher(...) *Dispatcher {
    return &Dispatcher{
        executors: []Executor{
            NewMyExecutor(logger),
            // ... other executors
        },
    }
}
```

### Adding a New LLM Provider

1. Implement the `Provider` interface:

```go
type Provider interface {
    Generate(ctx context.Context, prompt string, systemPrompt string) (string, TokenUsage, error)
    Close() error
}
```

2. Add factory case in `NewManager()`:

```go
case "myprovider":
    return NewMyProvider(cfg)
```

### Adding a Native Workflow

1. Implement the `Workflow` interface:

```go
type MyWorkflow struct{}

func (w *MyWorkflow) Name() string {
    return "my_agent"
}

func (w *MyWorkflow) Run(wc *WorkflowContext, initialPrompt string) error {
    // Optimized execution flow
    return nil
}
```

2. Register in `RegisterAll()`:

```go
func RegisterAll() {
    Register(&MyWorkflow{})
}
```

---

## Project Structure

```
druppie-fork/
├── core/
│   ├── druppie/
│   │   ├── main.go           # CLI entry point & API server (2,327 lines)
│   │   └── task_manager.go   # Async execution engine (1,586 lines)
│   ├── internal/
│   │   ├── config/           # Configuration management
│   │   ├── executor/         # Step executors
│   │   ├── iam/              # Identity & access control
│   │   ├── llm/              # LLM provider abstraction
│   │   ├── mcp/              # MCP protocol integration
│   │   ├── memory/           # Chat context management
│   │   ├── model/            # Core data types
│   │   ├── planner/          # Plan generation
│   │   ├── registry/         # Capability registry
│   │   ├── router/           # Intent analysis
│   │   ├── store/            # Persistence layer
│   │   └── workflows/        # Native workflow engine
│   └── deploy/helm/          # Kubernetes deployment
├── sherpa-server/            # TTS microservice
├── ui/                       # Web frontend
│   ├── chat/                 # Chat interface
│   └── views/                # View templates
├── docker-compose.yml
└── Dockerfile
```

---

## License

See LICENSE file for details.
