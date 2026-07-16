---
id: "016"
title: Auto-compression of agent conversation context via single-shot LLM summarization
status: accepted
date: 2026-07-16
deciders:
  - Nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

## Context

Long agent sessions (especially `update_project` workflows with many tool-calling
iterations) accumulate messages until the LLM context window overflows. Without
intervention, the agent run fails or degrades with no recovery path.

A secondary pressure exists on **planner runs specifically**: the orchestrator
(`orchestrator.py:_prepend_agent_summary`) accumulates done-summaries from all
completed agent runs and prepends them to the planner's prompt. This accumulation
is unbounded (no cap, no reset) and is per-line deduplicated. It competes with the
planner's own prompt for context space.

## Decision

Implement **single-shot, whole-history LLM summarization** via `MessageCompactor`
(`agent_runtime/compaction.py`). When the estimated token count exceeds a
configurable threshold, the entire conversation body (everything after the
system + initial-user header) is serialized and sent to the LLM for a ≤300-word
summary. The body is then replaced with a single `[CONVERSATION SUMMARY]` message.

Key design choices:

- **Token estimation:** char-based heuristic (`chars / 4 + 4` per message),
  self-calibrating via EMA against real `usage.prompt_tokens` from the LLM,
  clamped to [2.5, 6.0] chars/token. No `tiktoken` dependency.
- **Trigger:** fires when estimate > `max_context_tokens × summarization_threshold`
  (defaults: 150,000 × 0.70 = ~105k tokens). Checked every turn.
- **No dedicated summary model:** `summary_llm = None` in production — the agent's
  own main LLM performs the summarization.
- **Fallback:** if the LLM call fails or no LLM is available, old turns are
  dropped and replaced with a placeholder message (no real summary).
- **Backstops:** after `max_compactions` (default 10), the loop forces `done()`.
  If context still overflows after a compress attempt, the loop also forces
  `done()`. Tool results are independently truncated (head + tail, 15k chars
  default).
- **Configurable per-agent** via YAML `compression:` block with two knobs:
  `summarization_threshold` and `max_compactions`.

## Consequences

Positive:
- Agents survive long sessions instead of crashing on context overflow.
- Header (system prompt + initial instructions) is always preserved.
- Audit trail: each compression is persisted as a `CompactionEvent` row with
  phase, tokens before/after, and the generated summary text.

Negative:
- Information loss: a single 300-word summary replaces the entire conversation
  body. Early decisions may be lost if the LLM doesn't capture them.
- One LLM call per compression adds latency and cost.
- Fallback path (when summarization fails) drops history entirely with no summary.
- Char-based heuristic can drift before calibration samples accumulate.
- Does not address the unbounded planner summary relay (that is a separate problem).

Not yet exposed in YAML: `max_context_tokens` (150k, from `LoopConfig`),
`max_input_chars` (30k), `max_output_tokens` (1024), `tool_result_max_chars` (15k).

## Alternatives Considered

- **Hard truncation (drop oldest, no summarization).** Rejected as the primary
  mechanism — loses information abruptly. Used only as the fallback when LLM
  summarization fails.
- **Tiered summarization (keep recent in full, compress older).** Considered but
  not implemented — adds complexity. The current approach compresses everything
  at once.
- **Sliding window (evict oldest with no summarization).** Rejected — discards
  early context that may still be relevant (e.g. BA decisions needed by deployer).
