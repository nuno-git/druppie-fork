# Spec-Driven Documentation Framework

This document describes the complete specification-driven framework for the Druppie platform. It covers all artifact types, the enforcement loop, skills, and the hierarchical memory strategy.

**Status:** Active
**Branch:** `feature/vast-documentatieformat`
**Last updated:** 2026-06-09

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Eight Pillars](#2-the-eight-pillars)
3. [Directory Structure](#3-directory-structure)
4. [Artifact Lifecycle](#4-artifact-lifecycle)
5. [The Enforcement Loop (The Harness)](#5-the-enforcement-loop-the-harness)
6. [Skills — Contextual Loop Focus](#6-skills--contextual-loop-focus)
7. [Hierarchical Memory & Context Management](#7-hierarchical-memory--context-management)
8. [Putting It All Together — Feature Walkthrough](#8-putting-it-all-together--feature-walkthrough)
9. [Tooling Stack](#9-tooling-stack)
10. [Getting Started](#10-getting-started)

---

## 1. Overview

Druppie's documentation framework ensures that every decision is captured, every behavior is described in readable executable form, and every rule is automatically checked — so the product stays consistent even as team members and AI agents come and go.

The framework is built on a key insight from Michal's talk: **humans and LLMs both suffer from limited context**. People forget. LLMs context-compact. Without captured decisions, teams end up like the five monkeys — following rules without knowing why.

### Core Principles

1. **Text-based, agent-readable** — Every artifact is Markdown that humans and AI agents can read
2. **Enforced, not just documented** — Rules have corresponding lint/CI checks
3. **Living, not static** — The Current Architecture Specification (CAS) auto-updates from accepted ADRs
4. **Linked, not isolated** — PRDs link to ADRs, BDD scenarios link to PRDs, everything traces back

---

## 2. The Eight Pillars

| Pillar | Purpose | Format | Location |
|--------|---------|--------|----------|
| **Research** | Investigate options before committing to a decision | Markdown with trade-off tables | `docs/research/` |
| **ADR** | Record why a technical decision was made and how it's enforced | Markdown with YAML frontmatter | `docs/adrs/` |
| **PRD** | Describe why a feature exists, the problem, user journey | Lightweight Markdown | `docs/prds/` |
| **BDD** | Executable specification of what the system does | Gherkin `.feature` files | `testing/bdd/` |
| **Design System** | Component library, visual rules, usage constraints | Markdown + code examples | `docs/design-system/` |
| **CAS** | Current Architecture Specification — living snapshot of all active rules | Auto-generated Markdown | `docs/adrs/CAS.md` |
| **Memory** | Hierarchical context management for agents | Runtime (DB-backed) | Agent loop integration |
| **Harness** | Git hooks + CI that enforce all rules | Config files | Root of repo |

---

## 3. Directory Structure

```
docs/
├── adrs/                          # Architecture Decision Records
│   ├── TEMPLATE.md                # Template for new ADRs
│   ├── 001-*.md                   # Sequential ADR files
│   ├── 002-*.md
│   └── CAS.md                     # Auto-generated Current Architecture Spec
├── research/                      # Research documents (pre-ADR investigation)
│   └── TEMPLATE.md
├── prds/                          # Product Requirements Documents
│   └── TEMPLATE.md
├── design-system/                 # Frontend design system
│   ├── README.md                  # Component index + visual rules
│   └── components/                # Per-component documentation
│       └── button.md
├── specs/                         # Existing: platform standards
│   └── platform-standards.md
├── BACKLOG.md                     # Existing
├── FEATURES.md                    # Existing
├── TECHNICAL.md                   # Existing
├── TESTING.md                     # Existing
├── SANDBOX.md                     # Existing
└── SPEC-FRAMEWORK.md              # This file

testing/
├── tools/                         # Existing: YAML tool tests
├── agents/                        # Existing: YAML agent tests
├── checks/                        # Existing: assertion bundles
├── profiles/                      # Existing: judges, HITL
└── bdd/                           # NEW: BDD acceptance tests
    ├── features/                  # Gherkin .feature files
    │   ├── approval-workflow.feature
    │   └── session-lifecycle.feature
    └── steps/                     # Python step definitions
        ├── approval_steps.py
        ├── session_steps.py
        └── environment.py

druppie/skills/                    # Skills (existing + new framework skills)
├── feature-dev/SKILL.md           # NEW: end-to-end feature workflow
├── refactor/SKILL.md              # NEW: safe refactoring
├── bug-fix/SKILL.md               # NEW: root cause → fix → verify
├── adr-writer/SKILL.md            # NEW: ADR creation guidance
├── research-writer/SKILL.md       # NEW: research doc writing
├── prd-writer/SKILL.md            # NEW: PRD writing
├── generate-cas/SKILL.md          # NEW: CAS regeneration
├── architecture-principles/       # Existing
├── code-review/                   # Existing
├── git-workflow/                  # Existing
└── ...                            # Other existing skills

scripts/
├── generate_cas.py                # Generate CAS.md from accepted ADRs
├── validate_doc_links.py          # Validate cross-references
└── validate_adr_status.py         # Validate ADR frontmatter

# Enforcement config (root of repo)
lefthook.yml                       # Git hooks
.importlinter                      # Architecture import rules
```

---

## 4. Artifact Lifecycle

### Research → ADR → Implementation

```
Research (investigation)
  │
  ├── Question identified
  ├── Findings documented
  ├── Trade-off analysis
  └── Recommendation
        │
        ▼
  ADR (decision record)
  │
  ├── status: proposed
  ├── Review & discussion
  ├── status: accepted
  ├── Enforcement configured
  └── CAS regenerated
        │
        ▼
  Implementation
  │
  ├── PRD written (if feature)
  ├── BDD scenarios written
  ├── Code implemented
  ├── Lint + tests pass
  └── Merged
```

### ADR Status Model

| Status | Meaning | Agent visibility |
|--------|---------|-----------------|
| `proposed` | Under review, not yet accepted | Not loaded by agents |
| `accepted` | Active rule, currently enforced | Loaded via CAS |
| `deprecated` | Still valid but should not be used for new work | Visible but flagged |
| `superseded` | Replaced by a newer ADR (`superseded_by` field) | Not loaded by agents |

### Supersession Flow

When a new ADR replaces an old one:

1. Create new ADR with `status: accepted`
2. Update old ADR: `status: superseded`, add `superseded_by: "NNN"`
3. Same PR updates enforcement rules (lint config, CI)
4. Regenerate CAS — old rule disappears, new rule appears
5. Agents on next task load fresh CAS and never see the old rule

---

## 5. The Enforcement Loop (The Harness)

The harness ensures that every declared rule is automatically verified at commit time and in CI.

```
Developer/Agent writes code
          │
          ▼
  ┌──────────────────┐
  │  pre-commit hook  │  ← fast checks
  │  • ruff lint      │
  │  • black format   │
  │  • import-linter  │
  │  • doc link check │
  │  • ADR validation │
  └──────┬───────────┘
         │ passes
         ▼
  Push to remote → CI pipeline
         │
         ▼
  ┌─────────────────────────────┐
  │  1. Lint & format           │
  │  2. Architecture compliance │
  │  3. Type checking           │
  │  4. BDD suite               │
  │  5. YAML tool/agent tests   │
  │  6. Doc link validation     │
  │  7. CAS freshness check     │
  └──────┬──────────────────────┘
         │ fails? → agent/human gets exact rule violation + link to ADR
         ▼
       Merge if green
```

### What the Loop Checks

| Check | Tool | What it catches |
|-------|------|----------------|
| Python lint | ruff | Style, unused imports, complexity |
| Python format | black | Formatting consistency |
| Architecture layers | import-linter | API importing DB, domain importing services |
| Doc cross-references | validate_doc_links.py | Broken links between PRD↔ADR↔BDD |
| ADR consistency | validate_adr_status.py | Superseded without replacement, invalid status |
| CAS freshness | validate_doc_links.py | CAS.md stale vs accepted ADRs |
| BDD scenarios | behave | Acceptance criteria violations |
| Integration tests | YAML framework | Full pipeline regressions |

### Agent Failure Recovery

When an agent's commit fails the harness:

1. Agent sees the exact error (lint message, import violation)
2. Error message links to the relevant ADR (e.g., `See ADR-001: Layered Architecture`)
3. Agent reads the ADR for context on *why* the rule exists
4. Agent fixes the violation and re-commits
5. Loop continues until all checks pass

---

## 6. Skills — Contextual Loop Focus

Skills tailor the enforcement loop's focus for different task types. Each skill is a Markdown file in `druppie/skills/<name>/SKILL.md` that the agent reads when `invoke_skill` is called.

| Skill | When used | Documents loaded | Loop focus |
|-------|-----------|-----------------|------------|
| `feature-dev` | Building a new feature | PRD, relevant BDD, ADRs, CAS | Full lint + BDD tag filter |
| `refactor` | Changing structure without behavior | ADRs for boundaries, import rules | Architecture lint + duplication |
| `bug-fix` | Fixing a failing behavior | Failing BDD scenario, related PRD | Affected scenario + unit tests |
| `adr-writer` | Proposing or modifying an ADR | All ADRs, affected code | ADR consistency check |
| `research-writer` | Investigating options | Existing research, related ADRs | Doc link validation |
| `prd-writer` | Writing a feature spec | Related ADRs, BDD scenarios | Doc link validation |
| `generate-cas` | After ADR acceptance | All accepted ADRs | CAS freshness |

### How Agents Use Skills

1. Agent YAML definition includes `skills: [feature-dev, adr-writer]`
2. When the agent calls `invoke_skill(skill_name="feature-dev")`:
   - The skill's `allowed_tools` are added to the agent's tool set
   - The skill's Markdown body is returned as instructions
3. The agent follows the workflow described in the skill
4. If a rule violation occurs, the agent re-reads the linked ADR

---

## 7. Hierarchical Memory & Context Management

Based on the insight that **agents don't fail because of prompts, they fail because of context**.

### The Problem

- Long agent sessions accumulate messages without limit
- Context windows fill up with tool call results, conversation history, and intermediate reasoning
- Over-truncation breaks reasoning (agent forgets what it was doing)
- Raw summarization is unreliable (LLM decides what's important, inconsistently)

### The Solution: Smart Truncation + Memory Store

```
Agent's context window:
┌──────────────────────────────────────────────────┐
│ HEAD (always present)                             │
│ • System prompt                                   │
│ • First user message                              │
│ • Current task description                        │
├──────────────────────────────────────────────────┤
│ MEMORY REFERENCE                                  │
│ "N earlier exchanges available. Use memory_recall │
│  to retrieve specific context."                   │
├──────────────────────────────────────────────────┤
│ TAIL (always present)                             │
│ • Last K tool exchanges                           │
│ • Most recent results                             │
│ • Current reasoning context                       │
└──────────────────────────────────────────────────┘
```

**How it works:**
1. **Head** — System prompt + first user message (always kept)
2. **Middle** — Compressed and offloaded to memory store (DB table)
3. **Tail** — Last N tool exchanges (always kept)
4. **Memory recall** — Agent can use `memory_recall(query)` to retrieve specific offloaded context

### Sub-Agent Offloading

Heavy data operations (search, analysis, large file reads) run in sub-agents:
- Main agent context stays small (chat + light context only)
- Sub-agent handles heavy data in its own context
- Only the result (not the process) passes back to main agent

### Long-Session Evaluation

- Load 10 turns, test the 11th
- Context management bugs become testable
- Part of the CI pipeline for agent behavior tests

### Agent Configuration

```yaml
# In agent YAML definitions
context_budget: 8000    # tokens; 0 = unlimited (current behavior)
memory_enabled: true    # enable smart truncation + memory store
```

---

## 8. Putting It All Together — Feature Walkthrough

### Scenario: "Bulk Export" feature

**Step 1: Research** — Agent investigates ZIP file generation libraries, streaming approaches.
- Output: `docs/research/004-zip-export-approaches.md`
- Result: Python `zipfile` + background jobs recommended

**Step 2: ADR** — Agent records the architectural decision.
- Output: `docs/adrs/004-background-jobs-for-exports.md` (status: proposed)
- After review: status → accepted
- CAS regenerated automatically

**Step 3: PRD** — Agent describes the feature.
- Output: `docs/prds/001-bulk-export.md`
- Links to: ADR-004, BDD scenarios

**Step 4: BDD** — Agent writes acceptance criteria.
- Output: `testing/bdd/features/bulk-export.feature`
- Tagged: `@prd docs/prds/001-bulk-export.md`
- Scenarios: successful export, exceeding max reports, concurrent export prevention

**Step 5: Implementation** — Agent follows feature-dev skill.
- Loads CAS, ADR-004, PRD-001
- Writes code following layered architecture
- Pre-commit hook runs: lint passes, import-linter passes

**Step 6: Verification** — BDD scenarios run, tests pass.

**Step 7: Merge** — CI runs full suite, CAS freshness check passes, merge to `colab-dev`.

---

## 9. Tooling Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Git hooks | [lefthook](https://github.com/evilmartians/lefthook) | Fast pre-commit/pre-push checks |
| Python lint | [ruff](https://docs.astral.sh/ruff/) | Style, complexity, imports |
| Python format | [black](https://github.com/psf/black) | Formatting |
| Architecture lint | [import-linter](https://github.com/seddonym/import-linter) | Layer import rules |
| BDD | [behave](https://github.com/behave/behave) | Gherkin feature runner |
| Integration tests | YAML framework (existing) | Full MCP pipeline tests |
| Doc validation | Custom scripts | Cross-reference checking |
| CAS generation | `scripts/generate_cas.py` | Auto-generate from ADRs |
| Skills | Markdown + YAML | Agent guidance |
| Context management | Agent loop integration | Smart truncation + memory |

---

## 10. Getting Started

### For Humans

1. **New to the project?** Read `docs/adrs/CAS.md` — it's the current architecture state
2. **Making a decision?** Use the ADR template in `docs/adrs/TEMPLATE.md`
3. **Building a feature?** Write a PRD first using `docs/prds/TEMPLATE.md`
4. **Investigating options?** Document research in `docs/research/TEMPLATE.md`
5. **Adding a frontend component?** Follow `docs/design-system/README.md`

### For AI Agents

1. **Before any task:** Load `docs/adrs/CAS.md` for current architecture state
2. **Feature work:** Invoke `feature-dev` skill
3. **Writing an ADR:** Invoke `adr-writer` skill
4. **Fixing a bug:** Invoke `bug-fix` skill
5. **Refactoring:** Invoke `refactor` skill
6. **After ADR acceptance:** Invoke `generate-cas` skill to update CAS

### First-Time Setup

```bash
# Install enforcement tools
pip install import-linter lefthook
cd frontend && npm install && cd ..

# Install lefthook git hooks
lefthook install

# Generate initial CAS (if not present)
python scripts/generate_cas.py

# Validate everything
python scripts/validate_doc_links.py docs/
python scripts/validate_adr_status.py
lint-imports
```

---

## Preventing "Monkey-Ladder" Amnesia

This framework prevents the five-monkeys problem through three mechanisms:

1. **ADRs capture the "why"** — Every non-trivial decision has context, rationale, and consequences documented. New team members and agents read ADRs to understand *why* things are the way they are.

2. **The harness enforces the "what"** — Rules aren't just documented, they're linted. You can't accidentally violate an architecture rule without getting caught. The error message points you to the ADR explaining why the rule exists.

3. **The CAS provides the "now"** — Agents don't need to sift through a history of decisions. They read one document — the CAS — that tells them the current state of the architecture. Individual ADRs are available when they need the full rationale.

**Humans leaving:** Decisions live in permanent ADRs. Lint rules enforce them automatically.

**LLM context compaction:** Important constraints survive because the agent re-reads documents after rule violations. The loop re-injects the relevant ADR/PRD/BDD scenario on every failure.

**Consistency:** Architecture rules and the design system act as automated guards. Tabs vs spaces, import ordering, layer violations — these are not for discussion. They are rules, and they are enforced.

---

*"May the spec be with you."*
