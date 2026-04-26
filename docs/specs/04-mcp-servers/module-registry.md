# module-registry

**Port:** 9007. **Type:** core. **Dockerfile:** `druppie/mcp-servers/module-registry/Dockerfile`.

Self-description of the Druppie platform. Agents use this to discover what modules, tools, agents, and skills exist. 6 tools.

## Data sources

Configured via read-only volume mounts (see `docker-compose.yml`):

- `druppie/agents/definitions/` — agent YAMLs.
- `druppie/core/mcp_config.yaml` — MCP registry.
- `druppie/skills/` — skill markdown with frontmatter.
- `druppie/agents/builtin_tools.py` — copied for parsing.
- Live MCP servers — polled for current tool schemas (60 s cache).

## Dockerfile

- Base: `python:3.11-slim`.
- Creates `/data`.
- Standard FastMCP boilerplate.

## Tools

### `list_modules`

Args: `category?` (`core` | `module` | `""` for all).

Returns the current module registry with versions, type, tool count, and which agents use each module.

### `get_module`

Args: `module_id`, `version?` (e.g. `"v1"`).

Fetches live tool schemas from the running MCP server and returns: description, all versions, tool list with full schemas, agents using it.

### `search_modules`

Args: `query`.

Keyword search over module IDs, tool names, and descriptions.

### `list_components`

Args: `category?` (`agents` | `skills` | `builtin_tools` | `""`).

Returns agents, skills, or builtin tools.

### `get_agent`

Args: `agent_id`.

Full agent details: description, skills, modules used, builtin tools, approval overrides, config (temperature, max_tokens, etc.).

### `get_skill`

Args: `skill_name`.

Full skill content (body markdown) plus frontmatter (description, allowed_tools).

## Caching

`_tool_cache: dict[str, (timestamp, tools_list)]` with a 60 s TTL. Prevents hammering peer MCP servers when the registry is consulted in tight loops (e.g. by the architect repeatedly browsing modules).

## Used by

- **business_analyst** — `list_modules`, `get_module`, `search_modules`, `list_components` to check if a module already exists for a requirement before proposing a new one.
- **architect** — same plus `get_agent`, `get_skill` for existing-capability discovery.
- **build_classifier** — `list_modules` to decide whether a change implies modifying existing core modules (CORE_UPDATE) or standing up a new project (STANDALONE).

## Role in governance

Registry-as-code: everything an agent might want to know about platform state comes from code in the repo (YAML, markdown, Python), not from a mutable DB. That means the registry is deterministic per git commit and trivially reproducible.
