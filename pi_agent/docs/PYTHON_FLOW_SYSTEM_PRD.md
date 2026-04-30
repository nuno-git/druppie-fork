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

---

## Implementation Plan

### Phase 1: Core Infrastructure Changes

#### File: `src/flows/schema.ts`
**Changes:**
- Add `variables` field to `PhaseDef` interface for per-phase variable requirements
- Update variable typing to support type definitions (e.g., `- succeeded: bool`)
- Add validation that all defined variables are required (no optional variables)

#### File: `src/flows/executor/FlowContext.ts`
**Changes:**
- Simplify from Map-based to simple dict-like structure (closer to PRD's FlowState)
- Add method to validate required variables are set
- Add method to check if done tool was used by agent
- Update variable interpolation to support new syntax
- Remove complex agent reference parsing (simplify to direct variable access)

#### File: `src/flows/executor/FlowExecutor.ts`
**Changes:**
- Add done tool to agent tool list automatically
- Implement done tool enforcement for ALL phases (raise error if not used)
- Implement variable validation after each phase (all defined variables are required)
- Update phase execution to check done tool usage unconditionally
- Modify agent result handling to extract done tool parameters
- Add error handling for missing done tool, missing variables, or missing message

#### File: `src/flows/tools/decision-tool.ts`
**Changes:**
- Update condition evaluation to support simplified FlowState
- Add support for new variable interpolation patterns
- Ensure compatibility with per-phase variable definitions

### Phase 2: Done Tool Implementation

#### File: `src/tools/done-tool.ts` (NEW FILE)
**Changes:**
- Create new done tool with required `variables` and `message` parameters
- Implement tool definition following TypeScript tool patterns
- Add validation that both parameters are provided
- Add descriptive error messages for missing parameters
- Integrate with existing tool infrastructure

#### File: `src/agents/runner.ts`
**Changes:**
- Update agent execution to detect and handle done tool calls
- Modify result extraction to capture done tool parameters
- Update summary/variable extraction to work with done tool output
- Add validation for done tool usage in agent results

### Phase 3: Agent YAML Updates

#### File: `.pi/agents/verifier.md`
**Changes:**
- Remove JSON output requirement
- Remove complex variable definitions from instructions
- Add done tool usage instructions with examples
- Simplify output to use done tool instead of JSON + verdict line
- Update examples to show done(variables={succeeded: true}, message="...")

#### File: `.pi/agents/planner.md`
**Changes:**
- Remove any variable output requirements
- Add done tool usage instructions
- Update examples to use done tool
- Simplify completion message format

#### File: `.pi/agents/analyst.md`
**Changes:**
- Add done tool usage instructions
- Update completion pattern to use done tool
- Remove any structured output requirements

#### File: `.pi/agents/wave-orchestrator.md`
**Changes:**
- Add `spawn_subagents: true` to frontmatter (if not present)
- Add `allowed_subagents: [builder, tester]` to frontmatter
- Add done tool usage instructions for coordination
- Update subagent spawning examples
- Add done tool call after subagent completion

### Phase 4: Flow YAML Updates

#### File: `.pi/flows/tdd.yaml`
**Changes:**
- Add `variables` field to phases that require variable setting
- Update verify phase to require `succeeded` variable
- Remove complex variable sets, simplify to inline expressions
- Update conditions to use simplified variable access
- Add explicit variable requirements for relevant phases

**Example changes:**
```yaml
# Before:
- name: verify
  agent: verifier
  description: Run tests and fix simple issues
  set:
    testsPassed: true
    buildPassed: true
    remainingIssuesCount: 0

# After:
- name: verify
  agent: verifier
  description: Run tests and set succeeded variable
  variables:  # Variables this agent MUST set
    - succeeded: bool
```

### Phase 5: Agent Discovery and Configuration

#### File: `src/agents/runner.ts` (agent discovery section)
**Changes:**
- Update frontmatter parsing to handle `spawn_subagents` field
- Update frontmatter parsing to handle `allowed_subagents` field
- Add validation for subagent configuration
- Update AgentDefinition interface to include subagent fields

#### File: `src/flows/executor/FlowExecutor.ts` (agent preparation)
**Changes:**
- Add support for subagent spawning in base options
- Implement allowed subagent validation
- Pass subagent configuration to agent runner

### Phase 6: Testing Infrastructure

#### File: `src/test-yaml-flow.ts`
**Changes:**
- Add tests for done tool enforcement
- Add tests for required variable validation
- Add tests for per-phase variable definitions
- Update existing tests to use new flow structure
- Add tests for error conditions (missing done, missing variables)

#### File: New test file: `src/flows/test/done-tool.test.ts`
**Changes:**
- Create comprehensive tests for done tool functionality
- Test parameter validation
- Test integration with FlowExecutor
- Test error handling

### Phase 7: Documentation and Migration

#### File: `.pi/agents/*.md` (all agent files)
**Changes:**
- Update system prompts to reflect new completion pattern
- Add done tool usage examples to all agents
- Remove deprecated JSON output instructions
- Standardize completion message format

### Summary of File Changes

**Core Files (5 files):**
1. `src/flows/schema.ts` - Add per-phase variable definitions
2. `src/flows/executor/FlowContext.ts` - Simplify to dict-like, add validation
3. `src/flows/executor/FlowExecutor.ts` - Add done tool enforcement
4. `src/flows/tools/decision-tool.ts` - Update for simplified state
5. `src/tools/done-tool.ts` - NEW: Done tool implementation

**Agent Files (5+ files):**
6. `.pi/agents/verifier.md` - Remove JSON, add done tool
7. `.pi/agents/planner.md` - Add done tool usage
8. `.pi/agents/analyst.md` - Add done tool usage
9. `.pi/agents/wave-orchestrator.md` - Add subagent config, done tool
10. `.pi/agents/*.md` - Update remaining agents

**Flow Files (1+ files):**
11. `.pi/flows/tdd.yaml` - Add per-phase variables, simplify structure

**Agent Infrastructure (2 files):**
12. `src/agents/runner.ts` - Update discovery, add done tool handling
13. `src/agents/runner.ts` (agent discovery) - Add subagent field parsing

**Testing Files (2 files):**
14. `src/test-yaml-flow.ts` - Add done tool and validation tests
15. `src/flows/test/done-tool.test.ts` - NEW: Comprehensive done tool tests

### Key Implementation Patterns

**Done Tool Pattern:**
```typescript
// Tool definition
{
  name: "done",
  description: "Mark your work as complete. YOU MUST USE THIS TOOL TO FINISH.",
  parameters: {
    type: "object",
    properties: {
      variables: {
        type: "object",
        description: "Variables to set in FlowState",
      },
      message: {
        type: "string",
        description: "Completion message",
      }
    },
    required: ["variables", "message"]
  }
}
```

**Per-Phase Variable Pattern:**
```yaml
# Flow YAML
- name: verify
  agent: verifier
  variables:
    - succeeded: bool
    - bugs_fixed: int
```

**Enforcement Pattern:**
```typescript
// After agent execution - ALWAYS enforce done tool usage
if (!doneToolUsed) {
  throw new Error(`Agent ${agentName} did not use required 'done' tool`);
}

// Validate message was provided
if (!doneToolMessage || doneToolMessage.trim() === "") {
  throw new Error(`Agent ${agentName} must provide a message in done tool`);
}

// Validate all defined variables were set (all are required)
for (const variable of phase.variables) {
  if (!setVariables.has(variable.name)) {
    throw new Error(`Agent ${agentName} did not set required variable: ${variable.name}`);
  }
}
```

This implementation plan provides a clear roadmap for transitioning from the current complex JSON-based agent output system to the simplified done tool-based system while maintaining all functionality and adding proper enforcement mechanisms.

---

# Iteration 2: Critical Fixes and Implementation Gaps

## Overview

After reviewing the implementation against the PRD requirements, several critical issues were identified that prevent full compliance. The implementation is approximately 60% complete with solid foundations but missing critical enforcement functionality and containing遗留 legacy code.

## Implementation Status Summary

### ✅ Correctly Implemented (60%)
- Done tool created and integrated with FlowExecutor
- Per-phase variable definitions in schema.ts
- YAML parsing supports variable type definitions
- Done tool parameter extraction handles multiple formats
- Agent YAML files updated with done tool instructions
- Spawn subagents configuration in place
- Flow YAML updated with variables field

### ❌ Critical Issues Found (40%)
1. **FlowExecutor enforcement bugs** - Conditional enforcement, legacy fallbacks, missing message validation
2. **schema.ts missing enforcement** - No type validation, no enforcement mechanisms
3. **Agent JSON remnants** - Complex JSON structures still present in agent files
4. **Missing file updates** - runner.ts, FlowContext.ts, decision-tool.ts not updated
5. **Done tool validation gaps** - Missing runtime validation and error handling bugs

---

## Detailed Fix Plan

### Priority 1: Fix Critical FlowExecutor Enforcement Bugs

**File:** `src/flows/executor/FlowExecutor.ts`

**Bug #1: Conditional Done Tool Enforcement (CRITICAL)**
**Location:** Lines 243-246
**Current Code:**
```typescript
// Enforce done tool usage if phase has required variables
if (phase.variables && phase.variables.length > 0) {
  this.enforceDoneTool(phase, agentName, result.output);
}
```

**Problem:** Only enforces done tool when `phase.variables` exists, allowing agents to complete without using done tool for phases without variables.

**Fix Required:**
```typescript
// Enforce done tool usage for ALL phases (unconditional)
this.enforceDoneTool(phase, agentName, result.output);
```

**Bug #2: Legacy Variable Fallback (HIGH)**
**Location:** Lines 264-269
**Current Code:**
```typescript
if (this.doneToolUsed) {
  for (const [key, value] of Object.entries(this.doneToolVariables)) {
    ctx.setVariable(key, value);
  }
} else if (result.variables) {
  // Fallback to legacy variable extraction if no done tool
  for (const [key, value] of result.variables.entries()) {
    ctx.setVariable(key, value);
  }
}
```

**Problem:** Allows agents to bypass done tool enforcement entirely by using old variable extraction method.

**Fix Required:**
```typescript
// Store variables from done tool (required)
if (this.doneToolUsed) {
  for (const [key, value] of Object.entries(this.doneToolVariables)) {
    // Ensure value is of the correct type
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      ctx.setVariable(key, value);
    } else {
      // Convert to string for complex types
      ctx.setVariable(key, String(value));
    }
  }
}
// Remove the else if block completely
```

**Bug #3: Missing Message Parameter Validation (MEDIUM)**
**Location:** Lines 363-402 in `enforceDoneTool()`
**Current Code:**
```typescript
private enforceDoneTool(phase: PhaseDef, agentName: string, agentOutput: string): void {
  this.extractDoneToolUsage(agentOutput);

  // Check if done tool was used
  if (!this.doneToolUsed) {
    throw new Error(
      `Agent "${agentName}" in phase "${phase.name}" did not use the done tool. ` +
      // ... error message
    );
  }

  // Validate that all required variables were set
  const missingVariables: string[] = [];
  if (phase.variables) {
    for (const variable of phase.variables) {
      if (!(variable.name in this.doneToolVariables)) {
        missingVariables.push(variable.name);
      }
    }
  }
  // ... rest of validation
}
```

**Problem:** Doesn't validate that `message` parameter was provided in done tool call, despite it being required.

**Fix Required:**
```typescript
private enforceDoneTool(phase: PhaseDef, agentName: string, agentOutput: string): void {
  this.extractDoneToolUsage(agentOutput);

  // Check if done tool was used
  if (!this.doneToolUsed) {
    throw new Error(
      `Agent "${agentName}" in phase "${phase.name}" did not use the done tool. ` +
      `You MUST use the done tool at the end of your work with all required variables and a message.`
    );
  }

  // Validate that message was provided
  if (!this.doneToolMessage || this.doneToolMessage.trim() === "") {
    throw new Error(
      `Agent "${agentName}" in phase "${phase.name}" used done tool but did not provide a required message. ` +
      `The done tool requires both variables and message parameters.`
    );
  }

  // Validate that all defined variables were set
  const missingVariables: string[] = [];
  if (phase.variables) {
    for (const variable of phase.variables) {
      if (!(variable.name in this.doneToolVariables)) {
        missingVariables.push(variable.name);
      }
    }
  }

  if (missingVariables.length > 0) {
    throw new Error(
      `Agent "${agentName}" in phase "${phase.name}" did not set all required variables via done tool. ` +
      `Missing variables: ${missingVariables.join(", ")}. ` +
      `Required variables: ${phase.variables?.map(v => v.name).join(", ") || "none"}. ` +
      `Please use the done tool with all required variables.`
    );
  }
}
```

---

### Priority 2: Complete schema.ts Enforcement Implementation

**File:** `src/flows/schema.ts`

**Missing Feature #1: Type System Enhancement**
**Current Implementation (Line 75):**
```typescript
type: string;
```

**Problem:** String-based type system allows invalid type names like "string" instead of "str", or typos like "bol" instead of "bool".

**Fix Required:**
```typescript
// Define supported variable types
export type VariableType = "str" | "int" | "float" | "bool";

export interface PhaseVariable {
  /** Variable name (must be valid JavaScript identifier) */
  name: string;
  /** Variable type: "str", "int", "float", or "bool" */
  type: VariableType;
}
```

**Missing Feature #2: Type Validation Function**
**Current State:** No validation function exists to check if variable values match their declared types.

**Fix Required:**
```typescript
/**
 * Validate that a variable value matches its declared type.
 *
 * @param variable - The variable definition from flow YAML
 * @param value - The actual value set by the agent
 * @returns true if type matches, false otherwise
 */
export function validateVariableType(variable: PhaseVariable, value: unknown): boolean {
  switch (variable.type) {
    case "str":
      return typeof value === "string";
    case "int":
      return typeof value === "number" && Number.isInteger(value);
    case "float":
      return typeof value === "number";
    case "bool":
      return typeof value === "boolean";
    default:
      // Should never happen with VariableType union, but handle gracefully
      console.warn(`Unknown variable type: ${variable.type}`);
      return true;
  }
}
```

**Missing Feature #3: Phase Variable Validation Function**
**Current State:** Schema validates structure but doesn't provide enforcement mechanism for checking agents set required variables with correct types.

**Fix Required:**
```typescript
/**
 * Validate that all variables required by a phase were set by the agent
 * and that their values match the declared types.
 *
 * @param phase - The phase definition
 * @param setVariables - Variables actually set by the agent via done tool
 * @param flowPath - Path to the flow file (for error messages)
 * @throws FlowValidationError if validation fails
 */
export function validatePhaseVariables(
  phase: PhaseDef,
  setVariables: Record<string, unknown>,
  flowPath: string
): void {
  const errors: string[] = [];
  const prefix = `Phase "${phase.name}"`;

  if (phase.variables) {
    for (const variable of phase.variables) {
      // Check if variable was set
      if (!(variable.name in setVariables)) {
        errors.push(
          `${prefix}: Required variable '${variable.name}' (type: ${variable.type}) was not set by agent`
        );
        continue;
      }

      // Check if variable type matches
      const value = setVariables[variable.name];
      if (!validateVariableType(variable, value)) {
        errors.push(
          `${prefix}: Variable '${variable.name}' expected type '${variable.type}' ` +
          `but got ${typeof value} (value: ${JSON.stringify(value)})`
        );
      }
    }
  }

  if (errors.length > 0) {
    throw new FlowValidationError(
      `Phase variable validation failed`,
      flowPath,
      errors
    );
  }
}
```

**Integration Required:**
Add call to `validatePhaseVariables()` in FlowExecutor after extracting done tool variables:

```typescript
// In FlowExecutor.ts, after extracting done tool variables
if (this.doneToolUsed) {
  // Validate types and completeness
  validatePhaseVariables(phase, this.doneToolVariables, this.config.flowPath);

  // Set variables in context
  for (const [key, value] of Object.entries(this.doneToolVariables)) {
    ctx.setVariable(key, value);
  }
}
```

---

### Priority 3: Remove JSON Structures from Agent YAML Files

**File:** `.pi/agents/verifier.md`

**Issue:** Lines 61-88 contain complex JSON output examples that should be removed per PRD.

**Current Content (Lines 61-88):**
```markdown
## Example Output Structure

When you find issues, structure them as:

```json
{
  "testsPassed": false,
  "buildPassed": false,
  "fixes": [
    {
      "file": "src/utils.ts",
      "issue": "Missing null check",
      "fix": "Add if (value !== null) check"
    }
  ],
  "remainingIssues": [
    {
      "file": "src/api.ts",
      "issue": "Type mismatch",
      "severity": "high"
    }
  ]
}
```

Use the done tool to report this:

```bash
done(variables={
    "testsPassed": true,
    "buildPassed": true,
    "fixes": [...],
    "remainingIssues": [...]
}, message="...")
```
```

**Fix Required:**
Replace with simplified version that only sets `succeeded: bool`:

```markdown
## Completion

After running tests and analysis, use the done tool to report results:

### Success Case
```bash
# If all tests pass and no issues found
done(variables={
    "succeeded": true
}, message="All tests passed successfully. No issues found.")
```

### Failure Case
```bash
# If tests fail or issues found
done(variables={
    "succeeded": false
}, message="Tests failed with 2 errors. See test output for details.")
```

**Important:** Only set the `succeeded` variable as specified in the flow YAML. Describe any issues in the message parameter rather than creating complex JSON structures.
```

---

**File:** `.pi/agents/planner.md`

**Issue:** Lines 28-47 contain complete JSON schema definitions that should be removed.

**Current Content (Lines 28-47):**
```markdown
## Output Format

Your plan should follow this JSON structure:

```json
{
  "summary": "Brief overview of the plan",
  "approach": "Implementation approach",
  "steps": [
    {
      "step": 1,
      "description": "Step description",
      "files": ["file1.ts", "file2.ts"],
      "estimatedComplexity": "low|medium|high"
    }
  ],
  "dependencies": ["external-dep1", "external-dep2"],
  "risks": ["potential risk 1", "potential risk 2"]
}
```

Write this plan to `plan.md` and use done tool to complete.
```

**Fix Required:**
Replace with simple instructions:

```markdown
## Creating the Plan

1. Read requirements and test files
2. Use explore subagents for research and discovery
3. Create a clear, step-by-step build plan
4. Write the plan to `plan.md` in markdown format

## Plan Format

Use clear markdown format for your plan:

```markdown
# Build Plan

## Summary
Brief overview of what will be implemented.

## Approach
Description of the implementation approach and key decisions.

## Implementation Steps

### Step 1: [Step Name]
- Description of what to do
- Files to modify
- Key considerations

### Step 2: [Step Name]
- Description of what to do
- Files to modify
- Key considerations

## Dependencies
List any external dependencies that need to be installed.

## Risks
List potential risks and mitigation strategies.
```

## Completion

After creating the plan, use the done tool:

```bash
done(variables={}, message="Build plan created and saved to plan.md")
```
```

---

**File:** `.pi/agents/analyst.md`

**Issue:** Lines 12-31 contain JSON schema for analysis output that should be removed.

**Current Content (Lines 12-31):**
```markdown
## Output Structure

Your analysis should include:

```json
{
  "goals": ["goal1", "goal2"],
  "testRequirements": ["test1", "test2"],
  "architecture": {
    "components": ["comp1", "comp2"],
    "dataFlow": "description"
  },
  "technicalConsiderations": ["consideration1", "consideration2"]
}
```

Write this analysis to `analysis.md` and use done tool to complete.
```

**Fix Required:**
Replace with simple markdown format instructions:

```markdown
## Creating the Analysis

Analyze the task and create a comprehensive analysis document. Write your analysis to `analysis.md` in markdown format.

## Analysis Format

```markdown
# Task Analysis

## Goals
List the main goals and objectives.

## Test Requirements
Detail what tests need to be created and what they should verify.

## Architecture
Describe the system architecture and key components.

## Technical Considerations
List any technical constraints, dependencies, or considerations.

## Next Steps
Outline the recommended next steps for implementation.
```

## Completion

After completing your analysis, use the done tool:

```bash
done(variables={}, message="Analysis complete and saved to analysis.md")
```
```

---

### Priority 4: Update Missing Critical Files

**File:** `src/agents/runner.ts`

**Issue:** No logic to detect or handle done tool calls, no validation that agents used done tool.

**Required Changes:**

1. **Add Done Tool Detection in Agent Results:**
```typescript
// In the function that processes agent results
export interface AgentResult {
  output: string;
  doneToolUsed: boolean;
  doneToolVariables: Record<string, unknown>;
  doneToolMessage: string;
  // ... other fields
}

// After running agent, check for done tool usage
const doneToolUsage = extractDoneToolUsage(agentOutput);
return {
  output: agentOutput,
  doneToolUsed: doneToolUsage.used,
  doneToolVariables: doneToolUsage.variables,
  doneToolMessage: doneToolUsage.message,
  // ... other fields
};
```

2. **Add Done Tool Extraction Function:**
```typescript
/**
 * Extract done tool usage from agent output.
 * This duplicates logic from FlowExecutor for consistency,
 * or could be moved to a shared utility module.
 */
function extractDoneToolUsage(output: string): {
  used: boolean;
  variables: Record<string, unknown>;
  message: string;
} {
  // Implementation similar to FlowExecutor.extractDoneToolUsage()
  // ... parsing logic for multiple done tool call formats
  return { used: false, variables: {}, message: "" };
}
```

3. **Update Frontmatter Parsing for Subagent Fields:**
```typescript
// Ensure these fields are parsed from agent YAML frontmatter
export interface AgentDefinition {
  name: string;
  description: string;
  tools: string[];
  spawn_subagents?: boolean;
  allowed_subagents?: string[];
  model?: string;
  // ... other fields
}
```

---

**File:** `src/flows/executor/FlowContext.ts`

**Issue:** No validation methods, needs simplification to dict-like structure per PRD.

**Required Changes:**

1. **Add Variable Validation Method:**
```typescript
/**
 * Validate that all required variables have been set.
 *
 * @param requiredVars - Array of variable names that must be set
 * @throws Error if any required variables are missing
 */
validateRequiredVariables(requiredVars: string[]): void {
  const missing: string[] = [];
  for (const varName of requiredVars) {
    if (!this.variables.has(varName)) {
      missing.push(varName);
    }
  }
  if (missing.length > 0) {
    throw new Error(
      `Missing required variables in FlowState: ${missing.join(", ")}`
    );
  }
}
```

2. **Simplify Variable Access (Optional Future Enhancement):**
```typescript
// Consider adding simpler dict-like access
get(key: string): string | number | boolean | undefined {
  return this.variables.get(key);
}

set(key: string, value: string | number | boolean): void {
  this.variables.set(key, value);
}

// Allow iteration like a dict
entries(): IterableIterator<[string, string | number | boolean]> {
  return this.variables.entries();
}
```

3. **Add Done Tool Usage Tracking (Optional):**
```typescript
// Could be added if FlowContext needs to track done tool usage
private doneToolUsed: boolean = false;

markDoneToolUsed(): void {
  this.doneToolUsed = true;
}

wasDoneToolUsed(): boolean {
  return this.doneToolUsed;
}
```

---

**File:** `src/flows/tools/decision-tool.ts`

**Issue:** Still uses complex `@agentName.property` syntax that should be simplified per PRD.

**Required Changes:**

1. **Simplify Expression Evaluation for Dict-like State:**
```typescript
// Update evaluateSafe() to work with simplified FlowState
function evaluateSafe(expr: string, context: Record<string, unknown>): any {
  // Remove or simplify agent reference replacement (@agentName.property)
  // Work with direct variable access (${variableName})
  // ... implementation
}
```

2. **Remove Complex Agent Reference Parsing:**
```typescript
// Simplify or remove this logic if @-syntax is being deprecated
// The PRD states: "Remove complex agent reference parsing (simplify to direct variable access)"
```

3. **Update for Simplified Variable Access:**
```typescript
// Ensure decision tool works with ${variable} syntax
// Remove dependency on @agentName.property references
```

---

### Priority 5: Add Missing Done Tool Parameter Validation

**File:** `src/flows/tools/done-tool.ts`

**Issue #1: No Runtime Parameter Validation**
**Location:** Lines 72-76
**Current Code:**
```typescript
async execute(
  toolCallId: string,
  params: { variables: Record<string, unknown>; message: string }
) {
  const { variables, message } = params;
  // No validation that parameters are actually provided
```

**Fix Required:**
```typescript
async execute(
  toolCallId: string,
  params: { variables: Record<string, unknown>; message: string }
) {
  const { variables, message } = params;

  // Validate required parameters
  if (!variables) {
    throw new Error(
      "Done tool requires 'variables' parameter. " +
      "Usage: done(variables={...}, message='...')"
    );
  }

  if (message === undefined || message === null) {
    throw new Error(
      "Done tool requires 'message' parameter. " +
      "Usage: done(variables={...}, message='...')"
    );
  }

  if (typeof message !== "string" || message.trim() === "") {
    throw new Error(
      "Done tool 'message' parameter must be a non-empty string. " +
      "Please provide a descriptive message about what was accomplished."
    );
  }

  // Continue with rest of implementation
```

**Issue #2: Error Handling Bug**
**Location:** Line 120
**Current Code:**
```typescript
return {
  output: JSON.stringify({
    success: false,
    error: errorMessage,
    variables: Object.keys(variables), // This will fail if variables is undefined
  }),
```

**Fix Required:**
```typescript
return {
  output: JSON.stringify({
    success: false,
    error: errorMessage,
    variables: variables ? Object.keys(variables) : [],
  }),
```

**Issue #3: Missing TypeBox Required Validation**
**Location:** Lines 49-62
**Current Code:**
```typescript
const ParametersSchema = Type.Object({
  variables: Type.Record(...),
  message: Type.String(...),
});
```

**Fix Required:**
```typescript
const ParametersSchema = Type.Object({
  variables: Type.Record(
    Type.String(),
    Type.Unknown(),
    {
      description:
        "Variables to set in FlowState. MUST include all variables specified in the flow YAML phase. " +
        "These variables will be available to subsequent phases via ${variable} syntax.",
    }
  ),
  message: Type.String({
    description:
      "Completion message describing what was done. THIS IS REQUIRED. " +
      "Should clearly state the outcome and any important details.",
    minLength: 1, // Ensure non-empty message
  }),
}, { additionalProperties: false }); // Strict validation
```

---

## Implementation Order

### Phase 1: Critical Bug Fixes (High Priority)
1. Fix FlowExecutor conditional enforcement bug
2. Remove FlowExecutor legacy fallback
3. Add FlowExecutor message validation
4. Fix done-tool error handling bug

### Phase 2: Core Functionality (High Priority)
5. Complete schema.ts type validation
6. Add schema.ts enforcement functions
7. Integrate schema.ts validation into FlowExecutor
8. Add done-tool runtime parameter validation

### Phase 3: Agent Cleanup (Medium Priority)
9. Remove JSON structures from verifier.md
10. Remove JSON structures from planner.md
11. Remove JSON structures from analyst.md
12. Update agent examples to match flow YAML expectations

### Phase 4: Infrastructure Updates (Medium Priority)
13. Update runner.ts with done tool detection
14. Add validation methods to FlowContext.ts
15. Simplify decision-tool.ts for new state

### Phase 5: Testing and Documentation (Low Priority)
16. Add comprehensive tests for all fixes
17. Verify all agents work with updated system

---

## Success Criteria for Iteration 2

- [ ] FlowExecutor enforces done tool usage for ALL phases (no conditional enforcement)
- [ ] FlowExecutor validates message parameter is provided and non-empty
- [ ] No legacy variable fallback exists in FlowExecutor
- [ ] schema.ts has proper VariableType union type
- [ ] schema.ts has validateVariableType() function
- [ ] schema.ts has validatePhaseVariables() function
- [ ] FlowExecutor calls validatePhaseVariables() after extracting done tool variables
- [ ] done-tool validates both parameters at runtime
- [ ] done-tool has descriptive error messages for missing parameters
- [ ] done-tool error handling bug is fixed
- [ ] No JSON output structures remain in agent YAML files
- [ ] All agent examples match flow YAML variable expectations
- [ ] runner.ts detects and handles done tool calls
- [ ] FlowContext.ts has validation methods
- [ ] decision-tool.ts works with simplified state

---

## Estimated Effort

- **Phase 1 (Critical Bugs):** 2-3 hours
- **Phase 2 (Core Functionality):** 3-4 hours
- **Phase 3 (Agent Cleanup):** 2-3 hours
- **Phase 4 (Infrastructure):** 2-3 hours
- **Phase 5 (Testing/Docs):** 2-3 hours

**Total Estimated Time:** 11-16 hours

---

## Testing Strategy

After implementing each phase, run:

1. **Unit Tests:**
   ```bash
   npm test -- src/flows/schema.test.ts
   npm test -- src/flows/tools/done-tool.test.ts
   npm test -- src/flows/executor/FlowExecutor.test.ts
   ```

2. **Integration Tests:**
   ```bash
   npm test -- src/test-yaml-flow.ts
   npm test -- src/test-done-enforcement.ts
   ```

3. **End-to-End Tests:**
   ```bash
   npm run test:e2e
   ```

4. **Manual Testing:**
   - Run TDD flow with simple task
   - Verify agents must use done tool
   - Verify error messages are clear
   - Test with missing variables
   - Test with wrong types
   - Test with missing message

---

## Rollback Plan

If any changes break existing functionality:

1. Each fix should be in a separate commit for easy rollback
2. Keep backup of original files before modification
3. Test incrementally after each phase
4. Use git to revert specific commits if needed

```bash
# Example rollback
git revert <commit-hash>
# or
git checkout HEAD~1 -- path/to/file.ts
```
