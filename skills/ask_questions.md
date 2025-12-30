---
id: ask_questions
name: "Ask Questions"
description: "Interactively query the user to gather missing requirements or clarify ambiguity."
version: 1.0.0
---

## Description
This skill allows an agent to pause execution and request specific information from the user. It is essential for "Discovery" phases where goals or parameters are undefined.

## Parameters
- `questions` (List<String>): A list of specific questions to ask.
- `assumptions` (List<String>): A corresponding list of default answers/assumptions if the user does not respond. MUST match the length of `questions`.

## Behavior
- The system will pause and present these questions to the user.
- The system will auto-accept defaults if configured (e.g. in test mode) or if the user chooses to accept defaults.
- The answers are returned as the result of the step.
