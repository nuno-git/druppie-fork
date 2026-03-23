# Testing Framework v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the testing framework with three seed modes (record_only, replay, live), three-layer tool verification, comprehensive test suite (~45 tests), and an analytics dashboard with graphs.

**Architecture:** Backend extends existing testing modules with replay executor, result validators, and side-effect verifiers. New TestAssertionResult DB model stores per-assertion results for analytics. Frontend adds two new pages (Analytics, BatchDetail) using Recharts for visualization.

**Tech Stack:** Python/FastAPI, SQLAlchemy, Pydantic, React, Recharts, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-23-testing-framework-v3-design.md`

---

### Task 1: DB Models — TestAssertionResult + TestRun extensions

**Files:**
- Create: `druppie/db/models/test_assertion_result.py`
- Modify: `druppie/db/models/test_run.py`
- Modify: `druppie/db/models/__init__.py`

- [ ] **Step 1: Create TestAssertionResult model**
- [ ] **Step 2: Add agent_id + mode columns to TestRun, add indexes**
- [ ] **Step 3: Register in __init__.py**
- [ ] **Step 4: Reset DB to apply changes**
- [ ] **Step 5: Commit**

---

### Task 2: Schema Extensions — seed_schema + v2_schema

**Files:**
- Modify: `druppie/testing/seed_schema.py`
- Modify: `druppie/testing/v2_schema.py`

- [ ] **Step 1: Add `execute` field to ToolCallFixture, `mode` to SessionFixture**
- [ ] **Step 2: Add `mode`, `seed_sessions`, `verify`, `result_valid`, `status`, `error_contains` to v2_schema**
- [ ] **Step 3: Commit**

---

### Task 3: Replay Config

**Files:**
- Create: `druppie/testing/replay_config.py`
- Create: `testing/profiles/replay_config.yaml`

- [ ] **Step 1: Create Pydantic model for replay config**
- [ ] **Step 2: Create YAML config with blocklist + defaults**
- [ ] **Step 3: Commit**

---

### Task 4: Result Validators (Layer 1)

**Files:**
- Create: `druppie/testing/result_validators.py`

- [ ] **Step 1: Implement validators (not_empty, no_error, json_parseable, contains, matches)**
- [ ] **Step 2: Commit**

---

### Task 5: Side-Effect Verifiers (Layer 2)

**Files:**
- Create: `druppie/testing/verifiers.py`

- [ ] **Step 1: Implement verifiers (file_exists, file_not_empty, file_contains, mermaid_valid, etc.)**
- [ ] **Step 2: Commit**

---

### Task 6: Replay Executor

**Files:**
- Create: `druppie/testing/replay_executor.py`
- Modify: `druppie/testing/seed_loader.py`

- [ ] **Step 1: Implement ReplayExecutor with should_execute, get_mock_result, execute_tool**
- [ ] **Step 2: Add mode parameter to seed_loader, wire up replay path**
- [ ] **Step 3: Commit**

---

### Task 7: Extended Assertions — v2_assertions.py

**Files:**
- Modify: `druppie/testing/v2_assertions.py`

- [ ] **Step 1: Add result_valid, status, error_contains, error_matches assertion types**
- [ ] **Step 2: Add verify runner that executes side-effect checks**
- [ ] **Step 3: Commit**

---

### Task 8: Test Runner — v2_runner.py extensions

**Files:**
- Modify: `druppie/testing/v2_runner.py`

- [ ] **Step 1: Handle seed_sessions with mode overrides**
- [ ] **Step 2: Store TestAssertionResult rows for each assertion/judge/verify result**
- [ ] **Step 3: Store agent_id and mode on TestRun**
- [ ] **Step 4: Commit**

---

### Task 9: New Eval Definitions (10 new evals)

**Files:**
- Create: `testing/evals/planner-correct-next-agent.yaml`
- Create: `testing/evals/planner-two-step-plan.yaml`
- Create: `testing/evals/ba-writes-fd.yaml`
- Create: `testing/evals/ba-asks-questions.yaml`
- Create: `testing/evals/architect-design-quality.yaml`
- Create: `testing/evals/agent-uses-done.yaml`
- Create: `testing/evals/agent-status-signal.yaml`
- Create: `testing/evals/tool-returns-valid-result.yaml`
- Create: `testing/evals/hitl-question-quality.yaml`
- Create: `testing/evals/workflow-agent-sequence.yaml`

- [ ] **Step 1: Write all 10 eval YAML files**
- [ ] **Step 2: Commit**

---

### Task 10: New Test Definitions — Router + Planner + BA + Architect

**Files:**
- Create/Modify: `testing/tests/router-*.yaml` (5 new)
- Create: `testing/tests/planner-*.yaml` (7 new)
- Create: `testing/tests/ba-*.yaml` (4 new)
- Create: `testing/tests/architect-*.yaml` (5 new)

- [ ] **Step 1: Write router tests (ambiguous, nonexistent, dutch, empty, gibberish)**
- [ ] **Step 2: Write planner tests (7 tests)**
- [ ] **Step 3: Write BA tests (4 tests)**
- [ ] **Step 4: Write architect tests (5 tests)**
- [ ] **Step 5: Commit**

---

### Task 11: New Test Definitions — Tool Integration + E2E + HITL + Edge

**Files:**
- Create: `testing/tests/tool-*.yaml` (17 new)
- Create: `testing/tests/e2e-*.yaml` (6 new)
- Create: `testing/tests/hitl-*.yaml` (3 new)
- Create: `testing/tests/edge-*.yaml` (3 new)
- Create: `testing/sessions/architect-bad-mermaid.yaml` (for Layer 3 tests)

- [ ] **Step 1: Write tool integration tests (Layer 1, 2, 3)**
- [ ] **Step 2: Write E2E workflow tests**
- [ ] **Step 3: Write HITL + edge case tests**
- [ ] **Step 4: Write supporting session fixtures**
- [ ] **Step 5: Commit**

---

### Task 12: Analytics API Endpoints

**Files:**
- Modify: `druppie/api/routes/evaluations.py`

- [ ] **Step 1: Add analytics endpoints (summary, trends, by-agent, by-eval, by-tool, by-test, batch detail)**
- [ ] **Step 2: Add test-assertion-results detail endpoint for batch drill-down**
- [ ] **Step 3: Commit**

---

### Task 13: Frontend — Install Recharts + API Client

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/services/api.js`

- [ ] **Step 1: Install recharts**
- [ ] **Step 2: Add analytics API client functions**
- [ ] **Step 3: Commit**

---

### Task 14: Frontend — Analytics Page

**Files:**
- Create: `frontend/src/pages/Analytics.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Create Analytics page with summary cards, trend line chart, by-agent/eval/tool bar charts, slowest tests table, recent batches list**
- [ ] **Step 2: Add route in App.jsx**
- [ ] **Step 3: Commit**

---

### Task 15: Frontend — Batch Detail Page

**Files:**
- Create: `frontend/src/pages/BatchDetail.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Create BatchDetail page with pie chart, bar chart, expandable test results with assertion details**
- [ ] **Step 2: Add route in App.jsx**
- [ ] **Step 3: Commit**

---

### Task 16: Frontend — Link Evaluations page to Analytics/Batch pages

**Files:**
- Modify: `frontend/src/pages/Evaluations.jsx`

- [ ] **Step 1: Add analytics link at top**
- [ ] **Step 2: Add batch detail link on each batch row**
- [ ] **Step 3: Commit**

---

### Task 17: Testing Guide

**Files:**
- Create: `testing/GUIDE.md`

- [ ] **Step 1: Write comprehensive guide on creating tests, evals, sessions, and using the framework**
- [ ] **Step 2: Commit**

---

### Task 18: Verify Everything Works

- [ ] **Step 1: Reset DB**
- [ ] **Step 2: Run seed to populate test data**
- [ ] **Step 3: Run pytest to ensure no regressions**
- [ ] **Step 4: Verify admin UI loads analytics page**
- [ ] **Step 5: Final commit**
