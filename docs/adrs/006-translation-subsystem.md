---
id: "006"
title: Add backend translation service for bilingual support
status: accepted
date: 2026-06-10
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/006-translation-subsystem.md
linked_research: null
---

# ADR 006: Add backend translation service for bilingual support

## Context

Druppie serves Dutch waterschaps (water authorities) whose primary language is Dutch. Agent outputs, summaries, and UI text need to be available in both Dutch and English. The LLM providers Druppie uses may output in either language depending on the prompt and context. A consistent translation layer was needed rather than relying on each agent to produce bilingual output.

## Decision

Build a backend translation service that translates agent outputs using LiteLLM as the model abstraction layer. The service auto-detects the input language and translates to the target language (NL or EN). The translation model is configurable via environment variables (default: gemma-3-27b for cost efficiency). Translation is opt-in per request, not forced on every output. The service handles markdown formatting preservation and technical term handling. Code blocks, file paths, and proper nouns are preserved as-is.

## Consequences

Positive:

- Consistent bilingual output without burdening each agent prompt
- Configurable model for cost and quality tradeoff
- LiteLLM abstraction allows model swapping

Negative:

- Translation adds latency to responses
- Translation quality depends on the configured model (gemma-3-27b is budget-tier)
- Markdown formatting can occasionally break during translation
