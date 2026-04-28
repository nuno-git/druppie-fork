# PRD: YAML-Configurable Flow System for pi_agent

## Context

The current pi_agent architecture has hardcoded flows in TypeScript (tdd.ts: 814 lines, explore.ts: 280 lines). Adding new flows or modifying existing ones requires writing TypeScript code. This creates a barrier to entry and makes experimentation difficult.

**Current State:**
- Flows are TypeScript orchestrators that sequence agents
- Agents output structured JSON (GoalAnalysis, BuildPlan, VerificationResult)
- Tool results return only deliverables (PR URL, branch, commits)
- No free-text summaries of what each agent did
- Loops and conditionals are hardcoded in TypeScript

**Desired State:**
- Flows defined in YAML files in `.pi/flows/` directory
- Agents output free-text summaries of what they did
- Tool results return all agent summaries
- Agents can set variables for flow control
- Loops and conditionals defined in YAML
- Easy to create new flows without writing TypeScript

## Goals

1. **Separate flows from agents** - Flows are orchestration, agents do the work
2. **YAML-configurable flows** - Define agent sequences, loops, and conditionals declaratively
3. **Agent summaries** - Each agent ends with a free-text summary of what it did
4. **Summary propagation** - Each agent gets summaries from all previous agents
5. **Variable system** - Agents can set variables used in flow control (if/else/while)
6. **No changes to explore flow** - Keep router + spawn_parallel_explorers as-is

## Architecture

### Flow YAML Schema

```yaml
# .pi/flows/tdd.yaml
name: tdd
description: Test-driven development flow with analysis, planning, implementation, and verification

variables:
  maxIterations: 3
  iteration: 1

phases:
  # Sequential phase: run one agent
  - name: analyze
    agent: analyst
    description: Analyze the task and define goals, tests, and architecture

  # Loop phase: retry until condition is false
  - name: build_loop
    while: "${iteration} <= ${maxIterations} && (!@lastVerification?.testsPassed || @lastVerification?.remainingIssues?.length > 0)"
    phases:
      - name: plan
        agent: planner
        description: Create a build plan (initial or fix plan)
        inputs:
          previousSummaries: true  # Include all previous agent summaries

      - name: execute
        agent: wave-orchestrator
        description: Execute build waves in parallel
        builtIn: true  # System-provided agent
        config:
          sourceAgent: planner  # Get plan from this agent's summary
          workerAgent: builder
          maxWaves: 10

      - name: verify
        agent: verifier
        description: Run tests and fix simple issues
        inputs:
          previousSummaries: true

    # Update loop variable
    set:
      iteration: "${iteration} + 1"

  # Conditional phase: only run if condition is true
  - name: push
    if: "${task.pushOnComplete} && @lastVerification?.testsPassed && @lastVerification?.buildPassed"
    agent: push-agent
    description: Push commits and create PR
    builtIn: true

  # Conditional phase
  - name: pr_author
    if: "${task.pushOnComplete} && @push?.ok"
    agent: pr-author
    description: Write PR title and body
    inputs:
      previousSummaries: true

# Output format for tool result
output:
  format: summaries  # Return all agent summaries as a map
  include:
    - analyzer
    - planner
    - wave-orchestrator
    - verifier
    - pr-author
```

### Enhanced Agent Schema

Agents keep their current frontmatter but add summary guidance:

```yaml
---
name: analyst
description: Analyzes a task to define goals, acceptance criteria, test cases, and architecture
tools: [read, bash, grep, find, ls]
model: zai/glm-5.1
---

# ... agent prompt ...

## Your Summary

After you complete your analysis, write a brief summary (3-5 sentences) that includes:
- What you were asked to analyze
- What approach you took
- What key decisions you made
- What you're passing to the next agent

This summary will be read by the next agent in the flow.
```

### Variable System

**Setting variables:**
Agents can set variables in their summaries using a special format:

```
## Summary
I analyzed the task and determined we need to implement user authentication.

## Variables
branchName: feat/user-auth
testFramework: vitest
verifyCommand: npm test
```

The flow executor parses this and makes variables available:
- In subsequent agent prompts as `${branchName}`
- In while/if conditions as `@variables.branchName`
- In set expressions as `"${iteration} + 1"`

**Built-in variables:**
- `${iteration}` - Current loop iteration
- `${task.*}` - Task specification fields
- `@lastAgentName.summary` - Last summary from named agent
- `@lastVerification` - Parsed verification result (for TDD)

### Flow Components

#### 1. FlowExecutor Class

**File:** `src/flows/executor/FlowExecutor.ts`

**Responsibilities:**
- Parse YAML flow definitions
- Execute phases sequentially or in loops
- Maintain flow context (variables, summaries)
- Evaluate conditions (while/if)
- Set variables from agent summaries
- Collect agent summaries for output

**Key methods:**
```typescript
class FlowExecutor {
  async execute(flowPath: string, task: TaskSpec, config: AgentConfig): Promise<FlowResult>

  private async executePhase(phase: PhaseDef, ctx: FlowContext): Promise<void>
  private async executeLoop(loop: LoopDef, ctx: FlowContext): Promise<void>
  private evaluateCondition(condition: string, ctx: FlowContext): boolean
  private extractVariables(summary: string): Map<string, string>
}
```

#### 2. FlowContext Class

**File:** `src/flows/executor/FlowContext.ts`

**Responsibilities:**
- Store flow state (variables, summaries, iteration)
- Provide variable interpolation for prompts
- Track agent summaries for propagation
- Expose evaluation context for conditions

**Key methods:**
```typescript
class FlowContext {
  setVariable(name: string, value: string): void
  getVariable(name: string): string | undefined
  interpolate(str: string): string  // Replace ${var} with values
  addSummary(agentName: string, summary: string): void
  getSummaries(): Map<string, string>
  toEvalContext(): object  // For decision tool evaluation
}
```

#### 3. Decision Tool

**File:** `src/flows/tools/decision-tool.ts`

**Responsibilities:**
- Safely evaluate JavaScript expressions
- Provide access to flow context variables
- Support property access (`@lastVerification.testsPassed`)
- Support basic operations (arithmetic, comparisons, logical)

**Implementation:**
```typescript
export function createDecisionTool(ctx: FlowContext): ToolDefinition {
  return {
    name: "evaluate_condition",
    parameters: Type.Object({
      expression: Type.String(),
    }),
    async execute(toolCallId: string, params: { expression: string }) {
      // Safe evaluation using Function constructor with restricted scope
      // Has access to ctx.variables and @-prefixed agent results
      const result = evaluateSafe(params.expression, ctx.toEvalContext());
      return { output: String(result), details: { result } };
    },
  };
}
```

**Safety:**
- Restricted to expression evaluation (no statements)
- No access to global scope
- Timeout and memory limits
- Whitelisted operations only

#### 4. Wave Orchestrator Agent (Built-in)

**File:** `.pi/agents/wave-orchestrator.md` (system agent, not user-editable)

**Purpose:** Execute parallel waves of worker agents

**How it works:**
1. Reads the previous agent's summary (planner)
2. Parses wave structure from summary (JSON code block)
3. Uses runSubagentsParallel to execute waves
4. Writes a summary of what was executed

**Example wave structure:**
```json
{
  "waves": [
    [
      { "id": "step1", "prompt": "Write the auth service", "files": ["src/auth.ts"] },
      { "id": "step2", "prompt": "Write the auth tests", "files": ["src/auth.test.ts"] }
    ]
  ]
}
```

**Summary output:**
```
## Summary
Executed 1 wave with 2 parallel steps:
- step1 (auth service): ✓ Success, 1 commit
- step2 (auth tests): ✓ Success, 1 commit

## Variables
step1.success: true
step2.success: true
totalCommits: 2
```

#### 5. Enhanced Agent Runner

**File:** `src/agents/runner.ts` (modify existing)

**Changes:**
- After agent runs, extract the summary section from output
- Parse and return separately from structured JSON (if any)
- Extract variables from summary if present
- Return structure: `{ success, summary, variables, output, error }`

**Implementation:**
```typescript
interface RunSubagentResult {
  success: boolean;
  summary: string;  // Extracted summary section
  variables?: Map<string, string>;  // Parsed from ## Variables section
  output: string;  // Full output
  error?: string;
}

function extractSummary(output: string): string {
  // Find ## Summary section, return content until next ## or end
}

function extractVariables(summary: string): Map<string, string> {
  // Parse ## Variables section as key: value pairs
}
```

### Tool Result Structure

**For TDD flow:**
```json
{
  "success": true,
  "flow": "tdd",
  "summaries": {
    "analyst": "Analyzed the task to implement user auth. Determined we need...",
    "planner": "Created initial build plan with 2 waves. Wave 1 implements auth service...",
    "wave-orchestrator": "Executed 2 waves. Wave 1: 2 parallel steps (both successful). Wave 2: 1 step (verifier fixes).",
    "verifier": "Ran test suite. All tests passing. Fixed 2 minor issues (missing import, typo).",
    "pr-author": "Created PR for feat/user-auth with title 'feat: implement user authentication'."
  },
  "deliverables": {
    "pr_url": "https://github.com/...",
    "branch": "feat/user-auth",
    "commits": ["abc123", "def456"]
  }
}
```

**For Explore flow (unchanged):**
```json
{
  "success": true,
  "flow": "explore",
  "answer": "The auth system uses JWT tokens issued by /api/auth/login. Tokens are..."
}
```

## Implementation Plan

### Phase 1: Foundation (Week 1)

**Goal:** Build core infrastructure for YAML flows

1. **Flow YAML parser** (`src/flows/schema.ts`)
   - Parse YAML files
   - Validate flow schema
   - Type definitions for FlowDef, PhaseDef, LoopDef

2. **FlowContext** (`src/flows/executor/FlowContext.ts`)
   - Variable storage and interpolation
   - Summary tracking
   - Evaluation context builder

3. **Decision tool** (`src/flows/tools/decision-tool.ts`)
   - Safe expression evaluation
   - Support @-syntax for agent results
   - Unit tests for safety

4. **Enhanced agent runner** (`src/agents/runner.ts`)
   - Extract summaries from agent output
   - Parse variables from summaries
   - Return new RunSubagentResult structure

5. **Agent summary updates**
   - Add "## Summary" section to all agents
   - Add "## Variables" section where applicable
   - Update prompts to emphasize summary writing

**Deliverables:**
- Working FlowContext with variable interpolation
- Safe decision tool with test coverage
- All agents producing summaries
- Unit tests for core components

### Phase 2: Flow Executor (Week 2)

**Goal:** Build generic flow execution engine

1. **FlowExecutor skeleton** (`src/flows/executor/FlowExecutor.ts`)
   - YAML flow loading
   - Sequential phase execution
   - Agent invocation with summary propagation

2. **Condition evaluation**
   - Integrate decision tool
   - Evaluate if/while conditions
   - Handle @-syntax for agent results

3. **Variable setting**
   - Parse ## Variables from summaries
   - Set variables in context
   - Support expression evaluation (math, string ops)

4. **Error handling**
   - Phase failure handling
   - Retry logic
   - Clean error messages

**Deliverables:**
- Working FlowExecutor for sequential flows
- Condition evaluation working
- Variables flowing through phases
- Integration tests

### Phase 3: Advanced Flow Features (Week 3)

**Goal:** Support loops and conditionals

1. **Loop execution**
   - while loop implementation
   - Iteration tracking
   - Break conditions (max iterations)

2. **Conditional phases**
   - if/else implementation
   - Nested conditions
   - Skip logic

3. **Wave orchestrator agent**
   - Create system agent
   - Parse wave structure from planner summary
   - Execute parallel waves
   - Write summary of execution

4. **Push agent (built-in)**
   - Create system agent for git push
   - Handle bundling and isolated push
   - Write summary with PR details

**Deliverables:**
- Full TDD flow in YAML
- Loops and conditionals working
- Wave orchestrator functional
- TDD flow migrated to YAML

### Phase 4: Integration & Polish (Week 4)

**Goal:** Complete migration and testing

1. **TDD flow migration**
   - Create `.pi/flows/tdd.yaml`
   - Migrate all logic from tdd.ts
   - Test parity with existing flow

2. **CLI updates**
   - Add `--flow` flag to specify flow file
   - Default flows: tdd, explore
   - List available flows command

3. **Tool result updates**
   - Update execute_coding_task_pi.py
   - Return summaries for TDD flow
   - Keep explore flow unchanged

4. **Documentation**
   - Flow YAML reference
   - Variable system guide
   - How to create custom flows
   - Migration guide for existing agents

5. **Testing**
   - End-to-end tests for TDD flow
   - Unit tests for all components
   - Performance tests
   - Backwards compatibility tests

**Deliverables:**
- Fully working YAML-based TDD flow
- Documentation complete
- All tests passing
- Backwards compatible with existing flows

## File Structure

```
pi_agent/
├── .pi/
│   ├── agents/           # Agent definitions (unchanged)
│   │   ├── analyst.md
│   │   ├── planner.md
│   │   ├── builder.md
│   │   ├── verifier.md
│   │   ├── pr-author.md
│   │   ├── router.md
│   │   ├── explorer.md
│   │   └── wave-orchestrator.md  # NEW: System agent
│   └── flows/            # NEW: Flow definitions
│       ├── tdd.yaml      # Migrated from tdd.ts
│       └── explore.yaml  # Optional (explore.ts remains)
├── src/
│   ├── flows/
│   │   ├── executor/
│   │   │   ├── FlowExecutor.ts    # NEW: Generic flow engine
│   │   │   └── FlowContext.ts     # NEW: Flow state management
│   │   ├── tools/
│   │   │   └── decision-tool.ts   # NEW: Condition evaluation
│   │   ├── tdd.ts                 # MODIFIED: Use FlowExecutor
│   │   ├── explore.ts             # UNCHANGED
│   │   └── schema.ts              # NEW: YAML schemas & validation
│   └── agents/
│       └── runner.ts              # MODIFIED: Extract summaries
```

## Migration Strategy

### Backwards Compatibility

1. **Keep existing tdd.ts and explore.ts** as legacy entry points
2. **Add feature flag** to use YAML flows: `PI_AGENT_USE_YAML_FLOW=1`
3. **Gradual migration**: Users can opt-in to YAML flows
4. **Fallback**: If YAML flow fails, fall back to TS flow
5. **Deprecation**: After 2 releases, remove TS flows

### Testing Strategy

1. **A/B testing**: Run both TS and YAML flows in parallel on test tasks
2. **Compare outputs**: Ensure same results
3. **Performance**: Monitor for regressions
4. **Error cases**: Test failure modes

### Rollout Plan

1. **Alpha release** (end of Week 2): Internal testing
2. **Beta release** (end of Week 3): Select users opt-in
3. **GA release** (end of Week 4): Default to YAML flows
4. **Remove TS flows** (2 releases later): Clean up legacy code

## Success Criteria

1. ✅ TDD flow migrated to YAML with 100% feature parity
2. ✅ All agents produce free-text summaries
3. ✅ Variables and conditions work in YAML flows
4. ✅ Tool results include all agent summaries
5. ✅ Explore flow unchanged
6. ✅ Backwards compatible with existing integrations
7. ✅ Documentation complete
8. ✅ Performance within 10% of TS flows

## Open Questions

1. **Should we support sub-flow composition?** (Deferred to v2)
2. **Should flow YAML support imports/templates?** (Deferred to v2)
3. **How to handle agent versioning?** (Track in separate RFC)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| YAML flows slower than TS | High | Performance targets, optimization |
| Expression evaluation security | High | Sandboxing, timeouts, whitelists |
| Agent summary quality varies | Medium | Prompt engineering, examples |
| Migration breaks existing flows | High | Backwards compatibility, A/B testing |
| Complex YAML hard to debug | Medium | Error messages, debug mode |

## Implementation Status

- [x] PRD approved
- [x] Phase 1: Foundation ✅
- [x] Phase 2: Flow Executor ✅
- [x] Phase 3: Advanced Features ✅
- [x] Phase 4: Integration & Polish ✅

**Status**: Complete and ready for testing!
