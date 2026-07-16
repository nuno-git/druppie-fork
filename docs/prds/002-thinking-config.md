---
id: "002"
title: "Thinking/Reasoning Configuration"
status: approved
author: nuno
date: 2026-05-20
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# Thinking/Reasoning Configuration — Design Spec

## 1. Overview

**Problem:** Thinking/reasoning tokens from LLMs aren't being captured because we never request them from the model.

**Goal:** Make thinking mode configurable per agent and per model profile, so reasoning tokens flow through the existing pipeline and land in the already-built `thinking_content` storage and frontend display.

**Scope:** Backend config pipeline + litellm integration only. Frontend display and database storage are already done.

## 2. Background

GLM-5/5.1 has thinking enabled by default, but litellm needs explicit configuration to pass thinking parameters to OpenAI-compatible providers. Different providers use different mechanisms:

| Provider | Parameter | Format |
|----------|-----------|--------|
| ZAI / GLM | `extra_body` | `{"thinking": {"type": "enabled"}}` |
| Anthropic | `thinking` (top-level) | `{"type": "enabled", "budget_tokens": 1024}` |
| OpenAI GPT-5 | `reasoning_effort` | `"low" \| "medium" \| "high"` |
| DeepSeek | handled natively | `reasoning_content` auto-captured |

litellm normalizes the response: regardless of provider, reasoning content appears in `reasoning_content` on the response object.

## 3. Current Pipeline (as-is)

```
Agent YAML (llm_profile, temperature, max_tokens)
  → AgentDefinition (domain/agent_definition.py:127-130)
    → llm_profiles.yaml (provider, model per entry)
      → resolve_model() (llm/resolver.py:75) → ResolvedModel
        → LLMService.create_llm_for_agent() (llm/service.py:107) → ChatLiteLLM(provider, model, temperature)
          → _build_kwargs() (llm/litellm_provider.py:356) → kwargs dict
            → litellm.acompletion(**kwargs)
```

Gaps in the current flow:

- No `thinking` field in `AgentDefinition`
- No `thinking` field in `llm_profiles.yaml` entries
- No `thinking` in `ResolvedModel`
- No `thinking_mode` param in `ChatLiteLLM`
- Current hardcoded `thinking` in `PROVIDER_CONFIGS` is wrong (not configurable)

## 4. Proposed Design

### 4.1 Config Schema

#### llm_profiles.yaml

Add `thinking` to profile entries:

```yaml
profiles:
  standard:
    - provider: zai
      model: glm-5
      thinking: enabled
    - provider: deepinfra
      model: moonshotai/Kimi-K2.5-Turbo
      thinking: enabled
    - provider: azure_foundry
      model: GPT-5-MINI
      reasoning_effort: low
    - provider: ollama
      model: gpt-oss:120b

  cheap:
    - provider: zai
      model: glm-5
      thinking: disabled           # explicitly off for speed
    - provider: deepinfra
      model: moonshotai/Kimi-K2.5-Turbo
      thinking: disabled
    - provider: zai
      model: glm-4.7
      thinking: disabled
    - provider: ollama
      model: gpt-oss:20b
    - provider: azure_foundry
      model: GPT-5-MINI
      reasoning_effort: low
```

Valid values for `thinking`:

- `enabled` — request thinking tokens from the model
- `disabled` — explicitly send disable param (sends `{"thinking": {"type": "disabled"}}`) to override provider defaults
- omitted/absent — don't send any thinking parameter (use model's default behavior)

#### Agent YAML

Per-agent override:

```yaml
# In any agent definition YAML:
llm_profile: standard
thinking: enabled              # overrides profile-level setting
reasoning_effort: low          # optional effort level (low/medium/high)
```

Resolution order: agent-level > profile-level > no param sent (model default).

### 4.2 Domain Model Changes

#### AgentDefinition (domain/agent_definition.py)

```python
# Add after max_iterations (line 130):
thinking: str | None = None            # "enabled" | "disabled" | None (use profile default)
reasoning_effort: str | None = None    # "low" | "medium" | "high" | None
```

### 4.3 Resolver Changes

#### ResolvedModel (llm/resolver.py)

```python
@dataclass
class ResolvedModel:
    provider: str
    model: str | None
    source: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    # New:
    thinking: str | None = None            # from profile entry
    reasoning_effort: str | None = None    # from profile entry
```

#### resolve_model()

Read `thinking` and `reasoning_effort` from the matched profile entry and store them in `ResolvedModel`.

### 4.4 Service Layer Changes

#### LLMService.create_llm_for_agent()

Merge thinking config from both `resolved` (profile) and `agent_def` (agent override). Agent override wins.

```python
# Merge thinking config: agent override > profile default
effective_thinking = agent_def.thinking or resolved.thinking
effective_effort = agent_def.reasoning_effort or resolved.reasoning_effort

primary = ChatLiteLLM(
    provider=resolved.provider,
    model=resolved.model,
    temperature=agent_def.temperature,
    thinking=effective_thinking,
    reasoning_effort=effective_effort,
)
```

### 4.5 ChatLiteLLM Changes

#### __init__() — accept thinking params

```python
def __init__(
    self,
    ...
    thinking: str | None = None,          # "enabled" | "disabled" | None
    reasoning_effort: str | None = None,  # "low" | "medium" | "high" | None
):
    self.thinking = thinking
    self.reasoning_effort = reasoning_effort
```

#### _build_kwargs() — provider-specific dispatch

Remove hardcoded `thinking` from `PROVIDER_CONFIGS`. Instead, add provider-specific dispatch in `_build_kwargs()`:

```python
# Thinking/reasoning — provider-specific dispatch
if self.thinking == "enabled":
    if self.provider in ("zai", "deepinfra"):
        # OpenAI-compatible: use extra_body
        kwargs.setdefault("extra_body", {})["thinking"] = {"type": "enabled"}
    elif self.provider == "anthropic":
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": 10000}
    # else: litellm handles natively (e.g., deepseek)
elif self.thinking == "disabled":
    # Always send explicit disable to override provider defaults
    if self.provider in ("zai", "deepinfra"):
        kwargs.setdefault("extra_body", {})["thinking"] = {"type": "disabled"}

if self.reasoning_effort:
    kwargs["reasoning_effort"] = self.reasoning_effort
```

#### Remove from PROVIDER_CONFIGS

Delete the `"thinking": {"type": "enabled"}` line from the zai `PROVIDER_CONFIGS` entry. Thinking is now configurable per profile/agent and doesn't belong in provider-level defaults.

### 4.6 Preserved Thinking (Future)

For multi-turn agent runs, we should eventually support `clear_thinking: false` so reasoning persists across turns. This would require:

1. Returning `reasoning_content` in subsequent message turns
2. Adding `clear_thinking: false` to the thinking config
3. Modifying the agent loop to include `reasoning_content` in message history

Out of scope for the initial implementation, but worth keeping in mind.

## 5. Migration

- No database changes (the `thinking_content` column already exists)
- Remove hardcoded `thinking` from `PROVIDER_CONFIGS`
- Add `thinking: enabled` to zai and deepinfra entries in `llm_profiles.yaml`
- Existing agents work unchanged (`thinking=None` means no param sent, same behavior as before)

## 6. Files Changed

| File | Change |
|------|--------|
| `druppie/agents/definitions/llm_profiles.yaml` | Add `thinking` to entries |
| `druppie/domain/agent_definition.py` | Add `thinking`, `reasoning_effort` fields |
| `druppie/llm/resolver.py` | Read thinking from profile, add to `ResolvedModel` |
| `druppie/llm/service.py` | Merge thinking config, pass to `ChatLiteLLM` |
| `druppie/llm/litellm_provider.py` | Remove hardcoded `PROVIDER_CONFIGS` thinking, add to `__init__`, add provider dispatch in `_build_kwargs` |

## 7. Decisions

| Question | Decision |
|----------|----------|
| Standard profile defaults? | No param sent (model default). `thinking` only on entries that explicitly need it. |
| `thinking: disabled` behavior? | Always send explicit disable param to override provider defaults. |
| Per-agent `reasoning_effort`? | Yes, needed — some agents benefit from low effort (speed), others from high (quality). |
| `thinking: adaptive`? | Not needed for now. Only `enabled` / `disabled` / omitted. |
