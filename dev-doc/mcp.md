# MCP Server Configuration

The **Model Context Protocol (MCP)** allows Druppie to connect to external tools and data sources. This guide explains how to add, configure, and manage MCP servers.

## 1. What is an MCP Server?

An MCP server is a standalone process (or container) that exposes "Tools" and "Resources" over a standard protocol (JSON-RPC). Druppie acts as the **Host/Client**.

Commmon examples:
*   `filesystem`: Read/Write files.
*   `git`: Clone, commit, push.
*   `postgres`: Query a database.

## 2. Adding an MCP Server

There are two primary ways to register an MCP server in Druppie.

### A. Static Registration (The "Registry" Way)

For servers that should always be available (Infrastructure), define them in the **Registry**.
Usually, this is done by adding a markdown file in the `mcp/` directory of your workspace (e.g. `mcp/my-server.md`).

**Format:**
```markdown
---
name: my-custom-server
type: mcp
category: utility
command: docker
args:
  - run
  - -i
  - --rm
  - my-org/mcp-server:latest
---
# My Custom Server
Description of what this server does.
```
*   **Command**: The executable to run (usually `docker` or `node`).
*   **Args**: Arguments for the command.

### B. Dynamic Registration (Development/Runtime)

For temporary or local testing, you can register a server via the API or CLI (if available).
These configs are stored in `.druppie/mcp_servers.json`.

**Via API (`POST /v1/mcp/servers`):**
```json
{
  "name": "local-dev-server",
  "url": "http://localhost:3000" // If using HTTP transport (SSE)
}
```
*Note: Currently Druppie Core focuses on Stdio transport for Registry servers.*

## 3. Configuring Server Arguments

Many MCP servers require environment variables (API Keys) or specific arguments (Allowed Paths).

### Environment Variables
Druppie passes its own environment variables to the MCP processes. You can set them in your `.env` file or export them before running Druppie.
*   `GITHUB_TOKEN` -> Passed to Git MCP.
*   `POSTGRES_URL` -> Passed to DB MCP.

### Arguments in Registry
You can hardcode arguments in the registry frontmatter:
```yaml
args:
  - --allowed-paths=/tmp
  - --debug
```

## 4. MCP Transport Modes

1.  **Stdio (Standard Input/Output)**:
    *   **Default** for most servers.
    *   Druppie spawns the process (`docker run ...`) and communicates via Stdin/Stdout.
    *   Secure and isolated.

2.  **HTTP (SSE)**:
    *   Used for remote servers or local development where you run the server separately.
    *   Configure via `url` field instead of `command`.

## 5. Troubleshooting

*   **Logs**: Check the Druppie Core console output. MCP stderr is usually piped there.
*   **Connection Refused**: If using HTTP, ensure the server is running.
*   **Permission Denied**: If using Docker, ensure the volume mounts are correct (Druppie handles some default mounts for `.druppie` dir).
