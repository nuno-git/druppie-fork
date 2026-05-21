# YAML Flow System - Integration Tests

## Overview

This directory contains integration tests for the new YAML-configurable flow system. These tests validate that agent summaries are properly returned when using the `execute_coding_task_pi` tool with the YAML-based TDD flow.

## Test Files

### Tool Tests (testing/tools/)

#### 1. yaml-flow-smoke-test.yaml
**Purpose**: Quick validation that the YAML flow system returns agent summaries correctly

**What it tests:**
- ✅ execute_coding_task_pi with `flow=tdd` returns summaries
- ✅ All 5 agent summaries present (analyst, planner, wave-orchestrator, verifier, pr-author)
- ✅ Each summary is non-empty and properly formatted
- ✅ Deliverables (branch, commits) included
- ✅ Explore flow still works (returns "answer" field)

**Runtime**: ~30 seconds (mocked, no real LLM calls)

**How to run:**
```bash
# Via UI
Navigate to Evaluations → Select "yaml-flow-smoke-test" → Run

# Via API
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-flow-smoke-test"}'
```

---

#### 2. yaml-tdd-flow-summarize-results.yaml
**Purpose**: Comprehensive validation of YAML flow with all assertions

**What it tests:**
- ✅ Tool result structure validation
- ✅ Each agent summary format validation
- ✅ Summary content quality checks
- ✅ Deliverable presence and structure
- ✅ Complete flow execution validation

**Runtime**: ~1 minute (mocked)

**How to run:**
```bash
# Via UI
Navigate to Evaluations → Select "yaml-tdd-flow-summarize-results" → Run

# Via API
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-tdd-flow-summarize-results"}'
```

---

### Agent Tests (testing/agents/)

#### yaml-flow-agent-summaries.yaml
**Purpose**: Test real developer agent using YAML flow and returning summaries

**What it tests:**
- ✅ Developer agent calls execute_coding_task_pi with flow=tdd
- ✅ Tool result contains all 5 agent summaries
- ✅ Each summary follows expected format (2-5 sentences)
- ✅ Summaries explain what each agent did (not just JSON)
- ✅ Judge validates summary quality

**Runtime**: ~5-10 minutes (real LLM calls)

**How to run:**
```bash
# Via UI
Navigate to Evaluations → Select "yaml-flow-agent-summaries" → Run

# Via API
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-flow-agent-summaries"}'
```

---

## Test Validation Details

### What Gets Validated

#### 1. Tool Call Parameters
- ✅ `flow: "tdd"` parameter is passed
- ✅ `repo_target: "project"` is set correctly
- ✅ Task description is included
- ✅ Language is specified

#### 2. Tool Result Structure
```json
{
  "success": true,
  "run_id": "...",
  "pi_coding_run_id": "...",
  "summaries": {
    "analyst": "...",
    "planner": "...",
    "wave-orchestrator": "...",
    "verifier": "...",
    "pr-author": "..."
  },
  "deliverables": {
    "branch": "...",
    "commits": [...]
  }
}
```

#### 3. Agent Summary Formats

**Analyst Summary:**
- Mentions: task analysis, approach taken, key decisions
- Length: 2-5 sentences
- Example: "Analyzed task to implement hello world. Determined we need a simple TypeScript function..."

**Planner Summary:**
- Mentions: build plan (wave count), approach
- Length: 2-5 sentences
- Example: "Created initial build plan with 1 wave. Wave 1 implements hello-world.ts..."

**Wave Orchestrator Summary:**
- Mentions: waves executed, step results, what was built
- Length: 2-5 sentences
- Example: "Executed 1 wave with 1 step (hello-world.ts). Step succeeded with 1 commit."

**Verifier Summary:**
- Mentions: test results, verification outcome
- Length: 2-5 sentences
- Example: "Verified hello-world.ts compiles successfully. All checks passing."

**PR Author Summary:**
- Mentions: PR created or skipped
- Length: 1-3 sentences
- Example: "Skipped PR creation (pushOnComplete was false)."

#### 4. Variable System
- ✅ Agents set variables via `## Variables` section
- ✅ Variables used in flow control (while/if conditions)
- ✅ Variable interpolation works (`${variable}`)

#### 5. Flow Control
- ✅ While loops execute based on conditions
- ✅ If conditions control phase execution
- ✅ Max iterations enforced (safety limit)

---

## Comparison with Legacy Flow

| Aspect | Legacy (TypeScript) | YAML Flow |
|--------|-------------------|------------|
| **Deliverables only** | ✅ PR URL, branch, commits | ✅ All of above + summaries |
| **Agent output** | Structured JSON (hidden) | ✅ Free-text summaries (visible) |
| **Flow definition** | Hardcoded in tdd.ts | ✅ YAML file (tdd.yaml) |
| **Modifiability** | Requires TypeScript | ✅ Edit YAML |
| **Observability** | Journal events only | ✅ Summaries + journal |
| **Testing** | Full integration | ✅ Full integration |

---

## Expected Behavior

### Before (Legacy Flow)
```json
{
  "success": true,
  "run_id": "...",
  "pi_coding_run_id": "...",
  "pr_url": "https://github.com/...",
  "branch": "feat/hello-world",
  "commits": [...]
}
```

### After (YAML Flow)
```json
{
  "success": true,
  "run_id": "...",
  "pi_coding_run_id": "...",
  "summaries": {
    "analyst": "Analyzed task...",
    "planner": "Created plan...",
    "wave-orchestrator": "Executed...",
    "verifier": "Verified...",
    "pr-author": "Created PR..."
  },
  "deliverables": {
    "pr_url": "...",
    "branch": "...",
    "commits": [...]
  }
}
```

**Key Addition**: The `summaries` object gives full visibility into what each agent did!

---

## Running the Tests

### Prerequisites

1. Druppie backend running
2. MCP servers configured
3. Test database available
4. Gitea instance running

### Quick Test (Recommended First)

```bash
# 1. Run the smoke test (quick validation)
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-flow-smoke-test"}'
```

### Full Test

```bash
# 2. Run the comprehensive tool test
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-tdd-flow-summarize-results"}'
```

### Agent Test (Real LLM)

```bash
# 3. Run with real developer agent
curl -X POST http://localhost:8001/api/evaluations/run-tests \
  -H "Content-Type: application/json" \
  -d '{"test_name": "yaml-flow-agent-summaries"}'
```

---

## Test Results Interpretation

### Success Criteria

**Smoke Test:**
- ✅ Tool result contains "summaries" key
- ✅ All 5 agent summaries present
- ✅ Each summary non-empty
- ✅ Explore flow still works

**Comprehensive Test:**
- ✅ All smoke test criteria
- ✅ Each summary follows format guidelines
- ✅ Summaries explain what agents did
- ✅ Deliverables included

**Agent Test:**
- ✅ Developer agent uses flow=tdd
- ✅ All summaries properly formatted
- ✅ Judge validates summary quality
- ✅ Real LLM produces good summaries

### Failure Diagnosis

If tests fail:

1. **"summaries key missing"**
   - Check that execute_coding_task_pi.py was updated
   - Verify `PI_AGENT_USE_YAML_FLOW` is not required (automatic)

2. **"Agent summary empty"**
   - Check agent .md files have `## Summary` section
   - Verify agents are producing summaries

3. **"Flow validation failed"**
   - Check .pi/flows/tdd.yaml syntax
   - Verify YAML parser is using js-yaml

4. **"TypeScript compilation failed"**
   - Run `npm run build` in pi_agent directory
   - Check for type errors

---

## Continuous Integration

### CI/CD Pipeline

```yaml
# .github/workflows/test-yaml-flow.yml
name: Test YAML Flow

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      - name: Install dependencies
        run: |
          cd pi_agent
          npm install
          npm run build
      - name: Run component tests
        run: |
          cd pi_agent
          npm run build
          node dist/test-yaml-flow.js
      - name: Start Druppie
        run: docker compose up -d
      - name: Run smoke test
        run: |
          curl -X POST http://localhost:8001/api/evaluations/run-tests \
            -H "Content-Type: application/json" \
            -d '{"test_name": "yaml-flow-smoke-test"}'
```

---

## Known Limitations

1. **Sandbox Operations**: Tests use `mock: true` to skip sandbox operations
2. **LLM Calls**: Most tests use mock results to save time
3. **Git Operations**: Push/PR not actually executed (mocked)
4. **Performance**: No benchmarking vs legacy flow yet

### Full E2E Test (Future)

To test with real operations:
1. Remove `mock: true` from tool calls
2. Set real LLM API keys
3. Enable sandbox infrastructure
4. Allow git push operations
5. Run on real repository

---

## Maintenance

### Adding New Tests

1. Create new YAML file in `testing/tools/` or `testing/agents/`
2. Follow existing patterns (see examples)
3. Tag appropriately: `[yaml-flow]`, `[tdd]`, `[summaries]`
4. Include assertions for validation

### Updating Tests

When YAML flow evolves:
1. Update agent summary format in tests
2. Add new agents to summary checks
3. Update tool result format validation
4. Keep tests in sync with implementation

---

## Summary

✅ **3 integration tests created**
- 1 smoke test (quick validation)
- 1 comprehensive tool test (full validation)
- 1 agent test (real LLM)

✅ **Ready to run**
- Via UI or API
- Mock mode for speed
- Real agent test available

✅ **Validates key features**
- Agent summaries returned
- All 5 agents included
- Proper formatting
- Deliverables included
- Backwards compatible

The YAML flow system integration tests are complete and ready for execution! 🎉
