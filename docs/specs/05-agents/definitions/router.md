# router

File: `druppie/agents/definitions/router.yaml` (86 lines).

## Role

Classification gateway — the first real agent to see every user message. Decides whether the conversation is a new project, an update to an existing project, or general chat.

## Config

| Field | Value |
|-------|-------|
| category | system |
| llm_profile | cheap |
| temperature | 0.1 |
| max_tokens | 4096 |
| max_iterations | 10 |
| builtin tools | `set_intent`, `done`, `hitl_ask_question`, `hitl_ask_multiple_choice_question` |
| MCPs | `web` (search_files, list_directory, read_file, fetch_url, search_web, get_page_info) |
| system prompts | tool_only_communication, summary_relay, done_tool_format, workspace_state |

## Outputs

Exactly one call to `set_intent` per run, then `done()`.

`set_intent` variants:
- `{intent: "create_project", project_name: "<name>"}` — creates a new Gitea repo + workspace and updates the planner's prompt accordingly.
- `{intent: "update_project", project_id: "<uuid>"}` — resumes work on an existing project.
- `{intent: "general_chat"}` — conversational path; no project created.

## Decision heuristics

- Message references "build / create / make" + no existing project context → `create_project`.
- Message references an existing project (by name or ID) and says "fix / update / change / add" → `update_project`.
- Questions about architecture, comparisons, "how should I…", "what would you recommend…" → `general_chat`.
- Ambiguous → use `hitl_ask_multiple_choice_question` to ask the user.

## Web MCP usage

The router has web access so it can look up reference material (NORA principles, existing projects in the dataset) before classifying. In practice most routes are classified without web lookups.

## No project creation for general_chat

`general_chat` sessions have `project_id = null` on the session row. Skills, architect, and business_analyst can still be invoked (for advice), but no files are written.
