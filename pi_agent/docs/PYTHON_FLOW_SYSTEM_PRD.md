# Python Flow System - Simplified PRD

## Overview

The Python flow system uses a simple "done" tool for agents to indicate completion. Agents run, use tools, set variables in FlowState, and must use the "done" tool to complete. Variables that agents must set are defined per phase in flow YAML files, allowing the same agent to set different variables in different runs.

## Current Problems

### 1. Overcomplicated Agent Output
Agents currently output complex JSON structures:
```json
{
  "status": "success",
  "done": false,
  "findings": {
    "tests_passed": true,
    "build_passed": true,
    "issues_remaining": 0
  },
  "deliverables": {
    "files_created": ["test.ts"],
    "commits": ["abc123"]
  },
  "summary": "Created test.ts and verified implementation"
}
```

**Problem**: Too complex, unclear what "done: false" means, why continue if done is false?

### 2. Data Classes for Agent Output
Currently defining data classes for agent output globally.

**Problem**: Agent output is per-agent and per-run, should not be defined globally.

### 3. Verifier Logic Confusion
Verifier outputs complex JSON with multiple fields (tests_passed, build_passed, issues_remaining).

**Problem**: Verifier should just set a simple `succeeded` variable.

## Proposed Solution

### 1. Done Tool - Required Completion Mechanism

Agents use a simple "done" tool to indicate completion and set variables:

```python
# Tool definition
done_tool = {
    "name": "done",
    "description": "Mark your work as complete. YOU MUST USE THIS TOOL TO FINISH.",
    "parameters": {
        "type": "object",
        "properties": {
            "variables": {
                "type": "object",
                "description": "Variables to set in FlowState. MUST include all variables specified in the flow YAML phase.",
                "additionalProperties": True
            },
            "message": {
                "type": "string",
                "description": "Completion message describing what was done. THIS IS REQUIRED."
            }
        },
        "required": ["variables", "message"]
    }
}
```

**Enforcement Rules:**
- Agents **CANNOT** finish without using the done tool
- Both `variables` and `message` are **REQUIRED**
- If variables are specified in the flow YAML phase, the agent **MUST** set all of them
- System validates that done tool was used and all required variables were set

**Usage examples:**

```json
// Verifier sets succeeded variable (required by flow YAML)
{
  "tool": "done",
  "parameters": {
    "variables": {
      "succeeded": true
    },
    "message": "All tests passed"
  }
}

// Builder can set multiple variables (required by flow YAML)
{
  "tool": "done",
  "parameters": {
    "variables": {
      "files_created": 3,
      "tests_written": 5
    },
    "message": "Implementation complete: created 3 files and 5 tests"
  }
}
```

### 2. Variables Defined Per Phase in Flow YAML

Variables that agents must set are defined in the flow YAML for each phase, not in agent YAML. This allows the same agent to set different variables in different runs.

**Example flow.yaml:**
```yaml
name: tdd
variables:
  succeeded: false
  iteration: 1
  maxIterations: 3

phases:
  # First verifier run - sets 'succeeded' variable
  - name: verify_1
    agent: verifier
    description: Initial verification
    variables:  # Variables this agent MUST set
      - succeeded: bool
    set:
      testsPassed: ${succeeded}

  # Same agent, different variables to set
  - name: verify_2
    agent: verifier
    description: Final verification
    variables:  # Different variables this time
      - final_tests_passed: bool
      - bugs_found: int
```

**Agent YAML (verifier.yaml) - NO variable definitions:**
```yaml
---
name: verifier
description: Runs tests and sets variables as specified in flow YAML
tools: [bash, read]
model: zai/glm-5.1
---

You are the **Verifier**. Your job is to:
1. Run the test commands using the `bash` tool
2. Check the results
3. Use the `done` tool to set the variables specified in the flow YAML phase

CRITICAL: You MUST use the `done` tool to complete. Both `variables` and `message` are required.

Example:
```
bash: "npm test"

If tests pass:
  done(variables={succeeded: true}, message="All tests passed successfully")

If tests fail:
  done(variables={succeeded: false}, message="Tests failed with 2 errors")
```

### 3. Flow YAML Variable System

**Flow YAML structure:**
```yaml
name: tdd
description: Test-driven development flow

# Global variables (initial state)
variables:
  succeeded: false
  iteration: 1
  maxIterations: 3

phases:
  # Phase 1: Analyze - no variables to set
  - name: analyze
    agent: analyst
    description: Analyze task and create test files

  # Phase 2: Build loop with verifier
  - name: build_loop
    while: "!${succeeded} && ${iteration} <= ${maxIterations}"
    phases:
      - name: plan
        agent: planner
        description: Create build plan

      - name: build
        agent: builder
        description: Implement according to plan

      # Verifier MUST set 'succeeded' variable
      - name: verify
        agent: verifier
        description: Run tests and set succeeded variable
        variables:  # REQUIRED: variables this agent MUST set
          - succeeded: bool
    set:
      iteration: "${iteration} + 1"

  # Phase 3: Push - only if succeeded
  - name: push
    if: "${succeeded}"
    agent: builder
    description: Push commits and create PR
```

### 4. Agent Configuration (Declarative)

All agent capabilities defined in YAML (NO variables in agent YAML):

```yaml
---
name: planner
description: Creates build plans and coordinates implementation
tools: [read, write, bash, grep, find]
spawn_subagents: true
allowed_subagents: [explore]
model: zai/glm-5.1
---

You are the **Planner**. Your job is to:
1. Read requirements and test files
2. Create a build plan
3. Use explore subagents for research and discovery
4. Use the `done` tool to set variables as specified in the flow YAML phase

CRITICAL: You MUST use the `done` tool to complete. Both `variables` and `message` are required.

Example:
```
spawn_subagents(
  tasks=[
    {agent: "explore", prompt: "Research best practices for implementing feature X"},
    {agent: "explore", prompt: "Find similar implementations in the codebase"}
  ]
)

done(variables={}, message="Plan complete and exploration finished")
```

### 5. FlowState for Variables Only

**FlowState is just a dict:**
```python
# Initial state from flow YAML
state = {
    "succeeded": False,
    "iteration": 1,
    "maxIterations": 3,
    "testsPassed": False
}

# Agent updates state via done tool (required)
agent uses: done(variables={"succeeded": True}, message="Tests passed")

# Flow checks state inline
while: "!${succeeded} && ${iteration} <= ${maxIterations}"

# Flow updates state inline
set:
  iteration: "${iteration} + 1"
  testsPassed: true
```

**No complex state management, no state classes, just a dict.**

### 6. Done Tool Enforcement

The system enforces that agents properly complete their work:

```python
def execute_phase(phase, state, agent_map):
    agent = agent_map[phase.agent]
    tools = load_tools(agent.tools) + [done_tool]

    result = run_agent(agent, phase.description, tools)

    # ENFORCEMENT: Agent MUST use done tool
    done_tool_used = False
    set_variables = {}

    if result.tool_calls:
        for call in result.tool_calls:
            if call.name == "done":
                done_tool_used = True
                set_variables = call.parameters.variables

    if not done_tool_used:
        raise Error(f"Agent {agent.name} did not use required 'done' tool")

    # ENFORCEMENT: Agent MUST set all required variables
    if hasattr(phase, 'variables'):
        for var_def in phase.variables:
            var_name = list(var_def.keys())[0]
            if var_name not in set_variables:
                raise Error(f"Agent {agent.name} did not set required variable: {var_name}")

    # Update state with variables from done tool
    state.update(set_variables)
```

### 7. No "Should Continue" Functions

**Inline conditions only:**

```yaml
# While loop - inline condition
- name: build_loop
  while: "!${succeeded} && ${iteration} <= ${maxIterations}"
  phases:
    - name: build
      agent: builder
    - name: verify
      agent: verifier
      variables:
        - succeeded: bool

# If condition - inline condition
- name: push
  if: "${succeeded}"
  agent: builder
```

**No functions like:**
```python
# REMOVE THIS
def should_continue(phase, state):
    # Complex logic...
    pass
```

## Code Structure

### File: flow_executor.py
```python
from typing import Dict, Any

FlowState = Dict[str, Any]

done_tool = {
    "name": "done",
    "description": "Mark your work as complete. YOU MUST USE THIS TOOL TO FINISH.",
    "parameters": {
        "type": "object",
        "properties": {
            "variables": {
                "type": "object",
                "description": "Variables to set in FlowState. MUST include all variables specified in the flow YAML phase.",
                "additionalProperties": True
            },
            "message": {
                "type": "string",
                "description": "Completion message describing what was done. THIS IS REQUIRED."
            }
        },
        "required": ["variables", "message"]
    }
}

def evaluate_expr(expr: str, state: FlowState) -> Any:
    """Safely evaluate an expression with state variables."""
    return eval(expr, {}, state)

def execute_phase(phase, state: FlowState, agent_map):
    """Execute a single phase with an agent."""
    agent = agent_map[phase.agent]
    tools = load_tools(agent.tools) + [done_tool]

    result = run_agent(agent, phase.description, tools)

    # ENFORCEMENT: Agent MUST use done tool
    done_tool_used = False
    set_variables = {}

    if result.tool_calls:
        for call in result.tool_calls:
            if call.name == "done":
                done_tool_used = True
                set_variables = call.parameters.variables

    if not done_tool_used:
        raise Error(f"Agent {agent.name} did not use required 'done' tool")

    # ENFORCEMENT: Agent MUST set all required variables
    if hasattr(phase, 'variables'):
        for var_def in phase.variables:
            var_name = list(var_def.keys())[0]
            if var_name not in set_variables:
                raise Error(f"Agent {agent.name} did not set required variable: {var_name}")

    # Update state with variables from done tool
    state.update(set_variables)

    # Check if condition
    if hasattr(phase, 'if') and not evaluate_expr(phase.if, state):
        return

    # Set variables inline
    if hasattr(phase, 'set'):
        for key, expr in phase.set.items():
            state[key] = evaluate_expr(expr, state)

def execute_flow(flow_config, agent_map, initial_state: FlowState) -> FlowState:
    """Execute a flow from config."""
    state = initial_state.copy()

    for phase in flow_config.phases:
        # While loop
        if hasattr(phase, 'while'):
            while evaluate_expr(phase.while, state):
                for subphase in phase.phases:
                    execute_phase(subphase, state, agent_map)
                # Update after loop
                if hasattr(phase, 'set'):
                    for key, expr in phase.set.items():
                        state[key] = evaluate_expr(expr, state)
        # Single phase
        else:
            execute_phase(phase, state, agent_map)

    return state
```

### File: flow.yaml
```yaml
name: tdd
description: Test-driven development flow

# Global variables
variables:
  succeeded: false
  iteration: 1
  maxIterations: 3

phases:
  - name: analyze
    agent: analyst
    description: Analyze task and create test files

  - name: build_loop
    while: "!${succeeded} && ${iteration} <= ${maxIterations}"
    phases:
      - name: plan
        agent: planner
        description: Create build plan

      - name: build
        agent: builder
        description: Implement according to plan

      - name: verify
        agent: verifier
        description: Run tests and set succeeded variable
        variables:  # REQUIRED variables this agent MUST set
          - succeeded: bool
    set:
      iteration: "${iteration} + 1"

  - name: push
    if: "${succeeded}"
    agent: builder
    description: Push commits and create PR
```

## Simplified Code Structure

### File: flow_executor.py
```python
from typing import Dict, Any

FlowState = Dict[str, Any]

def done_tool(variables: dict, message: str = None) -> dict:
    """Tool for agents to mark completion and set variables."""
    return {
        "tool": "done",
        "parameters": {
            "variables": variables,
            "message": message
        }
    }

def evaluate_expr(expr: str, state: FlowState) -> Any:
    """Safely evaluate an expression with state variables."""
    return eval(expr, {}, state)

def execute_phase(phase, state: FlowState, agent_map):
    """Execute a single phase with an agent."""
    agent = agent_map[phase.agent]
    tools = load_tools(agent.tools) + [done_tool]

    result = run_agent(agent, phase.description, tools)

    # Update state if agent used done tool
    if result.tool_calls:
        for call in result.tool_calls:
            if call.name == "done":
                state.update(call.parameters.variables)

    # Check if condition
    if hasattr(phase, 'if') and not evaluate_expr(phase.if, state):
        return

    # Set variables
    if hasattr(phase, 'set'):
        for key, expr in phase.set.items():
            state[key] = evaluate_expr(expr, state)

def execute_flow(flow_config, agent_map, initial_state: FlowState) -> FlowState:
    """Execute a flow from config."""
    state = initial_state.copy()

    for phase in flow_config.phases:
        # While loop
        if hasattr(phase, 'while'):
            while evaluate_expr(phase.while, state):
                for subphase in phase.phases:
                    execute_phase(subphase, state, agent_map)
                # Update after loop
                if hasattr(phase, 'set'):
                    for key, expr in phase.set.items():
                        state[key] = evaluate_expr(expr, state)
        # Single phase
        else:
            execute_phase(phase, state, agent_map)

    return state
```

### File: flow.yaml
```yaml
name: tdd
variables:
  succeeded: false
  iteration: 1
  maxIterations: 3

phases:
  - name: analyze
    agent: analyst
    description: Analyze task and create tests

  - name: build_loop
    while: "!${succeeded} && ${iteration} <= ${maxIterations}"
    phases:
      - name: plan
        agent: planner
        description: Create build plan

      - name: build
        agent: builder
        description: Implement according to plan

      - name: verify
        agent: verifier
        description: Run tests and set succeeded variable
    set:
      iteration: "${iteration} + 1"

  - name: push
    if: "${succeeded}"
    agent: builder
    description: Push commits and create PR
```

## Implementation Plan

### Phase 1: Create Done Tool
- [ ] Implement `done_tool` with required `variables` and `message` parameters
- [ ] Add enforcement: agents MUST use done tool to complete
- [ ] Add enforcement: agents MUST set all required variables from flow YAML
- [ ] Test basic usage

### Phase 2: Update Agent YAML Structure
- [ ] Add `spawn_subagents: true/false` field to agent YAML
- [ ] Add `allowed_subagents: [agent-names]` field to agent YAML
- [ ] Update agent instructions to reflect subagent capabilities
- [ ] Update wave-orchestrator agent with subagent spawning

### Phase 3: Update Flow YAML
- [ ] Define variables per phase (not in agent YAML)
- [ ] Use `succeeded` variable in while conditions
- [ ] Remove builder agent from TDD flow
- [ ] Use wave-orchestrator to spawn building agents
- [ ] Use inline set expressions

### Phase 4: Update FlowExecutor
- [ ] Implement done tool enforcement
- [ ] Implement required variable validation
- [ ] Implement inline condition evaluation
- [ ] Update FlowState to simple dict

### Phase 5: Update Verifier
- [ ] Simplify verifier to only set `succeeded` variable
- [ ] Update verifier YAML instructions (no variable definitions in YAML)
- [ ] Test verifier flow

### Phase 6: Testing
- [ ] Test simple hello world flow
- [ ] Test TDD flow with wave-orchestrator spawning subagents
- [ ] Test error handling (agent not using done tool)
- [ ] Test error handling (agent not setting required variables)
- [ ] Test variable updates

## Success Criteria

- [ ] Verifier only sets `succeeded` variable (no complex JSON)
- [ ] Agents MUST use "done" tool to complete (enforced by system)
- [ ] Done tool requires both `variables` and `message` (enforced by system)
- [ ] Agents MUST set all required variables from flow YAML (enforced by system)
- [ ] Variables defined per phase in flow YAML (not in agent YAML)
- [ ] Same agent can set different variables in different runs
- [ ] No global data classes for agent output
- [ ] FlowExecutor enforces done tool usage and required variables
- [ ] No "should_continue" functions (inline conditions only)
- [ ] FlowState is a simple dict
- [ ] Flow YAML is clear and readable
- [ ] Agent YAML is declarative (tools, spawn_subagents, allowed_subagents)
- [ ] TDD flow uses wave-orchestrator to spawn building agents (no direct builder agent)
- [ ] Agent YAML defines spawn_subagents capability and allowed_subagents list

## Benefits

1. **Clearer Intent** - Done tool is explicit about completion and required
2. **Flexible** - Same agent can set different variables in different runs
3. **Declarative** - Agent capabilities in YAML (tools, spawn_subagents, allowed_subagents)
4. **Transparent** - Flow YAML clearly shows variables each agent must set
5. **Maintainable** - Simple structure, easy to modify
6. **Enforced** - System validates that agents properly complete work

## Example: Complete TDD Flow

### flow.yaml
```yaml
name: tdd
description: Test-driven development flow

# Global variables (initial state)
variables:
  succeeded: false
  iteration: 1
  maxIterations: 3

phases:
  # Phase 1: Analyze - creates test files
  - name: analyze
    agent: analyst
    description: Analyze task and create test files

  # Phase 2: Build loop with wave-orchestrator
  - name: build_loop
    while: "!${succeeded} && ${iteration} <= ${maxIterations}"
    phases:
      # Planner creates plan and can spawn subagents
      - name: plan
        agent: planner
        description: Create or update build plan

      # Wave-orchestrator spawns building agents
      - name: execute
        agent: wave-orchestrator
        description: Coordinate implementation by spawning builder subagents

      # Verifier checks and sets succeeded
      - name: verify
        agent: verifier
        description: Run tests and set succeeded variable
        variables:  # Variables verifier MUST set
          - succeeded: bool
    set:
      iteration: "${iteration} + 1"

  # Phase 3: Push - only if succeeded
  - name: push
    if: "${succeeded}"
    agent: wave-orchestrator
    description: Push commits and create PR
```

### wave-orchestrator.yaml
```yaml
---
name: wave-orchestrator
description: Coordinates implementation by spawning builder subagents
tools: [read, write, bash, grep, find]
spawn_subagents: true
allowed_subagents: [builder, tester]
model: zai/glm-5.1
---

You are the **Wave Orchestrator**. Your job is to:
1. Read the build plan from planner
2. Spawn builder subagents to implement the plan
3. Coordinate and collect results from subagents
4. Use the `done` tool to set variables as specified in the flow YAML phase

CRITICAL: You MUST use the `done` tool to complete. Both `variables` and `message` are required.

## Subagent Spawning

You can spawn subagents using the spawn_subagents tool:
```
spawn_subagents(
  tasks=[
    {agent: "builder", prompt: "Implement feature X according to plan"},
    {agent: "tester", prompt: "Write tests for feature X"}
  ]
)
```

The tool blocks until all subagents complete, then returns their results.

## Completion

After all subagents complete and results are collected:
```
done(
  variables={},
  message="Implementation complete: 5 files created by builder subagents"
)
```
```

### verifier.yaml
```yaml
---
name: verifier
description: Runs tests and sets variables as specified in flow YAML
tools: [bash, read]
model: zai/glm-5.1
---

You are the **Verifier**. Your job is to:
1. Run the test commands using the `bash` tool
2. Check the results
3. Use the `done` tool to set the variables specified in the flow YAML phase

CRITICAL: You MUST use the `done` tool to complete. Both `variables` and `message` are required.

Example:
```
bash: "npm test"

If tests pass:
  done(
    variables={succeeded: true},
    message="All tests passed successfully"
  )

If tests fail:
  done(
    variables={succeeded: false},
    message="Tests failed with 2 errors: expect 2 to equal 3"
  )
```
```

### planner.yaml
```yaml
---
name: planner
description: Creates build plans and uses explore subagents for research
tools: [read, write, bash, grep, find]
spawn_subagents: true
allowed_subagents: [explore]
model: zai/glm-5.1
---

You are the **Planner**. Your job is to:
1. Read requirements and test files
2. Use explore subagents for research and discovery
3. Create a build plan
4. Use the `done` tool to set variables as specified in the flow YAML phase

CRITICAL: You MUST use the `done` tool to complete. Both `variables` and `message` are required.

Example:
```
# Use explore subagents for research
spawn_subagents(
  tasks=[
    {agent: "explore", prompt: "Research best practices for implementing feature X"},
    {agent: "explore", prompt: "Find similar implementations in the codebase"}
  ]
)

# Read requirements and tests
read: "requirements.md"
read: "tests/"

# Create plan based on research
write: "plan.md", content="# Build Plan\n\n1. Implement X\n2. Write tests for X\n3. Verify tests pass"

done(
  variables={},
  message="Build plan created and saved to plan.md after research"
)
```
```

### Execution Flow

1. **Analyze phase runs** → creates test files
2. **Build loop starts** (while !succeeded and iteration <= 3)
   - Plan phase runs → creates plan
   - Execute phase runs (wave-orchestrator) → spawns builder subagents
   - Verify phase runs → runs tests, sets succeeded=true/false
   - Loop updates iteration
3. **Push phase runs** (if succeeded=true) → wave-orchestrator pushes and creates PR

**Key Points:**
- Builder agents are spawned by wave-orchestrator, not run directly in flow
- Planner agent uses only explore subagents for research
- Only phases that need variables define them in flow YAML (e.g., verifier sets succeeded)
- All agents MUST use done tool with required message
- System enforces that required variables are set when defined
