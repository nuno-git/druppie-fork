---
id: "006"
title: "Bilingual Translation Subsystem"
status: implemented
author: nuno
date: 2026-06-10
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/006-translation-subsystem.md"]
linked_research: []
linked_specs: ["testing/specs/features/translation-subsystem.feature"]
---

# PRD 006: Bilingual Translation Subsystem

## Problem

Druppie users (Dutch waterschap staff) need agent outputs in Dutch. Agents may produce English output depending on the LLM provider and prompt configuration. Asking each agent to produce bilingual output would bloat system prompts and reduce output quality. A centralized translation layer ensures consistency.

## Goal

A backend translation service that translates agent outputs between Dutch and English on demand. The service preserves markdown formatting, code blocks, file paths, and technical terms. The translation model is configurable without code changes.

## User Journey

1. Agent produces output (summary, plan, or chat message) in whatever language the LLM generates.
2. Frontend or API consumer requests translation to the user's preferred language.
3. Translation service detects input language via heuristic checks.
4. Service calls LiteLLM with the configured translation model.
5. Translated output preserves markdown structure and technical terms.
6. Translated text returned to the consumer.

## Constraints

- Translation model configurable via environment variables.
- LiteLLM as the abstraction layer (swappable models).
- Markdown formatting must be preserved.
- Code blocks, file paths, and proper nouns must not be translated.

## Out of Scope

- Real-time streaming translation.
- Translation of agent system prompts (those are authored in the target language directly).
- Translation memory or glossary features.

## Open Questions

None. The feature is implemented.

## Linked Documents

- ADR 006: docs/adrs/006-translation-subsystem.md
- Spec: testing/specs/features/translation-subsystem.feature
