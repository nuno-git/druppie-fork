---
id: expand_loop
name: "Expand Loop"
description: "System skill to expand a list into multiple parallel steps."
type: skill
version: 1.0.0
---

## Description
This skill triggers the internal specialized logic to iterate over an array (e.g. `av_script`) and map it to a set of parallel tasks for another agent.

## Parameters
- `iterator_key` (string): The key in memory containing the list to iterate (e.g. "av_script").
- `target_agent` (string): The Agent ID to assign the expanded steps to.
- `target_action` (string): The action/skill to execute for each item.

## Behavior
- Does not execute anything itself.
- Returns immediately.
- Triggers the Planner's `expandLoop` logic to inject N new steps into the plan.
