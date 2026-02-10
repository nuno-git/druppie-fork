# LLM Standardization: LiteLLM vs LangChain/LangGraph

## Current State Analysis

### Problems with Current Implementation

The current `druppie/llm/` implementation has several issues:

1. **Custom HTTP Client Implementation** (`zai.py:134-178`)
   - Manual `httpx` calls for each provider
   - Custom retry logic with backoff (lines 224-322)
   - Duplicated across `ChatZAI` and `ChatDeepInfra`

2. **XML Tool Parsing Fallback** (`zai.py:458-470, 621-704`)
   - `_parse_tool_calls_from_text()` parses `<tool_call>...</tool_call>` markup
   - `_parse_malformed_args()` has tool-specific fallbacks (done, fail, write_file)
   - Complex regex parsing for LLMs that don't support native tool calling

3. **Schema Sanitization Hacks** (`zai.py:324-373`)
   - `_sanitize_tools()` fixes JSON Schema for GLM compatibility
   - Converts `integer` → `number`, handles empty `required` arrays
   - Provider-specific workarounds

4. **Duplicated Provider Logic**
   - `ChatZAI` and `ChatDeepInfra` are nearly identical (~700 lines each)
   - Different providers = copy-paste + tweak

---

## Option 1: LiteLLM

### What is LiteLLM?
A unified Python SDK for 100+ LLM providers (OpenAI, Anthropic, Azure, Ollama, etc.) with standardized API.

### How It Works

```python
import litellm
from litellm import completion

# Same code works for any provider
response = completion(
    model="gpt-4",  # or "claude-3-opus-20240229" or "deepinfra/Qwen/Qwen3-32B"
    messages=[{"role": "user", "content": "Hello"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "coding_write_file",
            "description": "Write a file",
            "parameters": {"type": "object", "properties": {...}}
        }
    }]
)

# Unified response format
print(response.choices[0].message.tool_calls)
```

### Key Features

| Feature | Support |
|---------|---------|
| Unified tool calling | Yes - standardized across providers |
| Async support | Yes - `acompletion()` |
| Streaming | Yes |
| Function calling detection | `litellm.supports_function_calling(model)` |
| Fallback for non-tool models | `litellm.add_function_to_prompt = True` |
| Custom callbacks | Yes - `log_pre_api_call`, `log_success_event`, etc. |
| Raw request/response logging | Yes via callbacks |
| Retry logic | Built-in with exponential backoff |

### Logging/Raw Request Capture

```python
import litellm
from litellm.integrations.custom_logger import CustomLogger

class DruppieLogger(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        # Capture raw request before sending
        self.raw_request = {
            "model": model,
            "messages": messages,
            "tools": kwargs.get("tools"),
        }

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        # Capture raw response
        self.raw_response = response_obj
        # Access cost: kwargs["response_cost"]

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # Same for async calls
        pass

litellm.callbacks = [DruppieLogger()]
```

### Implementation Sketch

```python
# druppie/llm/litellm_provider.py
import litellm
from litellm import acompletion

class LiteLLMProvider:
    """Unified LLM provider using LiteLLM."""

    def __init__(self, model: str = "deepinfra/Qwen/Qwen3-32B"):
        self.model = model
        # Configure callbacks for logging
        litellm.callbacks = [DruppieLogger()]

    async def achat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        response = await acompletion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
        )

        # Unified response parsing
        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments),
                })

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            model=self.model,
            provider="litellm",
        )
```

### Pros
- **100+ providers** with zero code changes
- **Built-in retry logic** - no custom implementation needed
- **Standardized tool calling** - no XML parsing fallback
- **Callbacks for logging** - raw request/response capture
- **Active maintenance** - large community, frequent updates
- **Cost tracking** - built-in token/cost calculation
- **Minimal code** - ~50 lines vs 700+ lines per provider

### Cons
- **Extra dependency** - adds `litellm` to requirements
- **Abstraction overhead** - one more layer
- **Provider-specific quirks** - still need to handle edge cases
- **Less control** - can't customize HTTP client settings as easily

---

## Option 2: LangChain (Chat Models Only)

### What is it?
LangChain's chat model abstraction without the full agent framework.

### How It Works

```python
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

# Define tools as Python functions
@tool
def coding_write_file(path: str, content: str) -> str:
    """Write a file to disk."""
    return f"Wrote {path}"

# Bind tools to model
llm = ChatOpenAI(model="gpt-4")
llm_with_tools = llm.bind_tools([coding_write_file])

# Invoke
response = llm_with_tools.invoke([{"role": "user", "content": "Write hello.txt"}])
```

### Pros
- **Type-safe tool definitions** - uses Python functions
- **Well-documented** - extensive examples
- **Integrates with LangSmith** - observability built-in

### Cons
- **Multiple packages** - `langchain-openai`, `langchain-anthropic`, etc.
- **Heavier abstraction** - more complex than LiteLLM
- **Provider packages** - each provider is a separate install
- **No unified `completion()` call** - different classes per provider

---

## Option 3: LangGraph (Full Agent Framework)

### What is it?
Low-level orchestration framework for stateful agents with tool execution loops.

### How It Works

LangGraph would replace not just the LLM layer but also the agent execution loop in `druppie/execution/`.

```python
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

# Define the agent loop
workflow = StateGraph(MessagesState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools=[coding_write_file, docker_build]))

# Add edges
workflow.add_edge("__start__", "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,  # Check for tool calls
    {"continue": "tools", "end": "__end__"}
)
workflow.add_edge("tools", "agent")

# Compile and run
app = workflow.compile()
result = app.invoke({"messages": [HumanMessage(content="Build the app")]})
```

### Pros
- **Full agent framework** - replaces execution loop too
- **Checkpointing** - resume from failures
- **Human-in-the-loop** - built-in support
- **LangSmith integration** - full observability

### Cons
- **Major refactor** - replaces `druppie/execution/` entirely
- **Learning curve** - different paradigm (state machines)
- **Overkill for LLM standardization** - we only want to fix LLM calls
- **Tight coupling** - harder to swap out later

---

## Recommendation: LiteLLM

### Why LiteLLM?

1. **Focused scope** - only replaces LLM layer, not the whole agent system
2. **Minimal changes** - drop-in replacement for current providers
3. **Raw logging** - callbacks capture exactly what we need
4. **No XML parsing** - standardized tool calling across all providers
5. **Future-proof** - easy to add new providers (Anthropic, Ollama, etc.)

### Migration Plan

#### Phase 1: Add LiteLLM Provider (non-breaking)
```
druppie/llm/
├── base.py           # Keep as-is
├── litellm_provider.py  # NEW - LiteLLM implementation
├── zai.py            # Keep for now
└── service.py        # Add "litellm" provider option
```

#### Phase 2: Migrate to LiteLLM
1. Set `LLM_PROVIDER=litellm` in `.env`
2. Test with existing agents
3. Verify tool calling works
4. Verify raw request logging works

#### Phase 3: Remove Old Providers
```
druppie/llm/
├── base.py           # Keep (interface contract)
├── litellm_provider.py  # Primary implementation
└── service.py        # Simplified
```
Delete: `zai.py`, `deepinfra.py`, `mock.py`

### Estimated Changes

| File | Change |
|------|--------|
| `druppie/llm/litellm_provider.py` | NEW ~100 lines |
| `druppie/llm/service.py` | Add LiteLLM option ~20 lines |
| `requirements.txt` | Add `litellm>=1.30.0` |
| `druppie/llm/zai.py` | DELETE (later) |
| `druppie/llm/deepinfra.py` | DELETE (later) |

### Code Reduction
- Current: ~1400 lines (zai.py + deepinfra.py + service.py)
- With LiteLLM: ~150 lines
- **Reduction: ~90%**

---

## Alternative: Keep Current + Fix

If you prefer not to add dependencies, the current code can be improved:

1. Extract common logic into base class
2. Use `httpx` retry middleware instead of custom logic
3. Remove XML parsing (only use providers with native tool calling)

But this still requires maintaining provider-specific code for each new provider.

---

## Summary

| Approach | Effort | Code Reduction | Future-Proof | Logging |
|----------|--------|----------------|--------------|---------|
| LiteLLM | Low | 90% | Excellent | Callbacks |
| LangChain | Medium | 70% | Good | LangSmith |
| LangGraph | High | N/A (different scope) | Good | LangSmith |
| Keep Current | Low | 0% | Poor | Manual |

**Recommendation: LiteLLM** - minimal effort, maximum benefit, preserves current architecture.
