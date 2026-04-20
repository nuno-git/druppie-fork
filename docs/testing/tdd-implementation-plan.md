# TDD Implementation Plan - Builder & Test Agents

> **⚠️ Superseded (2026-04-20).** The TDD flow has been moved entirely to
> OpenCode sandbox agents. `test_builder` and `test_executor` have been
> removed; the builder now owns the full TDD cycle via three OpenCode agents
> (`druppie-test-writer`, `druppie-implementer`, `druppie-test-runner`) called
> through `execute_coding_task`. See `docs/testing/tdd-workflow.md` for the
> current architecture. The content below describes the original design and
> is kept for historical context.

## Overview

This document combines the detailed implementation plan for the TDD agents (builder_planner, test_builder, builder, test_executor) with the follow-up standalone architecture plan. It provides a complete roadmap for implementing Test-Driven Development (TDD) workflows in the Druppie project.

---

## Part 1: TDD Agent Implementation - Framework-Specific Actionable Steps

### Project Context & Framework Versions

#### Current Stack

| Component | Version | Documentation URL |
|-----------|--------|------------------|
| **Python** | 3.11+ | https://docs.python.org/3.11/ |
| **Pytest** | 7.4.0+ | https://docs.pytest.org/en/7.4.x/ |
| **Pytest-asyncio** | 0.23.0+ | https://pytest-asyncio.readthedocs.io/ |
| **Vite** | 5.0.0 | https://vitejs.dev/ |
| **Vitest** | 1.1.0 | https://vitest.dev/ |
| **React** | 18.2.0 | https://react.dev/ |
| **React Testing Library** | - | https://testing-library.com/react |
| **Playwright** | 1.40.0 | https://playwright.dev |
| **FastAPI** | 0.109.0+ | https://fastapi.tiangolo.com/ |
| **SQLAlchemy** | 2.0.0+ | https://docs.sqlalchemy.org/en/20/ |
| **Pydantic** | 2.5.0+ | https://docs.pydantic.dev/ |

#### Existing Components

1. **TDD Agent Definitions** - `druppie/agents/definitions/`
   - `builder_planner.yaml` - Creates implementation plans (builder_plan.md)
   - `test_builder.yaml` - Test generation (Red Phase)
   - `test_executor.yaml` - Test execution and iterative fixing (Green Phase)
   - MCP tools defined per agent

2. **Coding MCP Server** - `druppie/mcp-servers/coding/server.py` (221 lines)
   - `run_tests` tool present but basic
   - Support for file operations, git, commands

3. **Main Loop** - `druppie/core/loop.py` (2000+ lines)
   - Workflow execution engine
   - Agent orchestration
   - Missing: TDD retry logic, test result parsing

#### Integration Points

```
Planner Agent
    ↓ (Generates plan: builder_planner → test_builder → builder → test_executor)
Main Loop (execute_workflow_steps)
    ↓ (Run agents in sequence)
Builder Planner (builder_planner.yaml) → creates builder_plan.md
    ↓
Test Builder (test_builder.yaml) → generates tests
    ↓
Builder (builder.yaml) → implements code
    ↓
Test Executor (test_executor.yaml) → runs tests with internal retry loop
    ↓ (Uses MCP tools + test_report builtin)
Coding MCP (server.py/module.py)
    ↓ (Executes tests)
Result: PASS/FAIL
    ↓ (Back to Planner)
Planner: PASS → deploy
         FAIL (< 3x) → builder retry → test_executor
         FAIL (>= 3x) → HITL escalation → user decides
```

---

## Part 2: Implementation Tasks Summary

### Completed Tasks (Phase 1: Foundation & MCP Server)

1. **TDD Agent Definitions** - COMPLETED ✅
   - builder_planner.yaml: Implementation planning (builder_plan.md)
   - test_builder.yaml: Framework-specific test generation guidelines (Pytest, Vitest, Jest, Playwright)
   - test_executor.yaml: Iterative test execution with strategy rotation and PASS/FAIL reporting
   - builder.yaml: Updated with TDD retry scenario support
   - test_report builtin tool for structured iteration tracking

2. **Coding MCP Server Module** - COMPLETED ✅
   - Enhanced `run_tests()` with coverage, verbose, framework parameters
   - Framework detection with version requirements and doc URLs
   - Test output parsing for vitest, jest, pytest, playwright, gotest
   - Coverage JSON parsing for v8 (vitest/jest) and pytest formats
   - New `get_test_framework()` and `get_coverage_report()` methods

3. **Planner Agent TDD Workflow** - COMPLETED ✅
   - Added builder_planner, test_builder, builder, test_executor to AVAILABLE AGENTS
   - TDD workflow for CREATE_PROJECT and UPDATE_PROJECT
   - TDD retry mechanism (up to 3x) with HITL escalation

### Pending Tasks (Phase 2: Standalone Integration)

4. ~~**TDD Workflow Handler Module**~~ - REMOVED (logic handled by agents + MCP servers)

5. ~~**TDD Configuration Module**~~ - REMOVED (configuration handled by agent YAMLs + MCP servers)

6. ~~**Testing MCP Server**~~ - REMOVED (testing tools integrated into Coding MCP server + test_report builtin)

7. **Frontend Test Result UI Components** - STANDALONE NEW FILES ⏳
   - `frontend/src/components/chat/TestResultCard.jsx` (NEW)
   - Test result visualization components

8. **Documentation Files** - STANDALONE NEW FILES ⏳
   - `docs/testing/tdd-workflow.md` (NEW)
   - `docs/testing/framework-guide.md` (NEW)

---

## Part 3: Alignment with User Story Requirements

### User Story Requirements vs. Implementation Plan

**User Story Requirements:**
1. ✅ Four separate agents: Builder Planner, Test Builder, Builder, and Test Executor
2. ✅ Builder and Test Executor interact via internal fix-loop (no planner round-trips)
3. ✅ Test Executor validates functional & technical requirements
4. ✅ Test Builder generates tests with comprehensive coverage goal
5. ✅ Follows Test Driven Development (TDD): Plan (builder_planner) → Red (test_builder) → Green (builder + test_executor)
6. ✅ Automatic internal retry in Test Executor with strategy rotation
7. ✅ Max iterations in test_executor (100), strategy rotation after 2 failures
8. ✅ Explicit Pass/Fail result with justification via test_report builtin tool
9. ✅ Test Executor determines build quality for acceptance
10. ✅ Planner agent directs builder_planner, test_builder, builder, and test_executor
11. ✅ Coding MCP extended with build/test commands
12. ✅ Builder Planner creates detailed implementation plans (builder_plan.md)
13. ✅ TDD retry mechanism: planner retries builder → test_executor up to 3 times on failure
14. ✅ HITL escalation after 3 failures: user chooses continue/deploy/abort

**Implementation Plan Coverage:**
- **Framework Support**: Python/Pytest, Frontend/Vitest, Node.js/Jest, E2E/Playwright
- **Coverage Analysis**: 80% threshold for new code, 50% minimum
- **Retry Logic**: Configurable max retries (default: 3)
- **Output Format**: Structured PASS/FAIL with detailed feedback
- **Integration**: Standalone modules, no modifications to existing working code
- **MCP Tools**: Enhanced coding MCP with test execution tools + test_report builtin

### Missing from User Story but Addressed in Plan:
1. **Framework Detection**: Auto-detection of test frameworks
2. **Coverage Tool Integration**: Pytest-cov, @vitest/coverage-v8
3. **Documentation URLs**: Framework-specific documentation links
4. **Frontend UI Components**: Test result visualization
5. **Standalone Architecture**: No modifications to existing working code

### Next Steps:
1. Create directory structure for new modules
2. Implement Phase 2 standalone modules
3. Add integration to main loop (import-based, no modifications)
4. Test end-to-end TDD workflow
5. Update user story with completed implementation details

---

## Part 4: Implementation Order

### Phase 1: Foundation (COMPLETED ✅)
1. ✅ Test Builder + Test Executor agent definitions (split from single Tester)
2. ✅ Coding MCP server module
3. ✅ Coding MCP server tools
4. ✅ Planner agent TDD workflow (updated for test_builder → builder → test_executor)
5. ✅ test_report builtin tool for structured iteration tracking

### Phase 2: Standalone Integration (PENDING)
5. ~~TDD workflow handler module~~ - REMOVED
6. ~~TDD configuration module~~ - REMOVED
7. ~~Testing MCP server~~ - REMOVED (integrated into coding MCP)
8. ⏳ Frontend test result UI
9. ⏳ Documentation updates

### Phase 3: Testing & Validation (PENDING)
10. ⏳ Unit tests for TDD helpers
11. ⏳ Integration tests for testing MCP
12. ⏳ E2E TDD workflow tests

---

## Conclusion

The implementation addresses all user story requirements. TDD logic is handled by the agent definitions (planner, builder_planner, test_builder, builder, test_executor YAMLs) and the Coding MCP server, without redundant Python abstraction layers. The removed `tdd_workflow.py`, `tdd_config.py`, and `tdd_integration.py` modules were never integrated into the main loop and duplicated logic already present in agents and MCP servers.