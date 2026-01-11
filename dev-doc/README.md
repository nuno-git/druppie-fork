# Druppie Core Technical Documentation

Welcome to the technical documentation for **Druppie Core**, the central orchestration engine of the Druppie platform. This directory contains detailed information for developers working on or extending the core logic.

## 📚 Documentation Index

*   **[Architecture & Internals](./architecture.md)**
    *   High-level system design.
    *   Component breakdown (`registry`, `planner`, `executor`, `mcp`).
    *   Data flow of a user request.
*   **[Workflow Development](./workflows.md)** -- **Start Here if adding Features**
    *   How to create new Go-based Workflows.
    *   Using the `WorkflowContext` helpers (e.g. `CallLLM`).
    *   Calling MCP tools programmatically.
*   **[Extending Druppie (Executors)](./extensions.md)**
    *   How to add new native `Executors` (Go logic for specific steps).
    *   Registering new components.
*   **[MCP Server Config](./mcp.md)**
    *   Adding and configuring Model Context Protocol servers.
    *   Static vs Dynamic registration.
*   **[Agent Definitions](./agents.md)**
    *   Creating new Agents (Markdown format).
    *   Linking Agents to Native Workflows.
*   **[API Reference](./api.md)**
    *   HTTP Endpoints (`/v1/...`).
    *   WebSocket / Real-time events (if applicable).
*   **[Deployment & Config](../core/deploy/helm/README.md)**
    *   Helm Chart documentation (located in `core/deploy`).
    *   Configuration options (`config.yaml`).

## 🚀 Quick Start (Local Development)

### Prerequisites
*   Go 1.23+
*   Docker (for running dependencies or MCP servers)

### Running the Server
```bash
# From project root
go run core/druppie/main.go serve
```
The server will start on port `8080` (default).

### Configuration
Druppie Core looks for configuration in `.druppie/config.yaml` or environment variables.
See [Deployment Config](../core/deploy/helm/README.md) for full details on `LLM`, `IAM`, and `Build` settings.

## 📂 Project Structure (`/core`)

*   **`cmd/` / `druppie/`**: Entry points (CLI and Server).
*   **`internal/`**: Core logic packages.
    *   `planner`: AI Planning engine (Generates steps).
    *   `executor`: Executes steps (MCP tools, internal logic).
    *   `mcp`: Model Context Protocol implementation.
    *   `workflows`: Hardcoded, complex business logic flows.
    *   `llm`: Abstraction layer for Gemini, Ollama, etc.
    *   `store`: File-based persistence.
*   **`deploy/`**: Helm charts and container configs.
