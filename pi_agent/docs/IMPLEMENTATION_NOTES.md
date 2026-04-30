# Python Flow System Migration Guide

## Overview

This guide documents the migration from the old YAML flow system to the new Python Flow System with the `done` tool. The migration introduces a simplified agent completion mechanism, per-phase variable definitions, and better enforcement of agent behavior.

### Key Changes

1. **Done Tool Requirement**: All agents MUST use the `done` tool to complete their work
2. **Per-Phase Variables**: Variables are defined in flow YAML phases, not in agent YAML
3. **Enforcement**: System validates that agents use done tool and set required variables
4. **Simplified Output**: Agents no longer output complex JSON structures
5. **Declarative Configuration**: Agent capabilities defined in YAML (spawn_subagents, allowed_subagents)

## Before/After Examples

### Agent YAML Files

#### Before (Old System)

```yaml
---
name: verifier
description: Runs tests and outputs complex JSON
tools: read,bash,edit,write,grep,find,ls
model: zai/glm-5.1
---

You are the **Verifier** agent. You run tests and output results.

## Process
1. Run the test suite
2. Output your results as JSON

## Your Output
You MUST produce JSON with this structure:

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
```

#### After (New System)

```yaml
---
name: verifier
description: Runs tests and sets variables as specified in flow YAML
tools: read,bash,edit,write,grep,find,ls
model: zai/glm-5.1
---

You are the **Verifier** agent. Your job is to:
1. Run the test commands using the `bash` tool
2. Check the results
3. Use the `done` tool to set the variables specified in the flow YAML phase

## Process
1. Read the project structure to understand what was built
2. Run the full test suite
3. Run the build command
4. If anything fails:
   a. Diagnose the root cause
   b. Try to fix simple issues (typos, missing imports, small logic errors)
   c. Re-run tests and build after each fix (max 3 attempts)
5. **If you made ANY fix, commit it and verify the commit landed**
6. **Use the `done` tool to complete**

## Completion

When you have completed your verification work, you MUST use the `done` tool to finish:

```bash
done(variables={
    "succeeded": true
}, message="All tests passed successfully")
```

If tests fail:
```bash
done(variables={
    "succeeded": false
}, message="Tests failed with 2 errors")
```

## Variables

The `done` tool's `variables` parameter will set these for the flow:
- `succeeded` (boolean): Whether all tests passed

These variables are used by the flow executor to decide whether to continue looping or finish.
```

### Flow YAML Files

#### Before (Old System)

```yaml
name: tdd
description: Test-driven development flow

# Initial variables for the flow
variables:
  maxIterations: 3
  iteration: 1
  firstIteration: true
  succeeded: false

phases:
  - name: analyze
    agent: analyst
    description: Analyze the task

  - name: build_loop
    while: "( ${firstIteration} || !${succeeded} ) && ${iteration} <= ${maxIterations}"
    phases:
      - name: plan
        agent: planner
        description: Create a build plan

      - name: execute
        agent: wave-orchestrator
        description: Execute build waves in parallel

      - name: verify
        agent: verifier
        description: Run tests and fix simple issues
        set:
          succeeded: true

    set:
      iteration: "${iteration} + 1"
```

#### After (New System)

```yaml
name: tdd
description: Test-driven development flow with analysis, planning, implementation, and verification

# Initial variables for the flow
variables:
  maxIterations: 3
  iteration: 1
  firstIteration: true
  succeeded: false

phases:
  # Phase 1: Analyze the task
  - name: analyze
    agent: analyst
    description: Analyze the task and define goals, tests, and architecture

  # Phase 2: Build loop (plan → execute → verify, retry as needed)
  - name: build_loop
    # Continue while: (first iteration OR not succeeded) AND within max iterations
    while: "( ${firstIteration} || !${succeeded} ) && ${iteration} <= ${maxIterations}"
    phases:
      # Phase 2a: Create or update the build plan
      - name: plan
        agent: planner
        description: Create a build plan (initial or fix plan)
        inputs:
          previousSummaries: true
        set:
          firstIteration: false

      # Phase 2b: Execute the plan in parallel waves
      - name: execute
        agent: wave-orchestrator
        description: Execute build waves in parallel
        inputs:
          previousSummaries: true

      # Phase 2c: Verify the implementation
      - name: verify
        agent: verifier
        description: Run tests and fix simple issues
        inputs:
          previousSummaries: true
        variables:
          - succeeded: bool
        set:
          succeeded: true

    # Update iteration counter after each loop
    set:
      iteration: "${iteration} + 1"
```

## Migration Steps

### Step 1: Update Agent YAML Files

1. **Remove complex JSON output requirements**
   - Delete sections that describe JSON structure requirements
   - Remove examples of complex JSON output

2. **Add done tool instructions**
   - Add a `## Completion` section
   - Explain that agents MUST use the `done` tool to finish
   - Provide clear examples of done tool usage

3. **Remove global variable definitions**
   - Delete any `## Variables` sections that define output structure
   - Move variable documentation to describe what the flow YAML might require

4. **Simplify agent instructions**
   - Focus on what the agent should DO, not what it should OUTPUT
   - Let the flow YAML define what variables need to be set

### Step 2: Update Flow YAML Files

1. **Define variables per phase**
   - Add a `variables` field to phases that require variable setting
   - Specify the variable names and types: `- succeeded: bool`

2. **Update conditions to use simplified variables**
   - Keep using `${variableName}` syntax for interpolation
   - Ensure variable names match what agents will set via done tool

3. **Remove complex variable sets**
   - Simplify `set` clauses to direct variable assignments
   - Use inline expressions: `iteration: "${iteration} + 1"`

4. **Add variable requirements for phases**
   - Mark phases that must set specific variables
   - Document what each variable should contain

### Step 3: Add Subagent Configuration (if applicable)

For agents that spawn subagents:

1. **Add `spawn_subagents: true`** to agent YAML frontmatter
2. **Add `allowed_subagents: [agent-names]`** to specify which agents can be spawned
3. **Update agent instructions** to document subagent spawning capabilities

Example:
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
```

### Step 4: Update Tool Implementations

1. **Implement the done tool**
   - Create a tool with required `variables` and `message` parameters
   - Ensure both parameters are required (not optional)

2. **Add done tool to agent tool list**
   - Automatically inject the done tool when preparing agents
   - Ensure it's always available regardless of agent configuration

3. **Implement enforcement**
   - After agent execution, check if done tool was used
   - Raise an error if done tool wasn't called
   - Validate that all required variables were set

### Step 5: Update Agent Runner

1. **Extract done tool parameters**
   - Parse tool call results to find done tool calls
   - Extract `variables` and `message` from done tool
   - Store them for flow executor use

2. **Validate done tool usage**
   - Check that agent called done tool exactly once
   - Ensure both `variables` and `message` were provided
   - Return clear error messages if validation fails

3. **Propagate variables to flow state**
   - Update flow state with variables from done tool
   - Ensure variables are available for interpolation in conditions

### Step 6: Update Flow Executor

1. **Implement per-phase variable validation**
   - For each phase, check if `variables` field is defined
   - Validate that all required variables were set by agent
   - Provide clear error messages for missing variables

2. **Update condition evaluation**
   - Ensure variables set by done tool are available in conditions
   - Support inline expressions in `set` clauses
   - Handle variable interpolation correctly

3. **Add error handling**
   - Catch and surface errors from missing done tool
   - Catch and surface errors from missing variables
   - Provide actionable error messages to developers

## Common Pitfalls and Solutions

### Pitfall 1: Agent Not Using Done Tool

**Symptom:**
```
Error: Agent verifier did not use required 'done' tool
```

**Cause:**
Agent completed its work but forgot to call the done tool.

**Solution:**
- Update agent YAML instructions to emphasize done tool requirement
- Add explicit example of done tool usage
- Consider adding system prompt reminders about done tool

**Prevention:**
- Always include a `## Completion` section in agent YAML
- Make done tool examples prominent and clear
- Test agents thoroughly to ensure they call done tool

### Pitfall 2: Missing Required Variables

**Symptom:**
```
Error: Agent verifier did not set required variable: succeeded
```

**Cause:**
Agent called done tool but didn't set all variables required by the flow YAML phase.

**Solution:**
- Check the flow YAML phase for required variables
- Ensure agent YAML instructions match what the flow requires
- Verify done tool call includes all required variables

**Prevention:**
- Document required variables clearly in agent YAML
- Cross-reference flow YAML requirements with agent instructions
- Add validation tests for variable setting

### Pitfall 3: Variable Type Mismatches

**Symptom:**
```
Error: Variable 'succeeded' expected boolean but got string
```

**Cause:**
Agent set a variable with the wrong type (e.g., `"true"` instead of `true`).

**Solution:**
- Ensure done tool calls use correct JSON types
- Use `true/false` for booleans, not `"true"/"false"`
- Use numbers without quotes, strings with quotes

**Prevention:**
- Document expected types in flow YAML
- Provide examples with correct types in agent YAML
- Add type validation in the done tool implementation

### Pitfall 4: Missing Message Parameter

**Symptom:**
```
Error: Done tool requires 'message' parameter
```

**Cause:**
Agent called done tool but didn't provide the required message.

**Solution:**
- Always include a `message` parameter in done tool calls
- The message should describe what was accomplished
- Keep messages concise but informative

**Prevention:**
- Make message parameter clear in agent instructions
- Show examples of good messages vs bad messages
- Test that agents always include messages

### Pitfall 5: Complex JSON Output Instead of Done Tool

**Symptom:**
Agent outputs complex JSON structure but doesn't call done tool.

**Cause:**
Agent instructions weren't updated from old system.

**Solution:**
- Remove all JSON output requirements from agent YAML
- Replace with done tool instructions
- Simplify agent to focus on DOING, not OUTPUTTING

**Prevention:**
- Audit agent YAML files for old JSON structures
- Standardize on done tool pattern
- Test with simple tasks first

### Pitfall 6: Subagent Configuration Missing

**Symptom:**
```
Error: Agent wave-orchestrator attempted to spawn subagents but spawn_subagents not enabled
```

**Cause:**
Agent tries to spawn subagents but configuration is missing in YAML.

**Solution:**
- Add `spawn_subagents: true` to agent YAML frontmatter
- Add `allowed_subagents: [agent-names]` to specify which agents can be spawned
- Update agent instructions to document subagent capabilities

**Prevention:**
- Document subagent spawning clearly in agent YAML
- Provide examples of spawn_subagents tool usage
- Test subagent spawning thoroughly

### Pitfall 7: Variable Interpolation Errors

**Symptom:**
```
Error: Failed to evaluate expression '${iteration + 1}: variable 'iteration' not found
```

**Cause:**
Flow YAML references a variable that hasn't been set yet.

**Solution:**
- Ensure all variables are initialized in the `variables` section at the top of the flow YAML
- Check that variable names match exactly (case-sensitive)
- Verify that agents set variables before they're used in conditions

**Prevention:**
- Initialize all variables at flow level
- Use consistent naming conventions
- Test flow execution step by step

## Migration Checklist

### Pre-Migration

- [ ] Review all existing agent YAML files
- [ ] Document current variable output structure for each agent
- [ ] Identify agents that spawn subagents
- [ ] Review all flow YAML files for variable usage
- [ ] Create a backup of existing agent and flow files

### Agent YAML Updates

- [ ] Remove all JSON output structure requirements
- [ ] Add `## Completion` section with done tool instructions
- [ ] Add done tool examples for each agent
- [ ] Remove global variable definitions
- [ ] Simplify agent instructions to focus on actions
- [ ] Add `spawn_subagents: true` for agents that spawn subagents
- [ ] Add `allowed_subagents: [list]` for subagent-capable agents
- [ ] Test each agent individually with done tool

### Flow YAML Updates

- [ ] Add `variables` field to phases that require variable setting
- [ ] Specify variable names and types in phase definitions
- [ ] Update conditions to use simplified variable access
- [ ] Simplify `set` clauses to direct assignments
- [ ] Ensure all variables are initialized at flow level
- [ ] Test flow execution with each update

### Tool Implementation

- [ ] Implement done tool with required parameters
- [ ] Add parameter validation (variables, message both required)
- [ ] Inject done tool into agent tool lists automatically
- [ ] Add done tool parameter extraction in agent runner
- [ ] Test done tool with various parameter combinations

### Enforcement Implementation

- [ ] Add done tool usage check after agent execution
- [ ] Add required variable validation after each phase
- [ ] Provide clear error messages for validation failures
- [ ] Test enforcement with missing done tool scenarios
- [ ] Test enforcement with missing variable scenarios

### Flow Executor Updates

- [ ] Implement per-phase variable validation
- [ ] Update condition evaluation to use new variable system
- [ ] Add inline expression evaluation for `set` clauses
- [ ] Add error handling for validation failures
- [ ] Test flow execution with loops and conditions

### Testing

- [ ] Test simple linear flow (no loops)
- [ ] Test flow with while loops
- [ ] Test flow with if conditions
- [ ] Test agents that set variables
- [ ] Test agents that spawn subagents
- [ ] Test error handling (missing done tool)
- [ ] Test error handling (missing variables)
- [ ] Test variable type mismatches
- [ ] Test complex nested flows

### Documentation

- [ ] Update agent YAML documentation
- [ ] Update flow YAML documentation
- [ ] Create migration guide (this document)
- [ ] Add troubleshooting section
- [ ] Document common patterns and examples
- [ ] Update API documentation for done tool

## Troubleshooting Guide

### Issue: Agent hangs indefinitely

**Possible Causes:**
1. Agent is waiting for user input when it shouldn't be
2. Agent is stuck in a loop trying to fix an issue
3. Done tool is not being called properly

**Diagnosis Steps:**
1. Check agent logs for tool calls
2. Verify agent is calling done tool
3. Check for any HITL tool calls that might be blocking

**Solutions:**
- Ensure agent YAML has clear done tool instructions
- Add timeout limits for agent execution
- Review agent instructions for ambiguous requirements

### Issue: Variable not available in conditions

**Symptom:**
Flow condition fails because variable is undefined.

**Diagnosis Steps:**
1. Check if variable is defined in flow YAML `variables` section
2. Verify agent is setting the variable via done tool
3. Check variable name spelling and case sensitivity

**Solutions:**
- Initialize all variables at flow level
- Ensure agent done tool call includes the variable
- Use consistent naming conventions

### Issue: Loop doesn't terminate

**Symptom:**
Flow runs indefinitely, never exiting the while loop.

**Diagnosis Steps:**
1. Check while condition logic
2. Verify agent is setting loop control variables correctly
3. Check for off-by-one errors in iteration counters

**Solutions:**
- Add max iteration safeguards
- Ensure agent updates loop control variables
- Test condition evaluation with different variable values

### Issue: Agent produces wrong output

**Symptom:**
Agent does something different than expected.

**Diagnosis Steps:**
1. Review agent YAML instructions for clarity
2. Check if agent has the right tools available
3. Verify agent prompt is being constructed correctly

**Solutions:**
- Make agent instructions more specific
- Add examples to agent YAML
- Test agent with simple, well-defined tasks

### Issue: Subagent spawning fails

**Symptom:**
Error when agent tries to spawn subagents.

**Diagnosis Steps:**
1. Check if `spawn_subagents: true` is set in agent YAML
2. Verify `allowed_subagents` list is correct
3. Check if subagent YAML files exist

**Solutions:**
- Add spawn_subagents configuration to agent YAML
- Verify subagent names match actual agent definitions
- Test subagent spawning independently

### Issue: Performance degradation

**Symptom:**
Flow execution is slower than before migration.

**Diagnosis Steps:**
1. Profile flow execution to find bottlenecks
2. Check if done tool validation is too strict
3. Look for unnecessary condition evaluations

**Solutions:**
- Optimize condition evaluation logic
- Cache frequently used values
- Reduce validation overhead where safe

## Best Practices

### Agent YAML

1. **Keep instructions focused on actions**
   - Tell agents what to DO, not what to OUTPUT
   - Let the done tool handle completion signaling

2. **Provide clear completion examples**
   - Show exactly how to call the done tool
   - Include examples for both success and failure cases

3. **Document variables clearly**
   - Explain what each variable represents
   - Specify expected types and formats

4. **Use simple, direct language**
   - Avoid ambiguous instructions
   - Be explicit about expectations

### Flow YAML

1. **Define all variables upfront**
   - Initialize all variables in the `variables` section
   - Document what each variable represents

2. **Keep conditions simple**
   - Use inline expressions that are easy to understand
   - Avoid complex nested conditions

3. **Specify phase requirements clearly**
   - Use `variables` field to document what agents must set
   - Add comments explaining phase logic

4. **Test incrementally**
   - Test each phase independently
   - Build up complexity gradually

### Testing

1. **Test each agent independently**
   - Verify agents call done tool correctly
   - Check that required variables are set

2. **Test flow execution paths**
   - Test success paths
   - Test failure paths
   - Test loop boundaries

3. **Test error conditions**
   - Test missing done tool scenarios
   - Test missing variable scenarios
   - Test type mismatch scenarios

4. **Use representative test cases**
   - Test with real-world scenarios
   - Cover edge cases and corner cases

## Conclusion

Migrating to the Python Flow System with the done tool provides significant benefits:

1. **Clearer intent** - Done tool is explicit about completion
2. **Better enforcement** - System validates proper agent behavior
3. **Flexible configuration** - Same agent can set different variables in different contexts
4. **Simpler agent code** - Agents focus on doing, not outputting
5. **Easier debugging** - Clear error messages when requirements aren't met

Follow this guide carefully, test thoroughly, and you'll have a smooth migration to the new system.

## Additional Resources

- **Python Flow System PRD**: `docs/PYTHON_FLOW_SYSTEM_PRD.md` - Detailed design specification
- **YAML Flows Implementation**: `docs/YAML_FLOWS_IMPLEMENTATION.md` - Original YAML flow implementation
- **Agent Documentation**: `.pi/agents/*.md` - Current agent definitions with done tool examples
- **Flow Examples**: `.pi/flows/*.yaml` - Current flow definitions with per-phase variables

For questions or issues, refer to the troubleshooting guide or consult the PRD for detailed design decisions.
