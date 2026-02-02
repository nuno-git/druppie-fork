# MCP Builder Template

Use this document as a template to create new MCP (Model Context Protocol) servers for Druppie.

## MCP Server Structure

Create a new directory in `mcp-servers/YOUR-MCP-NAME/` with these files:

```
mcp-servers/YOUR-MCP-NAME/
├── Dockerfile          # Container definition
├── module.py          # Business logic class
├── server.py          # FastMCP HTTP server wrapper
├── requirements.txt    # Python dependencies
└── README.md          # Documentation (optional)
```

---

## File: module.py (Business Logic)

This file contains all the business logic for your MCP server.

```python
"""YOUR-MCP-NAME MCP Server - Business Logic Module.

Describe what this MCP server does here.
"""

import logging
from typing import Any
from pathlib import Path

logger = logging.getLogger("YOUR-Mcp-NAME-mcp")


class YourModule:
    """Business logic module for YOUR-MCP-NAME operations."""

    def __init__(
        self,
        # Add configuration parameters here
        workspace_root: str,
        # Add more params as needed
    ):
        """Initialize the module.

        Args:
            workspace_root: Base path for workspaces
            # Add more param descriptions
        """
        self.workspace_root = Path(workspace_root)
        # Add more initialization logic

    # =============================================================================
    # TOOL 1: Example Tool
    # =============================================================================

    async def example_tool(
        self,
        workspace_id: str,
        param1: str,
        param2: int | None = None,
    ) -> dict:
        """Do something useful.

        Args:
            workspace_id: Workspace identifier
            param1: Description of param1
            param2: Optional description of param2

        Returns:
            Dictionary with success status and result data
        """
        try:
            logger.info("Executing example_tool in workspace %s", workspace_id)

            # Your business logic here

            return {
                "success": True,
                "result": "operation completed",
                # Add more fields as needed
            }

        except Exception as e:
            logger.error("Error in example_tool: %s", str(e))
            return {
                "success": False,
                "error": str(e),
            }

    # =============================================================================
    # ADD MORE TOOLS HERE
    # =============================================================================
```

---

## File: server.py (FastMCP Wrapper)

This file wraps your module with FastMCP and exposes it as an HTTP server.

```python
"""YOUR-MCP-NAME MCP Server.

Short description of what this server does.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP

from module import YourModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("YOUR-Mcp-NAME-mcp")

mcp = FastMCP("YOUR-MCP-NAME MCP Server")

# Environment variables
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", "/workspaces")
# Add more env vars as needed

module = YourModule(
    workspace_root=WORKSPACE_ROOT,
    # Pass more configuration here
)


# =============================================================================
# TOOL 1: example_tool
# =============================================================================

@mcp.tool()
async def example_tool(
    workspace_id: str,
    param1: str,
    param2: int | None = None,
) -> dict:
    """Do something useful.

    Args:
        workspace_id: Workspace identifier
        param1: Description of param1
        param2: Optional description of param2

    Returns:
        Dictionary with success status and result data
    """
    return await module.example_tool(
        workspace_id=workspace_id,
        param1=param1,
        param2=param2,
    )


# =============================================================================
# ADD MORE TOOL WRAPPERS HERE
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    # Health check endpoint
    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "YOUR-Mcp-NAME-mcp"
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "900X"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
```

---

## File: Dockerfile

```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed
# RUN apt-get update && apt-get install -y \
#     some-package \
#     && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY module.py .
COPY server.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MCP_PORT=900X
ENV WORKSPACE_ROOT=/workspaces

# Expose MCP port
EXPOSE 900X

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:900X/health || exit 1

# Run the server
CMD ["python", "server.py"]
```

---

## File: requirements.txt

```txt
fastmcp>=0.4.0
# Add your dependencies here
# Example:
# httpx>=0.25.0
# pyyaml>=6.0
# some-library>=1.0.0
```

---

## Configuration: mcp_config.yaml

Add your MCP to `druppie/core/mcp_config.yaml`:

```yaml
mcps:
  your-mcp:
    url: ${MCP_YOUR_URL:-http://mcp-your-mcp:900X}
    description: "Brief description of what this MCP does"
    tools:
      - name: example_tool
        description: "Do something useful"
        requires_approval: false
        # parameters: (optional, for validation)
        #   type: object
        #   properties:
        #     param1:
        #       type: string
        #   required:
        #     - param1

      - name: another_tool
        description: "Another tool"
        requires_approval: true
        required_role: developer
```

**Notes:**
- Replace `your-mcp` with your MCP identifier (lowercase, hyphens)
- Replace `900X` with a unique port (e.g., 9003, 9004, 9006, etc.)
- `required_role` options: `developer`, `architect`, `admin`, or any custom role

---

## Configuration: docker-compose.yml

Add your MCP service to `druppie/docker-compose.yml`:

```yaml
services:
  # ... other services ...

  mcp-your-mcp:
    build:
      context: ./mcp-servers/your-mcp
      dockerfile: Dockerfile
    container_name: druppie-mcp-your-mcp
    environment:
      WORKSPACE_ROOT: /workspaces
      MCP_PORT: "900X"
      # Add your environment variables here
      #   YOUR_API_KEY: ${YOUR_API_KEY:-}
      #   YOUR_CONFIG: default_value
    volumes:
      - druppie_new_workspace:/workspaces
      # Add more volumes if needed
      #   - /var/run/docker.sock:/var/run/docker.sock
      #   - ./data:/data
    ports:
      - "900X:900X"
    networks:
      - druppie-new-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:900X/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
```

**Important:**
- Use a unique port (check existing ports: 9001, 9002, 9005)
- Mount `druppie_new_workspace` if you need workspace access
- Add `/var/run/docker.sock` volume if you need Docker access
- Use `druppie-new-network` for internal communication

---

## Configuration: Backend Environment

Add environment variables to `druppie-backend` service in `docker-compose.yml`:

```yaml
druppie-backend:
  # ... existing config ...
  environment:
    # ... existing env vars ...
    MCP_YOUR_URL: http://mcp-your-mcp:900X
```

---

## Agent Configuration

Update agent YAML files to use your MCP tools:

```yaml
# File: druppie/agents/definitions/your-agent.yaml

# MCP tools this agent can use
mcps:
  your-mcp:
    - example_tool
    - another_tool
  # ... other MCPs ...
```

---

## Development Workflow

### 1. Create the MCP Server

```bash
# Create directory
mkdir -p druppie/mcp-servers/your-mcp

# Create files
touch druppie/mcp-servers/your-mcp/Dockerfile
touch druppie/mcp-servers/your-mcp/module.py
touch druppie/mcp-servers/your-mcp/server.py
touch druppie/mcp-servers/your-mcp/requirements.txt

# Fill in the templates above
```

### 2. Update Configuration Files

1. Add tools to `druppie/core/mcp_config.yaml`
2. Add service to `druppie/docker-compose.yml`
3. Add environment variables to `druppie-backend`
4. Update agent YAML files to use tools

### 3. Build and Test

```bash
# Build just your MCP
docker-compose build mcp-your-mcp

# Start your MCP
docker-compose up -d mcp-your-mcp

# Check logs
docker-compose logs -f mcp-your-mcp

# Test health check
curl http://localhost:900X/health

# Restart everything
docker-compose down
docker-compose up -d
```

### 4. Test Tools

Use the backend to test your MCP tools:

```bash
# Check available tools
curl http://localhost:8100/api/mcps

# List tools for your MCP
curl http://localhost:8100/api/mcps/your-mcp/tools
```

---

## Best Practices

### Security

1. **Input Validation**: Always validate inputs in `module.py`
2. **Path Traversal Protection**: Use `resolve_path()` pattern for file operations
3. **Command Injection**: Use blocklist for shell commands (see `mcp-servers/coding/module.py`)
4. **Timeouts**: Set timeouts on external operations
5. **Error Handling**: Never expose sensitive data in error messages

### Error Responses

Always return dictionaries with this structure:

```python
# Success
{
    "success": True,
    "result": "data",
    # Add more fields as needed
}

# Error
{
    "success": False,
    "error": "Human-readable error message",
    # Add more context if helpful
}
```

### Logging

Use structured logging with context:

```python
logger.info(
    "tool_executed",
    workspace_id=workspace_id,
    param1=param1,
)

logger.error(
    "tool_failed",
    workspace_id=workspace_id,
    error=str(e),
    exc_info=True,  # Include stack trace for errors
)
```

### Async/Await

- All tool functions must be `async`
- Use `await` for I/O operations (HTTP requests, file I/O, subprocess)
- Keep CPU-bound operations synchronous

### Parameter Handling

- Use `str | None` for optional parameters with defaults
- Use proper type hints for all parameters
- Document all parameters in docstrings

---

## Examples

### Example 1: API Integration MCP

```python
# module.py
import httpx

class ApiModule:
    async def fetch_data(self, api_key: str, endpoint: str) -> dict:
        """Fetch data from external API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.example.com/{endpoint}",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            return {
                "success": response.status_code == 200,
                "data": response.json() if response.status_code == 200 else None,
                "status_code": response.status_code,
            }
```

### Example 2: Database MCP

```python
# module.py
import sqlite3

class DatabaseModule:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def query(self, sql: str) -> dict:
        """Execute SQL query."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            return {
                "success": True,
                "rows": [dict(row) for row in rows],
                "count": len(rows),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            conn.close()
```

### Example 3: File Processing MCP

```python
# module.py
from pathlib import Path
import json

class FileProcessorModule:
    def process_json(self, workspace_id: str, path: str) -> dict:
        """Process JSON file."""
        file_path = self.workspace_root / workspace_id / path

        if not file_path.exists():
            return {"success": False, "error": "File not found"}

        data = json.loads(file_path.read_text())

        # Process data
        result = {k: len(str(v)) for k, v in data.items()}

        return {
            "success": True,
            "processed": result,
            "original_keys": list(data.keys()),
        }
```

---

## Troubleshooting

### MCP Not Responding

1. Check health endpoint: `curl http://localhost:900X/health`
2. Check logs: `docker-compose logs -f mcp-your-mcp`
3. Verify port is not in use: `netstat -an | grep 900X`

### Tools Not Available in Agent

1. Verify tools listed in `mcp_config.yaml`
2. Check agent YAML includes the MCP
3. Restart backend: `docker-compose restart druppie-backend`

### Workspace Access Issues

1. Ensure volume is mounted: `druppie_new_workspace:/workspaces`
2. Check `WORKSPACE_ROOT` environment variable
3. Verify workspace directory structure

---

## Checklist

Before deploying your new MCP:

- [ ] All tools are async and properly typed
- [ ] Error handling covers all code paths
- [ ] Logging includes relevant context
- [ ] Health check endpoint is configured
- [ ] Dockerfile uses Python 3.11 or later
- [ ] Requirements.txt is minimal and pinned
- [ ] Port is unique (not 9001, 9002, 9005)
- [ ] Tools configured in `mcp_config.yaml`
- [ ] Service added to `docker-compose.yml`
- [ ] Backend environment variables updated
- [ ] Agent YAML files updated to use tools
- [ ] Security review completed (input validation, path traversal, etc.)
- [ ] Documentation in README.md (optional)

---

## Resources

- FastMCP Documentation: https://github.com/jlowin/fastmcp
- Model Context Protocol: https://modelcontextprotocol.io/
- Druppie Architecture: See `MCP-ARCHITECTURE.md`
