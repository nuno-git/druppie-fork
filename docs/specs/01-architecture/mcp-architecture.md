# MCP Architecture

MCP (Model Context Protocol) is the **only** interface agents have to the outside world. No agent writes a file, runs a container, calls a web API, or touches git except by invoking an MCP tool.

## Components

```
┌────────────────────────────┐         ┌──────────────────────────┐
│   Agent (LLM loop)         │         │  ToolRegistry (in-proc) │
│   druppie/agents/loop.py   │────────►│  druppie/core/tool_...  │
│                            │  uses   │  + MCPConfig            │
└───────────┬────────────────┘         └──────────────────────────┘
            │ tool call {server, tool, arguments}
┌───────────▼────────────────┐         ┌──────────────────────────┐
│   ToolExecutor             │────────►│  MCPConfig.needs_approval│
│   druppie/execution/       │         │  InjectionRule.apply     │
│   tool_executor.py         │         └──────────────────────────┘
└───────────┬────────────────┘
            │ HTTP POST /v1/mcp (FastMCP JSON-RPC)
            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Module containers — one FastMCP server per module                │
│    module-coding:9001   ┃ module-docker:9002 ┃ module-web:9005    │
│    module-filesearch:9004 ┃ module-archimate:9006 ┃ module-registry:9007 │
└──────────────────────────────────────────────────────────────────┘
```

## Tool registration

At backend startup (`druppie/api/main.py:112`):

1. `ToolRegistry.initialize()` iterates every entry in `druppie/core/mcp_config.yaml`.
2. For each MCP server URL, it calls `tools/list` (MCP protocol method) and receives the full list of tool schemas.
3. Tool schemas are combined with `BUILTIN_TOOL_DEFS` (from `druppie/agents/builtin_tools.py`).
4. Each tool becomes a `ToolDefinition` object: `name, server, description, json_schema, requires_approval, required_role`.
5. The registry exposes:
   - `get(tool_key)` — look up by `"server:tool"` or `"tool"` for builtin.
   - `get_tools_for_agent(agent_mcps, builtin_tool_names)` — filter by what an agent's YAML lists.
   - `to_openai_format(tools)` — emit schemas in the OpenAI function-calling format (with optional strict mode).

If `initialize()` fails for a server, the registry logs and falls back to builtin-only. Agents that depend on that server will fail at LLM-call time.

## Per-tool dispatch

For each tool call in the LLM response, `ToolExecutor.execute(tool_call_id)` runs:

1. **Classify the tool.**
   - `BUILTIN_TOOLS` set: `done, make_plan, set_intent, hitl_ask_question, hitl_ask_multiple_choice_question, create_message, invoke_skill, execute_coding_task, test_report` → run in-process.
   - `HITL_TOOLS` subset: create a `Question` row, set `tool_call.status = WAITING_ANSWER`, return.
   - Any other tool → MCP dispatch.
2. **Approval check.** `MCPConfig.needs_approval(server, tool, agent_overrides)` returns `(requires_approval: bool, required_role: str|None)`. Two layers are merged:
   - Agent-level `approval_overrides` in `agent_definition.yaml`.
   - Global `tools[].requires_approval` in `mcp_config.yaml`.
   If approval required: create `Approval` row, set `tool_call.status = WAITING_APPROVAL`, return.
3. **Argument injection.** For each `InjectionRule` that `applies_to_tool(tool_name)`:
   - Look up the value from context (`session.id`, `project.id`, etc.).
   - If `hidden: true`, the parameter was already stripped from the schema shown to the LLM — inject before dispatch.
   - If not hidden, the LLM supplied a value but we override.
4. **Argument validation.** `ToolDefinition.validate_arguments()`:
   - Validate JSON schema.
   - On failure, normalise common LLM mistakes: `"null"` → None, `"{}"` → {}, `"true"` → True. Strip unknown fields.
   - Retry validation with normalised args; if still invalid, fail the tool call.
5. **Dispatch.** `MCPHttp.call(server_url, tool, args)` — JSON-RPC over HTTP to `/v1/mcp`. Timeout from `LONG_RUNNING_TOOLS` map (1200 s for `run_tests`, `install_test_dependencies`, `compose_up`; 60 s default).
6. **Result persistence.** Update `tool_call.status = COMPLETED|FAILED`, `.result`, `.error_message`, `.executed_at`.

## Injection rules example

From `druppie/core/mcp_config.yaml`:

```yaml
mcps:
  coding:
    url: http://module-coding:9001
    inject:
      session_id:
        from: session.id
        hidden: true
        tools: [read_file, write_file, ...]
      project_id:
        from: project.id
        hidden: true
        tools: [...]
```

LLM sees `write_file(path, content)` but actual call is `write_file(path, content, session_id=…, project_id=…, user_id=…, repo_name=…, repo_owner=…)`. The MCP server uses these identity fields to scope filesystem access to the session's workspace.

## Approval model

Three role values exist in practice:
- Realm roles: `admin`, `architect`, `developer`, `business_analyst`, `infra-engineer`, `product-owner`, `compliance-officer`, `viewer`, `user`.
- Synthetic role: `session_owner` — only the user who started the session can approve. Used for design approvals (functional/technical design) where the business owner is the approver, not a role.

Default approval matrix (see `druppie/core/mcp_config.yaml` for the authoritative list):

| Tool | Default approval | Rationale |
|------|------------------|-----------|
| `coding:read_file, list_dir, get_git_status, run_tests, …` | none | Reads and test runs are safe |
| `coding:write_file, batch_write_files, make_design, run_git, …` | none (per agent override) | Agents doing design writes override to require approval |
| `coding:merge_pull_request` | `developer` | Irreversible; must be human-approved |
| `docker:build, run, compose_up, compose_down, stop, remove, exec_command` | `developer` | Shared Docker daemon, affects infra |
| `filesearch:*, web:*, archimate:*, registry:*` | none | Read-only |

Per-agent overrides (in `agent_definition.yaml`):
- `business_analyst` overrides `coding:make_design` → requires `session_owner` approval (business owner approves the functional design).
- `architect` overrides `coding:make_design` → requires `architect` role approval (architect peer-review).
- `deployer` inherits docker defaults → `developer` approval for every compose operation.
- `update_core_builder` overrides `builtin:done` → requires `developer` (PR must be merged first).

## Adding a new MCP module

Summarised from `druppie/skills/module-convention/SKILL.md` (full details in `04-mcp-servers/module-convention.md`):

1. Create `druppie/mcp-servers/module-<name>/` with `MODULE.yaml`, `Dockerfile`, `requirements.txt`, `server.py`, `v1/{module.py, tools.py}`.
2. `server.py` is boilerplate — uses `module_router.run_module(module_name, default_port)`.
3. Add a service to `docker-compose.yml` referencing the new Dockerfile and a port in `9010-9099` (9001–9009 reserved for core).
4. Add an entry to `druppie/core/mcp_config.yaml` with `url`, `type` (core/module/both), `inject`, `tools` (with approval rules).
5. Optionally give existing agents access by adding the module ID to their `mcps:` list in `agent_definition.yaml`.
6. Reset the stack — `ToolRegistry.initialize()` will discover the new tools on next startup.

## Versioning

`MODULE.yaml` declares `latest_version: "1.0.0"` and a list `versions: ["1.0.0"]`. `server.py` mounts one FastMCP app per major version at `/v{major}/mcp`, plus `/mcp` aliased to the latest. This means:
- Breaking changes get a new `v2/` directory.
- Old agents can pin to `v1/mcp` until migrated.
- The module registry exposes `list_modules` / `get_module` showing all active versions.

In practice today every module is at v1 and no v2 has been promoted.
