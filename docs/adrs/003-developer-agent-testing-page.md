---
id: "003"
title: Add developer page for single-agent testing
status: accepted
date: 2026-07-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/003-developer-agent-testing-page.md
linked_research: null
---

## Context

Testing individual agents required running the full Druppie pipeline (router to BA to architect to planner to developer). That made for a slow feedback loop during agent development. There was no way to isolate and test a single agent's behavior, prompts, or tool access on its own.

## Decision

Build a dedicated developer page (`/tools/developer`) that creates a minimal
session with a single pending agent run and executes it directly through the
shared orchestrator (`execute_pending_runs`). The page lets you pick any
YAML-defined agent, optionally select a project for `current_project` scoped
agents, enter a prompt, and execute. This skips the multi-step pipeline entirely.

### Architecture

**Frontend** (`frontend/src/pages/DeveloperPage.jsx`, ~355 lines):

- Route `/tools/developer`, registered in `App.jsx`. NavRail entry: "Agent Test".
- Form state: `selectedAgentId`, `selectedProjectId`, `taskPrompt`.
- Agent dropdown populated from `GET /api/agents`. Each agent carries a
  `git_scope` property (from the `mcps.coding.git` field in its YAML).
- Project picker is conditional: shown only when
  `selectedAgent?.git_scope === "current_project"`. For `update_core` agents,
  the form shows "Core update — no project needed".
- Execute calls `executeAgentTest({ agent_id, prompt, project_id })`.
- Polls `GET /api/agent-test/runs/{id}` every 1.5s until terminal status.
- History panel lists prior sessions titled "Agent Test: ..."; clicking one
  opens `/chat?session={id}&mode=inspect`.

**Backend** (`druppie/api/routes/agent_test.py`):

- `POST /api/agent-test/execute` — creates a minimal session, creates a pending
  agent_run, launches `orchestrator.execute_pending_runs(session_id)` in a
  background task.
- `GET /api/agent-test/runs/{agent_run_id}` — returns current run status.

Execution uses the exact same orchestrator, MCP tools, and sandbox as the chat
and retry flows. There is no separate execution path.

### `git_scope` values

- `current_project` — agent operates on a project repo in Gitea. Project
  selection required.
- `update_core` — agent operates on Druppie's own GitHub repo. No project
  needed. Current core agents: `ultimate_dev_core`, `core_explorer`,
  `core_builder_subagent`.
- `other_projects` — agent can work across multiple projects.

## Consequences

Positive: fast iteration on individual agents, easy debugging of agent behavior and prompts, and the same execution engine as production so there's no drift.

Negative: a test-only page not meant for end users, a risk of false confidence if agent behavior differs inside the full multi-step context, and the maintenance burden of a second entry point into the orchestrator.
