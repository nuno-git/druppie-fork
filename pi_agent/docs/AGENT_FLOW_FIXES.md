# Agent Flow Fixes - Corrected Approach

## Your Feedback Points

You're absolutely right! Let me correct the PRD based on your feedback:

### 1. Subagent Spawning EXISTS
- **Current State**: `spawn_parallel_explorers` tool exists in explore flow (router agent uses it)
- **Your Need**: Make this capability declarative in agent YAML
- **Solution**: Add `spawn_subagents` field to agent frontmatter

### 2. Tools Should Be in Agent YAML
- **Current State**: Some tools defined in flow, some in agent YAML
- **Your Need**: ALL tools should be defined in agent YAML frontmatter
- **Solution**: Move all tool definitions to agent YAML files

### 3. Keep Flow Power (Not Over-Simplified)
- **Current State**: My PRD was too simplified, removed loops/variables
- **Your Need**: Keep loops, variables, while conditions in YAML flow
- **Solution**: Maintain current YAML flow power, fix agent execution

### 4. Agent Subagent Authorization
- **Current State**: No declarative way to specify which agents can be spawned
- **Your Need**: Declarative `allowed_subagents` in agent YAML
- **Solution**: Add authorization check based on agent YAML

## Proposed Solution

### 1. Extend Agent Definition

Add these fields to agent YAML frontmatter:

```yaml
---
name: planner
description: Creates build plans for the TDD flow
tools: [read, write, bash, grep, find]
spawn_subagents: true                    # Can spawn subagents
allowed_subagents: [builder, tester]   # Which agents can be spawned
model: zai/glm-5.1
---
```

**Fields:**
- `spawn_subagents: true/false` - Whether this agent can spawn subagents
- `allowed_subagents: [agent-names]` - Which agents this agent is allowed to spawn

### 2. Agent Definition Interface Update

```typescript
export interface AgentDefinition {
  name: string;
  description: string;
  tools?: string[];
  spawn_subagents?: boolean;           // NEW
  allowed_subagents?: string[];         // NEW
  model?: string;
  systemPrompt: string;
  source: "project" | "user";
  filePath: string;
}
```

### 3. Universal Spawn Tool for Agents

Instead of `spawn_parallel_explorers` (explore-specific), create generic tool:

```typescript
// pi_agent/src/flows/universal-spawn.ts
export function createSpawnSubagentsTool(
  parentAgent: AgentDefinition,
  allowedAgents: AgentDefinition[],
  baseOpts: RunSubagentOptions
): any {
  return {
    name: "spawn_subagents",
    label: "Spawn subagents",
    description: `Fan out subagents in parallel. Allowed agents: ${allowedAgents.map(a => a.name).join(", ")}`,
    parameters: Type.Object({
      tasks: Type.Array(
        Type.Object({
          agent: Type.String({
            description: `Agent name to spawn. Allowed: ${allowedAgents.map(a => a.name).join(", ")}`,
          }),
          prompt: Type.String({
            description: "Self-contained prompt for this subagent",
          }),
        }),
      ),
    }),
    async execute(toolCallId, params) {
      // Validate each requested agent is allowed
      const specs = params.tasks.map(t => {
        const agent = allowedAgents.find(a => a.name === t.agent);
        if (!agent) {
          throw new Error(`Agent "${t.agent}" not allowed. Allowed: ${allowedAgents.map(a => a.name).join(", ")}`);
        }
        return {
          agent,
          prompt: t.prompt,
          meta: {
            parentAgentId: parentAgent.name,
            parentToolCallId: toolCallId,
          },
        };
      });
      
      const subResults = await runSubagentsParallel(specs, baseOpts);
      
      return {
        output: JSON.stringify({
          count: subResults.length,
          results: subResults.map((r, i) => ({
            id: params.tasks[i].id,
            agent: params.tasks[i].agent,
            success: r.success,
            output: r.output,
            ...(r.error ? { error: r.error } : {}),
          })),
        }),
      };
    },
  };
}
```

### 4. FlowExecutor Tool Injection

Modify `FlowExecutor` to automatically inject spawn tool:

```typescript
// pi_agent/src/flows/executor/FlowExecutor.ts
async executeAgentPhase(phase, ctx, agentMap, baseOpts) {
  const agent = agentMap.get(phase.agent);
  
  // Build tools list from agent definition + spawn tool if enabled
  const tools = this.buildAgentTools(agent, agentMap, baseOpts);
  
  // Inject spawn tool if agent has permission
  if (agent.spawn_subagents && agent.allowed_subagents?.length > 0) {
    const allowedAgents = agent.allowed_subagents
      .map(name => agentMap.get(name))
      .filter(Boolean);
    
    const spawnTool = createSpawnSubagentsTool(agent, allowedAgents, baseOpts);
    tools.push(spawnTool);
  }
  
  // Run agent with tools
  const result = await runSubagent(agent, prompt, baseOpts, { tools });
  // ...
}
```

### 5. Fix Agent Instructions

**Planner** (with subagent spawning):
```yaml
---
name: planner
description: Creates build plans and coordinates implementation
tools: [read, write, bash, grep, find]
spawn_subagents: true
allowed_subagents: [builder, tester]
model: zai/glm-5.1
---

You are the **Planner**. Your job is to:

1. **Read requirements and test files** from the analyst
2. **Create a build plan** in clear text (save to plan.md)
3. **Coordinate implementation** by spawning builder subagents

## Subagent Spawning

You can use the `spawn_subagents` tool to coordinate multiple builders in parallel:

```json
{
  "tasks": [
    {
      "id": "scaffold",
      "agent": "builder",
      "prompt": "Create project scaffold: package.json, tsconfig.json, and empty src/"
    },
    {
      "id": "implement",
      "agent": "builder", 
      "prompt": "Implement the main functionality in src/ based on requirements"
    },
    {
      "id": "tests",
      "agent": "tester",
      "prompt": "Write tests for the implementation and verify they pass"
    }
  ]
}
```

The tool blocks until all subagents complete, then returns their results.

## Committing

After all builders complete, you MUST:
- Review the results from each
- If any failed, spawn a fix round with the failed agent
- If all succeeded, output: "PLAN COMPLETE"

You are the COORDINATOR, not the implementer. Use subagents, don't do the work yourself.
```

**Builder** (no subagents):
```yaml
---
name: builder
description: Executes a single build step
tools: [read, bash, write, grep, find, ls]
spawn_subagents: false  # or omit field
model: zai/glm-5.1
---

You are the **Builder**. You receive a specific task and execute it directly.

YOU DO NOT SPAWN SUBAGENTS. Just do the work yourself.

## Mandatory sequence

1. Read the task carefully
2. Inspect current state
3. Make the edits
4. Run tests/validations
5. Stage + commit changes
6. Verify commit landed
7. Output "STEP COMPLETE"
```

### 6. Keep YAML Flow Power

Maintain current YAML flow with loops and variables:

```yaml
name: tdd
description: Test-driven development flow
variables:
  maxIterations: 3
  iteration: 1
  testsPassed: false
  buildPassed: false
  remainingIssuesCount: 999

phases:
  - name: analyze
    agent: analyst
    description: Analyze task and create tests
    inputs:
      previousSummaries: true
    
  - name: build_loop
    while: "( ${firstIteration} || !${testsPassed} ) && ${iteration} <= ${maxIterations}"
    phases:
      - name: plan
        agent: planner
        description: Create or update build plan
        inputs:
          previousSummaries: true
        set:
          firstIteration: false
          
      - name: execute
        agent: planner  # Planner coordinates via spawn_subagents
        description: Coordinate builders and testers
        inputs:
          previousSumaries: true
        
      - name: verify
        agent: verifier
        description: Run tests and verify implementation
        inputs:
          previousSummaries: true
        set:
          testsPassed: true
          buildPassed: true
          remainingIssuesCount: 0
          
    set:
      iteration: "${iteration} + 1"
      
  - name: push
    if: "${task.pushOnComplete} && ${testsPassed} && ${buildPassed}"
    agent: builder
    description: Push commits and create PR
    builtIn: true
```

### 7. Tool Definition in Agent YAML

All tools should be defined in agent YAML frontmatter:

```yaml
---
name: analyst
description: Analyzes requirements and creates tests
tools: [read, write, bash, grep, find]
spawn_subagents: false
model: zai/glm-5.1
---
```

**No tools in flow YAML** - the flow only defines phases and execution logic.

## Implementation Priority

### High Priority
1. **Add spawn_subagents to AgentDefinition interface**
2. **Update agent YAML frontmatter** with `spawn_subagents` and `allowed_subagents`
3. **Create generic spawn_subagents tool** (not explore-specific)
4. **Update FlowExecutor** to inject spawn tool when needed

### Medium Priority  
5. **Fix agent instructions** to use tools properly (analyst must write files)
6. **Ensure YAML flow maintains current power** (loops, variables, while conditions)
7. **Remove tool definitions from flow YAML** (keep only phase definitions)

### Low Priority
8. **Add spawn authorization checks** (prevent unauthorized spawning)
9. **Improve error handling** for failed subagent spawns
10. **Add subagent visualization** in UI (show parent-child relationships)

## Benefits of This Approach

1. **Declarative Agent Config** - All capabilities defined in agent YAML
2. **Maintains Flow Power** - Loops, variables, conditions preserved
3. **Clear Tool Ownership** - Tools live with agents, not flows
4. **Flexible Coordination** - Any agent can spawn authorized subagents
5. **Backwards Compatible** - Can gradually migrate existing flows
6. **Visible Coordination** - User sees planner coordinating builders

## Next Steps

1. Update AgentDefinition interface
2. Add spawn_subagents field to agent YAML files
3. Create generic spawn_subagents tool
4. Update FlowExecutor for tool injection
5. Fix agent instructions (analyst must write files)
6. Test with existing TDD flow

This keeps the power of the YAML system while making agent capabilities declarative and clear.
