# TDD Workflow Documentation

## Overview

The Test-Driven Development (TDD) workflow implementation provides a comprehensive framework for automated testing within the Druppie platform. This documentation covers the architecture, components, configuration, and usage of the TDD system.

## Architecture

### Component Diagram

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Planner Agent │    │   Builder Agent │    │   Tester Agent  │
│   (creates TDD  │───▶│   (implements   │───▶│   (validates    │
│    workflow)    │    │    code)        │    │    tests)       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                      │                       │
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 Main Execution Loop                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │            TDD Integration Module                   │    │
│  │  • Parses test results                              │    │
│  │  • Determines retry logic                           │    │
│  │  • Generates builder retry steps                    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         │                      │                       │
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Coding MCP     │    │  Testing MCP    │    │  Frontend UI    │
│  Server         │    │  Server         │    │  Components     │
│  • run_tests()  │    │  • test suites  │    │  • TestResultCard│
│  • file ops     │◀──▶│  • coverage     │    │  • WorkflowEvent│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Components

### 1. Testing MCP Server (`druppie/mcp-servers/testing/`)

Standalone MCP server for test execution:

- **`server.py`**: FastAPI server with test execution endpoints
- **`module.py`**: Test execution logic with framework detection
- **`requirements.txt`**: Dependencies for test execution
- **`Dockerfile`**: Containerization for microservice deployment

### 2. Frontend Components

- **`TestResultCard.jsx`**: Rich visualization of test results with statistics, coverage, and feedback
- **`WorkflowEvent.jsx`**: Updated to render TestResultCard for test events
- **`eventUtils.jsx`**: Extended with test event types, icons, and styling

## Configuration

TDD configuration is handled through agent YAML definitions and the Testing MCP server. The planner agent defines retry limits (default: 3 attempts), and the tester agent defines coverage thresholds and framework-specific settings.

### Project Type Detection

The Testing MCP server automatically detects project types:
- **Python**: `pyproject.toml`, `requirements.txt`, `setup.py`
- **Frontend**: `package.json` with React/Vue/Angular dependencies
- **Node.js**: `package.json` with Node.js runtime
- **Go**: `go.mod`, `.go` files

### Frontend Integration

Test results automatically appear in the chat with the `TestResultCard` component.

## Workflow Examples

### Successful TDD Workflow

```
1. Planner creates TDD workflow with builder → tester steps
2. Builder implements feature
3. Tester runs tests → PASS with 85% coverage
4. System continues to next step
```

### Failed Test with Retry

```
1. Builder implements feature
2. Tester runs tests → FAIL with 3 failed tests
3. System parses feedback, determines retry needed
4. Creates builder retry step with feedback
5. Builder fixes issues (attempt 2/3)
6. Tester runs tests → PASS
7. System continues
```

### Coverage Below Threshold

```
1. Builder implements feature
2. Tester runs tests → PASS with 65% coverage
3. System continues (coverage warning logged)
4. Optional: Can configure retry_on_low_coverage=true
```

## Test Frameworks Supported

| Framework | Command | Coverage Tool | Min Version |
|-----------|---------|---------------|-------------|
| **Pytest** | `pytest` | pytest-cov | 7.4.0 |
| **Vitest** | `npm test -- --run` | @vitest/coverage-v8 | 1.1.0 |
| **Jest** | `npm test` | jest | 29.0.0 |
| **Playwright** | `npx playwright test` | - | 1.40.0 |
| **Go Test** | `go test ./...` | go test -cover | 1.21 |

## Event Types

The system creates these event types in the timeline:

- `test_started`: Test execution began
- `test_completed`: Test execution completed
- `test_result`: Test results available (renders TestResultCard)
- `tdd_validation`: TDD validation step
- `test_passed`: Tests passed
- `test_failed`: Tests failed

## Error Handling

### Common Error Scenarios

1. **Test Framework Not Detected**
   - System falls back to default framework
   - Logs warning with detection details

2. **Coverage Report Missing**
   - If `require_coverage=true`, validation fails
   - If `require_coverage=false`, continues with warning

3. **Test Execution Timeout**
   - Configurable timeout (default: 300 seconds)
   - Can retry on timeout (`retry_on_timeout=true`)

4. **Maximum Retries Exceeded**
   - Workflow fails with descriptive error
   - All retry attempts logged

### Logging

TDD components use structured logging with these keys:
- `tdd_processing_started`: TDD processing began
- `tdd_processing_completed`: TDD processing completed
- `tdd_config_loaded`: Configuration loaded
- `test_framework_detected`: Test framework detected
- `coverage_validation`: Coverage validation result

## Troubleshooting

### Common Issues

1. **Tests Not Running**
   - Check MCP server connectivity
   - Verify workspace permissions
   - Check test framework installation

2. **Coverage Not Reported**
   - Verify coverage tool installation
   - Check test output format

3. **Retry Not Triggering**
   - Check planner agent retry instructions
   - Verify tester agent PASS/FAIL output format

4. **Frontend Not Rendering**
   - Verify TestResultCard import
   - Check browser console for errors

### Debugging

Check MCP server logs:

```bash
docker logs druppie-mcp-coding
```