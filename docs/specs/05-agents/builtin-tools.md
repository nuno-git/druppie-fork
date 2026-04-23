# Builtin Tools

`druppie/agents/builtin_tools.py`. Tools that run in-process (not via MCP), exposed to agents via `BUILTIN_TOOL_DEFS`.

## The 9 builtin tools

| Tool | Description |
|------|-------------|
| `done` | Signal agent completion. Required for every agent run. |
| `make_plan` | Planner only — insert new PENDING agent runs. |
| `set_intent` | Router only — classify session intent and create project. |
| `hitl_ask_question` | Ask user a free-text question. Pauses the agent. |
| `hitl_ask_multiple_choice_question` | Ask with choices. Pauses the agent. |
| `create_message` | Summarizer only — user-facing message. |
| `invoke_skill` | Load a SKILL.md into the agent's context. |
| `execute_coding_task` | Builder/developer/update_core_builder — spawn sandbox. |
| `test_report` | Test_executor only — structured PASS/FAIL report. |

## Schemas

Exact schemas in `BUILTIN_TOOL_DEFS`:

### `done`
```json
{
  "name": "done",
  "description": "Complete this agent run. summary is prepended to the next agent's context.",
  "parameters": {
    "type": "object",
    "properties": {
      "summary": {"type": "string", "description": "Single-line summary of what was accomplished, including concrete details (branch names, file paths, container names, URLs)."},
      "next_agent": {"type": "string", "description": "Optional: agent_id to run next, bypassing the Planner.", "enum": ["business_analyst", "architect", "build_classifier", "builder_planner", "test_builder", "builder", "test_executor", "developer", "deployer", "update_core_builder", "reviewer", "summarizer"]}
    },
    "required": ["summary"]
  }
}
```

### `make_plan`
```json
{
  "name": "make_plan",
  "description": "Create the next steps of the execution plan.",
  "parameters": {
    "type": "object",
    "properties": {
      "steps": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "agent_id": {"type": "string"},
            "prompt": {"type": "string"}
          },
          "required": ["agent_id", "prompt"]
        }
      }
    },
    "required": ["steps"]
  }
}
```

### `set_intent`
```json
{
  "name": "set_intent",
  "description": "Declare the intent for this session.",
  "parameters": {
    "type": "object",
    "properties": {
      "intent": {"type": "string", "enum": ["create_project", "update_project", "general_chat"]},
      "project_id": {"type": "string", "description": "For update_project: the existing project UUID"},
      "project_name": {"type": "string", "description": "For create_project: the name of the new project"}
    },
    "required": ["intent"]
  }
}
```

### HITL tools
```json
{
  "name": "hitl_ask_question",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "context": {"type": "string", "description": "Optional background info shown to the user"}
    },
    "required": ["question"]
  }
}
```

```json
{
  "name": "hitl_ask_multiple_choice_question",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "choices": {"type": "array", "items": {"type": "string"}, "minItems": 2},
      "context": {"type": "string"}
    },
    "required": ["question", "choices"]
  }
}
```

The system auto-appends "Other" (or "Anders" in Dutch) to the choices if not already present — agents don't need to.

### `create_message`
```json
{
  "name": "create_message",
  "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}
}
```

### `invoke_skill`
```json
{
  "name": "invoke_skill",
  "parameters": {
    "type": "object",
    "properties": {
      "skill_name": {"type": "string", "description": "The name of the skill to invoke (e.g., 'code-review', 'git-workflow')"}
    },
    "required": ["skill_name"]
  }
}
```

The schema does not enforce an enum — the `SkillService` resolves the name at invocation time and returns an error if the skill is not found. Currently five skills exist under `druppie/skills/`: `architecture-principles`, `code-review`, `git-workflow`, `making-mermaid-diagrams`, `module-convention`.

### `execute_coding_task`
```json
{
  "name": "execute_coding_task",
  "description": "Spawn an isolated sandbox to run a complex coding task. The sandbox sees the workspace and can commit/push.",
  "parameters": {
    "type": "object",
    "properties": {
      "task": {"type": "string", "description": "Self-contained prompt for the sandbox agent. Must be fully specified."},
      "agent": {"type": "string", "default": "explore", "description": "Which sandbox agent persona (explore, implement, test)."},
      "repo_target": {"type": "string", "enum": ["project", "druppie_core"], "default": "project"}
    },
    "required": ["task"]
  }
}
```

### `test_report`
```json
{
  "name": "test_report",
  "parameters": {
    "type": "object",
    "properties": {
      "iteration": {"type": "integer"},
      "tests_passed": {"type": "boolean"},
      "summary": {"type": "string"},
      "test_command": {"type": "string"},
      "failed_count": {"type": "integer"},
      "passed_count": {"type": "integer"},
      "error_classification": {"type": "string", "description": "assertion_failure, missing_function, import_error, type_error, syntax_error, configuration_error, environment_error, test_error"}
    },
    "required": ["iteration", "tests_passed", "summary"]
  }
}
```

## Default tool set

Every agent receives `{done, hitl_ask_question, hitl_ask_multiple_choice_question}` unless its YAML explicitly lists `builtin_tools:`. Additional builtins are granted by inclusion in that list:

- router: + `set_intent`
- planner: + `make_plan`
- summarizer: + `create_message`
- architect, business_analyst, developer: + `invoke_skill`
- builder, developer, update_core_builder: + `execute_coding_task`
- test_executor: + `test_report`

## Tool handlers

Each builtin has a handler in `druppie/execution/builtin_handlers.py` (or `tool_executor.py` for simple cases). Handlers:
- Receive the parsed arguments + the agent run context.
- Execute side effects (insert rows, update session).
- Return a string or dict that becomes the tool call result.

Some handlers have privileged side effects:
- `set_intent` creates Project + Gitea repo if needed.
- `make_plan` inserts PENDING agent runs.
- `done` updates agent run status.
- `execute_coding_task` creates SandboxSession and calls control plane.
