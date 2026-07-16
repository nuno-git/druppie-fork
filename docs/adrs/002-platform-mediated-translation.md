---
id: "002"
title: Mediate all translation in the platform, keep agents monolingual English
status: proposed
date: 2026-07-16
deciders:
  - architect
  - backend-team
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

> **Where this fits:** This ADR records the design decision behind Druppie's bilingual
> (Dutch/English) support. The "how it is wired" reference lives in
> [`docs/reference/TRANSLATION.md`](../reference/TRANSLATION.md); the testable behaviour lives in
> [`testing/specs/features/translation-guards.feature`](../../testing/specs/features/translation-guards.feature).

## Context

Druppie serves Dutch and English users, but agent prompts, tool contracts and design artifacts are
easier to reason about — and less prone to language mixing — when every agent works in a single
language. Translation is also error-prone with LLMs (hallucination, truncation, dropped structure),
so *where* and *when* translation happens, and *how* failures surface, are architectural concerns
rather than per-agent details.

## Decision

Translation is a platform responsibility. We commit to four principles:

1. **Agents are monolingual English.** Every agent receives a fixed English-only instruction block
   and never sees or emits non-English text. This keeps prompts and tool contracts simple.
2. **The platform translates, not the agents.** All translation happens in the backend (via
   LiteLLM) at the orchestrator, tool-executor and builtin-tools seams — never inside agent prompts.
   User input is translated to English for agents; agent output is translated back to the user's
   language for display.
3. **Session language is locked early.** The first user message sets `session.language`; later HITL
   answers do not change it. English is the source of truth (e.g. design docs write the English file
   first, then generate the Dutch copy).
4. **Fail loud, never degrade silently.** Missing/invalid translation configuration raises and
   switches the session to English with a bilingual notice; per-call runtime failures surface a
   visible `[NIET VERTAALD / NOT TRANSLATED]` marker or a bilingual "translation unavailable"
   notice rather than serving untranslated text as if it were translated.

## Consequences

- (+) Agents stay simple and language-agnostic; only the platform deals with two languages.
- (+) English design artifacts remain a single source of truth, with Dutch copies auto-generated.
- (+) Translation problems are visible to users and operators instead of silently corrupting output.
- (−) The platform must carry quality/error guards (hallucination guard, untranslated-retry,
   `<think>` stripping, chunked long-document translation) — see the linked spec for the exact
   testable behaviour.
- (−) Dutch design approval requires writing two files (English source + Dutch copy) while showing
   the reviewer a single session-language file.
- (−) The fail-loud guarantee is currently **incomplete**: `translate_from_english()` (EN→NL) has no
   hallucination/truncation guard (only NL→EN does), and there is no structural protection for
   frontmatter/IDs/code — these are tracked gaps (issues #275/#278/#269/#240/#73).

<!-- LATER (PBI 9744 — afdwingen): hoe deze beslissing wordt afgedwongen wordt in PBI 9744
     onderzocht en hier toegevoegd. -->
