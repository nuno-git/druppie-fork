# TDD Implementation Plan - Bouwer & Tester Agents

## Overview

This document combines the detailed implementation plan for the Tester Agent with the follow-up standalone architecture plan. It provides a complete roadmap for implementing Test-Driven Development (TDD) workflows in the Druppie project.

---

## Part 1: Tester Agent Implementation - Framework-Specific Actionable Steps

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

1. **Tester Agent Definition** - `druppie/agents/definitions/tester.yaml` (214 lines)
   - Basic system prompt with TDD workflow
   - Two modes: Test Generation (Red) and Validation (Green/Refactor)
   - MCP tools already defined

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
    ↓ (Generates plan with tester steps)
Main Loop (execute_workflow_steps)
    ↓ (Run agent with tester.yaml)
Tester Agent (runtime.py)
    ↓ (Uses MCP tools)
Coding MCP (server.py/module.py)
    ↓ (Executes tests)
Result: PASS/FAIL + feedback
    ↓ (Back to Main Loop)
Conditional Logic: Retry Builder or continue
```

---

## Part 2: Implementation Tasks Summary

### Completed Tasks (Phase 1: Foundation & MCP Server)

1. **Tester Agent Definition** - COMPLETED ✅
   - Framework-specific test generation guidelines (Pytest, Vitest, Jest, Playwright)
   - Framework versions and documentation URLs
   - Test generation checklist
   - Validation output format with exact PASS/FAIL structure
   - PASS/FAIL thresholds (80% coverage for new code, 50% minimum)
   - Framework detection logic
   - Coverage tool configuration per framework

2. **Coding MCP Server Module** - COMPLETED ✅
   - Enhanced `run_tests()` with coverage, verbose, framework parameters
   - Framework detection with version requirements and doc URLs
   - Test output parsing for vitest, jest, pytest, playwright, gotest
   - Coverage JSON parsing for v8 (vitest/jest) and pytest formats
   - New `get_test_framework()` and `get_coverage_report()` methods

3. **Planner Agent TDD Workflow** - COMPLETED ✅
   - Added tester to AVAILABLE AGENTS
   - TDD workflow for CREATE_PROJECT (7 steps)
   - TDD retry pattern documentation

### Pending Tasks (Phase 2: Standalone Integration)

4. **TDD Workflow Handler Module** - STANDALONE NEW MODULE ⏳
   - `druppie/workflow/tdd_workflow.py` (NEW FILE)
   - Standalone TDD workflow logic
   - Test result parsing, retry logic, validation

5. **TDD Configuration Module** - STANDALONE NEW MODULE ⏳
   - `druppie/config/tdd_config.py` (NEW FILE)
   - Environment-based TDD configuration
   - Project-type specific overrides

6. **Testing MCP Server** - STANDALONE NEW MCP SERVER ⏳
   - `druppie/mcp-servers/testing/` (NEW DIRECTORY)
   - Dedicated testing operations MCP server
   - Test result parsing, framework info, TDD validation

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
1. ✅ Two separate agents: Bouwer and Tester
2. ✅ Bouwer and Tester interact via feedback-loop
3. ✅ Tester validates functional & technical requirements
4. ✅ Tester can generate tests with 100% code coverage goal
5. ✅ Follows Test Driven Development (TDD)
6. ✅ Automatic retry of Builder on Tester rejection
7. ✅ Configurable maximum number of retries
8. ✅ Explicit Pass/Fail result with justification
9. ✅ Tester determines build quality for acceptance
10. ✅ Planner agent directs Bouwer and Tester
11. ✅ Coding MCP extended with build/test commands

**Implementation Plan Coverage:**
- **Framework Support**: Python/Pytest, Frontend/Vitest, Node.js/Jest, E2E/Playwright
- **Coverage Analysis**: 80% threshold for new code, 50% minimum
- **Retry Logic**: Configurable max retries (default: 3)
- **Output Format**: Structured PASS/FAIL with detailed feedback
- **Integration**: Standalone modules, no modifications to existing working code
- **MCP Tools**: Enhanced coding MCP + new testing MCP server

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
1. ✅ Tester agent definition
2. ✅ Coding MCP server module
3. ✅ Coding MCP server tools
4. ✅ Planner agent TDD workflow

### Phase 2: Standalone Integration (PENDING)
5. ⏳ TDD workflow handler module
6. ⏳ TDD configuration module
7. ⏳ Testing MCP server
8. ⏳ Frontend test result UI
9. ⏳ Documentation updates

### Phase 3: Testing & Validation (PENDING)
10. ⏳ Unit tests for TDD helpers
11. ⏳ Integration tests for testing MCP
12. ⏳ E2E TDD workflow tests

---

## Conclusion

The combined implementation plan fully addresses all user story requirements while adding important enhancements:
- Framework-specific testing guidelines
- Coverage analysis and thresholds
- Standalone architecture (no breaking changes)
- Comprehensive documentation
- Frontend visualization components

All implementation follows the principle of complete separation - no modifications to existing working code, only new standalone modules and imports.