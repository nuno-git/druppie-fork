# Developer Page — Agent Testing

## Overview

The developer page is a dedicated spot for testing individual agents in isolation. It lives at `/tools/developer` and shows up in the NavRail as **Agent Test**.

The point is speed. Instead of running the full Druppie pipeline (router → BA → architect → planner → developer) just to exercise one agent, you pick an agent, optionally pick a project, type a prompt, and hit Execute. The page spins up a minimal session and runs only the agent you selected.

## User Flow

1. **Select an agent.** A dropdown lists every YAML agent definition, fetched from `GET /api/agents`. Each agent carries a `git_scope` property, which comes from the `mcps.coding.git` field in its YAML.
2. **Select a project (conditional).** The project picker only appears when the chosen agent has `git_scope: current_project`. For `git_scope: update_core` agents, the form shows "Core update — no project needed" instead, and the picker stays hidden.
3. **Enter a prompt.** Free text describing what you want the agent to do.
4. **Click Execute.** The page creates a minimal session and kicks off the agent run.

### The three `git_scope` values

`git_scope` tells the system which codebase the agent works against.

- `current_project` — the agent operates on a project repo hosted in Gitea. Project selection is required.
- `update_core` — the agent operates on Druppie's own codebase, hosted on GitHub. No project is needed. When the sandbox spins up, it clones the Druppie repo instead of a project repo.
- `other_projects` — the agent can work across multiple projects.

## Architecture

### Frontend

Everything lives in one file: `frontend/src/pages/DeveloperPage.jsx`. It is a single ~355-line component.

- **Route:** `/tools/developer`, registered in `App.jsx`.
- **NavRail entry:** "Agent Test".
- **Form state:** three values, `selectedAgentId`, `selectedProjectId`, and `taskPrompt`.
- **Conditional logic:** the project picker is gated by `needsProject = selectedAgent?.git_scope === "current_project"`.
- **Execute handler:** calls `executeAgentTest({ agent_id, prompt, project_id })`.
- **Polling:** after Execute, the page polls `GET /api/agent-test/runs/{id}` every 1.5 seconds until the run reaches a terminal status.
- **History panel:** lists prior sessions titled "Agent Test: ...". Clicking one opens `/chat?session={id}&mode=inspect`.

### Backend

The backend lives in `druppie/api/routes/agent_test.py`.

- `POST /api/agent-test/execute` — creates a minimal session, creates a pending agent_run, and launches the orchestrator in a background task.
- `GET /api/agent-test/runs/{agent_run_id}` — returns the current run status.

Execution uses the shared `orchestrator.execute_pending_runs(session_id)`. That is the exact same engine the chat and retry flows use. There is no separate execution path here. The developer page relies on the same orchestrator, the same MCP tools, and the same sandbox setup as everything else.

## What "update core" means

"Update core" is not a mode the user picks. It is an inherent property of the agent, declared in its YAML definition.

When an agent has `git: update_core` in its `mcps.coding` config, the module-coding MCP server clones Druppie's own GitHub repo into the sandbox instead of cloning a project repo. The agent then works against the Druppie codebase and can open PRs there.

The current core agents are:

- `ultimate_dev_core`
- `core_explorer`
- `core_builder_subagent`

## Related docs

- ADR: `docs/adrs/003-developer-agent-testing-page.md`
- PRD: `docs/prds/003-developer-agent-testing-page.md`
- Spec: `docs/specs/003-developer-agent-testing-page.feature`
