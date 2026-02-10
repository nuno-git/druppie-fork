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

### 1. TDD Workflow Handler (`druppie/workflow/tdd_workflow.py`)

Core logic for TDD workflow processing:

- **`parse_test_result()`**: Parses tester agent output for PASS/FAIL verdict, test statistics, and coverage
- **`is_validation_step()`**: Identifies tester validation steps in workflow
- **`determine_tdd_next_action()`**: Decides next action (continue/retry/fail) based on test results
- **`generate_builder_retry_step()`**: Creates builder retry steps with tester feedback
- **`validate_tdd_workflow_result()`**: Validates test results against thresholds
- **`handle_tdd_workflow_step()`**: Main entry point for workflow step handling

### 2. TDD Configuration (`druppie/config/tdd_config.py`)

Configuration management using Pydantic Settings:

- **Framework Settings**: Test framework commands and versions (Pytest, Vitest, Jest, Playwright, Go Test)
- **Coverage Settings**: Thresholds per project type (Python: 80%, Frontend: 70%, etc.)
- **Retry Settings**: Retry logic configuration (max retries, delays, backoff)
- **Workflow Settings**: TDD workflow behavior and validation settings

### 3. Testing MCP Server (`druppie/mcp-servers/testing/`)

Standalone MCP server for test execution:

- **`server.py`**: FastAPI server with test execution endpoints
- **`module.py`**: Test execution logic with framework detection
- **`requirements.txt`**: Dependencies for test execution
- **`Dockerfile`**: Containerization for microservice deployment

### 4. Frontend Components

- **`TestResultCard.jsx`**: Rich visualization of test results with statistics, coverage, and feedback
- **`WorkflowEvent.jsx`**: Updated to render TestResultCard for test events
- **`eventUtils.jsx`**: Extended with test event types, icons, and styling

### 5. TDD Integration (`druppie/workflow/tdd_integration.py`)

Integration layer for main execution loop:

- **`TDDIntegration` class**: Main integration class
- **`process_tdd_output()`**: Processes tester agent output
- **`create_test_event()`**: Creates timeline events for test results
- **`get_tdd_retry_config()`**: Retrieves retry configuration

## Configuration

### Environment Variables

```bash
# TDD Enable/Disable
TDD_WORKFLOW_ENABLE_TDD=true

# Coverage Thresholds
TDD_COVERAGE_DEFAULT_THRESHOLD=80.0
TDD_COVERAGE_PYTHON_THRESHOLD=80.0
TDD_COVERAGE_FRONTEND_THRESHOLD=70.0
TDD_COVERAGE_NODEJS_THRESHOLD=75.0
TDD_COVERAGE_GO_THRESHOLD=85.0

# Retry Configuration
TDD_RETRY_MAX_RETRIES=3
TDD_RETRY_INITIAL_DELAY=5
TDD_RETRY_MAX_DELAY=30
TDD_RETRY_BACKOFF_FACTOR=2.0

# Framework Commands
TDD_FRAMEWORK_PYTEST_COMMAND=pytest
TDD_FRAMEWORK_PYTEST_COVERAGE_COMMAND=pytest --cov --cov-report=json
TDD_FRAMEWORK_VITEST_COMMAND=npm test -- --run
TDD_FRAMEWORK_VITEST_COVERAGE_COMMAND=npm test -- --run --coverage
```

### Project Type Detection

The system automatically detects project types:
- **Python**: `pyproject.toml`, `requirements.txt`, `setup.py`
- **Frontend**: `package.json` with React/Vue/Angular dependencies
- **Node.js**: `package.json` with Node.js runtime
- **Go**: `go.mod`, `.go` files

## Usage

### 1. Basic Integration

```python
from druppie.workflow.tdd_integration import process_tdd_output

# Process tester agent output
result = process_tdd_output(
    agent_id="tester",
    agent_output=tester_output,
    session_id=session_id,
)

if result["processed"] and result["should_retry"]:
    retry_step = result["retry_step"]
    # Schedule builder retry step
```

### 2. Manual Test Result Parsing

```python
from druppie.workflow.tdd_workflow import parse_test_result

parsed = parse_test_result(tester_output)
print(f"Verdict: {parsed['verdict']}")
print(f"Tests: {parsed['summary']['passed']}/{parsed['summary']['total']} passed")
print(f"Coverage: {parsed.get('coverage', 'N/A')}%")
```

### 3. Configuration Access

```python
from druppie.config.tdd_config import (
    get_tdd_settings,
    get_max_retries,
    get_coverage_threshold,
)

settings = get_tdd_settings()
max_retries = get_max_retries()
threshold = get_coverage_threshold("python")
```

### 4. Frontend Integration

Test results automatically appear in the workflow timeline with the `TestResultCard` component. Test events have category "test" and use teal styling.

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

## Testing

### Unit Tests

Run the comprehensive test suite:

```bash
python test_tdd_workflow.py
```

### Test Coverage

The test suite covers:
- Test result parsing
- Configuration loading
- Integration logic
- Workflow step handling
- End-to-end simulation

### Manual Testing

1. **Test Result Parsing**: Verify different output formats
2. **Configuration**: Test environment variable overrides
3. **Frontend**: Verify TestResultCard rendering
4. **Integration**: Test with mock agent outputs

## Performance Considerations

### Optimizations

1. **Cached Settings**: TDD settings are cached with `@lru_cache`
2. **Lazy Loading**: Components load only when needed
3. **Minimal Dependencies**: Standalone modules with minimal imports
4. **Async Processing**: Designed for async execution environments

### Resource Usage

- **Memory**: Minimal (configuration objects, parsed results)
- **CPU**: Test execution is delegated to MCP servers
- **Network**: Only MCP server communication

## Security

### Input Validation

- **Agent Output**: Parsed with strict regex patterns
- **Configuration**: Validated with Pydantic
- **Event Data**: Sanitized before frontend rendering

### Access Control

- **MCP Servers**: Isolated in containers
- **Test Execution**: Runs in workspace sandbox
- **Configuration**: Environment variable based

## Monitoring

### Metrics to Track

1. **Test Success Rate**: Percentage of passing tests
2. **Average Coverage**: Mean coverage across projects
3. **Retry Frequency**: How often retries occur
4. **Test Execution Time**: Duration of test runs
5. **Framework Usage**: Distribution of test frameworks

### Alerting

Configure alerts for:
- Consistently low coverage (< 50%)
- High retry frequency (> 50% of workflows)
- Test timeouts
- Framework detection failures

## Troubleshooting

### Common Issues

1. **Tests Not Running**
   - Check MCP server connectivity
   - Verify workspace permissions
   - Check test framework installation

2. **Coverage Not Reported**
   - Verify coverage tool installation
   - Check coverage command configuration
   - Review test output format

3. **Retry Not Triggering**
   - Check `max_retries` configuration
   - Verify test result parsing
   - Check `retry_on_test_failure` setting

4. **Frontend Not Rendering**
   - Check event type categorization
   - Verify TestResultCard import
   - Check browser console for errors

### Debugging

Enable debug logging:

```python
import structlog
structlog.configure(processors=[structlog.dev.ConsoleRenderer()])
```

Check MCP server logs:

```bash
docker logs mcp-testing
```

## Future Enhancements

### Planned Features

1. **Parallel Test Execution**: Run tests in parallel
2. **Test History**: Track test results over time
3. **Custom Test Suites**: User-defined test configurations
4. **Performance Testing**: Integration with performance tests
5. **Security Testing**: Automated security scanning

### Integration Points

1. **CI/CD Pipeline**: Direct integration with CI systems
2. **Code Quality Tools**: SonarQube, CodeClimate integration
3. **Notification Systems**: Slack, email notifications
4. **Metrics Export**: Prometheus metrics endpoint

## Conclusion

The TDD workflow implementation provides a robust, configurable system for automated testing within Druppie. It supports multiple test frameworks, provides rich visualization, and integrates seamlessly with the existing architecture while maintaining the standalone principle of not modifying working code.

The system is production-ready with comprehensive testing, detailed documentation, and clear upgrade paths for future enhancements.