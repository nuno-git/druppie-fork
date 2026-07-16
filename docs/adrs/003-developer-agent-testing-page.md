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

Build a dedicated developer page (`/tools/developer`) that creates a minimal session with a single pending agent run and executes it directly through the shared orchestrator (`execute_pending_runs`). The page lets you pick any YAML-defined agent, optionally select a project for `current_project` scoped agents, enter a prompt, and execute. This skips the multi-step pipeline entirely.

## Consequences

Positive: fast iteration on individual agents, easy debugging of agent behavior and prompts, and the same execution engine as production so there's no drift.

Negative: a test-only page not meant for end users, a risk of false confidence if agent behavior differs inside the full multi-step context, and the maintenance burden of a second entry point into the orchestrator.
