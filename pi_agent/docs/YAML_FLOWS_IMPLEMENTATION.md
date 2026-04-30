# YAML Flow System - Implementation Summary

## Overview

The YAML-configurable flow system has been successfully implemented for pi_agent. This enables defining agent orchestration flows in YAML files instead of writing TypeScript code.

## What Was Implemented

### Phase 1: Foundation ✅

1. **Flow Schema & Parser** (`src/flows/schema.ts`)
   - TypeScript interfaces for FlowDef, PhaseDef, OutputDef
   - YAML parsing with validation
   - Error handling with detailed messages

2. **FlowContext** (`src/flows/executor/FlowContext.ts`)
   - Variable storage and interpolation (`${var}` syntax)
   - Agent summary tracking and propagation
   - Loop iteration tracking
   - Evaluation context for conditions

3. **Decision Tool** (`src/flows/tools/decision-tool.ts`)
   - Safe JavaScript expression evaluation
   - Support for `@agent.property` references
   - Timeout protection (1 second)
   - Sandboxed execution (no global scope)

4. **Enhanced Agent Runner** (`src/agents/runner.ts`)
   - Extract summaries from agent output
   - Parse variables from summaries
   - New fields: `summary`, `variables`

5. **Agent Summary Updates**
   - All agents now include `## Summary` section
   - Agents can set `## Variables` for flow control
   - Updated agents: analyst, planner, builder, verifier, pr-author

### Phase 2: Flow Executor ✅

1. **FlowExecutor** (`src/flows/executor/FlowExecutor.ts`)
   - Executes YAML flow definitions
   - Sequential phase execution
   - Loop support (while conditions)
   - Conditional phases (if conditions)
   - Variable propagation between phases

2. **Integration** (`src/flows/tdd-wrapper.ts`)
   - Feature flag: `PI_AGENT_USE_YAML_FLOW=1`
   - Backwards compatible with legacy flow
   - Easy switch between implementations

### Phase 3: YAML Flow Definition ✅

1. **TDD Flow YAML** (`.pi/flows/tdd.yaml`)
   - Analyze → Plan → Execute → Verify → Push → PR
   - Loop with max 3 iterations
   - Conditional push/PR based on success
   - Returns all agent summaries

2. **Wave Orchestrator Agent** (`.pi/agents/wave-orchestrator.md`)
   - Executes parallel waves of builder agents
   - Reads plan from planner summary
   - Tracks results and reports outcomes

### Phase 4: Python Integration ✅

1. **Python Tool Updates** (`druppie/agents/execute_coding_task_pi.py`)
   - Returns agent summaries in tool result
   - New format: `{ summaries: {...}, deliverables: {...} }`
   - Explore flow unchanged (returns `answer`)

## Usage

### For Users

To use the new YAML-based TDD flow:

```bash
export PI_AGENT_USE_YAML_FLOW=1
# Run your pi_agent command as usual
```

### For Developers

To create a custom flow:

1. Create a YAML file in `.pi/flows/`:
```yaml
name: my-flow
description: My custom flow
variables:
  maxIterations: 3
phases:
  - name: step1
    agent: analyst
    description: First step
  - name: step2
    agent: planner
    description: Second step
    inputs:
      previousSummaries: true
output:
  format: summaries
  include: [analyst, planner]
```

2. Use it in your code:
```typescript
import { FlowExecutor } from "./flows/executor/FlowExecutor.js";

const executor = new FlowExecutor(journal);
const result = await executor.execute(
  "/path/to/.pi/flows/my-flow.yaml",
  task,
  config
);
```

## Agent Output Format

Agents should now include:

```markdown
## Summary
2-3 sentences about what you did and what you're passing to the next agent.

## Variables
key1: value1
key2: value2
```

## Tool Result Format

### TDD Flow
```json
{
  "success": true,
  "run_id": "...",
  "pi_coding_run_id": "...",
  "summaries": {
    "analyst": "Analyzed task to implement...",
    "planner": "Created build plan with...",
    "wave-orchestrator": "Executed 3 waves...",
    "verifier": "All tests passing...",
    "pr-author": "Created PR #123..."
  },
  "deliverables": {
    "pr_url": "https://github.com/...",
    "branch": "feat/user-auth",
    "commits": [{"sha": "abc123", "message": "..."}]
  }
}
```

### Explore Flow (unchanged)
```json
{
  "success": true,
  "answer": "The auth system uses..."
}
```

## File Structure

```
pi_agent/
├── .pi/
│   ├── agents/
│   │   ├── analyst.md          # Updated with summary
│   │   ├── planner.md          # Updated with summary
│   │   ├── builder.md          # Updated with summary
│   │   ├── verifier.md         # Updated with summary
│   │   ├── pr-author.md        # Updated with summary
│   │   ├── wave-orchestrator.md # NEW
│   │   ├── router.md           # Unchanged
│   │   └── explorer.md         # Unchanged
│   └── flows/
│       └── tdd.yaml            # NEW
├── src/
│   ├── flows/
│   │   ├── executor/
│   │   │   ├── FlowExecutor.ts    # NEW
│   │   │   └── FlowContext.ts     # NEW
│   │   ├── tools/
│   │   │   └── decision-tool.ts   # NEW
│   │   ├── tdd.ts                 # Modified (legacy)
│   │   ├── tdd-yaml.ts            # NEW
│   │   ├── tdd-wrapper.ts         # NEW
│   │   ├── explore.ts             # Unchanged
│   │   └── schema.ts              # NEW
│   └── agents/
│       └── runner.ts              # Enhanced
└── docs/
    ├── YAML_FLOWS_PRD.md          # NEW
    └── YAML_FLOWS_IMPLEMENTATION.md # NEW
```

## Testing

To test the new YAML flow:

```bash
cd /home/nuno/Documents/druppie-fork/pi_agent
export PI_AGENT_USE_YAML_FLOW=1
# Run your test command
```

## Migration Path

1. **Current**: Legacy TypeScript flow (default)
2. **Opt-in**: Set `PI_AGENT_USE_YAML_FLOW=1` to use YAML flow
3. **Parallel**: Run both in production to compare results
4. **Default**: After validation, make YAML flow the default
5. **Remove**: Deprecate legacy TypeScript flow after 2 releases

## Benefits

1. **No Code Changes**: Modify flows by editing YAML
2. **Clearer Intent**: YAML structure shows flow at a glance
3. **Agent Summaries**: Each agent explains what it did
4. **Better Debugging**: See what each agent produced
5. **Easier Testing**: Create test flows without TypeScript
6. **Backwards Compatible**: Existing flows still work

## Next Steps

1. Test the YAML flow with real tasks
2. Monitor performance vs legacy flow
3. Gather user feedback
4. Create additional custom flows
5. Add more built-in agents as needed

## Known Limitations

1. Wave orchestrator agent is defined but not fully implemented (needs to interface with runSubagentsParallel)
2. Error handling in loops could be improved
3. No sub-flow composition yet (deferred to v2)
4. Limited expression validation in conditions

## Questions?

See the PRD at `docs/YAML_FLOWS_PRD.md` for full design details.
