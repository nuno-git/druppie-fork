---
id: "017"
title: "Security & Compliance: Prompt Injection Defense and Input Validation"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 017: Security & Compliance: Prompt Injection Defense and Input Validation

## Problem

User input is passed directly into agent prompts without sanitization or boundary enforcement. There is no defense against prompt injection — a user could craft input that overrides agent instructions. HITL responses and tool results are also unvalidated, creating indirect injection vectors. There is no API rate limiting.

## Goal

Multi-layer input security: (1) a lightweight compliance agent that validates every user message and HITL response before it reaches the agent pipeline, (2) prompt injection defenses (boundary instructions, input classification), (3) API rate limiting to prevent abuse.

## User Journey

1. User sends a chat message.
2. Compliance agent (fast, cheap model) runs a safety check before the Router.
3. If safe: message proceeds to Router → normal pipeline.
4. If unsafe: message is blocked, user sees "Input blocked: potential prompt injection" with an explanation.
5. Agent reads a file via MCP tool — tool result is optionally validated for indirect injection.
6. User answers a HITL question — compliance agent validates the answer before passing it to the waiting agent.

## Constraints

- Compliance check must be fast (<500ms) and cheap (small model, simple prompt).
- Must return pass/fail with optional sanitized content.
- Failed validations block the input and notify the user.
- Must not block legitimate user input (low false-positive rate).
- Rate limiting must be configurable per user role.

## Out of Scope

- Output sanitization (validating what agents produce, not what users input).
- Encryption at rest beyond current PostgreSQL defaults.
- DDoS protection (infrastructure-level concern).

## Open Questions

- **Q1: Classification vs generation for compliance checks?**
  - Option A: Classification (is this safe?) — faster, cheaper.
  - Option B: Generation (sanitize and rewrite) — more flexible, higher latency.
  - Owner: architect.

## Linked Documents

- Source: `docs/BACKLOG.md` — "Prompt Injection Protection", "Compliance Agent for Input Validation", "No API Rate Limiting"
