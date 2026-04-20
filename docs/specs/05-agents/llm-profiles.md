# LLM Profiles

`druppie/agents/definitions/llm_profiles.yaml` — ordered provider chains per profile. Agents reference a profile by name; the resolver picks the first provider with credentials available and optionally wires a fallback.

## Profiles

### `standard` (execution agents, architect, builder, deployer, etc.)

Chain:
1. `zai` — `glm-5`
2. `deepinfra` — `moonshotai/Kimi-K2.5-Turbo`
3. `zai` — `glm-4.7`
4. `ollama` — `gpt-oss:120b`
5. `azure_foundry` — `GPT-5-MINI`

### `cheap` (router, planner, business_analyst, build_classifier, summarizer)

Same as standard but with a smaller ollama option:
1. `zai` — `glm-5`
2. `deepinfra` — `moonshotai/Kimi-K2.5-Turbo`
3. `zai` — `glm-4.7`
4. `ollama` — `gpt-oss:20b`
5. `azure_foundry` — `GPT-5-MINI`

### `ollama` (explicit local-only)

1. `ollama` — `gpt-oss:120b`
2. `ollama` — `gpt-oss:20b`
3. `ollama` — `qwen3-coder:30b`
4. `ollama` — `deepseek-r1:32b`
5. `ollama` — `gemma3:27b`

## Resolution

`druppie/llm/resolver.py`:

```python
def resolve_llm(profile_name: str) -> LLM:
    profile = load_profile(profile_name)
    primary = None
    fallback = None
    for entry in profile.providers:
        if credentials_available(entry.provider):
            if primary is None:
                primary = build_llm(entry)
            elif fallback is None:
                fallback = build_llm(entry)
                break
    if primary is None:
        raise RuntimeError(f"No LLM credentials for profile '{profile_name}'")
    return FallbackLLM(primary, fallback) if fallback else primary
```

## Credentials by provider

| Provider | Env vars |
|----------|----------|
| `zai` | `ZAI_API_KEY`, `ZAI_MODEL`, `ZAI_BASE_URL` |
| `deepinfra` | `DEEPINFRA_API_KEY`, `DEEPINFRA_MODEL`, `DEEPINFRA_BASE_URL` |
| `deepseek` | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` |
| `azure_foundry` | `FOUNDRY_API_KEY`, `FOUNDRY_MODEL`, `FOUNDRY_API_URL` |
| `ollama` | `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, optional `OLLAMA_API_KEY` |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` (agents don't use this by default) |

`LLM_FORCE_PROVIDER` and `LLM_FORCE_MODEL` in `.env` override the chain for every agent — used for quick local testing against a single provider.

## Fallback behaviour

When the primary provider fails (HTTP 5xx, rate limit, model-not-loaded for ollama):
1. Retry primary 3× with exponential backoff (0.5s, 1s, 2s). Each retry logged to `llm_retries`.
2. On final primary failure, try fallback once.
3. On fallback failure, surface the error — the agent run goes FAILED.

## LiteLLM wrapper

Druppie uses LiteLLM under the hood via `druppie/llm/litellm_provider.py`. This normalises OpenAI's `tool_calls` response shape across providers (Anthropic, Azure, Deepseek, etc.) so the agent loop can use a single parsing path.

## Per-agent overrides

Agent YAML can override profile choice or even hard-pin a model:
```yaml
llm_profile: standard   # pick a profile
# or
model: gpt-4o-2024-08-06  # hard-pin, ignores profile
temperature: 0.2
max_tokens: 16384
```

In practice only `temperature`, `max_tokens`, `max_iterations` are overridden — profiles handle provider selection.

## Sandbox models

Sandboxes use a different profile — defined in `druppie/opencode/config/sandbox_models.yaml`. That file maps the sandbox's internal model name (used by OpenCode CLI) to a concrete provider+model. See `06-sandbox/llm-proxy.md` for how the sandbox's LLM requests route through the local control plane.
