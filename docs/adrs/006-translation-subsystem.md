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

### Technical detail (wiring)

Druppie supports Dutch and English users while every agent stays monolingual English internally. All translation happens in the backend; the frontend does no translation (no i18n library) — it only renders backend-translated fields.

- **LLM call config** — `ChatLiteLLM`, `temperature=0.1`, `max_tokens=16384`, `timeout=120s`, `max_retries=2`. Provider/model resolved by `TranslationService._resolve_translation_config()` (`druppie/core/translation.py`) in this priority order:
  1. Admin runtime override — set via Model Management UI (`/models`), persisted in `model_override` table (`target_type="translation"`), applied immediately on change. Supports a configured fallback.
  2. Env vars — `TRANSLATION_PROVIDER` + `TRANSLATION_MODEL` (only if that provider has an API key).
  3. Legacy default — if `DEEPINFRA_API_KEY` set → `("deepinfra", "google/gemma-3-27b-it")`.
  4. Any available provider — first provider in `PROVIDER_CONFIGS` with an API key, using its `default_model` (e.g. `zai` → `glm-4.7`, `openrouter` → `google/gemma-3-27b-it`).
  5. None available → `TranslationNotAvailableError`.
  Translation is **not** hard-wired to DeepInfra; with no key and no override it falls through to the general provider ladder.

- **Components** — `TranslationService` singleton (`druppie/core/translation.py`: `translate_to_english()`/`translate_from_english()`/`translate_label()`/`_translate()`, config resolution, session-notification dedup with 24h in-memory TTL → assumes single worker); `LanguageDetector` (`druppie/core/language_detection.py`: hybrid keyword + `langdetect`, threshold `0.6`, `af`/`fy`/`de` treated as Dutch); orchestration seam in `druppie/execution/orchestrator.py` (detects language, sets `content`/`content_english`, catches `TranslationError` → English fallback); English-only prompt block injected in `druppie/agents/prompt_builder.py`; chat/summarizer translation in `druppie/agents/builtin_tools.py` → `create_message()`; long-content chunking and design/HITL/fallback seams in `druppie/execution/tool_executor.py`.

- **Design documents (dual-file, English = source of truth)** — only for `make_design`, only for a Dutch session, only for paths in `DESIGN_TRANSLATION_PATHS`. The English original (`docs/functional-design.md` / `technical-design.md` / `technical-research.md`) is written first; on success a second `write_file` MCP call writes the Dutch copy (`functioneel-ontwerp.md` / `technisch-ontwerp.md` / `technisch-onderzoek.md`). The approval card shows a single (session-language) file; the English original is still saved.

- **Persistence** — no translation cache (every call is fresh); no dedicated translation table/repository. Translated artifacts live inline: `messages.content` (translated) + `messages.content_english` (agent-facing); `make_design` tool-call args (`translated_content`/`translated_path`) + the dual files on disk; HITL `english_question`/`english_choices`. `_notified_sessions` is an in-memory dict, 24h TTL, process-local.

- **Database** — `sessions.language` (`VARCHAR(10)`, nullable: `nl`/`en`/`null`); `model_override` (`target_type="translation"`, admin override); `messages.content` / `messages.content_english` (display vs agent-facing).

- **Frontend** — no i18n library (`i18next`/`react-i18next` absent). `ChatHelpers.jsx` renders the translated design file when `translated_content`/`translated_path` present; `SessionDetail.jsx` renders `translated_path`. Dutch approval cards show a single (translated) file.

## Consequences

Positive:

- Consistent bilingual output without burdening each agent prompt
- Configurable model for cost and quality tradeoff
- LiteLLM abstraction allows model swapping

Negative:

- Translation adds latency to responses
- Translation quality depends on the configured model (gemma-3-27b is budget-tier)
- Markdown formatting can occasionally break during translation
