# Design Workflow Improvement Tickets

---

### 1. Architect: Multi-Solution Proposals with Pros/Cons

The architect currently produces one solution and writes the TD. Instead, it should present 2-3 solution options to the user via HITL with pros/cons, cost/complexity tradeoffs, and a recommendation. User picks. Only then does the architect write the TD for the chosen option.

---

### 2. Platform Standards File (Checked, Not Generated)

Create a `standards.yaml` (or similar) that defines things that are always true: data must be encrypted at rest, auth is Keycloak, containers run non-root, BIO classification is BBN, GDPR legal basis is checked, etc. The architect validates the design against these standards and only flags violations — it does not regenerate the same security/compliance tables from scratch every time.

---

### 3. Introduce SPEC.md (Actual Specification)

Add a specification document between TD and builder_plan. Contains: API endpoints with request/response schemas, data models with field-level detail, component interfaces, error handling table, state diagrams. This is the contract that test_builder and builder both work from. No more guessing.

---

### 4. Research-First Architect Workflow

Before designing, the architect must investigate: read similar projects' source code and TDs, analyze what patterns they used, check what modules they integrated and how. The research findings go into the TD as justification. Currently it calls `list_modules()` and `list_projects()` and moves on — that's not research.

---

### 5. Slim Down the TD Template

The current TD is 60% governance tables (NORA layers, compliance, security). Move the standard/repeatable governance checks into the standards file (ticket #2). The TD should focus on: architectural decisions made, component design, data flows, integration points, and why this approach was chosen over alternatives.

---

### 6. Spec-to-Test Traceability

Test builder should generate tests directly from SPEC.md with requirement IDs (e.g., `test_FR01_create_measurement`). Each spec requirement maps to at least one test. After tests run, produce a coverage-against-spec report — not just code coverage.

---

### 7. Builder Can Request Spec Clarification

Add a mechanism for the builder or test_builder to flag ambiguities in the spec and pause for clarification instead of guessing silently. Currently the pipeline is strict waterfall with no upward feedback.

---

### 8. Reusable Architecture Patterns Library

Maintain a library of proven patterns from past projects (e.g., "Python FastAPI service with health endpoint", "React SPA with Druppie SDK", "data pipeline with scheduled ingestion"). The architect references these instead of designing from zero each time. Patterns include file structure, dependencies, and Dockerfile templates.

---

### 9. Architect Reads Past Project Outcomes

When the architect does Level 2 research, it should not just list projects — it should read their TDs, check if they were successfully deployed, and learn from them. If a past project used a similar approach and failed 3 TDD cycles, that's relevant information.

---

### 10. Standards Validation as a Separate Step

Instead of the architect doing governance checks inline (which bloats the TD), add a lightweight validation agent or step that runs the approved TD against `standards.yaml` and produces a pass/fail checklist. Architect focuses on design, validator focuses on compliance.

---

### 11. Move TDD Flow Into OpenCode (Single Sandbox)

The current TDD flow is slow and fragile: test_builder writes tests via MCP tools, builder spawns a sandbox to implement, test_executor spawns another sandbox to run tests, and on failure we bounce between agents up to 3 times — each time spinning up a new sandbox, cloning the repo, installing deps. That's 6+ sandbox boots for one retry cycle.

Instead, collapse the entire build+test loop into a single OpenCode sandbox session. One sandbox gets the spec/plan, writes tests, implements code, runs tests, and iterates internally until green — all within one container with deps already installed. The Druppie agents just hand off the spec and receive the result. Faster, cheaper, and OpenCode's built-in edit-test loop is better at TDD than our multi-agent handoff.
