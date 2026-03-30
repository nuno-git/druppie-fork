# Evaluation Framework (Phases 2 & 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add DB models for evaluation results and build the LLM-as-Judge engine that loads YAML rubric definitions, extracts context from the DB, calls a judge LLM, and stores scored results.

**Architecture:** Evaluation definitions in `evaluations/` YAML files. JudgeEngine loads definitions, extracts context from DB (tool calls, messages, agent definitions), renders rubric prompts, calls judge LLM, parses JSON scores, stores in `benchmark_runs` + `evaluation_results` tables. CLI script for manual evaluation runs.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, Pydantic 2.x, PyYAML, ChatLiteLLM (existing), pytest

---

## File Structure

See plan details for full file tree covering DB models, domain models, evaluation engine, YAML definitions, CLI script, and tests.

## Tasks

- Task 1: DB Models (benchmark_run.py, evaluation_result.py)
- Task 2: Domain Models (evaluation.py with Summary/Detail pattern)
- Task 3: Evaluation YAML Schema (schema.py for rubric definitions)
- Task 4: Context Extraction (extract tool calls, messages, agent defs from DB)
- Task 5: Judge Engine (ties everything together)
- Task 6: Sample Evaluation YAML Files (architect + builder rubrics)
- Task 7: CLI Script (scripts/evaluate.py)
- Task 8: Full Test Suite Verification

## Dependencies

Tasks 1, 2, 3 are independent (parallel).
Task 4 depends on Task 3.
Task 5 depends on Tasks 1, 2, 3, 4.
Task 6 can start after Task 3.
Tasks 7, 8 depend on Task 5.
