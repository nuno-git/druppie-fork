# TDD Workflow Documentation

## Overview

The Test-Driven Development (TDD) workflow implementation provides a comprehensive framework for automated testing within the Druppie platform. This documentation covers the architecture, components, configuration, and usage of the TDD system.

## Architecture

### Component Diagram

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Planner Agent │    │ Builder Planner │    │  Test Builder   │    │  Builder Agent  │    │  Test Executor  │
│   (creates TDD  │───▶│   (creates      │───▶│   (generates    │───▶│   (implements   │───▶│   (runs tests,  │
│    workflow)    │    │    plan)        │    │    tests)       │    │    code)        │    │    fixes code)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                      │                       │                       │                       │
         │                      │                       │                       │                       │
         ▼                      ▼                       ▼                       ▼                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                 Main Execution Loop                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │  TDD Pipeline: builder_planner → test_builder → builder → test_executor (retry ≤3x) → HITL         │   │
│  │  • builder_planner creates implementation plan (builder_plan.md)                                     │   │
│  │  • test_builder writes tests (Red Phase)                                                             │   │
│  │  • builder implements code (Green Phase)                                                             │   │
│  │  • test_executor runs tests & iteratively fixes (internal retry loop)                                │   │
│  │  • On FAIL: planner retries builder → test_executor (up to 3x)                                      │   │
│  │  • After 3 failures: HITL escalation (continue/deploy/abort)                                         │   │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Coding MCP     │    │  test_report    │    │  Frontend UI    │
│  Server         │    │  builtin tool   │    │  Components     │
│  • run_tests()  │    │  • iteration    │    │  • TestResultCard│
│  • file ops     │    │    tracking     │    │  • WorkflowEvent│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Agent Responsibilities

| Agent | Phase | Responsibility |
|-------|-------|---------------|
| **builder_planner** | Plan | Reads design docs, creates `builder_plan.md` with code standards, test strategy, solution approach, change approach. |
| **test_builder** | Red (Write Tests) | Generates comprehensive test suites based on design docs and builder_plan.md. Sets up test framework. Does NOT run tests. |
| **builder** | Green (Implement) | Reads tests, implements source code to pass them. Commits implementation. Handles TDD retries on failure. |
| **test_executor** | Green/Refactor (Run & Fix) | Runs tests, diagnoses failures, applies fixes, re-runs. Internal retry loop with strategy rotation. |

### Flow

```
architect → builder_planner → test_builder → builder → test_executor (internal: run → fix → run → ...)
  → PASS: deployer
  → FAIL (retry < 3): builder (TDD RETRY) → test_executor
  → FAIL (retry >= 3): HITL escalation → user decides:
      → "Continue with instructions": builder (with guidance) → test_executor
      → "Deploy with warning": deployer
      → "Abort": summarizer
```

Previous flow (deprecated):
```
architect → test_builder → builder → test_executor
  → PASS: deployer
  → FAIL (gave up): deployer with warning
```

## Components

### 1. Builder Planner Agent (`agents/definitions/builder_planner.yaml`)

Creates detailed implementation plans before test generation begins:
- Reads functional_design.md and technical_design.md
- Writes builder_plan.md with code standards, test framework, test strategy, solution strategy, and change approach
- Guides downstream test_builder and builder agents

### 2. Test Builder Agent (`agents/definitions/test_builder.yaml`)

Generates tests before any implementation exists:
- Reads functional_design.md and technical_design.md
- Detects or sets up test framework
- Writes comprehensive test files covering all requirements
- Does NOT run tests (Red Phase — tests are expected to fail)

### 3. Builder Agent (`agents/definitions/builder.yaml`)

Implements code to make tests pass:
- Reads test files to understand requirements
- Implements source code
- Commits and pushes implementation

### 4. Test Executor Agent (`agents/definitions/test_executor.yaml`)

Runs tests and iteratively fixes code:
- Internal retry loop (no planner round-trips)
- Error classification: assertion_failure, missing_function, import_error, type_error, syntax_error, configuration_error, environment_error, test_error
- Fix strategies: fix_implementation, fix_test, fix_imports, fix_configuration, add_dependency, refactor_approach
- Strategy rotation: switches strategy after 2 consecutive failures with same strategy
- Reports via `test_report` builtin tool

### 5. test_report Builtin Tool

Structured reporting tool used by test_executor:
- Tracks iteration number, pass/fail status, changed files
- Records error classification and fix strategy
- Data automatically stored as ToolCall records

### 6. Frontend Components

- **`TestResultCard.jsx`**: Rich visualization of test results with statistics, coverage, and feedback
- **`WorkflowEvent.jsx`**: Updated to render TestResultCard for test events
- **`agentConfig.js`**: Contains `test_builder` and `test_executor` agent display config

## Configuration

TDD configuration is handled through agent YAML definitions and the Coding MCP server. The test_executor agent defines coverage thresholds and fix strategies.

### Project Type Detection

The Coding MCP server automatically detects project types:
- **Python**: `pyproject.toml`, `requirements.txt`, `setup.py`
- **Frontend**: `package.json` with React/Vue/Angular dependencies
- **Node.js**: `package.json` with Node.js runtime
- **Go**: `go.mod`, `.go` files

### Frontend Integration

Test results automatically appear in the chat with the `TestResultCard` component.

## Workflow Examples

### Successful TDD Workflow

```
1. Planner plans builder_planner after architect approval
2. Builder planner reads design docs, writes builder_plan.md
3. Planner plans test_builder
4. Test builder generates tests based on builder_plan.md (Red Phase)
5. Planner plans builder
6. Builder implements code
7. Planner plans test_executor
8. Test executor runs tests → PASS on first try
9. Planner plans deployer
```

### Failed Test with Internal Retry (test_executor level)

```
1. Test executor runs tests → 3 of 12 fail
2. Test executor classifies errors (import_error)
3. Test executor applies fix_imports strategy
4. Test executor commits fix, calls test_report(iteration=1)
5. Test executor re-runs tests → 1 of 12 fails
6. Test executor classifies error (assertion_failure)
7. Test executor applies fix_implementation strategy
8. Test executor commits fix, calls test_report(iteration=2)
9. Test executor re-runs tests → PASS
10. Test executor calls done() with PASS verdict
```

### TDD Retry Flow (planner level, up to 3x)

```
1. Test executor gives up → FAIL (attempt 1)
2. Planner counts "## TEST RESULT: FAIL" = 1, retry < 3
3. Planner plans builder with TDD RETRY and failure feedback
4. Builder makes targeted fixes based on failure details
5. Planner plans test_executor
6. Test executor runs tests → PASS
7. Planner plans deployer
```

### HITL Escalation Flow (after 3 failures)

```
1. Test executor gives up → FAIL (attempt 3)
2. Planner counts "## TEST RESULT: FAIL" = 3, retry >= 3
3. Planner plans developer with HITL escalation
4. Developer asks user via hitl_ask_multiple_choice_question:
   - "Doorgaan met specifieke instructies"
   - "Toch deployen met waarschuwing"
   - "Project afbreken"
5a. User chooses "continue": builder retries with user guidance → test_executor
5b. User chooses "deploy": deployer deploys with warning
5c. User chooses "abort": summarizer ends workflow
```

### Test Executor Gives Up (single attempt detail)

```
1. Test executor runs tests → 4 fail
2. Iterations 1-5: fix_implementation strategy (2 tests fixed, 2 remain)
3. Iterations 6-7: fix_configuration strategy (no progress)
4. Iteration 8: gives up after no progress
5. Test executor calls done() with FAIL verdict
6. Planner evaluates retry count and decides next action
```

## Test Frameworks Supported

| Framework | Command | Coverage Tool | Min Version |
|-----------|---------|---------------|-------------|
| **Pytest** | `pytest` | pytest-cov | 7.4.0 |
| **Vitest** | `npm test -- --run` | @vitest/coverage-v8 | 1.1.0 |
| **Jest** | `npm test` | jest | 29.0.0 |
| **Playwright** | `npx playwright test` | - | 1.40.0 |
| **Go Test** | `go test ./...` | go test -cover | 1.21 |

## Error Handling

### Common Error Scenarios

1. **Test Framework Not Detected**
   - System falls back to default framework
   - Logs warning with detection details

2. **Coverage Report Missing**
   - Test executor still reports PASS if all tests pass
   - Coverage noted as "unavailable" in summary

3. **Maximum Iterations Exhausted**
   - Test executor stops with FAIL verdict
   - Deployer deploys with warning about test failures

4. **Strategy Rotation**
   - After 2 consecutive failures with same strategy, switches to different strategy
   - Tries at least 2 different strategies before giving up

### Logging

TDD components use structured logging with these keys:
- `test_report`: Test iteration report recorded
- `test_framework_detected`: Test framework detected
- `coverage_validation`: Coverage validation result
