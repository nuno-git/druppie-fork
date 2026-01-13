---
id: orchestration
name: "Orchestration"
description: "Capability to manage complex workflows, schedule dependencies, and direct other agents."
type: skill
version: 1.0.0
---

## Description
This skill represents the ability of a "Spec Agent" or "Architect" to break down a high-level goal into executable steps for other agents.

## Usage
- Defining dependency chains (e.g. Script -> Audio -> Video).
- Assigning tasks to specific specialized agents (`execution-agents`).
- ensuring data flow between steps (mapping outputs to inputs).

## Logic
- Relies on the Planner's "Dependency-Driven Execution" strategy.
- Enforces strict stage-gating to prevent out-of-order execution.
