# MCP Config

`druppie/core/mcp_config.yaml` is the single source of truth for:
- Which MCP servers Druppie connects to
- What URL each listens on
- Type (core / module / both)
- Per-tool injection rules (standard args)
- Per-tool approval requirements (global defaults)

Loaded at startup by `druppie/core/mcp_config.py:MCPConfig` (singleton via `get_mcp_config()`).

## YAML shape

```yaml
mcps:
  <mcp_id>:
    url: ${ENV_VAR:-http://module-<slug>:<port>}
    type: core | module | both
    inject:
      <param_name>:
        from: "<dot.path.from.context>"     # e.g. session.id
        hidden: true | false                # hidden strips param from LLM schema
        tools: [tool1, tool2, ...]          # scope rule to specific tools (omit = all)
    tools:
      - name: <tool_name>
        requires_approval: true | false
        required_role: <role_name>          # realm role or "session_owner"
```

Environment variable substitution uses the shell `${VAR:-default}` syntax.

## Modules configured today

### `coding`

- **URL:** `http://module-coding:9001`
- **Type:** core
- **Inject:** `session_id`, `project_id`, `repo_name`, `repo_owner`, `user_id` — all `hidden: true`. Applied to every workspace-scoped tool.
- **Approval defaults:**
  - `read_file, write_file, make_design, list_dir, delete_file, batch_write_files, run_git, run_tests, create_pull_request, get_test_framework, get_coverage_report, install_test_dependencies, validate_tdd, get_git_status, list_projects, read_project_file, list_project_files` → none
  - `merge_pull_request` → `developer`
  - `_internal_*` → none (backend-only)
- **Agent overrides** (in agent YAML `approval_overrides`):
  - `business_analyst: coding:make_design` → `session_owner`
  - `architect: coding:make_design` → `architect`

### `docker`

- **URL:** `http://module-docker:9002`
- **Type:** core
- **Inject:** `session_id`, `repo_name`, `repo_owner`, `user_id`, `project_id` — hidden.
- **Approval defaults:**
  - `build, run, compose_up, compose_down, stop, remove, exec_command` → `developer`
  - `logs, list_containers, inspect` → none (read-only)

### `filesearch`

- **URL:** `http://module-filesearch:9004`
- **Type:** core
- **Inject:** none
- **Approval defaults:** all tools → none (read-only)

### `web`

- **URL:** `http://module-web:9005`
- **Type:** both (used by router, architect for web browsing)
- **Inject:** none
- **Approval defaults:** all tools → none

### `archimate`

- **URL:** `http://module-archimate:9006`
- **Type:** core (architect only uses this today)
- **Inject:** none
- **Approval defaults:** all tools → none (read-only)

### `registry`

- **URL:** `http://module-registry:9007`
- **Type:** core (business_analyst + architect + build_classifier use it)
- **Inject:** none
- **Approval defaults:** all tools → none

## Injection rules in detail

`MCPConfig.InjectionRule`:

```python
@dataclass
class InjectionRule:
    param: str            # name in the tool schema
    from_path: str        # e.g. "session.id" — navigated from a context dict
    hidden: bool          # strip from schema shown to LLM
    tools: list[str]|None # scope to specific tools (None = all)

    def applies_to_tool(self, tool_name: str) -> bool: ...
```

At dispatch time, the ToolExecutor builds a context dict from the current agent run:
```python
context = {
    "session": session,     # domain Session model
    "project": project,     # or None
    "user": user,           # domain User
}
```

Each rule's `from_path` is resolved via attribute access (`getattr(session, "id")`). If the path is missing, the rule is skipped (no injection) — rules are always best-effort.

Hidden params are removed from the schema ToolRegistry exposes to the LLM. When the LLM emits a call without them, the ToolExecutor fills them in. When the LLM (incorrectly) includes them, the injected values overwrite.

## Approval resolution order

For a tool call the ToolExecutor considers, in order:

1. **Agent-level override** — `approval_overrides` in the agent's YAML, keyed by `"<server>:<tool>"` or `"builtin:<tool>"`.
2. **Global default** — `tools[].requires_approval` in `mcp_config.yaml`.
3. **No approval** — if neither specifies, the tool runs without gating.

The first match wins. There is no "deny" layer — if the default says none and the agent override says `required_role: architect`, the override applies only to that agent. Other agents calling the same tool still proceed without approval.

## Env var substitution

Values like `${KEYCLOAK_URL:-http://keycloak:8080}` are resolved at YAML load time by a small templating pass. This lets the same config work in dev (Docker hostnames) and production (public hostnames).

## Hot-reload

Not supported. A config change requires a backend restart so `ToolRegistry.initialize()` re-fetches `tools/list` from every server.

## Gotchas

- **Ordering matters** within agent `approval_overrides` — dict ordering is preserved; duplicate keys are caught by Pydantic validation.
- **Injection is server-blind** — the rule doesn't know whether the target MCP server actually accepts the param. If you inject `session_id` into a module that doesn't take it, the call fails with a schema validation error at the MCP server.
- **Hidden + LLM creativity** — an LLM may try to add `session_id: null` to a call. Argument normalisation in the ToolExecutor strips unknown/invalid nulls before dispatch, so this is tolerated.
