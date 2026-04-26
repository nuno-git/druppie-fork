# Agent Tests

Path: `testing/agents/*.yaml`. Each file exercises one or more real LLM agents with HITL simulation.

Slower than tool tests. Non-deterministic (LLM output varies). The right choice when behaviour depends on agent reasoning:
- Does the architect really produce a TD that respects the FD?
- Does the BA avoid solution bias?
- Does the router classify intent correctly for edge cases?

## YAML shape

```yaml
agent-test:
  name: ba-design-no-bias
  description: BA writes FD without prescribing a solution
  tags: [type:agent, business_analyst, bias-check]

  # Optional: run a tool-test setup first (same merge semantics as tool tests)
  setup:
    - test: setup-create-project-pipeline

  # The user message that triggers the session
  message: "Build me a way to keep track of my coffee consumption"

  # Which agents to run (BoundedOrchestrator halts when all these are COMPLETED)
  agents:
    - business_analyst

  # Persona for answering HITL questions + approvals
  hitl: non-technical-pm      # name from testing/profiles/hitl.yaml

  # LLM judge profile
  judge_profile: default

  # Top-level assertions
  assert:
    - agent: business_analyst
      completed: true
    - agent: business_analyst
      tool: coding:make_design

  # Optional: side-effect verification
  verify:
    - type: file_exists
      path: docs/functional_design.md

  # Judge checks
  judge:
    context:
      - all_tool_calls: {agent: business_analyst}
    checks:
      - name: No AI bias
        check: "Does the FD treat the user's mention of 'AI' as a requirement
                rather than a proposed solution? (PASS if it explores WHY the
                user wants AI instead of bolting on LLM features)"
```

## Fields

| Field | Purpose |
|-------|---------|
| `name`, `description`, `tags` | Standard |
| `setup` | List of tool tests to run as fixtures |
| `message` | Kick-off message (sent as the user's first message) |
| `agents` | Agents the BoundedOrchestrator waits for. Others run if planner calls them but don't affect halt condition |
| `hitl` | HITL profile name. Can also be a list (rotate personas) or inline dict |
| `judge_profile` | Judge profile name from `testing/profiles/judges.yaml` |
| `assert`, `verify`, `judge` | As in tool tests |
| `inputs` | For manual tests — parameterised inputs rendered at runtime |

## HITL modes

- **Named profile** — `hitl: non-technical-pm`. Uses profile from `testing/profiles/hitl.yaml`.
- **List** — `hitl: [dev, picky]`. Rotate through on each question.
- **Inline** — `hitl: {model: glm-4.7, provider: zai, prompt: "You are..."}`. Ad-hoc.

## Manual tests (with `inputs`)

```yaml
agent-test:
  name: ba-custom-prompt
  inputs:
    - name: project_description
      type: string
      required: true
      default: "a todo app"
    - name: budget
      type: choice
      options: [low, medium, high]
      default: medium
  message: "Build me {{project_description}} with {{budget}} budget"
  agents: [business_analyst]
```

The UI's "Run Tests" modal shows an input form for each declared input. Template substitution happens in `TestRunner` before dispatch.

## Shipped files

```
testing/agents/
├── architect-reviews-fd.yaml
├── architect-reviews-vergunningzoeker.yaml
├── ba-design-no-bias.yaml
├── ba-fd-reject-then-approve.yaml
├── builder-uses-sdk.yaml
├── planner-after-ba.yaml
└── router-picks-correct-project.yaml
```

### `ba-fd-reject-then-approve.yaml`

Notable test — exercises the approval gate cycle:
1. BA writes FD.
2. session_owner approval gate fires. Persona rejects with a concrete gap.
3. BA reads rejection reason, revises FD.
4. Second approval gate fires. Persona approves.
5. BA emits `done(DESIGN_APPROVED)`.

Judge checks:
- Two `make_design` tool calls (first rejected, second approved).
- Evidence that the revised FD addresses the feedback.
- Final `done()` summary contains DESIGN_APPROVED.

This uses the `picky-session-owner` HITL profile which is programmed to reject the first attempt and approve the second.

## Tests that exercise the full pipeline

- `architect-reviews-fd.yaml` — BA → architect, architect produces TD.
- `planner-after-ba.yaml` — BA → planner re-evaluation → next agent selection.
- `builder-uses-sdk.yaml` — builder sandboxed task integration (including SDK use).
- `router-picks-correct-project.yaml` — router classification on an ambiguous message.

## Determinism

Agent tests are non-deterministic — different LLM runs give different specifics. Assertions cope by:
- Checking high-level outcomes (tool called, agent completed) rather than exact strings.
- Using LLM judges for qualitative checks.
- Using broad regex or contains checks.

A failing agent test is rarely a regression in one invocation — it's usually consistent across re-runs. The UI shows pass rate per test over time so flakiness is visible.
