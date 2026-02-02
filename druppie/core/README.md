# Core Layer

The core layer provides foundational services and configuration that other layers depend on: settings management, authentication, Gitea integration, and MCP server configuration.

## Files

### `__init__.py`
Exports the key configuration utilities: `Settings`, `get_settings`, `is_dev_mode`, `get_database_url`.

### `config.py`
Centralized configuration management using **Pydantic Settings**. All configuration values are loaded from environment variables and `.env` files.

The `Settings` class aggregates nested sub-settings:

```python
class Settings(BaseSettings):
    database: DatabaseSettings     # DB_URL, DB_ECHO, DB_POOL_SIZE
    keycloak: KeycloakSettings     # KEYCLOAK_URL, KEYCLOAK_REALM
    gitea: GiteaSettings           # GITEA_URL, GITEA_ADMIN_USER, GITEA_TOKEN
    llm: LLMSettings               # LLM_PROVIDER, ZAI_API_KEY, ZAI_MODEL
    mcp: MCPSettings               # MCP_CODING_URL, MCP_DOCKER_URL
    workspace: WorkspaceSettings   # WORKSPACE_ROOT
    api: APISettings               # API_HOST, API_PORT, CORS_ORIGINS, DEV_MODE
```

Access via the cached singleton:
```python
from druppie.core.config import get_settings
settings = get_settings()
db_url = settings.database.url
```

Key sub-settings:
- **DatabaseSettings**: Connection URL, pool size, echo mode.
- **KeycloakSettings**: Server URL, realm, issuer URL override.
- **GiteaSettings**: URLs (external and internal), admin credentials, org name.
- **LLMSettings**: Provider selection (auto/zai/mock), API keys, model name, base URL.
- **MCPSettings**: URLs for coding, docker, and HITL MCP servers.
- **APISettings**: Host, port, CORS origins, dev mode flag.

### `auth.py`
Authentication service supporting **Keycloak JWT validation** and **development mode bypass**.

**AuthService** class:
- `decode_token(token)` -- decodes and validates a JWT token using Keycloak's JWKS endpoint (RS256).
- `validate_request(authorization)` -- validates the Authorization header. Tries real token first, falls back to dev mode.
- `get_user_roles(user)` -- extracts roles from `realm_access.roles`.
- `has_role(user, role)` / `has_any_role(user, roles)` -- role checking with admin bypass.
- `is_keycloak_available()` -- health check for Keycloak connectivity.

**Dev mode safety**: Dev mode is refused in production environments (`ENVIRONMENT=production`). When enabled, all requests authenticate as a dev user with all roles.

The `DEV_USER` constant defines the default dev identity used when auth is bypassed.

### `gitea.py`
HTTP client for the **Gitea API**. Used internally by services and the execution layer -- not exposed as an MCP server.

**GiteaClient** class provides async methods for:

- **User operations**: `create_user()`, `ensure_user_exists()`, `find_user_by_email()`. Handles reserved username conflicts by auto-prefixing with `druppie_`.
- **Repository operations**: `create_repo()`, `delete_repo()`, `list_repos()`, `get_repo()`, `repo_exists()`. Supports creating repos under user accounts or the organization.
- **File operations**: `create_file()`, `update_file()`, `get_file()`, `list_files()`, `delete_file()`. All file operations use base64 encoding.
- **Branch operations**: `create_branch()`, `delete_branch()`, `list_branches()`, `branch_exists()`.
- **Merge operations**: `merge_branch()` (creates and merges a PR), `get_branch_diff()`.
- **URL helpers**: `get_clone_url()` (with embedded credentials for Docker network), `get_public_url()` (without credentials for display).

Uses `httpx.AsyncClient` with basic auth. The internal URL is used for Docker network communication while the external URL is for user-facing display.

### `mcp_client.py`
FastMCP client that adds **approval checking** on top of MCP tool execution. This is a higher-level client used by the older execution path.

**MCPClient** class:
- `call_tool(server, tool, args, session_id, agent_run_id, agent_id)` -- main entry point. Checks approval requirements using the layered system, creates approval records if needed, executes with retry for transient errors.
- `requires_approval(server, tool, agent_definition)` -- layered approval check: agent overrides first, then global mcp_config.yaml defaults.
- `_execute_tool_with_retry(server, tool, args, session_id)` -- retry with exponential backoff for transient errors.
- `to_openai_tools(mcp_ids)` / `to_openai_tools_async(mcp_ids)` -- converts MCP tools to OpenAI function calling format for LLM integration.
- `generate_tool_descriptions(agent_mcps)` -- generates formatted tool descriptions for agent system prompts. Filters out hidden parameters.

**Error classification** (`classify_error`): Categorizes exceptions as transient (retryable), permission, validation (LLM-recoverable), or fatal.

### `mcp_config.py`
MCP configuration loader and approval rules engine.

**MCPConfig** class:
- Loads `mcp_config.yaml` with environment variable substitution (`${VAR:-default}` syntax).
- `get_server_url(server)` -- returns server URL with `/mcp` suffix for FastMCP transport.
- `needs_approval(server, tool, agent_definition)` -- layered approval: agent overrides > global config.
- `get_injection_rules(server, tool_name)` -- returns `InjectionRule` objects for declarative argument injection.
- `get_hidden_params(server)` -- identifies parameters to hide from LLM schemas.
- `get_all_tools_for_agent(agent_mcps)` -- returns tool definitions filtered by agent access.

**InjectionRule** dataclass: Defines how to automatically inject context values (session.id, project.repo_name) into tool arguments at execution time. Rules with `hidden: true` are removed from LLM-visible schemas.

## Layer Connections

- **Depends on**: `druppie.repositories` (mcp_client.py uses ApprovalRepository, ExecutionRepository), `druppie.domain` (agent_definition).
- **Depended on by**: `druppie.api` (auth, config), `druppie.execution` (mcp_config, mcp_http), `druppie.services` (deployment uses Gitea), `druppie.agents` (mcp_client for tool execution).

## Conventions

1. Configuration is loaded once via `get_settings()` (cached with `lru_cache`).
2. Singletons are used for stateful clients (GiteaClient, MCPClient, MCPConfig, AuthService) with `get_*()` factory functions.
3. Environment variables use prefix-based namespacing (DB_, KEYCLOAK_, GITEA_, MCP_, etc.).
4. The `mcp_config.yaml` file is the single source of truth for MCP server definitions, tool approval requirements, and injection rules.
