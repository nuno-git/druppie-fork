# Design: OpenCode Sandbox Config & Schema Fix

## Problem

1. **No git push from sandbox**: OpenCode in the sandbox commits but never pushes to Gitea. Changes are lost when the container stops.
2. **No agent selection**: `execute_coding_task` always uses OpenCode's default `build` agent. Druppie's builder and tester agents need different sandbox behaviors.
3. **User override risk**: If config lives in the project repo, users can edit agent instructions and permissions.
4. **Pydantic schema bug**: `execute_coding_task` is missing from `PARAMS_MODEL_MAP`, so the LLM sees no required parameters and calls it without `task`.

## Design

### A. OpenCode Config Folder (`druppie/sandbox-config/`)

A `.opencode/` folder in the Druppie codebase with agent definitions, permissions, and instructions. This gets injected into every sandbox via `OPENCODE_CONFIG_CONTENT` env var (highest user-level precedence). User project repos cannot override it.

```
druppie/sandbox-config/
├── opencode-config.json       # Base config: default_agent, permissions
└── agents/
    ├── druppie-builder.md     # Builder agent: code + commit + push
    └── druppie-tester.md      # Tester agent: test + report
```

**Config assembly**: The entrypoint reads the base config JSON and merges agent markdown content into `OPENCODE_CONFIG_CONTENT`. Combined with `OPENCODE_DISABLE_PROJECT_CONFIG=true`, this completely overrides any user-provided config.

#### opencode-config.json

```json
{
  "default_agent": "druppie-builder",
  "permission": {
    "*": { "*": "allow" }
  }
}
```

#### druppie-builder.md

```markdown
---
description: Druppie coding agent — implements code and pushes to git
mode: primary
---

## Git Workflow (MANDATORY)
After completing ALL code changes:
1. Stage files: `git add -A`
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.

## Coding Standards
- Write clean, working code
- Follow existing project patterns
- Create proper Dockerfiles for web apps
```

#### druppie-tester.md

```markdown
---
description: Druppie testing agent — writes tests and validates code
mode: primary
---

## Git Workflow (MANDATORY)
After completing ALL test changes:
1. Stage files: `git add -A`
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.

## Testing Standards
- Auto-detect test framework from project files
- Write comprehensive tests with good coverage
- Report results in structured format
```

### B. Thread `agent` Parameter Through 5 Layers

Add `agent` parameter to select which OpenCode agent handles the prompt.

**Layer 1 — server.py** (`execute_coding_task`):
```python
async def execute_coding_task(
    task: str,
    agent: str = "druppie-builder",   # NEW
    model: str = "zai-coding-plan/glm-4.7",
    ...
)
```
Pass `agent` in POST `/sessions/{id}/prompt` body: `{"content": task, "agent": agent, ...}`

**Layer 2 — router.ts** (control plane):
Extract `body.agent` from POST `/sessions/:id/prompt` and store in message record.

**Layer 3 — session-instance.ts** (message queue):
Add `agent TEXT` column to messages table. Include `agent` field in WebSocket command sent to sandbox.

**Layer 4 — bridge.py** (sandbox bridge):
Extract `cmd.get("agent")` in `_handle_prompt()`. Pass to `_build_prompt_request_body()`. Include `"agent": agent` in request body to OpenCode.

**Layer 5 — OpenCode** (already supports it):
OpenCode's `/session/:id/message` API already accepts an `agent` field. No changes needed.

### C. Entrypoint Config Loading

Modify `entrypoint.py` to:

1. Set `OPENCODE_DISABLE_PROJECT_CONFIG=true` in OpenCode's env
2. Expand `OPENCODE_CONFIG_CONTENT` to include agent definitions from config files
3. The config files are bundled into the sandbox Docker image at build time

**How config gets into the sandbox image**: The `Dockerfile.sandbox` already copies `/app/sandbox/` files. We add a COPY step for the config files, or mount them via the sandbox-manager.

**Alternative (simpler)**: The entrypoint already constructs `OPENCODE_CONFIG_CONTENT` as JSON. We expand that JSON inline in entrypoint.py with the agent definitions and instructions. The `druppie/sandbox-config/` files serve as the source-of-truth that gets transcribed into the entrypoint config. This avoids needing to bundle extra files into the image.

**Recommended approach**: Expand the entrypoint's existing `OPENCODE_CONFIG_CONTENT` construction to include:
- `default_agent: "druppie-builder"`
- `agent` dict with druppie-builder and druppie-tester definitions (including prompts)
- Set `OPENCODE_DISABLE_PROJECT_CONFIG=true` in env

The `druppie/sandbox-config/` files are the human-readable source. A helper in the entrypoint or the MCP server reads them and serializes to JSON. OR, for simplicity, the agent prompts are defined inline in `entrypoint.py` since they're short.

### D. Pydantic Schema Fix

**File**: `druppie/tools/params/coding.py`

```python
class ExecuteCodingTaskParams(BaseModel):
    task: str = Field(description="The coding task description for the sandbox agent")
    agent: str = Field(
        default="druppie-builder",
        description="Which sandbox agent to use (druppie-builder for coding, druppie-tester for testing)"
    )
    model: str = Field(
        default="zai-coding-plan/glm-4.7",
        description="LLM model for the sandbox agent"
    )
    timeout_seconds: int = Field(
        default=600,
        description="Max wait time in seconds"
    )
```

**File**: `druppie/core/tool_registry.py`

Add to `PARAMS_MODEL_MAP`:
```python
("coding", "execute_coding_task"): ExecuteCodingTaskParams,
```

### E. Update Druppie Agent Definitions

**builder.yaml**: Update sandbox docs to include `agent` parameter:
```yaml
# SANDBOX CODING
# execute_coding_task(task="...", agent="druppie-builder")
# For testing: agent="druppie-tester"
```

**tester.yaml**: Update sandbox docs:
```yaml
# SANDBOX CODING
# execute_coding_task(task="...", agent="druppie-tester")
```

### F. mcp_config.yaml Update

Add `agent` to the execute_coding_task parameter schema:
```yaml
- name: execute_coding_task
  parameters:
    properties:
      task:
        type: string
        description: "The coding task for the sandbox agent"
      agent:
        type: string
        description: "Which sandbox agent (druppie-builder or druppie-tester)"
      model:
        type: string
      timeout_seconds:
        type: integer
    required:
      - task
```

## Implementation Phases

### Phase 1: Pydantic Schema Fix (unblocks basic usage)
1. Create `ExecuteCodingTaskParams` in `coding.py`
2. Register in `PARAMS_MODEL_MAP`
3. Update `mcp_config.yaml` with `agent` parameter
4. Verify: LLM sees `task` as required, `agent` as optional

### Phase 2: Agent Parameter Threading (5 layers)
1. `server.py` — add `agent` param, pass in prompt body
2. `router.ts` — extract and store agent from prompt request
3. `session-instance.ts` — add agent column, include in WebSocket command
4. `bridge.py` — extract agent, pass to OpenCode API
5. Verify: agent field reaches OpenCode

### Phase 3: OpenCode Config
1. Create `druppie/sandbox-config/` with config JSON and agent markdown files
2. Modify `entrypoint.py` to expand `OPENCODE_CONFIG_CONTENT` with agent definitions
3. Set `OPENCODE_DISABLE_PROJECT_CONFIG=true`
4. Verify: OpenCode uses druppie-builder by default

### Phase 4: E2E Verification
1. Run sandbox with druppie-builder agent — expect code + commit + push to Gitea
2. Run sandbox with druppie-tester agent — expect tests + commit + push
3. Verify server.py git pull succeeds after sandbox pushes
4. Test that user .opencode/ in project repo is ignored

### Phase 5: Update Druppie Agent Definitions
1. Update builder.yaml sandbox docs with agent parameter
2. Update tester.yaml sandbox docs with agent parameter

## Files Changed

| File | Change |
|------|--------|
| `druppie/tools/params/coding.py` | Add `ExecuteCodingTaskParams` |
| `druppie/core/tool_registry.py` | Register in `PARAMS_MODEL_MAP` |
| `druppie/core/mcp_config.yaml` | Add `agent` param to execute_coding_task |
| `druppie/mcp-servers/coding/server.py` | Add `agent` param, pass in prompt body |
| `druppie/sandbox-config/opencode-config.json` | NEW — base OpenCode config |
| `druppie/sandbox-config/agents/druppie-builder.md` | NEW — builder agent |
| `druppie/sandbox-config/agents/druppie-tester.md` | NEW — tester agent |
| `vendor/.../entrypoint.py` | Expand OPENCODE_CONFIG_CONTENT, set DISABLE_PROJECT_CONFIG |
| `vendor/.../bridge.py` | Thread `agent` param through to OpenCode |
| `vendor/.../session-instance.ts` | Add agent column, pass in WS command |
| `vendor/.../router.ts` | Extract agent from prompt request |
| `druppie/agents/definitions/builder.yaml` | Update sandbox docs |
| `druppie/agents/definitions/tester.yaml` | Update sandbox docs |
