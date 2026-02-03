# LLM Providers

This document describes how Druppie integrates with LLM providers, how provider selection works, the tool call parsing pipeline, token tracking, and known issues.

---

## 1. Supported Providers

Druppie supports three LLM providers and an auto-detection mode. All providers implement the `BaseLLM` abstract class defined in `druppie/llm/base.py`.

### 1.1 Z.AI (`zai`)

- **Class:** `ChatZAI` in `druppie/llm/zai.py`
- **API:** OpenAI-compatible chat completions endpoint at `https://api.z.ai/api/coding/paas/v4/chat/completions`
- **Default model:** `GLM-4.7`
- **Environment variables:**
  - `ZAI_API_KEY` (required)
  - `ZAI_MODEL` (default: `GLM-4.7`)
  - `ZAI_BASE_URL` (default: `https://api.z.ai/api/coding/paas/v4`)
- **Native tool calling:** `supports_native_tools` returns `False` (the base class default). This means Z.AI agents receive XML-format tool call instructions injected into the system prompt, and the runtime parses `<tool_call>...</tool_call>` tags from text responses as a fallback.
- **Timeout:** 500 seconds (default)
- **Retry:** 3 attempts with linear backoff (5s, 10s, 15s) for 5xx errors and timeouts. 429/401 errors are not retried.

### 1.2 DeepInfra (`deepinfra`)

- **Class:** `ChatDeepInfra` in `druppie/llm/deepinfra.py`
- **API:** OpenAI-compatible chat completions endpoint at `https://api.deepinfra.com/v1/openai/chat/completions`
- **Default model:** `Qwen/Qwen3-Next-80B-A3B-Instruct`
- **Environment variables:**
  - `DEEPINFRA_API_KEY` (required)
  - `DEEPINFRA_MODEL` (default: `Qwen/Qwen3-Next-80B-A3B-Instruct`)
  - `DEEPINFRA_BASE_URL` (default: `https://api.deepinfra.com/v1/openai`)
  - `DEEPINFRA_MAX_TOKENS` (default: `16384`)
- **Native tool calling:** `supports_native_tools` returns `True`. Tools are passed via the OpenAI `tools` parameter, and the model returns structured `tool_calls` in the response. However, a text-based fallback parser also exists for Qwen models that sometimes emit `<tool_call>` tags in content instead.
- **Timeout:** 300 seconds (default)
- **Retry:** Same as Z.AI -- 3 attempts with linear backoff for 5xx and timeouts.

### 1.3 Mock (`mock`)

- **Class:** `ChatMock` in `druppie/llm/mock.py`
- **API:** None -- returns hardcoded responses based on system prompt analysis.
- **Model name:** `mock`
- **Native tool calling:** `supports_native_tools` returns `False` (base default).
- **Use case:** Testing without external API calls. Analyzes the system prompt to detect agent type (router, planner, developer) and returns pre-built tool call responses.
- **Token counting:** Approximated as `len(text) // 4` -- purely for testing purposes.

### 1.4 Auto-detection (`auto`)

Not a provider itself. When `LLM_PROVIDER=auto` (the default), the `LLMService` checks for available API keys in this order:

1. If `DEEPINFRA_API_KEY` is set, use `deepinfra`
2. Else if `ZAI_API_KEY` is set, use `zai`
3. Else raise `LLMConfigurationError`

Note: DeepInfra is preferred over Z.AI when both keys are present.

---

## 2. Provider Selection

### 2.1 Environment Variable

Set `LLM_PROVIDER` in your `.env` file or environment:

```bash
LLM_PROVIDER=zai        # Use Z.AI explicitly
LLM_PROVIDER=deepinfra  # Use DeepInfra explicitly
LLM_PROVIDER=mock       # Use mock for testing
LLM_PROVIDER=auto       # Auto-detect (default)
```

### 2.2 How It Works Internally

Provider selection happens in `LLMService.get_provider()` (`druppie/llm/service.py`):

1. Read `LLM_PROVIDER` from environment (default: `"auto"`)
2. Validate the API key exists for the chosen provider
3. Cache the result in `self._provider`

The LLM client is created lazily in `LLMService.get_llm()` and cached as a singleton (`self._llm`). The global singleton `LLMService` instance is accessed via `get_llm_service()`.

### 2.3 Docker Compose

In `druppie/docker-compose.yml`, all LLM environment variables are passed through from the host `.env` file with defaults:

```yaml
LLM_PROVIDER: ${LLM_PROVIDER:-auto}
ZAI_API_KEY: ${ZAI_API_KEY:-}
ZAI_MODEL: ${ZAI_MODEL:-GLM-4.7}
ZAI_BASE_URL: ${ZAI_BASE_URL:-https://api.z.ai/api/coding/paas/v4}
DEEPINFRA_API_KEY: ${DEEPINFRA_API_KEY:-}
DEEPINFRA_MODEL: ${DEEPINFRA_MODEL:-Qwen/Qwen3-Next-80B-A3B-Instruct}
DEEPINFRA_BASE_URL: ${DEEPINFRA_BASE_URL:-https://api.deepinfra.com/v1/openai}
```

---

## 3. Per-Agent Model Configuration

### 3.1 What the YAML Says

Every agent YAML definition has a `model` field:

| Agent             | YAML `model` | `max_tokens` | `temperature` |
|-------------------|-------------|-------------|---------------|
| router            | `glm-4`    | 4096        | 0.1           |
| planner           | `glm-4`    | 16384       | 0.1           |
| business_analyst  | `glm-4`    | 100000      | 0.2           |
| architect         | `glm-4`    | 100000      | 0.2           |
| developer         | `glm-4`    | 163840      | 0.1           |
| deployer          | `glm-4`    | 100000      | 0.1           |
| reviewer          | `glm-4`    | 100000      | 0.1           |
| tester            | `glm-4`    | 100000      | 0.1           |
| summarizer        | `glm-4`    | 2048        | 0.3           |

The `model` field is defined as `str | None = None` in `AgentDefinition` (in `druppie/domain/agent_definition.py`).

### 3.2 What the Code Actually Does (IMPORTANT)

**The per-agent `model` field from YAML is NOT used for LLM selection.** Here is the honest truth about what happens:

1. The `Agent` class in `druppie/agents/runtime.py` has a lazy `llm` property (line 155-159):
   ```python
   @property
   def llm(self):
       if self._llm is None:
           self._llm = get_llm_service().get_llm()
       return self._llm
   ```

2. `get_llm_service()` returns the **global singleton** `LLMService`, and `get_llm()` creates a **single cached LLM client** using the environment variables (`ZAI_MODEL`, `DEEPINFRA_MODEL`).

3. The YAML `model` field (e.g., `glm-4`) is **completely ignored** for provider/model selection. All agents use the same global LLM instance with the same model (e.g., `GLM-4.7` from `ZAI_MODEL`).

4. The YAML `model` value is only referenced in **one place** -- as a fallback for the `model` field when recording LLM calls in the database (line 532):
   ```python
   model=self.llm.model if hasattr(self.llm, 'model') else self.definition.model or "unknown",
   ```
   Since `self.llm.model` always exists, the YAML `model` value is never actually used even here.

### 3.3 What IS Respected From YAML

- **`max_tokens`:** This IS respected. The runtime passes `max_tokens=self.definition.max_tokens` to `achat()` on each call (line 539). The `achat()` method uses this as a per-call override of the instance default.
- **`temperature`:** This is NOT respected per-agent. The LLM client uses the temperature from its constructor (0.7 default), not from the YAML definition.
- **`max_iterations`:** This IS respected. Controls the tool-calling loop limit per agent.

### 3.4 Summary of the Gap

The YAML config gives the **appearance** of per-agent model selection, but the runtime uses a global singleton LLM. To actually support per-agent models, the `Agent.llm` property would need to create or select an LLM client based on `self.definition.model` instead of calling the global singleton.

---

## 4. Tool Call Parsing

Tool call parsing is one of the most complex parts of the LLM integration. There are multiple parsing strategies, and they differ between providers.

### 4.1 Overview: Two Parsing Paths

The system has two fundamentally different paths for extracting tool calls from LLM responses:

1. **Native OpenAI tool calls** -- The API response includes structured `message.tool_calls` with `function.name` and `function.arguments` (JSON string).
2. **Text-based tool calls** -- The LLM outputs `<tool_call>{"name": "...", "arguments": {...}}</tool_call>` tags in the response content, which must be parsed from text.

Both providers attempt native parsing first, then fall back to text parsing.

### 4.2 Z.AI (`ChatZAI._parse_response`)

**Step 1: Native tool calls** (lines 325-348)

If the API response contains `message.tool_calls`:
- Extract `function.name` and `function.arguments` from each tool call
- Parse `arguments` as JSON
- On JSON parse failure, delegate to `_parse_malformed_args()`
- If parsed args are not a dict, wrap in `{"value": args}` or default to `{}`

**Step 2: Text fallback** (lines 351-356)

If no native tool calls were found AND the response has content text:
- Call `_parse_tool_calls_from_text()` which uses regex to find `<tool_call>...</tool_call>` blocks
- Also handles unclosed `<tool_call>` tags (some LLMs forget the closing tag)
- Each extracted block is parsed by `_parse_single_tool_call()`:
  - First tries `json.loads()` on the block content
  - Falls back to regex extraction of `"name"` and `"arguments"` fields
  - Falls back to `_parse_malformed_args()` for the arguments
- Tool call markup is stripped from the response content

**Step 3: Response cleaning** (`_clean_response`)
- Strip whitespace
- Remove `<think>...</think>` blocks (chain-of-thought reasoning markers)
- Remove markdown code fences (`\`\`\`json ... \`\`\``)

### 4.3 DeepInfra (`ChatDeepInfra._parse_response`)

**Step 1: Native tool calls** (lines 331-354)

Same logic as Z.AI -- parses `message.tool_calls` from the API response, with JSON parsing and `_parse_malformed_args()` fallback.

**Step 2: Text fallback** (lines 357-367)

If no native tool calls found, calls `_extract_tool_calls_from_text()` which is more robust than Z.AI's version:
- Uses a regex pattern to find `<tool_call>...</tool_call>` blocks
- For each match:
  - Fixes malformed JSON (missing opening brace before `"name"`)
  - Balances braces by counting `{` and `}` characters
  - Finds matching brace pairs to extract valid JSON substrings
  - Tries `json.loads()` on the cleaned JSON
  - On failure, falls back to regex-based `name`/`arguments` extraction with `_parse_malformed_args()`
- Returns both the extracted tool calls and the cleaned content

**Step 3: Response cleaning** (`_clean_response`)

Same as Z.AI: strips whitespace, removes `<think>` blocks, removes markdown code fences.

### 4.4 Malformed Arguments Parser

Both providers share similar `_parse_malformed_args()` logic. This is the last-resort parser for when JSON parsing fails on tool arguments:

**Common fixes applied:**
1. Remove XML-like tags (e.g., `<path>` tags embedded in arguments)
2. Remove duplicate colons (`::` -> `:`)
3. Fix missing commas between JSON fields
4. Fix unquoted keys (`{path: "..."` -> `{"path": "..."`)
5. Find and extract a JSON object from the cleaned string

**Tool-specific fallbacks:**

| Tool | Extraction Strategy |
|------|-------------------|
| `done` | Regex for `"summary"` field; defaults to `[PARSE_ERROR] Raw: ...` |
| `fail` | Regex for `"reason"` field |
| `ask_human` / `hitl_ask` | Regex for `"question"` field |
| `write_file` / `coding_write_file` | Regex for `"path"` and `"content"` fields; also tries code block format |
| `read_file` / `coding_read_file` | Regex for `"path"` field |
| `batch_write_files` (DeepInfra only) | Specialized `_parse_batch_write_files_args()` that walks characters to handle escaped content |

### 4.5 System Prompt Injection (XML Format Instructions)

The runtime in `Agent._build_system_prompt()` dynamically adjusts the system prompt based on whether the LLM supports native tools:

- **If `llm.supports_native_tools` is `True`** (DeepInfra): Minimal tool instructions are injected. No XML format examples. Tools are passed via the API's `tools` parameter.
- **If `llm.supports_native_tools` is `False`** (Z.AI, Mock): Full XML format instructions are injected into the system prompt, including:
  - The `<tool_call>{"name": "...", "arguments": {...}}</tool_call>` format specification
  - Multiple examples of correct and incorrect tool usage
  - Built-in tool documentation (hitl_ask_question, hitl_ask_multiple_choice_question, done)

This two-track approach means Z.AI agents get ~50 extra lines of prompt text explaining the XML tool format.

---

## 5. Token Tracking

### 5.1 Where Tokens Come From

Token counts are reported by the LLM API in the response's `usage` object:
```json
{
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801
  }
}
```

Both `ChatZAI` and `ChatDeepInfra` extract these from the response and include them in the `LLMResponse` object. The mock provider approximates tokens as `len(text) // 4`.

### 5.2 Storage Hierarchy

Tokens are tracked at three levels in the database:

**Level 1: LLM Call** (`druppie/db/models/llm_call.py`)
- Each individual LLM API call stores `prompt_tokens`, `completion_tokens`, `total_tokens`
- Written by `ExecutionRepository.update_llm_response()`

**Level 2: Agent Run** (`druppie/db/models/agent_run.py`)
- Accumulated across all LLM calls in one agent run
- Updated by `ExecutionRepository.update_tokens()` which adds incrementally:
  ```python
  agent_run.prompt_tokens = (agent_run.prompt_tokens or 0) + prompt_tokens
  agent_run.completion_tokens = (agent_run.completion_tokens or 0) + completion_tokens
  agent_run.total_tokens = agent_run.prompt_tokens + agent_run.completion_tokens
  ```

**Level 3: Session** (`druppie/db/models/session.py`)
- Accumulated across all agent runs in one session
- Fields: `prompt_tokens`, `completion_tokens`, `total_tokens`

**Level 4: Project** (aggregated at query time)
- `ProjectRepository` sums session-level tokens using SQL `func.sum()` when fetching project stats

### 5.3 What Gets Recorded Per LLM Call

The runtime (`Agent._run_loop`) records these fields for each LLM call:
- `provider` -- from `self.llm.provider_name` (e.g., "zai", "deepinfra")
- `model` -- from `self.llm.model` (e.g., "GLM-4.7")
- `request_messages` -- the full message history sent to the LLM
- `tools_provided` -- the OpenAI-format tool definitions
- `response_content` -- a JSON string containing content, tool_calls, and token counts (truncated to 10000 chars)
- `response_tool_calls` -- structured list of tool calls with id, name, args
- `prompt_tokens`, `completion_tokens`, `duration_ms`

### 5.4 In-Memory Call History

Each provider also maintains an in-memory `call_history` list for debugging. This is separate from the database records. It tracks:
- Timestamp, model, provider, status (pending/success/error/retry)
- Duration in milliseconds
- Error details and retryability for failed calls
- Content preview and tool call count for successful calls

Accessed via `LLMService.get_call_history()` and cleared with `LLMService.clear_call_history()`.

---

## 6. Known Issues

### 6.1 Per-Agent Model Selection Does Not Work

**Severity: Design gap**

As documented in Section 3, every YAML agent definition specifies `model: glm-4`, but this field is completely ignored. All agents share the same global LLM singleton, which uses whatever model is configured in the environment variables (e.g., `GLM-4.7`). There is no mechanism to use different models for different agents (e.g., a cheaper model for the router, a more capable model for the developer).

### 6.2 Per-Agent Temperature Is Ignored

**Severity: Low**

YAML definitions specify different temperatures per agent (0.1 for most, 0.2 for architect/business_analyst, 0.3 for summarizer). These are parsed into `AgentDefinition.temperature` but never passed to the LLM. The LLM client uses its constructor default (0.7) for all calls.

### 6.3 Z.AI Does Not Declare Native Tool Support

**Severity: Medium**

`ChatZAI.supports_native_tools` returns `False` (inherited from `BaseLLM`), which means:
- Z.AI agents get verbose XML format instructions injected into every system prompt
- The runtime relies on text-based `<tool_call>` parsing as the primary mechanism
- This wastes prompt tokens and introduces parsing fragility

If the Z.AI GLM-4.7 model actually supports OpenAI-style native tool calling (it does appear to, since the code passes tools via the API and checks `message.tool_calls`), then `supports_native_tools` should probably return `True`. The text fallback would still catch any edge cases.

### 6.4 Duplicated Code Between Providers

**Severity: Low (maintainability)**

`ChatZAI` and `ChatDeepInfra` share approximately 80% of their code:
- `chat()` and `achat()` methods are nearly identical
- `_format_error()` is identical except for provider name strings
- `_clean_response()` is identical
- `_parse_malformed_args()` is nearly identical (DeepInfra adds `batch_write_files` handling)

The only meaningful differences are:
- `supports_native_tools` return value
- DeepInfra has `_extract_tool_calls_from_text()` (more robust) vs Z.AI's `_parse_tool_calls_from_text()`
- DeepInfra has `_parse_batch_write_files_args()` as an additional malformed args handler
- DeepInfra reads `DEEPINFRA_MAX_TOKENS` env var in `LLMService`

### 6.5 Malformed Args Fallbacks Are Fragile

**Severity: Medium**

The `_parse_malformed_args()` method uses regex to extract tool arguments when JSON parsing fails. This is inherently fragile:
- Regex patterns assume specific field names and formats
- Nested JSON or escaped characters can break extraction
- The `write_file` content extraction fails if the content contains unescaped quotes
- The `batch_write_files` parser in DeepInfra walks characters manually to handle escaping, but this can still fail on complex file content

When all parsing fails, the method returns `{}` (empty dict), which means the tool call is dispatched with no arguments. This can cause confusing downstream errors.

### 6.6 Tool Name Format Inconsistencies

**Severity: Low**

Tool names undergo multiple transformations:
1. MCP config defines tools as `server:tool_name` (e.g., `coding:write_file`)
2. The runtime converts to underscore format for OpenAI tools: `coding_write_file`
3. When parsing tool calls, the runtime splits back: `coding_write_file` -> server=`coding`, tool=`write_file`
4. For builtin tools, the name is used as-is: `done`, `hitl_ask_question`

The split-back logic (line 612-614) uses `split("_", 1)`, which means a tool name like `get_git_status` would become server=`get`, tool=`git_status` -- incorrect. However, this is mitigated by the builtin tool check happening first, and MCP tools using the colon-separated format.

### 6.7 `get_call_history` Not on Base Class

**Severity: Very low**

The `get_call_history()` and `clear_call_history()` methods are defined on each concrete provider but not on `BaseLLM`. The `LLMService` calls these methods, which would fail with `AttributeError` if a new provider forgot to implement them. This is currently not a problem since all three providers implement these methods.

### 6.8 Singleton LLM Prevents Hot-Swapping

**Severity: Low**

The `LLMService` caches both the provider string and the LLM instance. Changing `LLM_PROVIDER` or API keys at runtime has no effect -- the application must be restarted. This is by design for simplicity but worth noting.

---

## 7. How to Add a New Provider

### 7.1 Implement the BaseLLM Interface

Create a new file `druppie/llm/your_provider.py`:

```python
from druppie.llm.base import BaseLLM, LLMResponse

class ChatYourProvider(BaseLLM):
    """Your provider implementation."""

    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self.call_history: list[dict] = []
        self._bound_tools: list[dict] = []

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def provider_name(self) -> str:
        return "your_provider"

    @property
    def supports_native_tools(self) -> bool:
        # Return True if your model handles OpenAI-style tool_calls natively
        # Return False to use XML <tool_call> format in prompts
        return True

    def bind_tools(self, tools: list[dict]) -> "ChatYourProvider":
        new_instance = ChatYourProvider(api_key=self.api_key, model=self.model)
        new_instance._bound_tools = tools
        return new_instance

    def chat(self, messages, tools=None) -> LLMResponse:
        # Synchronous chat completion
        ...

    async def achat(self, messages, tools=None, max_tokens=None) -> LLMResponse:
        # Async chat completion (this is what the agent runtime calls)
        ...

    def get_call_history(self) -> list[dict]:
        return self.call_history.copy()

    def clear_call_history(self) -> None:
        self.call_history = []
```

### 7.2 Required Methods

| Method | Description |
|--------|-------------|
| `chat()` | Synchronous chat completion. Returns `LLMResponse`. |
| `achat()` | Async chat completion. The primary method used by the agent runtime. |
| `bind_tools()` | Create a new instance with tools pre-bound. |
| `model_name` (property) | Return the model name string. |
| `provider_name` (property) | Return the provider identifier string. |
| `supports_native_tools` (property) | Whether to use native OpenAI tool calling or XML prompt injection. |
| `get_call_history()` | Return in-memory call history for debugging. |
| `clear_call_history()` | Clear in-memory call history. |

### 7.3 The LLMResponse Contract

Your provider must return `LLMResponse` with these fields:

```python
LLMResponse(
    content="cleaned text response",
    raw_content="original unprocessed response",
    tool_calls=[
        {
            "id": "unique_call_id",
            "name": "tool_name",
            "args": {"key": "value"},  # Must be a dict
        }
    ],
    prompt_tokens=123,
    completion_tokens=456,
    total_tokens=579,
    model="your-model-name",
    provider="your_provider",
)
```

### 7.4 Register in LLMService

1. **Add import** in `druppie/llm/__init__.py`:
   ```python
   from .your_provider import ChatYourProvider
   ```

2. **Add to `__all__`** in `druppie/llm/__init__.py`.

3. **Add provider branch** in `LLMService.get_provider()` (`druppie/llm/service.py`):
   ```python
   elif provider == "your_provider":
       if not your_key:
           raise LLMConfigurationError("YOUR_PROVIDER_API_KEY required")
       self._provider = "your_provider"
   ```

4. **Add client creation** in `LLMService.get_llm()`:
   ```python
   elif provider == "your_provider":
       self._llm = ChatYourProvider(
           api_key=os.getenv("YOUR_PROVIDER_API_KEY"),
           model=os.getenv("YOUR_PROVIDER_MODEL", "default-model"),
       )
   ```

5. **Add to docker-compose.yml** environment section:
   ```yaml
   YOUR_PROVIDER_API_KEY: ${YOUR_PROVIDER_API_KEY:-}
   YOUR_PROVIDER_MODEL: ${YOUR_PROVIDER_MODEL:-default-model}
   ```

### 7.5 Tool Call Parsing Advice

If your model supports native OpenAI-style tool calling:
- Set `supports_native_tools = True`
- Parse `message.tool_calls` from the API response
- Still add a text-based fallback for `<tool_call>` tags (models sometimes output these despite native support)

If your model does NOT support native tool calling:
- Set `supports_native_tools = False`
- The system prompt will include XML format instructions
- You MUST implement `<tool_call>` tag parsing in your response handler
- Consider copying the parsing logic from `ChatZAI._parse_tool_calls_from_text()` or `ChatDeepInfra._extract_tool_calls_from_text()`

In either case, implement `_parse_malformed_args()` for the common tools (`done`, `fail`, `hitl_ask`, `write_file`) to handle the inevitable cases where the model outputs broken JSON.

---

## Appendix: File Reference

| File | Description |
|------|-------------|
| `druppie/llm/__init__.py` | Module exports |
| `druppie/llm/base.py` | `BaseLLM` abstract class, `LLMResponse` model, exception hierarchy |
| `druppie/llm/service.py` | `LLMService` singleton, provider selection, `get_llm_service()` |
| `druppie/llm/zai.py` | Z.AI (GLM) provider implementation |
| `druppie/llm/deepinfra.py` | DeepInfra provider implementation |
| `druppie/llm/mock.py` | Mock provider for testing |
| `druppie/agents/runtime.py` | Agent runtime -- where LLM is called and tool calls are executed |
| `druppie/domain/agent_definition.py` | `AgentDefinition` model (YAML schema including `model` field) |
| `druppie/agents/definitions/*.yaml` | Per-agent configuration files |
| `druppie/db/models/llm_call.py` | Database model for individual LLM API calls |
| `druppie/db/models/agent_run.py` | Database model for agent runs (aggregated tokens) |
| `druppie/db/models/session.py` | Database model for sessions (aggregated tokens) |
| `druppie/repositories/execution_repository.py` | Data access for LLM calls and token tracking |
