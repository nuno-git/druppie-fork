# Implementatieplan: Builder & Tester Agents met TDD

## Overzicht

Dit plan beschrijft de implementatie van de Builder en Tester agents die samenwerken volgens Test Driven Development (TDD), met een feedback-loop en retry-mechanisme.

**Volgens PBI:**
- Bouwer en Tester interacteren via feedback-loop
- Tester valideert functionele én technische requirements
- Tester kan tests genereren met 100% code coverage
- TDD flow: test → build → test
- Configureerbaar maximum aantal retries
- Expliciet Pass/Fail-resultaat met onderbouwing

---

## Architectuur

### Agents

1. **Builder Agent** (`builder.yaml`): Implementeert code om tests te laten slagen
2. **Tester Agent** (`tester.yaml`): Genereert tests en valideert implementaties
3. **Planner Agent** (`planner.yaml`): Orkestreert de TDD flow

### TDD Workflow

```
┌─────────────────────────────────────────────────────────┐
│ PLANNER: Maakt execution plan met TDD steps             │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 1: TESTER - Test Generation (Red Fase)             │
│  - Leest architecture.md / SPEC.md                       │
│  - Genereert uitgebreide test suite                       │
│  - Doel: 100% coverage voor nieuwe code                  │
│  - Resultaat: Alle tests FAIL (geen implementation)      │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 2: BUILDER - Implementatie (Green Fase)             │
│  - Leest test files om requirements te begrijpen          │
│  - Implementeert minimale code om tests te laten slagen  │
│  - Runt build command indien nodig                       │
│  - Commit & push naar git                                │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 3: TESTER - Validatie (Green/Refactor Fase)       │
│  - Voert alle tests uit                                 │
│  - Analyseert resultaten                                │
│  - Bepaalt: PASS of FAIL                                │
└──────────────┬──────────────────────────────────────────┘
               │
         ┌─────┴─────┐
         │ PASS?     │
         └─────┬─────┘
               │
      YES      │      NO
   ┌───────────┘      └────────────┐
   │                                 │
   ▼                                 ▼
┌─────────────┐              ┌────────────────────────┐
│ STEP 4:     │              │ BUILDER RETRY LOOP      │
│ APPROVAL    │              │  - Tester geeft          │
│ (review     │              │    specifieke feedback   │
│  results)   │              │  - Builder fixt issues  │
└─────────────┘              │  - Retry < max_retries  │
   │                         └───────────┬────────────┘
   ▼                                     │
┌─────────────┐                    Retry < max?
│ STEP 5:     │                    ┌────┴────┐
│ DEPLOYER    │                    │         │
│ (build &    │               YES  │    NO   │
│  deploy)    │               ┌────┴─┐  ┌────┴─┐
└─────────────┘               │      │  │      │
                              ▼      ▼  ▼      ▼
                          ┌─────────────────┐
                          │ FAIL - Max       │
                          │ retries bereikt  │
                          │ met uitleg       │
                          └─────────────────┘
```

---

## Implementatie Stappen

### Stap 1: Builder Agent Implementeren

**Bestand:** `druppie/agents/definitions/builder.yaml`

**Al gecreëerd** met volgende functionaliteit:

**Capabilities:**
- `read_file` - Leest test files om requirements te begrijpen
- `write_file` - Schrijft/updates code files
- `batch_write_files` - Efficiënt multi-file updates
- `run_command` - Voert build commands uit (npm run build, etc.)
- `list_dir` - Bekijkt project structuur
- `commit_and_push` - Commit changes naar git

**TDD Workflow:**
1. Analyseer test files → Begrijp wat geïmplementeerd moet worden
2. Implementeer minimale code om tests te laten slagen
3. Run build command indien nodig
4. Commit & push
5. Rapporteer wat geïmplementeerd is

**Feedback Handling:**
- Leest specifieke foutmeldingen van Tester
- Maakt doelgerichte fixes
- Rewrite geen onnodige code
- Reportt wat er gefixt is

### Stap 2: Tester Agent Implementeren

**Bestand:** `druppie/agents/definitions/tester.yaml`

**Al gecreëerd** met volgende functionaliteit:

**Capabilities:**
- `read_file` - Leest specs en code
- `write_file` - Schrijft test files
- `run_tests` - Voert tests uit (auto-detect framework)
- `run_command` - Voert coverage commands uit
- `commit_and_push` - Commit test files

**TWO MODES:**

**Mode 1: Test Generation (Red Fase)**
1. Lees architecture.md / SPEC.md
2. Lees bestaande code voor patterns
3. Genereer uitgebreide tests:
   - Alle functionele requirements
   - Edge cases en error scenarios
   - 100% code coverage doelen
4. Schrijf test files
5. Commit & push
6. Rapporteer test coverage doelen

**Mode 2: Validatie (Green/Refactor Fase)**
1. Run alle tests
2. Analyseer resultaten
3. Bepaal PASS/FAIL
4. Genereer gedetailleerd rapport met:
   - Totale / Passed / Failed / Skipped
   - Coverage percentage
   - Specifieke foutmeldingen
   - Feedback voor Builder (indien FAIL)
   - Retry count

**PASS/FAIL Criteria:**

**PASS:**
- Alle tests pass (0 failures)
- Coverage > 80% (voor nieuwe code)
- Geen kritieke errors
- Implementation voldoet aan requirements

**FAIL:**
- Eén of meer tests falen
- Coverage < 50% (voor nieuwe code)
- Implementation mist key requirements
- Code quality issues die acceptatie belemmeren

**Output Format:**
```markdown
## TEST RESULT: PASS of FAIL

### Summary
- Total: X | Passed: X | Failed: X | Skipped: X
- Coverage: X%

### Details
[Failed tests met error messages]

### Verdict
**PASS** of **FAIL** (moet bold en expliciet zijn)

### Feedback for Builder (indien FAIL)
- Specifieke issues
- Wat gefixt moet worden
- Expected vs actual
- Aanbevelingen

### Retry Count
- Current attempt: X / max_retries
- Continue: JA/NEE
```

### Stap 3: Planner Agent Uitbreiden

**Bestand:** `druppie/agents/definitions/planner.yaml`

**Toevoegingen aan AVAILABLE AGENTS:**
```yaml
AVAILABLE AGENTS (per goal.md workflow):
- architect: Designs system architecture
- tester: Generates tests and validates implementation
- builder: Implements code to satisfy tests
- deployer: Handles Docker build and deployment
```

**Nieuwe workflow voor CREATE_PROJECT:**

**Originele flow (4 steps):**
1. Architect → Approval → Developer → Deployer

**Nieuwe TDD flow (6-7 steps):**
1. **Architect** - Design architecture
2. **Approval** - Review architecture
3. **Tester (Generation)** - Generate tests
4. **Builder** - Implement code
5. **Tester (Validation)** - Validate implementation
   - *Indien PASS*: Ga naar step 6
   - *Indien FAIL*: Retry Builder (max N keer)
6. **Approval** - Review test results
7. **Deployer** - Build and deploy

**Planner Prompt Updates:**

Voeg deze instructies toe aan planner.yaml:

```yaml
STEP 3 - TESTER (GENERATION): Generate comprehensive tests
  - Reads architecture.md/SPEC.md
  - Detects appropriate test framework:
    * Python Backend → Pytest (pytest, pytest-cov)
    * Frontend (Vite/React) → Vitest (vitest, @testing-library)
    * Node.js Backend → Jest (jest, supertest)
  - Generates test suite with 100% coverage goal
  - Creates test files
  - Type: agent
  - Agent: tester
  - Prompt: "Generate comprehensive tests for [project] based on architecture.md. Detect the appropriate framework: use Pytest for Python backend, Vitest for frontend, or Jest for Node.js backend. Cover all functional requirements, edge cases, and aim for 100% code coverage. Commit the test files."

STEP 4 - BUILDER: Implement code to make tests pass
  - Reads test files to understand requirements
  - Implements code to satisfy tests
  - Runs build command if needed
  - Type: agent
  - Agent: builder
  - Prompt: "Implement the [project] to make all tests pass. Read the test files first to understand requirements. Use batch_write_files for efficiency. Run build command if needed. Commit and push changes."

STEP 5 - TESTER (VALIDATION): Run tests and validate
  - Executes all tests
  - Analyzes coverage
  - Returns PASS/FAIL verdict
  - Type: agent
  - Agent: tester
  - Prompt: "Run all tests and validate the implementation. Return a detailed PASS/FAIL report with coverage metrics. If FAIL, provide specific feedback for the builder to fix."

STEP 6 - APPROVAL: Review test results before deployment
  - Type: approval
  - Message: "Tests completed. Review results and approve to proceed with deployment."
  - required_roles: ["developer", "admin"]
  - context: { test_results: "from tester validation" }

STEP 7 - DEPLOYER: Build and deploy
  - Type: agent
  - Agent: deployer
  - Prompt: "Build and deploy [project]. Build Docker image and run container. Return the access URL."
```

**Example JSON Output:**
```json
{
  "name": "Build Todo App with TDD",
  "description": "Design, test, implement, and deploy a todo application following TDD",
  "steps": [
    {
      "id": "step_1",
      "type": "agent",
      "agent_id": "architect",
      "prompt": "Design the architecture for a Todo application. Create architecture.md with: overview, components, API endpoints, data models, and technology choices."
    },
    {
      "id": "step_2",
      "type": "approval",
      "message": "Architecture design complete. Review architecture.md and approve to proceed.",
      "required_roles": ["developer", "admin"]
    },
    {
      "id": "step_3",
      "type": "agent",
      "agent_id": "tester",
      "prompt": "Generate comprehensive tests for the Todo application based on architecture.md. Use Pytest for Python backend with test_*.py files, or Vitest for frontend with *.test.jsx files. Create test files covering all CRUD operations, edge cases, and error scenarios. Aim for 100% code coverage. Include package.json with test scripts if needed. Commit the tests."
    },
    {
      "id": "step_4",
      "type": "agent",
      "agent_id": "builder",
      "prompt": "Implement the Todo application to make all tests pass. Read the test files first. Use batch_write_files to create all source files. Run npm run build if needed. Commit and push changes."
    },
    {
      "id": "step_5",
      "type": "agent",
      "agent_id": "tester",
      "prompt": "Run all tests and validate the implementation. Return a PASS/FAIL report with coverage. If FAIL, provide specific feedback for the builder."
    },
    {
      "id": "step_6",
      "type": "approval",
      "message": "Test validation complete. Review the PASS/FAIL result and approve to deploy.",
      "required_roles": ["developer", "admin"]
    },
    {
      "id": "step_7",
      "type": "agent",
      "agent_id": "deployer",
      "prompt": "Build and deploy the Todo application. Build Docker image and run container. Return the access URL."
    }
  ]
}
```

### Stap 4: Retry Mechanisme in Planner Agent

**Locatie:** `druppie/agents/definitions/planner.yaml`

**Retry Logic in Planner:**

De Planner agent beheert de TDD workflow en retry-logica door middel van **conditional steps** in het execution plan.

**Planner Prompt Updates voor Retry Handling:**

Voeg deze instructies toe aan planner.yaml:

```yaml
RETRY LOGIC IN TDD WORKFLOW:

When generating plans for CREATE_PROJECT with testing:

After STEP 5 (Tester Validation), implement retry logic:

1. IF Tester returns PASS:
   - Proceed to STEP 6 (Approval)
   - Then STEP 7 (Deployer)

2. IF Tester returns FAIL:
   - Check retry_count (starts at 0)
   - IF retry_count < MAX_RETRIES (default: 3):
     - Increment retry_count
     - Add conditional step: Builder with feedback
     - Return to STEP 5 (Tester Validation)
   - ELSE (max retries reached):
     - Mark workflow as FAILED
     - Return FAIL with tester's detailed explanation
     - DO NOT proceed to Deployer

CONDITIONAL STEP FORMAT:

{
  "id": "step_builder_retry",
  "type": "conditional",
  "condition": "retry_count < MAX_RETRIES AND test_result == 'FAIL'",
  "if_true": {
    "type": "agent",
    "agent_id": "builder",
    "prompt": "Fix the implementation based on this feedback from the tester:\n\n{tester_feedback}\n\nPrevious attempt (attempt {retry_count}/{MAX_RETRIES}) failed. Make targeted fixes to address these specific issues.",
    "then": "step_tester_validation"
  },
  "if_false": {
    "type": "fail",
    "message": "Max retries reached. Implementation could not pass tests. See tester feedback for details."
  }
}

WORKFLOW EXAMPLE WITH RETRY LOOP:

STEP 1: Architect → STEP 2: Approval → STEP 3: Tester (Gen)
  ↓
STEP 4: Builder
  ↓
STEP 5: Tester (Val)
  ↓
  ┌──────────────┐
  │ PASS?        │
  └──────┬───────┘
         │ YES     NO
         │         │
         │         ↓
         │      retry_count++
         │         │
         │    retry < max?
         │      ┌──┴──┐
         │      │     │
         │    YES    NO
         │      │     │
         │      ↓     ↓
         │  Builder   FAIL
         │  (retry)   (stop)
         │      │
         │      ↓
         └─→ STEP 5 (Tester again)

IMPORTANT: The Planner must dynamically manage the workflow based on tester results.
The execution runtime should support conditional branching.

PASS: Continue to Approval → Deployer
FAIL + retry < max: Builder (retry) → Tester (validate again)
FAIL + retry >= max: Stop with FAIL message
```

**Updated JSON Plan Example with Retry Loop:**

```json
{
  "name": "Build Todo App with TDD",
  "description": "Design, test, implement, and deploy a todo application following TDD",
  "config": {
    "max_retries": 3
  },
  "steps": [
    {
      "id": "step_1",
      "type": "agent",
      "agent_id": "architect",
      "prompt": "Design the architecture for a Todo application. Create architecture.md with: overview, components, API endpoints, data models, and technology choices."
    },
    {
      "id": "step_2",
      "type": "approval",
      "message": "Architecture design complete. Review architecture.md and approve to proceed.",
      "required_roles": ["developer", "admin"]
    },
    {
      "id": "step_3",
      "type": "agent",
      "agent_id": "tester",
      "prompt": "Generate comprehensive tests for the Todo application based on architecture.md. Use Pytest for Python backend with test_*.py files, or Vitest for frontend with *.test.jsx files. Create test files covering all CRUD operations, edge cases, and error scenarios. Aim for 100% code coverage. Include package.json with test scripts if needed. Commit the tests."
    },
    {
      "id": "step_4",
      "type": "agent",
      "agent_id": "builder",
      "prompt": "Implement the Todo application to make all tests pass. Read the test files first. Use batch_write_files to create all source files. Run npm run build if needed. Commit and push changes."
    },
    {
      "id": "step_5",
      "type": "agent",
      "agent_id": "tester",
      "prompt": "Run all tests and validate the implementation. Return a PASS/FAIL report with coverage. If FAIL, provide specific feedback for the builder.",
      "on_success": "step_6",
      "on_failure": "check_retry"
    },
    {
      "id": "check_retry",
      "type": "conditional",
      "condition": "retry_count < max_retries",
      "if_true": {
        "type": "agent",
        "agent_id": "builder",
        "prompt": "Previous implementation attempt failed. Fix these specific issues reported by the tester:\n\n{tester_feedback}\n\nAttempt {retry_count} of {max_retries}. Make targeted fixes only for the reported failures.",
        "metadata": {
          "is_retry": true,
          "increment_retry_count": true
        },
        "on_complete": "step_5"
      },
      "if_false": {
        "type": "fail",
        "message": "Max retries ({max_retries}) reached. Implementation could not pass all tests. See tester feedback for details:\n\n{tester_feedback}"
      }
    },
    {
      "id": "step_6",
      "type": "approval",
      "message": "Test validation complete. Review the PASS result and approve to deploy.",
      "required_roles": ["developer", "admin"]
    },
    {
      "id": "step_7",
      "type": "agent",
      "agent_id": "deployer",
      "prompt": "Build and deploy the Todo application. Build Docker image and run container. Return the access URL."
    }
  ]
}
```

**Planner Instructions for Conditional Workflow:**

```yaml
CONDITIONAL WORKFLOW HANDLING:

When generating plans that include testing and retry logic:

1. Use "conditional" step types for branching based on test results
2. Define "on_success" and "on_failure" transitions for steps
3. Use "metadata" for step variables (e.g., retry_count)
4. Support "if_true" and "if_false" branches in conditional steps
5. Use "{variable}" placeholders in prompts for dynamic values
6. Return explicit "fail" step type when max retries reached

VARIABLE TRACKING:
- retry_count: Starts at 0, increments on each Builder retry
- tester_feedback: Captured from Tester agent's FAIL result
- max_retries: Configurable (default: 3 from config.yaml)

SUCCESS PATH: step_5 → on_success → step_6 → step_7
RETRY PATH: step_5 → on_failure → check_retry → if_true → builder (retry) → step_5
FAIL PATH: step_5 → on_failure → check_retry → if_false → fail (stop)
```

### Stap 5: Coding MCP Uitbreidingen

**Bestand:** `druppie/mcp-servers/coding/server.py`

**Nodige verbeteringen:**

1. **`run_tests` tool** - Al aanwezig, controleer implementatie:
   - Auto-detect test framework (pytest, jest, go test, etc.)
   - Return formatted output with pass/fail counts
   - Support coverage reports

2. **`run_command` tool** - Voor build commands:
   ```python
   @mcp.tool()
   async def run_command(workspace_id: str, command: str, timeout: int = 60):
       """
       Run a shell command in the workspace (e.g., npm run build)
       """
       # Execute command in workspace directory
       # Return output, exit_code, and error
   ```

3. **Coverage support:**
   - Python: `pytest --cov=src --cov-report=json`
   - Node.js: `npm test -- --coverage --json`
   - Go: `go test -coverprofile=coverage.out`

### Stap 6: Configuratie

**Bestand:** `druppie/core/config.yaml`

Voeg TDD configuratie toe:

```yaml
tdd:
  max_retries: 3
  coverage_threshold: 80
  auto_generate_tests: true
  validation_timeout: 120  # seconds
```

### Stap 7: Router Agent Update

**Bestand:** `druppie/agents/definitions/router.yaml`

Zorg dat router builder en tester agents kent:

```yaml
# Update available agents list
builder: Builder Agent - Implements code following TDD
tester: Tester Agent - Generates tests and validates implementations
```

---

## Testscenario's

### Scenario 1: Succesvol TDD Flow (Python Backend)

1. User: "Create a todo app"
2. Planner genereert plan met 7 steps (architect → approval → tester → builder → tester → approval → deployer)
3. Architect: Maakt architecture.md
4. User approves architecture
5. Tester: Genereert test_*.py files met pytest voor todo CRUD
6. Builder: Implementeert app.py, routes, database
7. Tester: Runt `pytest --cov=. --cov-report=json` → Alle pass, coverage 95% → **PASS**
8. User approves
9. Deployer: Buildt en deployt
10. Result: Working todo app met goede tests

### Scenario 1b: Succesvol TDD Flow (Frontend)

1. User: "Create a React todo app"
2. Planner genereert plan
3. Architect: Maakt architecture.md met Vite + React stack
4. User approves
5. Tester: Genereert *.test.jsx files met Vitest, @testing-library
6. Builder: Implementeert componenten (App.jsx, TodoItem.jsx, TodoList.jsx)
7. Tester: Runt `npm run test -- --coverage --reporter=json` → Alle pass, coverage 92% → **PASS**
8. User approves
9. Deployer: Buildt met multi-stage Dockerfile (node build + nginx)
10. Result: Working React todo app met Vitest tests

### Scenario 2: Retry Flow

1. User: "Create a todo app"
2. ... (steps 1-4 zoals boven)
3. Tester: Genereert tests
4. Builder: Implementeert, maar vergeet error handling
5. Tester: Runt tests → 1 fail (delete zonder ID) → **FAIL**
6. Retry #1: Builder krijgt specifieke feedback
7. Builder: Voegt error handling toe
8. Tester: Runt tests → Alle pass → **PASS**
9. ... (deployment)

### Scenario 3: Max Retries Bereikt

1. User: "Create a complex app"
2. ... (steps 1-4)
3. Builder implementeert, maar heeft fundamenteel probleem
4. Tester: **FAIL** → Retry 1 → Builder fixt → Tester: **FAIL**
5. Retry 2 → Builder fixt → Tester: **FAIL**
6. Retry 3 → Builder fixt → Tester: **FAIL**
7. Max retries (3) bereikt
8. Result: **FAIL** met gedetailleerde uitleg waarom
9. Geen deployment

---

## Validatie Criteria

### PBI Acceptatiecriteria Check

- [x] Twee afzonderlijke agents geïmplementeerd (Builder, Tester)
- [ ] Bouwer en Tester interacteren via feedback-loop
- [ ] Tester valideert functionele én technische requirements
- [ ] Tester kan tests genereren met 100% coverage doelen
- [ ] Samenwerking volgt TDD (test → build → test)
- [ ] Bij afkeuring door Tester wordt Bouwer automatisch opnieuw aangestuurd
- [ ] Feedback-loop ondersteunt configureerbaar maximum retries
- [ ] Tester levert per run expliciet Pass/Fail-resultaat inclusief onderbouwing
- [ ] Tester bepaalt of build voldoende kwaliteit heeft voor acceptatie
- [ ] Planner-agent stuurt Bouwer en Tester aan via toegevoegde instructies
- [ ] Coding MCP is uitgebreid met build- en test-commands

### Test Cases

**Unit Tests:**
- Builder: Implementeert code correct op basis van tests
- Builder: Fixt specifieke issues op basis van feedback
- Tester: Genereert adequate test suite
- Tester: Bepaalt correct PASS/FAIL
- Planner: Genereert correct TDD plan

**Integration Tests:**
- End-to-end TDD flow met succes
- Retry flow werkt correct
- Max retries stopt flow correct
- Pass/Fail resultaat wordt correct verwerkt

**E2E Test:**
- User request → Planner → TDD flow → Deployment

---

## Volgende Stappen

1. ✅ Builder agent definition gecreëerd
2. ✅ Tester agent definition gecreëerd
3. ⏳ Planner agent update met TDD workflow
4. ⏳ Retry mechanism implementeren in loop.py
5. ⏳ Coding MCP validation (run_tests, run_command)
6. ⏳ Configuratie toevoegen (max_retries, coverage_threshold)
7. ⏳ Router agent update
8. ⏳ Testen van individuele agents
9. ⏳ E2E testing van TDD flow
10. ⏳ Documentatie updates

---

## Dependencies

**Interne:**
- Bestaande Planner agent
- Bestaande Architect agent
- Bestaande Deployer agent
- Coding MCP server

**Externe Test Frameworks:**

**Python Backend:**
- `pytest` - Test framework
- `pytest-cov` - Coverage reporting
- `pytest-asyncio` - Async test support (optioneel)

**Frontend (Vite/React):**
- `vitest` - Test framework (Vite-native)
- `@testing-library/react` - React component testing
- `@testing-library/jest-dom` - Custom matchers
- `@testing-library/user-event` - User interaction simulation

**Node.js Backend:**
- `jest` - Test framework
- `supertest` - HTTP endpoint testing
- `@types/jest` - TypeScript support (optioneel)

---

## Risico's en Mitigaties

**Risico 1:** Tester genereert onvoldoende tests
- **Mitigatie:** Sterre prompts in tester.yaml met coverage requirements

**Risico 2:** Builder gaat in oneindige loop
- **Mitigatie:** Hard limit op max_retries (standaard 3)

**Risico 3:** Test result parsing faalt
- **Mitigatie:** Gebruik gestructureerde output format met duidelijke markers

**Risico 4:** Coding MCP run_tests werkt niet voor alle frameworks
- **Mitigatie:** Auto-detect met fallback op handmatige command execution

---

## Appendix

### Test Framework Detection Logic

```python
def detect_test_framework(workspace):
    """Detect which test framework to use based on project structure"""
    # Python Backend - Pytest
    if exists("pytest.ini") or exists("pyproject.toml") or any(f.startswith("test_") for f in files):
        return "pytest"
    # Frontend - Vitest (preferred for Vite/React projects)
    if exists("vite.config.js") or exists("vite.config.ts"):
        return "vitest"
    # Node.js Backend - Jest (preferred for backend Node.js)
    if exists("package.json") and "test" in package_json["scripts"]:
        return "jest"
    return None
```

### Coverage Commands per Framework

| Framework | Use Case | Command | Output Format |
|----------|----------|---------|---------------|
| Pytest | Python Backend | `pytest --cov=. --cov-report=json --cov-report=term` | coverage.json |
| Vitest | Frontend (Vite/React) | `npm run test -- --coverage --reporter=json` | coverage/coverage-final.json |
| Jest | Node.js Backend | `npm test -- --coverage --coverageReporters=json` | coverage/coverage-final.json |

### Example Test Code

**Pytest (Python Backend):**
```python
# test_todos.py
import pytest
from app import app, db
from models import Todo

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()

def test_create_todo(client):
    response = client.post('/api/todos', json={
        'title': 'Test todo',
        'completed': False
    })
    assert response.status_code == 201
    assert response.json['title'] == 'Test todo'
    assert response.json['completed'] is False

def test_get_todo(client):
    # First create a todo
    client.post('/api/todos', json={'title': 'Test'})
    # Then retrieve it
    response = client.get('/api/todos/1')
    assert response.status_code == 200
    assert response.json['title'] == 'Test'

def test_delete_todo(client):
    client.post('/api/todos', json={'title': 'Test'})
    response = client.delete('/api/todos/1')
    assert response.status_code == 204
```

**Vitest (Frontend/React):**
```jsx
// TodoList.test.jsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import TodoList from './TodoList'

describe('TodoList', () => {
  const mockTodos = [
    { id: 1, title: 'Test todo', completed: false }
  ]

  it('renders todo items', () => {
    render(<TodoList todos={mockTodos} />)
    expect(screen.getByText('Test todo')).toBeInTheDocument()
  })

  it('calls onToggle when clicking a todo', () => {
    const onToggle = vi.fn()
    render(<TodoList todos={mockTodos} onToggle={onToggle} />)
    fireEvent.click(screen.getByText('Test todo'))
    expect(onToggle).toHaveBeenCalledWith(1)
  })

  it('shows completed todos with strikethrough', () => {
    const completedTodo = { ...mockTodos[0], completed: true }
    render(<TodoList todos={[completedTodo]} />)
    const todoElement = screen.getByText('Test todo')
    expect(todoElement).toHaveClass('line-through')
  })
})
```

**Jest (Node.js Backend):**
```javascript
// todos.test.js
const request = require('supertest')
const app = require('../app')

describe('Todo API', () => {
  describe('POST /api/todos', () => {
    it('should create a new todo', async () => {
      const response = await request(app)
        .post('/api/todos')
        .send({ title: 'Test todo', completed: false })
        .expect(201)

      expect(response.body).toHaveProperty('id')
      expect(response.body.title).toBe('Test todo')
      expect(response.body.completed).toBe(false)
    })

    it('should return 400 for invalid input', async () => {
      const response = await request(app)
        .post('/api/todos')
        .send({ title: '' })
        .expect(400)

      expect(response.body.error).toBeDefined()
    })
  })

  describe('GET /api/todos/:id', () => {
    it('should return a todo by id', async () => {
      // Create a todo first
      const createResponse = await request(app)
        .post('/api/todos')
        .send({ title: 'Test todo' })

      // Then get it
      const response = await request(app)
        .get(`/api/todos/${createResponse.body.id}`)
        .expect(200)

      expect(response.body.title).toBe('Test todo')
    })

    it('should return 404 for non-existent todo', async () => {
      await request(app)
        .get('/api/todos/999')
        .expect(404)
    })
  })
})
```

---

**Status:** Plan gereed voor implementatie
**Versie:** 1.0
**Datum:** 2026-02-05
