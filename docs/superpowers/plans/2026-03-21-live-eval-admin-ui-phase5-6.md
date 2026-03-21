# Phase 5 (Live Evaluation) & Phase 6 (Admin UI + Docker Profiles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add background evaluation of completed agent runs (Phase 5) and an admin UI with Docker Compose test profiles (Phase 6).

**Architecture:** Live evaluator hooks into orchestrator completion path, fires background tasks using existing JudgeEngine. REST API endpoints expose results. React admin page shows benchmark runs with drill-down. Docker Compose profiles for test isolation.

**Tech Stack:** Python/FastAPI, SQLAlchemy, React, @tanstack/react-query, Tailwind CSS, Docker Compose

## Tasks (11 total)

- Task 1: Evaluation config YAML loader
- Task 2: Live evaluator service (background evaluation)
- Task 3: Hook into orchestrator completion path
- Task 4: Evaluation repository (DB queries)
- Task 5: Evaluation service (business logic)
- Task 6: API routes for evaluations (admin only)
- Task 7: Frontend API client functions
- Task 8: Admin Evaluations page (React)
- Task 9: Wire up frontend navigation
- Task 10: Docker Compose test profiles
- Task 11: Full pipeline verification

## Dependencies

Tasks 1, 2, 4, 10 are independent (parallel).
Task 3 depends on Tasks 1, 2.
Task 5 depends on Task 4.
Task 6 depends on Task 5.
Task 7 depends on Task 6.
Task 8 depends on Task 7.
Task 9 depends on Task 8.
Task 11 depends on all.
