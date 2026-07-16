---
id: "003"
title: "Developer/Agent Testing Page"
status: implemented
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/003-developer-agent-testing-page.md"]
linked_research: []
linked_specs: ["docs/specs/003-developer-agent-testing-page.feature"]
---

## Problem

When developing or debugging agents, the feedback loop was too slow for iterative work. Changing a prompt, adding a tool, or tweaking a YAML definition meant the only way to test was to run the full Druppie pipeline: router to BA to architect to planner to developer.

That meant creating a full project session, walking through every upstream agent, and waiting for the pipeline to reach the agent you actually wanted to test. Ten seconds of curiosity turned into minutes of waiting, and most of that time was spent on agents you had no intention of changing.

Iterative development on a single agent became painful. You could not isolate the change, and you could not get a fast read on whether your edit helped or broke something.

## Goal

A dedicated page where developers can pick any single YAML-defined agent, optionally select a project, enter a prompt, and execute it on the spot.

The target: from "I want to test agent X" to "agent X is running" in under 10 seconds.

The agent runs through the same orchestrator as the real pipeline. There is no mocked execution, no shortcut path. The agent gets real MCP tools, a real sandbox, and a real LLM, exactly as it would in production.

## User Journey

1. The developer opens the "Agent Test" page from the NavRail at route `/tools/developer`.
2. They select an agent from the dropdown, which is populated from `GET /api/agents` and lists every YAML-defined agent.
3. If the selected agent has `git_scope: current_project`, a project dropdown appears and the developer picks a project. If the agent has `git_scope: update_core`, the project selector is hidden and the page shows "Core update, no project needed".
4. They type a prompt into the text area.
5. They click Execute.
6. The page polls the run status at `GET /api/agent-test/runs/{id}` every 1.5 seconds, moving through pending, then running, then completed or failed.
7. They can click any run in the history panel to open the full session in inspect mode.

## Constraints

- Must use the same orchestrator execution path as the real pipeline (`execute_pending_runs`). No parallel, simplified implementation.
- No mocked or simplified execution. The agent gets real MCP tools, a real sandbox, and a real LLM.
- The page is for authenticated users only. It is not exposed to end users in production.
- The project selector is conditional on the agent's `git_scope` property.

## Out of Scope

- Multi-agent pipelines or sequential agent chains. This page runs one agent at a time.
- Branch selection. The sandbox automatically handles which repo to clone based on `git_scope`.
- Production user access or role-based restrictions beyond authentication.

## Open Questions

No open questions remain. The feature is implemented and in active use.

## Linked Documents

- ADRs: `docs/adrs/003-developer-agent-testing-page.md`
- Specs: `docs/specs/003-developer-agent-testing-page.feature`
- Guide: `docs/guides/developer-page.md`
