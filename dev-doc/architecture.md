# System Architecture

Druppie Core follows a modular, service-oriented architecture designed to orchestrate AI agents and tools. It acts as the "brain", receiving user intents and translating them into executable plans.

## 🔄 Request Lifecycle

1.  **Ingestion**: A user sends a request to `POST /v1/chat/completions`.
2.  **Routing (`internal/router`)**:
    *   The **Router** (LLM-based) analyzes the intent.
    *   It decides if the request requires a complex **Plan**, a specific **Workflow**, or just a **Chat Response**.
3.  **Planning (`internal/planner`)**:
    *   If a plan is needed, the Planner generates a JSON-based `ExecutionPlan`.
    *   It selects appropriate **Agents** from the `Registry`.
    *   It breaks the task into **Steps**.
4.  **Execution (`core/druppie/task_manager.go`)**:
    *   The `TaskManager` runs a background loop for the plan.
    *   It iterates through steps, resolving dependencies.
    *   It dispatches steps to the appropriate **Executor**.
5.  **Execution Channels (`internal/executor`)**:
    *   **MCP**: Calls external tools via Model Context Protocol.
    *   **Plugin**: Runs local scripts/containers (Legacy).
    *   **Workflow**: Executes hardcoded Go logic.

## 🧩 Key Components

### 1. Registry (`internal/registry`)
The Registry is the source of truth for capabilities. It loads:
*   **Building Blocks**: Infrastructure definitions (Helm charts, Terraform).
*   **Skills/Tools**: MCP tool definitions.
*   **Agents**: AI Personas with specific prompts and tool access.
*   **Compliance**: Policy rules.

### 2. planner (`internal/planner`)
The core intelligence. It uses the LLM to:
*   Understand the context (History/Memory).
*   Select the best agents for the job.
*   Generate a DAG (Directed Acyclic Graph) of steps.

### 3. MCP Manager (`internal/mcp`)
Manages connections to Model Context Protocol servers.
*   **Static Servers**: Defined in `registry` (e.g. `filesystem`).
*   **Dynamic Servers**: Provisioned at runtime (e.g. `plan-scoped` servers).
*   **Tool Execution**: Routes `call_tool` requests to the correct server.

### 4. Store (`internal/store`)
Persistence layer. Currently implements a **File System Store** in `.druppie/`.
*   **Plans**: Saved as JSON.
*   **Logs**: Execution logs stored per plan.
*   **Config**: Global configuration.

## 🏗️ Internal Package Structure

The `internal` directory isolates core logic.
*   `llm`: Provider-agnostic LLM interface (Gemini, Ollama, OpenRouter).
*   `iam`: Identity and Access Management (Local/Keycloak).
*   `builder`: CI/CD integration (Tekton).
*   `workflows`: Go-native implementation of complex processes.
