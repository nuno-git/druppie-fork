# Simplify update_core Flow — Design Spec

## Problem

The current update_core flow is overly complex:
- Mid-flight intent switching (`switch_to_update_core` tool)
- Session repo context mutation (`repo_owner`/`repo_name` on Session model)
- Fragile Architect keyword detection triggering a separate tool call
- Intent flipping from `create_project` → `update_core` → needs manual reset
- 7+ agent handoffs with run cancellation mid-flow

## Solution

Replace the entire `switch_to_update_core` mechanism with a simple signal-based approach:

1. **Architect signals `DESIGN_APPROVED_CORE_UPDATE`** instead of calling a tool
2. **Planner reads the signal** and routes to a new `update_core_builder` agent
3. **`update_core_builder`** uses `execute_coding_task` — repo routing is hardcoded by agent_id check
4. **After core update**, Planner routes back to Architect (run 2) for the actual project design
5. **Session intent never changes** — stays `create_project` or `update_project` throughout

## Flow

```
Router → set_intent("create_project") → creates project + Gitea repo
→ BA (gathers requirements, DESIGN_APPROVED)
→ Architect (run 1: detects core change, writes TD, signals DESIGN_APPROVED_CORE_UPDATE)
→ update_core_builder (execute_coding_task → GitHub Druppie repo, creates PR, done() requires developer approval)
→ Human merges PR, approves done()
→ Architect (run 2: designs actual project with core changes in place, DESIGN_APPROVED)
→ normal flow (builder_planner → test_builder → builder → test_executor → deployer → summarizer)
```

## New Agent: `update_core_builder`

- Dedicated agent for Druppie core changes
- Uses `execute_coding_task` (existing tool)
- Repo routing: `execute_coding_task` checks `agent_id == "update_core_builder"` → uses `DRUPPIE_REPO_OWNER`/`DRUPPIE_REPO_NAME` env vars, GitHub provider
- `done` tool requires `developer` role approval (via `approval_overrides`)
- Approval message includes PR URL, tells reviewer to merge first
- Read-only MCP tools: `coding:read_file`, `coding:list_dir`

## Architect Changes

- Remove `switch_to_update_core` from `extra_builtin_tools`
- New signal: `DESIGN_APPROVED_CORE_UPDATE` (used instead of `DESIGN_APPROVED` when project modifies Druppie)
- Still writes `technical_design.md` as normal

## Planner Changes

- New re-evaluation: `DESIGN_APPROVED_CORE_UPDATE` → route to `update_core_builder`
- New re-evaluation: after `update_core_builder` completed → route to Architect (run 2)
- Remove all `update_core` intent handling (MODE 1 section 3, CHAT_ROUTE_UPDATE_CORE)
- Update mandatory sequences

## Cleanup

- Remove `switch_to_update_core` tool (definition, implementation, dispatch)
- Remove `repo_owner`/`repo_name` from Session model
- Remove `SessionRepository.update_repo_context()`
- Remove `update_core` intent routing in `execute_coding_task` and sandbox retry
- Remove `is_builtin_tool` entry for `switch_to_update_core`
- Update comments referencing `update_core` intent

## Env Vars

- `DRUPPIE_REPO_OWNER` (default: `nuno-git`)
- `DRUPPIE_REPO_NAME` (default: `druppie-fork`)

## DB Impact

- Remove 2 columns from `sessions` table → DB reset required
