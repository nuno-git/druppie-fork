# Declarative MCP Argument Injection

This document describes the declarative argument injection system for MCP tools.

## Overview

The injection system automatically populates tool arguments from context (session, project, user) at execution time. This:

1. **Prevents LLM guessing** - Parameters like `repo_name` are hidden from the LLM, so it can't guess wrong values
2. **Ensures correctness** - Values come directly from the database
3. **Simplifies prompts** - Agents don't need to know about session/project IDs

## How It Works

### Configuration in `mcp_config.yaml`

Each MCP server can define injection rules:

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    inject:
      # Simple format: param_name: context.path
      session_id:
        from: session.id
        hidden: true
      repo_name:
        from: project.repo_name
        hidden: true
      repo_owner:
        from: project.repo_owner
        hidden: true
    tools:
      - name: read_file
        # ...
```

### Rule Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `from` | string | required | Context path to resolve (e.g., `project.repo_name`) |
| `hidden` | bool | `true` | If true, parameter is hidden from LLM schema |
| `tools` | list | `null` | List of tool names this rule applies to. `null` = all tools |

### Context Paths

Available context paths:

| Path | Description |
|------|-------------|
| `session.id` | Current session UUID |
| `session.user_id` | User ID from session |
| `session.project_id` | Project ID from session |
| `project.id` | Project UUID |
| `project.repo_name` | Git repository name |
| `project.repo_owner` | Git repository owner |
| `project.name` | Project display name |
| `user.id` | User UUID |
| `user.username` | User's username |

### Tool-Specific Rules

You can limit rules to specific tools:

```yaml
inject:
  session_id:
    from: session.id
    hidden: true
    tools: [build, run]  # Only inject for these tools
```

## Components

### ToolContext (`druppie/execution/tool_context.py`)

Resolves context paths to values with lazy loading:

```python
from druppie.execution.tool_context import ToolContext

context = ToolContext(db, session_id)
repo_name = context.resolve("project.repo_name")  # "my-todo-app"
user_id = context.resolve("user.id")  # "abc123..."
```

### MCPConfig (`druppie/core/mcp_config.py`)

Manages injection rules:

```python
from druppie.core.mcp_config import get_mcp_config

config = get_mcp_config()

# Get all rules for a server
rules = config.get_injection_rules("coding")

# Get rules for a specific tool
rules = config.get_injection_rules("coding", "read_file")

# Get hidden params (for schema filtering)
hidden = config.get_hidden_params("coding")
# {"read_file": {"session_id", "repo_name", "repo_owner"}, ...}
```

### ToolExecutor (`druppie/execution/tool_executor.py`)

Applies injection at execution time:

```python
# In _execute_mcp_tool():
args = self._apply_injection_rules(
    server=tool_call.mcp_server,
    tool_name=tool_call.tool_name,
    args=args,
    session_id=tool_call.session_id,
)
```

## Example: Docker Build

Configuration:
```yaml
docker:
  inject:
    session_id:
      from: session.id
      hidden: true
      tools: [build, run]
    repo_name:
      from: project.repo_name
      hidden: true
      tools: [build]
```

LLM sees only:
```
docker:build
  REQUIRED: image_name
  OPTIONAL: git_url, branch, dockerfile, build_args
```

LLM calls:
```json
{
  "tool": "docker:build",
  "args": {
    "image_name": "todo-app:latest"
  }
}
```

After injection:
```json
{
  "image_name": "todo-app:latest",
  "session_id": "abc123-...",
  "repo_name": "todo-app-xyz789",
  "repo_owner": "druppie"
}
```

## Benefits

1. **No more repo_name guessing** - LLM can't provide wrong values
2. **Cleaner agent prompts** - No need to explain session IDs
3. **Centralized configuration** - All injection rules in one YAML file
4. **Easy to extend** - Add new injections without code changes
