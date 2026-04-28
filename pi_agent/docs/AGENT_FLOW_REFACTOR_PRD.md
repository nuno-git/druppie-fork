# Agent Flow Refactor PRD - Simplify YAML Flow Architecture

## Current Issues Identified

### 1. Analyst Agent Output Problem
- **Issue**: Analyst writes test files as "output" in final narrative instead of using write tool
- **Problem**: Files are never actually created in the repository
- **Impact**: Tests don't exist, verification fails
- **Expected**: Analyst should use `write` tool to create test files, then `git add/commit/push`

### 2. Planner Agent Purpose Confusion
- **Issue**: Planner creates complex JSON wave structure instead of simple build plan
- **Problem**: The "waves" concept is confusing and unnecessary
- **Expected**: Planner should create a straightforward build plan in natural language

### 3. Wave Orchestrator Visibility Issue
- **Issue**: Logs show `wave_start`/`wave_end` events but wave orchestrator itself is not visible
- **Problem**: Builder agents appear directly instead of being coordinated by wave orchestrator
- **Expected**: User should see wave orchestrator as the coordinating agent, with builder subagents

### 4. Builder Agent Spawning Mystery
- **Issue**: Builder agents appear magically spawned (builder-1, builder-2, etc.)
- **Problem**: No clear mechanism for how these subagents are created
- **User Question**: "We don't have tools for spawning subagents, right?"
- **Current Behavior**: Multiple builders run in parallel within "waves" but the orchestration is invisible

### 5. Overcomplicated Architecture
- **Current Flow**: Analyst → Planner → Wave Orchestrator → Multiple Builders → Verifier
- **Problem**: Too many layers, wave concept is confusing, unclear responsibilities
- **Expected**: Simpler, more direct flow

## Root Cause Analysis

### Missing Tool Infrastructure
Looking at the current codebase, there are no tools for:
- Spawning subagents
- Parallel execution coordination
- Subagent result collection

### YAML Flow vs Implementation Mismatch
The YAML flow defines a structure, but the implementation (pi_agent) doesn't properly execute it:
- YAML: `wave-orchestrator` agent should coordinate work
- Reality: Builder agents appear directly, wave orchestrator is invisible

### Agent Communication Issues
- Planner outputs JSON but there's no clear consumer
- Analyst outputs text but doesn't execute files
- Wave orchestrator coordinates but isn't visible to user

## Proposed Solution

### New Simplified Flow Architecture

```
1. ANALYZE
   - Agent: analyst
   - Purpose: Analyze requirements and create test files
   - Tools: write, read, bash, git (add/commit/push)
   - Output: Creates actual test files in repository

2. PLAN  
   - Agent: planner
   - Purpose: Create straightforward build plan
   - Tools: read (to see test files), write (to create plan.md if needed)
   - Output: Simple text-based build plan (no JSON waves)

3. BUILD
   - Agent: builder (single agent, not multiple)
   - Purpose: Implement according to plan
   - Tools: write, read, bash, git (add/commit/push)
   - Output: Creates implementation files

4. VERIFY
   - Agent: verifier
   - Purpose: Run tests and verify implementation
   - Tools: bash (test commands), read (check results)
   - Output: Test results and verification summary

5. PUSH (conditional)
   - Agent: push-agent or builder
   - Purpose: Push commits and create PR
   - Tools: git (push), PR creation
   - Output: Branch name and PR URL
```

### Key Changes Required

#### 1. Remove Wave Orchestrator
- **Action**: Delete `wave-orchestrator` agent and related code
- **Rationale**: Wave concept is confusing and unnecessary
- **Replacement**: Single builder agent handles implementation

#### 2. Fix Agent Responsibilities
- **Analyst**: Must use write tool to create actual test files, then commit
- **Planner**: Creates simple text-based plan (no JSON), may save to plan.md
- **Builder**: Single agent that implements everything according to plan
- **Verifier**: Runs tests, reports results clearly

#### 3. Improve Agent Tooling
Ensure each agent has proper tools:
- All agents: `read`, `write`, `bash`, `git`
- Analyst: Must actually create test files, not just describe them
- Planner: Can read existing files, create plan.md
- Builder: Must create all implementation files
- Verifier: Must run actual test commands

#### 4. Fix YAML Flow Definition
```yaml
# Simplified tdd.yaml
name: tdd
phases:
  # Phase 1: Analyze and create tests
  - name: analyze
    agent: analyst
    description: Analyze requirements and create test files
    tools: [read, write, bash, git]
    
  # Phase 2: Create build plan
  - name: plan
    agent: planner
    description: Create build plan based on requirements and tests
    tools: [read, write, bash, git]
    
  # Phase 3: Implement
  - name: build
    agent: builder
    description: Implement according to plan
    tools: [read, write, bash, git]
    
  # Phase 4: Verify
  - name: verify
    agent: verifier
    description: Run tests and verify implementation
    tools: [bash, read]
    
  # Phase 5: Push and PR (conditional)
  - name: push
    if: ${task.pushOnComplete}
    agent: builder
    description: Push commits and create PR
    tools: [bash, git]
```

#### 5. Fix Agent Instructions
Update each agent's `.md` file to be explicit about responsibilities:

**Analyst**:
```
You are the **Analyst**. Your job is to:
1. Read the requirements from the task description
2. Create test files using the `write` tool
3. Commit the test files using git: add, commit, push
4. Report what tests you created

CRITICAL: You MUST actually create files using the `write` tool, not just describe them in text.
```

**Planner**:
```
You are the **Planner**. Your job is to:
1. Read the requirements and test files created by analyst
2. Create a straightforward build plan in plain text
3. Optionally save the plan to `plan.md` using `write` tool
4. Report the plan to the builder

NO JSON, NO "waves", NO complex structures. Just clear text.
```

**Builder**:
```
You are the **Builder**. Your job is to:
1. Read the build plan from planner
2. Implement all the required files using `write` tool
3. Test the implementation locally
4. Commit each file: git add, commit
5. Report what you implemented

You work ALONE - no subagents, no parallel execution. Just do the work step by step.
```

**Verifier**:
```
You are the **Verifier**. Your job is to:
1. Run the test commands using `bash` tool
2. Check the output using `read` tool if needed
3. Report what passed and what failed

NO modifications - just verification and reporting.
```

#### 6. Subagent Spawning (If Needed)
If parallel execution is truly needed in the future:
- Create proper tool: `spawn_subagent(task: string, agent: string)`
- Implement subagent process management in pi_agent
- Make subagent results visible in UI
- Ensure proper cleanup and error handling

**For now**: Stick to sequential execution for simplicity.

## Implementation Plan

### Phase 1: Fix Agent Instructions
- [ ] Update analyst.md to require write tool usage
- [ ] Update planner.md to create text plans, not JSON
- [ ] Update builder.md to work alone, no subagents
- [ ] Update verifier.md to only verify, not modify

### Phase 2: Simplify YAML Flow
- [ ] Remove wave-orchestrator from YAML
- [ ] Create simplified phases: analyze → plan → build → verify → push
- [ ] Remove wave-related event generation

### Phase 3: Update Agent Tooling
- [ ] Ensure all agents have proper tools (read, write, bash, git)
- [ ] Test that analyst actually creates files
- [ ] Test that planner creates readable plans
- [ ] Test that builder implements correctly
- [ ] Test that verifier runs actual tests

### Phase 4: Fix UI/Event System
- [ ] Remove wave-related event handling in frontend
- [ ] Ensure each phase is clearly visible
- [ ] Show which agent is currently active
- [ ] Display clear progress: ANALYZE → PLAN → BUILD → VERIFY → PUSH

### Phase 5: Testing & Validation
- [ ] Create test case for simple hello world implementation
- [ ] Verify analyst creates test files
- [ ] Verify planner creates readable plan
- [ ] Verify builder implements correctly
- [ ] Verify verifier runs tests
- [ ] Verify end-to-end flow works

## Success Criteria

### Must Haves
- [ ] Analyst actually creates test files in repository
- [ ] Planner creates simple text-based plan (no JSON)
- [ ] Single builder agent handles implementation
- [ ] No wave concept or wave orchestrator
- [ ] Clear progress visible to user
- [ ] Each phase properly completes before next starts

### Should Haves  
- [ ] Agent instructions are clear and explicit
- [ ] Tool usage is consistent across agents
- [ ] Error handling is robust
- [ ] UI clearly shows current agent and phase

### Nice to Haves
- [ ] Plan saved to plan.md for reference
- [ ] Clear error messages if phase fails
- [ ] Retry mechanism for transient failures
- [ ] Progress estimation and time remaining

## Questions for Discussion

1. **Parallel Execution**: Do we actually need parallel execution for simple tasks?
   - If yes, need subagent spawning infrastructure
   - If no, sequential execution is simpler and clearer

2. **Test File Creation**: Should analyst create test files in a specific location?
   - `tests/` directory?
   - Same directory as implementation?
   - Standard naming convention?

3. **Plan Format**: Should the planner save plans to files?
   - Save to `plan.md` for reference?
   - Just keep in memory?
   - Both (save for transparency, use for execution)?

4. **Build Process**: Should builder do everything in one run or multiple steps?
   - One monolithic build?
   - Step-by-step with commits after each?
   - User preference?

5. **Error Recovery**: What happens if a phase fails?
   - Stop the flow?
   - Retry the phase?
   - Skip to next phase?

## Risks & Mitigations

### Risk 1: Breaking Existing Flows
- **Risk**: Changes might break other flows that depend on current structure
- **Mitigation**: Keep old flow as fallback, migrate incrementally

### Risk 2: Agent Confusion
- **Risk**: Agents might not understand new instructions
- **Risk**: Complex JSON parsing in planner output
- **Mitigation**: Keep plans simple text, test extensively

### Risk 3: Tool Availability
- **Risk**: Agents might not have proper tools configured
- **Mitigation**: Explicitly list required tools in agent definitions

## Timeline Estimate

- **Phase 1 (Agent Instructions)**: 1-2 hours
- **Phase 2 (YAML Flow)**: 1-2 hours  
- **Phase 3 (Agent Tooling)**: 2-3 hours
- **Phase 4 (UI/Events)**: 2-3 hours
- **Phase 5 (Testing)**: 3-4 hours

**Total**: 9-14 hours of focused development

## Conclusion

The current YAML flow architecture is overly complex with confusing wave orchestration and unclear agent responsibilities. By simplifying to a clear 4-step flow (ANALYZE → PLAN → BUILD → VERIFY) with explicit agent instructions and proper tool usage, we can create a system that is:

1. **Clearer** - Each agent has one clear job
2. **Simpler** - No confusing wave concept
3. **Transparent** - User can see what's happening
4. **Reliable** - Files are actually created and committed
5. **Maintainable** - Easier to understand and modify

The proposed changes address all the user's concerns while maintaining the core value of the YAML flow system.
