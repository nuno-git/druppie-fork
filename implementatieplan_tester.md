# Implementatieplan: Tester Agent - Volledige Uitwerking

## Overzicht

Dit document bevat een super gedetailleerd implementatieplan voor de **Tester Agent** binnen het Druppie project. De Tester Agent is verantwoordelijk voor:
1. Testgeneratie op basis van architecture/SPEC.md
2. Validatie van implementaties met expliciet PASS/FAIL oordeel
3. Feedback aan Builder Agent voor iteraties
4. Coverage analyse en rapportage

Dit plan bouwt voort op het bestaande `IMPLEMENTATIEPLAN_BUILDER_TESTER.md` en vertaalt de architectuur naar concrete implementatietaken.

---

## Project Context

### Bestaande Componenten

1. **Tester Agent Definition** - `druppie/agents/definitions/tester.yaml` (214 regels)
   - Basis systeemprompt met TDD workflow
   - Twee modes: Test Generation (Red) en Validation (Green/Refactor)
   - MCP tools al gedefinieerd

2. **Coding MCP Server** - `druppie/mcp-servers/coding/server.py` (221 regels)
   - `run_tests` tool aanwezig maar basaal
   - Ondersteuning voor file operations, git, commands

3. **Main Loop** - `druppie/core/loop.py` (2000+ regels)
   - Workflow execution engine
   - Agent orchestration
   - Mist: TDD retry logic, test result parsing

### Integratiepunten

```
Planner Agent
    ↓ (Genereert plan met tester steps)
Main Loop (execute_workflow_steps)
    ↓ (Run agent with tester.yaml)
Tester Agent (runtime.py)
    ↓ (Gebuikt MCP tools)
Coding MCP (server.py/module.py)
    ↓ (Voert tests uit)
Resultaat: PASS/FAIL + feedback
    ↓ (Terug naar Main Loop)
Conditional Logic: Retry Builder of ga door
```

---

## Implementatie Taken

---

## TASK 1: Tester Agent Definition Verfijnen

### Bestand: `druppie/agents/definitions/tester.yaml`

#### Subtask 1.1: System Prompt Uitbreiding

**Doel:** Meer gedetailleerde instructies voor testgeneratie per framework

**Te wijzigen secties:**

```yaml
TEST GENERATION GUIDELINES:

**Python Backend (Pytest):**
- Bestandsconventie: test_*.py in tests/ of root
- Teststructuur: 
  * test_*.py - test classes en functions
  * conftest.py - shared fixtures
  * pytest.ini - configuratie
- Fixture gebruik: @pytest.fixture voor setup/teardown
- Mocking: unittest.mock.patch voor externe dependencies
- Async tests: pytest-asyncio met @pytest.mark.asyncio
- Coverage: pytest --cov=. --cov-report=json --cov-report=term
- Voorbeeld patterns:
  * test_class_name_method_name - unit tests
  * test_endpoint_name - API integration tests
  * test_workflow_scenario - end-to-end scenario's

**Frontend (Vitest for Vite/React):**
- Bestandsconventie: *.test.jsx, *.test.ts, *.test.tsx
- Plaatsing: Naast componenten in src/ of tests/ directory
- Testing library imports:
  * @testing-library/react voor component rendering
  * @testing-library/jest-dom voor custom matchers
  * @testing-library/user-event voor user interactions
- Mocking: vi.mock() voor API calls en modules
- Test structuur:
  * describe('ComponentName', () => { ... })
  * it('should do something', () => { ... })
  * beforeEach/afterEach voor setup/teardown
- Snapshot tests: expect(component).toMatchSnapshot()
- Coverage: npm run test -- --coverage --reporter=json

**Node.js Backend (Jest):**
- Bestandsconventie: *.test.js, *.spec.js
- Plaatsing: tests/ directory naast src/
- Test structuur:
  * describe('FeatureName', () => { ... })
  * it('should do something', () => { ... })
- Mocking: jest.mock() voor dependencies
- API testing: supertest voor endpoint testing
- Async testing: async/await met promises
- Coverage: npm test -- --coverage --coverageReporters=json
```

#### Subtask 1.2: Test Generation Checklist Toevoegen

**Toe te voegen na "GENERATION STEPS":**

```yaml
TEST GENERATION CHECKLIST:

Before writing tests, verify:
□ Architecture.md or SPEC.md exists and is complete
□ Technology stack is clear (Python/React/Node.js)
□ Data models and API endpoints are defined
□ Edge cases are identified

Test coverage requirements:
□ All functional requirements from specs
□ Happy path scenarios (normal operations)
□ Error handling scenarios
□ Input validation (null, empty, invalid types)
□ Boundary conditions (limits, thresholds)
□ Security scenarios (unauthorized access, injection)
□ Performance edge cases (large datasets, timeouts)

Test file structure:
□ File name follows framework convention
□ Imports are correct
□ Tests are grouped logically (describe blocks)
□ Each test has clear, descriptive name
□ Tests are independent (no side effects)
□ Cleanup code present (afterEach, fixtures)
```

#### Subtask 1.3: Validation Output Format Specificeren

**Te wijzigen "OUTPUT FORMAT - CRITICAL!" sectie:**

```yaml
OUTPUT FORMAT - CRITICAL!

Your response MUST use this EXACT markdown structure:

```markdown
## TEST RESULT: PASS or FAIL

### Summary
- **Total:** X tests executed
- **Passed:** X tests
- **Failed:** X tests
- **Skipped:** X tests
- **Coverage:** X.XX% (if available)
- **Duration:** X.XX seconds

### Test Results by Category

**Unit Tests:**
- Passed: X / X
- Failed: X / X
- List failed tests with error messages

**Integration Tests:**
- Passed: X / X
- Failed: X / X
- List failed tests with error messages

### Coverage Analysis
- **Statement Coverage:** X.XX%
- **Branch Coverage:** X.XX%
- **Function Coverage:** X.XX%
- **Line Coverage:** X.XX%

Uncovered lines/files:
- File: line X, line Y
- Function: function_name (X% covered)

### Failed Tests Details
**Test Name:** test_description
- **Error:** Actual error message
- **Expected:** Expected behavior
- **Actual:** Actual behavior
- **File:** file_path:line_number
- **Stack Trace:** (if relevant)

[Repeat for each failed test]

### Verdict
**PASS** or **FAIL**

### Feedback for Builder (if FAIL)
**Critical Issues:**
- [ ] Issue 1: Description
  - What's wrong
  - How to fix
  - Code example if needed

**Coverage Gaps:**
- [ ] Missing tests for function X
- [ ] Edge cases not covered
- [ ] Error paths untested

**Recommendations:**
- Specific code changes needed
- Tests to add or modify
- Architecture considerations

### Retry Count
- **Current Attempt:** X
- **Max Retries:** X
- **Continue Retry:** YES/NO
```

**Parsing Rules:**
- Use "## TEST RESULT: PASS" or "## TEST RESULT: FAIL" for parsing
- Verdict must be in bold: **PASS** or **FAIL**
- Include retry count if provided in context
- If coverage < threshold, fail with specific coverage feedback

#### Subtask 1.4: PASS/FAIL Thresholds Configureren

**Toe te voegen na "OUTPUT FORMAT":**

```yaml
PASS/FAIL CRITERIA - Detailed:

**PASS Conditions (ALL must be true):**
1. All tests pass (0 failed tests)
2. Coverage > 80% for new code (or > 60% for existing code)
3. No critical errors (segfaults, panics, unhandled exceptions)
4. Implementation matches architecture requirements
5. Security basics present (input validation, error handling)

**FAIL Conditions (ANY will cause FAIL):**
1. One or more tests fail
2. Coverage < 50% for new code
3. Implementation missing key features from architecture
4. Critical bugs or crashes
5. Security vulnerabilities exposed
6. Code quality issues preventing deployment

**WARNING Conditions (still PASS but flag):**
1. Coverage between 50% and 80%
2. Deprecation warnings
3. Performance issues (slow tests)
4. Minor code style violations

**When Coverage Cannot Be Measured:**
- If coverage tool not available, skip coverage check
- Base verdict solely on test pass/fail results
- Note in feedback: "Coverage unavailable, skipping check"
```

#### Subtask 1.5: Framework Detection Logic Uitbreiden

**Te wijzigen "TEST FRAMEWORKS AUTO-DETECTED" sectie:**

```yaml
TEST FRAMEWORK DETECTION:

Detection Priority Order:
1. **Vitest** - Preferred for Vite/React projects
   - Detect: vite.config.js/ts exists
   - Or: package.json has "vitest" in devDependencies
   - Or: vitest.config.* exists

2. **Pytest** - Python backend
   - Detect: pytest.ini exists
   - Or: pyproject.toml has [tool.pytest]
   - Or: setup.py/cfg has pytest config
   - Or: test_*.py files present
   - Or: tests/ directory with pytest imports

3. **Jest** - Node.js backend or legacy frontend
   - Detect: jest.config.js exists
   - Or: package.json has "jest" section
   - Or: package.json has "test" script using jest
   - Or: *.test.js files present

4. **Go Test** - Go projects
   - Detect: *.go files with _test.go suffix
   - Or: go.mod exists

5. **Unknown/Custom** - Fallback
   - Ask user for clarification if unclear
   - Use run_tests with explicit command
```

#### Subtask 1.6: Coverage Tool Configuration

**Te updaten "CODE COVERAGE" sectie:**

```yaml
CODE COVERAGE COMMANDS:

**Python (Pytest):**
- Command: pytest --cov=. --cov-report=json --cov-report=term --cov-report=html
- Coverage file: coverage.json in project root
- Minimum acceptable: 80% for new code
- Exclusions (typical):
  * */tests/*
  * */migrations/*
  * */__init__.py
  * venv/*
  * .venv/*

**Frontend (Vitest):**
- Command: npm run test -- --coverage --reporter=json --reporter=terminal
- Coverage file: coverage/coverage-final.json
- Minimum acceptable: 80% for new code
- Exclusions (typical):
  * *.test.jsx
  * *.test.tsx
  * vitest.config.ts
  * tests/*
  * node_modules/*

**Node.js (Jest):**
- Command: npm test -- --coverage --coverageReporters=json --coverageReporters=text
- Coverage file: coverage/coverage-final.json
- Minimum acceptable: 80% for new code
- Exclusions (typical):
  * *.test.js
  * tests/*
  * node_modules/*
  * dist/*
  * build/*

**Go:**
- Command: go test -coverprofile=coverage.out ./...
- Coverage file: coverage.out
- Convert to %: go tool cover -func=coverage.out | tail -1
- Minimum acceptable: 70% for new code

**Coverage Parsing:**
- Read coverage JSON/file after test execution
- Calculate overall percentage
- Identify uncovered files/lines
- Report in feedback if below threshold
```

---

## TASK 2: Coding MCP Server Uitbreiden

### Bestand: `druppie/mcp-servers/coding/server.py` & `module.py`

#### Subtask 2.1: run_tests Tool Verbeteren

**Huidige implementatie (module.py):**
```python
async def run_tests(workspace_id: str, test_command: str | None = None, timeout: int = 120):
    """Run tests in the workspace and return structured results."""
    # Bestaande implementatie is waarschijnlijk basaal
```

**Nieuwe vereisten:**

1. **Auto-detection logica uitbreiden**
2. **Coverage resultaat parsing toevoegen**
3. **Gestructureerde output formatteren**
4. **Timeout handling verbeteren**
5. **Test framework specifieke opties**

**Nieuwe implementatie:**

```python
async def run_tests(
    workspace_id: str,
    test_command: str | None = None,
    timeout: int = 120,
    coverage: bool = True,
    verbose: bool = False,
) -> dict:
    """Run tests in workspace with auto-detection and coverage.
    
    Args:
        workspace_id: Workspace identifier
        test_command: Explicit test command (overrides auto-detection)
        timeout: Maximum execution time in seconds
        coverage: Whether to generate coverage report
        verbose: Enable verbose output
        
    Returns:
        Dict with:
        - success: bool
        - framework: Detected test framework
        - command: Command executed
        - exit_code: int
        - stdout: str
        - stderr: str
        - results: dict with test results (parsed if possible)
            - total: int
            - passed: int
            - failed: int
            - skipped: int
        - coverage: dict with coverage metrics (if available)
            - overall_percent: float
            - statement_percent: float
            - branch_percent: float
            - function_percent: float
            - file_coverage: list[dict] with file-level coverage
        - duration: float (seconds)
        - error: str (if error occurred)
    """
```

**Implementatie details:**

**Auto-detection functie:**
```python
def detect_test_framework(workspace_path: str) -> tuple[str, str]:
    """Detect test framework and return (framework, command).
    
    Priority:
    1. Vitest (Vite/React)
    2. Pytest (Python)
    3. Jest (Node.js)
    4. Go Test (Go)
    
    Returns:
        (framework, test_command) or ("unknown", "")
    """
    # Check for Vitest
    if (workspace_path / "vite.config.js").exists() or \
       (workspace_path / "vite.config.ts").exists() or \
       (workspace_path / "vitest.config.ts").exists():
        return "vitest", "npm run test"
    
    # Check for Pytest
    if (workspace_path / "pytest.ini").exists() or \
       (workspace_path / "pyproject.toml").exists():
        with open(workspace_path / "pyproject.toml") as f:
            if "pytest" in f.read():
                return "pytest", "pytest"
    
    # Check for Jest
    package_json = workspace_path / "package.json"
    if package_json.exists():
        data = json.loads(package_json.read_text())
        if "jest" in data.get("devDependencies", {}):
            return "jest", "npm test"
        if "vitest" in data.get("devDependencies", {}):
            return "vitest", "npm run test"
    
    # Check for Go
    if any(f.name.endswith("_test.go") for f in workspace_path.rglob("*.go")):
        return "gotest", "go test ./..."
    
    return "unknown", ""
```

**Coverage parsing per framework:**

```python
def parse_coverage_json(workspace_path: str, framework: str) -> dict | None:
    """Parse coverage JSON file based on framework.
    
    Args:
        workspace_path: Path to workspace
        framework: Detected framework name
        
    Returns:
        Coverage dict or None if not available
    """
    coverage_files = {
        "vitest": "coverage/coverage-final.json",
        "jest": "coverage/coverage-final.json",
        "pytest": "coverage.json",
    }
    
    coverage_file = workspace_path / coverage_files.get(framework, "")
    if not coverage_file.exists():
        return None
    
    try:
        with open(coverage_file) as f:
            data = json.load(f)
        
        # Vitest/Jest format
        if framework in ["vitest", "jest"]:
            total_lines = sum(f["lines"]["total"] for f in data.values())
            covered_lines = sum(f["lines"]["covered"] for f in data.values())
            return {
                "overall_percent": (covered_lines / total_lines * 100) if total_lines > 0 else 0,
                "file_coverage": [
                    {
                        "file": file_path,
                        "statement_percent": stats.get("s", {}).get("pct", 0),
                        "branch_percent": stats.get("b", {}).get("pct", 0),
                        "function_percent": stats.get("f", {}).get("pct", 0),
                        "line_percent": stats.get("l", {}).get("pct", 0),
                    }
                    for file_path, stats in data.items()
                ]
            }
        
        # Pytest format
        elif framework == "pytest":
            totals = data.get("totals", {})
            return {
                "overall_percent": totals.get("percent_covered", 0),
                "statement_percent": totals.get("num_statements_covered", 0) / totals.get("num_statements", 1) * 100,
                "branch_percent": totals.get("num_branches_covered", 0) / totals.get("num_branches", 1) * 100,
                "line_percent": totals.get("num_lines_covered", 0) / totals.get("num_lines", 1) * 100,
                "file_coverage": []
            }
        
        return None
        
    except Exception as e:
        logger.error(f"coverage_parse_error: {e}")
        return None
```

**Test result parsing per framework:**

```python
def parse_test_output(stdout: str, stderr: str, framework: str) -> dict:
    """Parse test output to extract pass/fail counts.
    
    Args:
        stdout: Standard output from test command
        stderr: Standard error from test command
        framework: Test framework name
        
    Returns:
        Dict with total, passed, failed, skipped counts
    """
    # Pytest output
    if framework == "pytest":
        # Parse: "passed, 1 failed, 2 skipped"
        import re
        match = re.search(r'(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?', stdout)
        if match:
            return {
                "total": sum(int(g) for g in match.groups() if g),
                "passed": int(match.group(1)) or 0,
                "failed": int(match.group(2)) or 0,
                "skipped": int(match.group(3)) or 0,
            }
    
    # Jest/Vitest output
    elif framework in ["jest", "vitest"]:
        # Parse: "Tests:      1 passed, 1 failed"
        import re
        match = re.search(r'Tests:\s+(\d+) (?:passed|failed)(?:,\s+(\d+) (?:passed|failed))?', stdout)
        # More complex parsing needed for Jest/Vitest output
        
    # Go test output
    elif framework == "gotest":
        # Parse: "ok      github.com/... 0.123s" or "FAIL"
        
    return {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
```

#### Subtask 2.2: Nieuwe Tool - get_test_framework

**Doel:** Expliciet framework detectie zonder tests te draaien

```python
@mcp.tool()
async def get_test_framework(workspace_id: str) -> dict:
    """Detect test framework in workspace without running tests.
    
    Returns:
        Dict with:
        - framework: Detected framework name (vitest, pytest, jest, gotest, unknown)
        - confidence: Confidence level (high, medium, low)
        - evidence: List of files/configurations that led to detection
        - test_command: Recommended test command
        - coverage_command: Recommended coverage command
    """
    workspace_path = get_workspace_path(workspace_id)
    if not workspace_path:
        return {"error": "Workspace not found"}
    
    framework, evidence, confidence = detect_test_framework_detailed(workspace_path)
    
    commands = {
        "vitest": {
            "test": "npm run test",
            "coverage": "npm run test -- --coverage --reporter=json",
        },
        "pytest": {
            "test": "pytest",
            "coverage": "pytest --cov=. --cov-report=json",
        },
        "jest": {
            "test": "npm test",
            "coverage": "npm test -- --coverage --coverageReporters=json",
        },
        "gotest": {
            "test": "go test ./...",
            "coverage": "go test -coverprofile=coverage.out ./...",
        },
    }
    
    return {
        "framework": framework,
        "confidence": confidence,
        "evidence": evidence,
        "test_command": commands.get(framework, {}).get("test", ""),
        "coverage_command": commands.get(framework, {}).get("coverage", ""),
    }
```

#### Subtask 2.3: Nieuwe Tool - get_coverage_report

**Doel:** Coverage rapport lezen en parseren zonder tests te draaien

```python
@mcp.tool()
async def get_coverage_report(workspace_id: str, framework: str | None = None) -> dict:
    """Get coverage report if available (without running tests).
    
    Args:
        workspace_id: Workspace identifier
        framework: Framework name (auto-detect if None)
        
    Returns:
        Dict with coverage metrics or error if not available
    """
    workspace_path = get_workspace_path(workspace_id)
    if not workspace_path:
        return {"error": "Workspace not found"}
    
    if not framework:
        framework, _, _ = detect_test_framework_detailed(workspace_path)
    
    coverage = parse_coverage_json(workspace_path, framework)
    
    if not coverage:
        return {"error": "No coverage report found"}
    
    return {
        "framework": framework,
        "overall_percent": coverage.get("overall_percent", 0),
        "breakdown": {
            "statement": coverage.get("statement_percent", 0),
            "branch": coverage.get("branch_percent", 0),
            "function": coverage.get("function_percent", 0),
            "line": coverage.get("line_percent", 0),
        },
        "file_coverage": coverage.get("file_coverage", []),
    }
```

#### Subtask 2.4: Module Updates

**Bestand: `druppie/mcp-servers/coding/module.py`**

**Nieuwe functies toevoegen:**

1. `detect_test_framework_detailed()` - Uitgebreide detectie met evidence
2. `parse_coverage_json()` - Coverage parsing per framework
3. `parse_test_output()` - Test output parsing per framework
4. `generate_test_command()` - Command generator met opties
5. `run_test_command()` - Helper voor test executie met timeout

---

## TASK 3: Planner Agent TDD Workflow Integratie

### Bestand: `druppie/agents/definitions/planner.yaml`

#### Subtask 3.1: TDD Workflow Steps Definiëren

**Toe te voegen aan "AVAILABLE AGENTS" en workflow instructies:**

```yaml
TDD WORKFLOW STEPS FOR CREATE_PROJECT:

Standard workflow (with testing):
1. ARCHITECT: Design architecture (architecture.md)
2. APPROVAL: Review and approve architecture
3. TESTER (GENERATION): Generate comprehensive test suite
4. BUILDER: Implement code to make tests pass
5. TESTER (VALIDATION): Run tests and validate implementation
   - If PASS: → Step 6 (Approval)
   - If FAIL: → Step 5a (Retry check)
5a. RETRY CHECK: Conditional step
   - If retry_count < max_retries: → Step 5b (Builder retry)
   - Else: → FAIL workflow
5b. BUILDER (RETRY): Fix implementation based on tester feedback
   - Then → Step 5 (Tester validation again)
6. APPROVAL: Review test results and implementation
7. DEPLOYER: Build and deploy

Total steps: 7 (with retry loop)
```

#### Subtask 3.2: Step Templates Definiëren

**Toe te voegen:**

```yaml
STEP TEMPLATES:

STEP 3 - TESTER (GENERATION):
  type: agent
  agent_id: tester
  prompt_template: |
    Generate comprehensive tests for the {project_type} project based on architecture.md.
    
    Requirements from architecture:
    {architecture_summary}
    
    Generate tests with 100% coverage goal:
    - Cover all functional requirements
    - Include edge cases and error scenarios
    - Use appropriate test framework (auto-detect or use {framework})
    - Follow {language} testing best practices
    
    Output:
    1. Test files following naming conventions
    2. Test configuration if needed (pytest.ini, vitest.config.js, etc.)
    3. Dependencies in package.json/pyproject.toml if needed
    4. Commit all test files with message "Add comprehensive tests"
  expected_output: Test suite created, committed

STEP 4 - BUILDER (IMPLEMENTATION):
  type: agent
  agent_id: builder
  prompt_template: |
    Implement the {project_type} project to make all tests pass.
    
    Context:
    - Architecture: {architecture_path}
    - Tests: {test_files}
    
    Implementation requirements:
    1. Read test files to understand requirements
    2. Implement code to satisfy all tests
    3. Follow architecture specifications
    4. Run build if needed
    5. Use batch_write_files for efficiency
    6. Commit with message "Implement {project_name}"
  expected_output: Code implemented, tests passing

STEP 5 - TESTER (VALIDATION):
  type: agent
  agent_id: tester
  prompt_template: |
    Run all tests and validate the {project_type} implementation.
    
    Instructions:
    1. Run all tests using appropriate command
    2. Generate coverage report
    3. Analyze results and determine PASS/FAIL
    4. Return structured report with:
       - Test results (passed/failed/skipped)
       - Coverage metrics
       - Explicit PASS or FAIL verdict
       - Feedback for builder if FAIL
       - Retry recommendation
    5. Use retry_count from context: {retry_count}/{max_retries}
  expected_output: Structured PASS/FAIL report

STEP 5b - BUILDER (RETRY):
  type: agent
  agent_id: builder
  prompt_template: |
    Previous implementation attempt failed. Fix the issues reported by the tester.
    
    Tester feedback:
    {tester_feedback}
    
    Retry context:
    - Attempt: {retry_count} of {max_retries}
    - Previous attempt failed at: test_name
    
    Fix requirements:
    1. Read the specific test failures
    2. Make targeted fixes (don't rewrite working code)
    3. Address all issues in feedback
    4. Re-run tests to verify fixes
    5. Commit with message "Fix test failures (attempt {retry_count})"
  expected_output: Issues fixed
```

#### Subtask 3.3: Conditional Step Logic

**Toe te voegen:**

```yaml
CONDITIONAL WORKFLOW HANDLING:

When generating plans that include testing:

1. Include retry_count variable in plan metadata:
   config:
     max_retries: 3
     retry_count: 0
     coverage_threshold: 80

2. Parse tester's validation result:
   - Look for "## TEST RESULT: PASS" or "## TEST RESULT: FAIL"
   - Extract verdict (PASS/FAIL)
   - Parse retry count from "Current Attempt: X"
   - Extract feedback for builder if FAIL

3. Conditional branching:
   if verdict == "PASS":
       → Next step (approval or deployer)
   else if verdict == "FAIL":
       if retry_count < max_retries:
           retry_count++
           → Builder (retry) step
           → Then back to Tester (validation)
       else:
           → FAIL workflow with tester feedback
```

---

## TASK 4: Main Loop Retry Mechanisme Implementeren

### Bestand: `druppie/core/loop.py`

#### Subtask 4.1: Test Result Parser Functie

**Nieuwe functie toevoegen:**

```python
def parse_test_result(result: str) -> dict:
    """Parse tester agent's test result output.
    
    Looks for:
    - ## TEST RESULT: PASS or FAIL
    - Verdict: **PASS** or **FAIL**
    - Retry count: "Current Attempt: X"
    - Summary stats (total, passed, failed)
    - Coverage percentage
    
    Args:
        result: String output from tester agent
        
    Returns:
        Dict with:
        - verdict: "PASS" or "FAIL"
        - retry_count: int (current attempt number)
        - should_retry: bool
        - summary: dict with test stats
        - coverage: float or None
        - feedback: str (if FAIL)
    """
    import re
    
    # Parse verdict from header
    verdict_match = re.search(r'## TEST RESULT:\s*(PASS|FAIL)', result, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"
    
    # Parse verdict from content (fallback)
    if not verdict_match:
        verdict_match = re.search(r'\*\*(PASS|FAIL)\*\*', result, re.IGNORECASE)
        verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"
    
    # Parse retry count
    retry_match = re.search(r'Current Attempt:\s*(\d+)', result)
    retry_count = int(retry_match.group(1)) if retry_match else 0
    
    # Parse summary stats
    total_match = re.search(r'Total:\s*(\d+)', result)
    passed_match = re.search(r'Passed:\s*(\d+)', result)
    failed_match = re.search(r'Failed:\s*(\d+)', result)
    
    summary = {
        "total": int(total_match.group(1)) if total_match else 0,
        "passed": int(passed_match.group(1)) if passed_match else 0,
        "failed": int(failed_match.group(1)) if failed_match else 0,
    }
    
    # Parse coverage
    coverage_match = re.search(r'Coverage:\s*([\d.]+)%', result)
    coverage = float(coverage_match.group(1)) if coverage_match else None
    
    # Extract feedback (if FAIL)
    feedback = ""
    if verdict == "FAIL":
        feedback_section = re.search(
            r'### Feedback for Builder.*?(?=### Retry|$)',
            result,
            re.DOTALL
        )
        if feedback_section:
            feedback = feedback_section.group(0).strip()
    
    # Determine if should retry
    should_retry = (verdict == "FAIL" and retry_count < 3)  # Default max_retries
    
    return {
        "verdict": verdict,
        "retry_count": retry_count,
        "should_retry": should_retry,
        "summary": summary,
        "coverage": coverage,
        "feedback": feedback,
    }
```

#### Subtask 4.2: TDD Workflow Handler

**Nieuwe functie toevoegen:**

```python
async def handle_tdd_workflow(
    db: DBSession,
    workflow: Workflow,
    steps: list[WorkflowStep],
    step_index: int,
    context: dict,
    exec_ctx: ExecutionContext,
) -> dict[str, Any]:
    """Handle TDD workflow with tester validation and retry logic.
    
    Called after tester validation step to determine next action:
    - If PASS: Continue to next step
    - If FAIL + retry available: Insert retry step and re-run tester
    - If FAIL + max retries: Fail workflow
    
    Args:
        db: Database session
        workflow: Current workflow
        steps: All workflow steps
        step_index: Index of tester validation step
        context: Execution context
        exec_ctx: ExecutionContext for events
        
    Returns:
        Dict with result or pause state
    """
    tester_step = steps[step_index]
    tester_result = tester_step.result_summary or ""
    
    # Parse test result
    test_analysis = parse_test_result(tester_result)
    
    logger.info(
        "tdd_test_result_parsed",
        verdict=test_analysis["verdict"],
        retry_count=test_analysis["retry_count"],
        should_retry=test_analysis["should_retry"],
        step_id=str(tester_step.id),
    )
    
    exec_ctx.emit("test_result", {
        "verdict": test_analysis["verdict"],
        "coverage": test_analysis["coverage"],
        "summary": test_analysis["summary"],
    })
    
    if test_analysis["verdict"] == "PASS":
        # Tests passed - continue to next step
        logger.info(
            "tdd_tests_passed_continuing",
            next_step_index=step_index + 1,
        )
        return {
            "action": "continue",
            "next_step": step_index + 1,
        }
    
    # Tests failed - check retry
    if test_analysis["should_retry"]:
        logger.info(
            "tdd_retry_initiated",
            retry_count=test_analysis["retry_count"] + 1,
            feedback_preview=test_analysis["feedback"][:200],
        )
        
        # Update context with retry information
        context["retry_count"] = test_analysis["retry_count"] + 1
        context["max_retries"] = context.get("max_retries", 3)
        context["tester_feedback"] = test_analysis["feedback"]
        context["previous_test_result"] = test_analysis
        
        exec_ctx.emit("retry_initiated", {
            "attempt": context["retry_count"],
            "max_retries": context["max_retries"],
        })
        
        # Insert builder retry step before next tester run
        return {
            "action": "retry",
            "retry_step": "builder",
            "retry_count": context["retry_count"],
            "feedback": test_analysis["feedback"],
        }
    
    # Max retries reached - fail workflow
    logger.error(
        "tdd_max_retries_reached",
        retry_count=test_analysis["retry_count"],
        feedback=test_analysis["feedback"],
    )
    
    # Update workflow status to failed
    update_workflow(
        db,
        workflow.id,
        status="failed",
    )
    
    update_workflow_step(
        db,
        tester_step.id,
        status="failed",
        result_summary=f"Max retries reached. {test_analysis['feedback'][:500]}",
    )
    
    exec_ctx.emit("workflow_failed", {
        "reason": "max_retries_reached",
        "retry_count": test_analysis["retry_count"],
        "feedback": test_analysis["feedback"],
    })
    
    return {
        "success": False,
        "error": f"Max retries ({test_analysis['retry_count']}) reached. Implementation could not pass tests.",
        "verdict": "FAIL",
        "feedback": test_analysis["feedback"],
    }
```

#### Subtask 4.3: execute_workflow_steps Uitbreiden

**Te wijzigen in execute_workflow_steps() na agent step completion:**

```python
# After agent step completes successfully (around line 660-680)
step_result = result.get("result")

# Check if this is a tester validation step requiring TDD handling
if step_type == "agent" and step.agent_id == "tester" and is_validation_step(step):
    tdd_result = await handle_tdd_workflow(
        db=db,
        workflow=workflow,
        steps=steps,
        step_index=i,
        context=context,
        exec_ctx=exec_ctx,
    )
    
    if tdd_result.get("action") == "retry":
        # Insert retry step and continue
        retry_result = await _handle_builder_retry(
            db=db,
            workflow=workflow,
            context=context,
            exec_ctx=exec_ctx,
            feedback=tdd_result["feedback"],
            retry_count=tdd_result["retry_count"],
        )
        
        if retry_result.get("paused"):
            return retry_result
        
        if not retry_result.get("success"):
            # Retry failed - stop workflow
            return retry_result
        
        # Retry succeeded - re-run tester validation
        result = await run_agent(
            db=db,
            agent_id="tester",
            prompt="Re-validate implementation after fixes",
            context=context,
            exec_ctx=exec_ctx,
        )
        
        if not result.get("success"):
            # Validation failed again - this is handled by TDD handler on next iteration
            pass
        
        continue  # Process the tester result
    
    elif not tdd_result.get("success"):
        # TDD workflow failed (max retries)
        return tdd_result
```

#### Subtask 4.4: Helper Functies

**Nieuwe helper functies toevoegen:**

```python
def is_validation_step(step: WorkflowStep) -> bool:
    """Check if this is a tester validation step (not generation).
    
    Validation steps:
    - Have "validation" or "validate" in description
    - Come after a builder step
    - Come before approval or deployer
    """
    desc = step.description.lower()
    return any(
        keyword in desc
        for keyword in ["validate", "validation", "run tests", "check tests"]
    )

async def _handle_builder_retry(
    db: DBSession,
    workflow: Workflow,
    context: dict,
    exec_ctx: ExecutionContext,
    feedback: str,
    retry_count: int,
) -> dict[str, Any]:
    """Handle builder retry with specific feedback.
    
    Args:
        db: Database session
        workflow: Current workflow
        context: Execution context with feedback
        exec_ctx: ExecutionContext
        feedback: Tester feedback for builder
        retry_count: Current retry attempt number
        
    Returns:
        Result from builder agent
    """
    from druppie.agents.runtime import Agent
    
    logger.info(
        "builder_retry_started",
        retry_count=retry_count,
        feedback_preview=feedback[:200],
    )
    
    exec_ctx.emit("builder_retry_started", {
        "attempt": retry_count,
        "feedback_preview": feedback[:200],
    })
    
    # Run builder with feedback
    result = await run_agent(
        db=db,
        agent_id="builder",
        prompt=f"""Previous implementation failed tests. Fix these specific issues:

{feedback}

This is retry attempt {retry_count}. Make targeted fixes to address the reported issues.""",
        context=context,
        exec_ctx=exec_ctx,
    )
    
    if result.get("paused"):
        return result
    
    if not result.get("success"):
        logger.error(
            "builder_retry_failed",
            retry_count=retry_count,
            error=result.get("error"),
        )
        return result
    
    exec_ctx.emit("builder_retry_completed", {
        "attempt": retry_count,
    })
    
    return result
```

---

## TASK 5: Configuratie en Settings

### Bestand: `druppie/core/config.py` of nieuwe `config.yaml`

#### Subtask 5.1: TDD Settings Toevoegen

**Toe te voegen aan config:**

```python
class TDDSettings(BaseSettings):
    """Test Driven Development settings."""
    
    max_retries: int = Field(
        default=3,
        description="Maximum number of builder retry attempts after test failures"
    )
    
    coverage_threshold: float = Field(
        default=80.0,
        description="Minimum code coverage percentage (0-100)"
    )
    
    coverage_warning_threshold: float = Field(
        default=60.0,
        description="Coverage percentage that triggers warning (but not fail)"
    )
    
    test_timeout: int = Field(
        default=120,
        description="Default timeout for test execution in seconds"
    )
    
    auto_generate_tests: bool = Field(
        default=True,
        description="Whether to automatically generate tests for new projects"
    )
    
    require_coverage: bool = Field(
        default=True,
        description="Whether to fail if coverage cannot be measured"
    )
    
    class Config:
        env_prefix = "TDD_"
```

#### Subtask 5.2: Environment Variables Documentatie

**Toe te voegen aan .env.example:**

```bash
# Test Driven Development (TDD) Settings
TDD_MAX_RETRIES=3
TDD_COVERAGE_THRESHOLD=80
TDD_COVERAGE_WARNING_THRESHOLD=60
TDD_TEST_TIMEOUT=120
TDD_AUTO_GENERATE_TESTS=true
TDD_REQUIRE_COVERAGE=true
```

---

## TASK 6: Testen en Validatie

### Subtask 6.1: Unit Tests voor Helper Functies

**Bestand: `tests/core/test_tdd_helpers.py`**

```python
import pytest
from druppie.core.loop import parse_test_result

class TestParseTestResult:
    """Test test result parser."""
    
    def test_parse_pass_result(self):
        result = """
## TEST RESULT: PASS

### Summary
- Total: 10 | Passed: 10 | Failed: 0 | Skipped: 0
- Coverage: 95%

### Verdict
**PASS**
"""
        parsed = parse_test_result(result)
        assert parsed["verdict"] == "PASS"
        assert parsed["retry_count"] == 0
        assert not parsed["should_retry"]
        assert parsed["coverage"] == 95.0
    
    def test_parse_fail_result(self):
        result = """
## TEST RESULT: FAIL

### Summary
- Total: 10 | Passed: 8 | Failed: 2 | Skipped: 0
- Coverage: 60%

### Verdict
**FAIL**

### Feedback for Builder
- Test test_create_todo failed: Expected 201, got 500
- Missing error handling
"""
        parsed = parse_test_result(result)
        assert parsed["verdict"] == "FAIL"
        assert parsed["retry_count"] == 0
        assert parsed["should_retry"] == True  # retry_count < max_retries
        assert "Test test_create_todo failed" in parsed["feedback"]
    
    def test_parse_fail_max_retries(self):
        result = """
## TEST RESULT: FAIL

### Summary
- Total: 10 | Passed: 9 | Failed: 1 | Skipped: 0

### Verdict
**FAIL**

### Retry Count
- Current Attempt: 3 / 3
- Continue to next iteration if: Current < max
"""
        parsed = parse_test_result(result)
        assert parsed["verdict"] == "FAIL"
        assert parsed["retry_count"] == 3
        assert not parsed["should_retry"]  # max_retries reached
```

### Subtask 6.2: Integration Tests voor MCP Tools

**Bestand: `tests/mcp/test_coding_tools.py`**

```python
import pytest
from druppie.mcp_servers.coding.module import CodingModule

@pytest.mark.asyncio
class TestCodingTestTools:
    """Test coding MCP test-related tools."""
    
    async def test_get_test_framework_vitest(self, workspace):
        module = CodingModule(workspace_root="/test")
        workspace_id = await module.register_workspace(
            workspace_id="test",
            workspace_path=workspace,
            project_id="test",
            branch="main",
        )
        
        result = await module.get_test_framework(workspace_id)
        assert result["framework"] in ["vitest", "pytest", "jest", "gotest"]
        assert "test_command" in result
        assert "coverage_command" in result
    
    async def test_run_tests_with_coverage(self, workspace_with_tests):
        module = CodingModule(workspace_root="/test")
        result = await module.run_tests(
            workspace_id="test",
            timeout=120,
            coverage=True,
        )
        
        assert result["success"] == True
        assert "results" in result
        assert "total" in result["results"]
        if "coverage" in result:
            assert "overall_percent" in result["coverage"]
```

### Subtask 6.3: E2E Test voor TDD Workflow

**Bestand: `tests/e2e/test_tdd_workflow.py`**

```python
import pytest
from druppie.core.loop import MainLoop

@pytest.mark.e2e
class TestTDDWorkflow:
    """End-to-end TDD workflow tests."""
    
    @pytest.mark.asyncio
    async def test_successful_tdd_flow(self, client, db):
        """Test complete TDD flow with pass."""
        loop = MainLoop()
        
        result = await loop.process_message(
            message="Create a simple todo app with TDD",
            project_name="test-todo",
            user_id="test-user",
        )
        
        assert result["success"] == True
        # Verify workflow completed with all 7 steps
        
    @pytest.mark.asyncio
    async def test_tdd_with_retry(self, client, db):
        """Test TDD flow that requires one retry."""
        # Create scenario where builder will fail first test
        # Then verify retry logic works
        
    @pytest.mark.asyncio
    async def test_tdd_max_retries(self, client, db):
        """Test TDD flow that exhausts all retries."""
        # Create scenario that cannot pass tests
        # Verify workflow fails with proper message
```

---

## TASK 7: Documentatie

### Subtask 7.1: Agent Documentation Updaten

**Bestand: `docs/agents/tester.md`**

**Nieuwe secties:**

```markdown
# Tester Agent

## Overview
The Tester Agent follows Test Driven Development (TDD) to:
1. Generate comprehensive test suites based on architecture
2. Validate implementations with explicit PASS/FAIL verdicts
3. Provide feedback for builder retries

## Modes of Operation

### Mode 1: Test Generation (Red Phase)
Triggered when:
- Planner creates a new project
- User explicitly requests test generation
- New features are added to existing project

Actions:
- Read architecture.md and specification files
- Detect test framework (vitest, pytest, jest, gotest)
- Generate tests covering:
  - All functional requirements
  - Edge cases and error scenarios
  - Input validation
  - Security scenarios
- Write test files with proper conventions
- Commit tests to git

Output:
- Summary of tests created
- Test file locations
- Coverage goals
- Dependencies needed

### Mode 2: Validation (Green/Refactor Phase)
Triggered after:
- Builder completes implementation
- Builder retry attempts
- Code changes that affect existing tests

Actions:
- Run all tests with coverage
- Parse test results
- Analyze code coverage
- Determine PASS/FAIL verdict
- Generate detailed report

Output Format:
```markdown
## TEST RESULT: PASS or FAIL

### Summary
- Total: X | Passed: X | Failed: X | Skipped: X
- Coverage: X%

### Verdict
**PASS** or **FAIL**

### Feedback for Builder (if FAIL)
[Specific issues and recommendations]

### Retry Count
- Current Attempt: X / max_retries
```

## PASS/FAIL Criteria

### PASS (all must be true):
- ✅ All tests pass (0 failures)
- ✅ Coverage > 80% for new code
- ✅ No critical errors
- ✅ Implementation matches requirements

### FAIL (any will cause):
- ❌ One or more tests fail
- ❌ Coverage < 50% for new code
- ❌ Missing key features
- ❌ Critical bugs or crashes

## Framework Support

### Vitest (Vite/React)
- Files: *.test.jsx, *.test.tsx
- Command: npm run test -- --coverage
- Coverage: coverage/coverage-final.json

### Pytest (Python)
- Files: test_*.py
- Command: pytest --cov=. --cov-report=json
- Coverage: coverage.json

### Jest (Node.js)
- Files: *.test.js
- Command: npm test -- --coverage
- Coverage: coverage/coverage-final.json

### Go Test
- Files: *_test.go
- Command: go test -coverprofile=coverage.out
- Coverage: coverage.out
```

### Subtask 7.2: TDD Workflow Documentatie

**Bestand: `docs/workflows/tdd.md`**

**Nieuw document:**

```markdown
# Test Driven Development (TDD) Workflow

## Overview
The TDD workflow ensures code quality through automated testing and validation.

## Workflow Steps

```
1. ARCHITECT → Design architecture
2. APPROVAL → User approves architecture
3. TESTER (GENERATION) → Generate comprehensive tests
4. BUILDER → Implement code to pass tests
5. TESTER (VALIDATION) → Run tests and validate
   ├─ PASS → Continue to step 6
   └─ FAIL → Check retry count
       ├─ retry < max → Retry builder (step 5b)
       └─ retry >= max → Fail workflow
6. APPROVAL → User approves implementation
7. DEPLOYER → Build and deploy
```

## Retry Mechanism

When tester returns FAIL:
1. Increment retry_count
2. Pass tester feedback to builder
3. Builder makes targeted fixes
4. Re-run tester validation
5. Repeat until PASS or max_retries reached

Default: max_retries = 3

## Configuration

Set via environment variables:
- TDD_MAX_RETRIES=3
- TDD_COVERAGE_THRESHOLD=80
- TDD_TEST_TIMEOUT=120

## Example Output

### Successful Flow:
```
Tester: Tests generated (10 tests, 100% coverage goal)
Builder: Code implemented
Tester: ## TEST RESULT: PASS
       - Total: 10 | Passed: 10 | Failed: 0
       - Coverage: 95%
Approval: User approves
Deployer: Application deployed
```

### Flow with Retry:
```
Tester: Tests generated
Builder: Code implemented (missing error handling)
Tester: ## TEST RESULT: FAIL
       - Total: 10 | Passed: 8 | Failed: 2
       - Feedback: test_delete_todo missing error handling
Retry 1: Builder adds error handling
Tester: ## TEST RESULT: PASS
       - Total: 10 | Passed: 10 | Failed: 0
       - Coverage: 92%
```

### Flow with Max Retries:
```
Tester: Tests generated
Builder: Code implemented
Tester: ## TEST RESULT: FAIL
       - Feedback: Complex architectural issue
Retry 1: Builder fixes part
Tester: ## TEST RESULT: FAIL
Retry 2: Builder fixes more
Tester: ## TEST RESULT: FAIL
Retry 3: Builder attempts final fix
Tester: ## TEST RESULT: FAIL
       - Current Attempt: 3 / 3
       - Continue: NO
Workflow: FAILED - Max retries reached
```
```

---

## TASK 8: Frontend Updates

### Subtask 8.1: Test Result UI Component

**Bestand: `frontend/src/components/chat/TestResultCard.jsx`**

**Nieuw component:**

```jsx
import React from 'react';

export default function TestResultCard({ result }) {
  const isPass = result.verdict === 'PASS';
  
  return (
    <div className={`border rounded-lg p-4 ${isPass ? 'border-green-500 bg-green-50' : 'border-red-500 bg-red-50'}`}>
      <div className="flex items-center gap-2 mb-3">
        <span className={`text-lg ${isPass ? 'text-green-600' : 'text-red-600'}`}>
          {isPass ? '✓' : '✗'}
        </span>
        <h3 className="font-semibold text-lg">
          Test Result: {result.verdict}
        </h3>
      </div>
      
      {result.summary && (
        <div className="grid grid-cols-4 gap-2 mb-3 text-sm">
          <div>
            <span className="text-gray-600">Total:</span> {result.summary.total}
          </div>
          <div className="text-green-600">
            <span className="text-gray-600">Passed:</span> {result.summary.passed}
          </div>
          <div className="text-red-600">
            <span className="text-gray-600">Failed:</span> {result.summary.failed}
          </div>
          <div>
            <span className="text-gray-600">Skipped:</span> {result.summary.skipped}
          </div>
        </div>
      )}
      
      {result.coverage !== null && (
        <div className="mb-3">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-600">Coverage</span>
            <span className={result.coverage >= 80 ? 'text-green-600' : result.coverage >= 60 ? 'text-yellow-600' : 'text-red-600'}>
              {result.coverage.toFixed(1)}%
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${result.coverage >= 80 ? 'bg-green-500' : result.coverage >= 60 ? 'bg-yellow-500' : 'bg-red-500'}`}
              style={{ width: `${result.coverage}%` }}
            />
          </div>
        </div>
      )}
      
      {!isPass && result.feedback && (
        <div className="mt-3 pt-3 border-t">
          <h4 className="font-medium text-sm text-gray-700 mb-2">Feedback for Builder:</h4>
          <div className="text-sm text-gray-600 whitespace-pre-wrap">
            {result.feedback}
          </div>
        </div>
      )}
      
      {result.retry_count !== undefined && (
        <div className="mt-3 pt-3 border-t text-sm">
          <span className="text-gray-600">Attempt: </span>
          <span className="font-medium">{result.retry_count} / {result.max_retries || 3}</span>
        </div>
      )}
    </div>
  );
}
```

### Subtask 8.2: Workflow Events for TDD

**Bestand: `frontend/src/components/chat/WorkflowEvent.jsx`**

**Update om test events te tonen:**

```jsx
// Add new event type cases
case 'test_result':
  return (
    <div className="flex items-start gap-2 p-3 bg-blue-50 rounded">
      <span className="text-blue-600">🧪</span>
      <div className="flex-1">
        <div className="font-medium text-sm">
          Test Result: <span className={event.verdict === 'PASS' ? 'text-green-600' : 'text-red-600'}>
            {event.verdict}
          </span>
        </div>
        {event.coverage && (
          <div className="text-xs text-gray-600">
            Coverage: {event.coverage.toFixed(1)}%
          </div>
        )}
      </div>
    </div>
  );

case 'retry_initiated':
  return (
    <div className="flex items-start gap-2 p-3 bg-yellow-50 rounded">
      <span className="text-yellow-600">🔄</span>
      <div className="flex-1">
        <div className="font-medium text-sm">Builder Retry Initiated</div>
        <div className="text-xs text-gray-600">
          Attempt {event.attempt} of {event.max_retries}
        </div>
      </div>
    </div>
  );
```

---

## TASK 9: Code Quality en Best Practices

### Subtask 9.1: Logging Verbeteren

**Toe te voegen in loop.py:**

```python
# Structured logging for TDD workflow
logger.info(
    "tester_validation_started",
    workflow_id=str(workflow.id),
    step_index=step_index,
    agent_id=step.agent_id,
)

logger.info(
    "test_result_parsed",
    verdict=test_analysis["verdict"],
    coverage=test_analysis["coverage"],
    failed_count=test_analysis["summary"]["failed"],
)

logger.debug(
    "tester_feedback_content",
    feedback=test_analysis["feedback"][:500],
)

logger.info(
    "builder_retry_starting",
    retry_count=retry_count,
    max_retries=max_retries,
)
```

### Subtask 9.2: Error Handling

**Te verbeteren:**

```python
# In parse_test_result, handle malformed output gracefully
try:
    verdict_match = re.search(r'## TEST RESULT:\s*(PASS|FAIL)', result, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"
except Exception as e:
    logger.warning("test_result_parse_failed", error=str(e))
    verdict = "FAIL"  # Fail safe

# In run_tests, handle timeout properly
try:
    result = await asyncio.wait_for(
        subprocess.run(...),
        timeout=timeout
    )
except asyncio.TimeoutError:
    logger.error("test_execution_timeout", timeout=timeout)
    return {
        "success": False,
        "error": f"Tests timed out after {timeout} seconds",
    }
```

---

## Implementatie Volgorde

**Fase 1: Foundation (Week 1)**
1. ✅ TASK 1.1: System prompt uitbreiden
2. ✅ TASK 1.2: Test generation checklist
3. ✅ TASK 1.3: Output format specificeren
4. ✅ TASK 1.4: PASS/FAIL thresholds
5. ✅ TASK 1.5: Framework detection
6. ✅ TASK 1.6: Coverage tool config

**Fase 2: MCP Server (Week 1-2)**
7. ✅ TASK 2.1: run_tests tool verbeteren
8. ✅ TASK 2.2: get_test_framework tool
9. ✅ TASK 2.3: get_coverage_report tool
10. ✅ TASK 2.4: Module helper functies

**Fase 3: Main Loop (Week 2)**
11. ✅ TASK 4.1: Test result parser
12. ✅ TASK 4.2: TDD workflow handler
13. ✅ TASK 4.3: execute_workflow_steps update
14. ✅ TASK 4.4: Helper functies

**Fase 4: Planner (Week 2)**
15. ✅ TASK 3.1: TDD workflow steps
16. ✅ TASK 3.2: Step templates
17. ✅ TASK 3.3: Conditional logic

**Fase 5: Config (Week 3)**
18. ✅ TASK 5.1: TDD settings
19. ✅ TASK 5.2: Environment variables

**Fase 6: Testing (Week 3-4)**
20. ✅ TASK 6.1: Unit tests
21. ✅ TASK 6.2: Integration tests
22. ✅ TASK 6.3: E2E tests

**Fase 7: Frontend (Week 4)**
23. ✅ TASK 8.1: Test result UI
24. ✅ TASK 8.2: Workflow events

**Fase 8: Documentation (Week 4)**
25. ✅ TASK 7.1: Agent documentation
26. ✅ TASK 7.2: TDD workflow docs

---

## Validation Criteria

### Functionele Requirements
- [ ] Tester agent kan tests genereren voor alle frameworks (pytest, vitest, jest, gotest)
- [ ] Tester agent valideert implementaties met expliciet PASS/FAIL
- [ ] Coverage wordt gemeten en gerapporteerd
- [ ] Retry mechanism werkt correct (max_retries wordt gerespecteerd)
- [ ] Feedback loop tussen Tester en Builder werkt
- [ ] Planner genereert correcte TDD workflow

### Technische Requirements
- [ ] run_tests tool detecteert framework automatisch
- [ ] Test output wordt correct geparsed
- [ ] Coverage rapporten worden correct gelezen
- [ ] Structured logging aanwezig
- [ ] Error handling is robust
- [ ] Unit tests voor alle nieuwe functies
- [ ] Integration tests voor MCP tools
- [ ] E2E tests voor volledige TDD workflow

### Code Quality
- [ ] Code volgt project conventions
- [ ] Type hints zijn correct
- [ ] Docstrings zijn aanwezig
- [ ] Logging is consistent
- [ ] Geen hardcoded waarden (configuratie via settings)

---

## Risico's en Mitigaties

### Risico 1: Test Output Parsing Faalt
- **Mitigatie:** Fallback op regex patterns, fail safe op FAIL
- **Prioriteit:** High
- **Oplossing:** Multiple parsing strategies, uitgebreide unit tests

### Risico 2: Coverage Niet Beschikbaar
- **Mitigatie:** Optionele coverage check, waarschuwing niet error
- **Prioriteit:** Medium
- **Oplossing:** Coverage flag, graceful degradation

### Risico 3: Infinite Retry Loop
- **Mitigatie:** Hard limit op max_retries, exponential backoff
- **Prioriteit:** High
- **Oplossing:** Timeout per test run, max_retries limit

### Risico 4: Framework Detectie Incorrect
- **Mitigatie:** User override mogelijkheid, expliciete command support
- **Prioriteit:** Low
- **Oplossing:** test_command parameter, verbose logging

---

## Dependencies

### Interne
- ✅ druppie.core.loop - Workflow execution
- ✅ druppie.agents.runtime - Agent runtime
- ✅ druppie.core.mcp_client - MCP client
- ✅ druppie.db - Database models en CRUD

### Externe
- ✅ pytest - Python testing
- ✅ vitest - Frontend testing (Vite)
- ✅ jest - Node.js testing
- ✅ fastmcp - MCP server framework

---

## Volgende Stappen

Na voltooiing van dit plan:

1. Implementatie volgens Fase 1-8 volgorde
2. Code review door team
3. Testing op dev omgeving
4. Staging deployment
5. Productie release

---

**Document Versie:** 1.0  
**Datum:** 2026-02-05  
**Auteur:** AI Assistant  
**Status:** Gereed voor implementatie
