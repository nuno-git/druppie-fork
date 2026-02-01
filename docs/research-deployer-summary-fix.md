# Research: Deployer Summary Bug & Agent Pipeline Improvements

> Deep research into why the deployer agent outputs `done(summary="Task completed")` instead
> of a detailed summary, and what improvements can be made to prevent this across all agents.

---

## Table of Contents

1. [The Smoking Guns](#1-the-smoking-guns)
2. [Full Tool Call Parsing Pipeline](#2-full-tool-call-parsing-pipeline)
3. [System Prompt Assembly Analysis](#3-system-prompt-assembly-analysis)
4. [LangGraph Comparison & Migration Options](#4-langgraph-comparison--migration-options)
5. [Concrete Improvement Proposals](#5-concrete-improvement-proposals)

---

## 1. The Smoking Guns

### Smoking Gun #1: Regex fallbacks default to "Task completed"

Both `deepinfra.py` and `zai.py` have identical fallback logic that **silently replaces any
unparseable summary with "Task completed"**.

**`druppie/llm/deepinfra.py:659-667`** (the `_parse_malformed_args` method):
```python
if tool_name == "done":
    summary_match = re.search(
        r'"?summary"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
    )
    return {
        "summary": summary_match.group(1) if summary_match else "Task completed",
        "artifacts": [],
        "data": {},
    }
```

**`druppie/llm/zai.py:452-460`** - identical pattern.

The regex `[^"]*` stops at the **first double quote** inside the summary value. So if the
Qwen model generates:

```json
{"summary": "Agent developer: Created branch \"feature/add-todo\".\nAgent deployer: ..."}
```

The regex captures only: `Agent developer: Created branch ` (stops at the backslash-quote).
And if the regex fails entirely, it silently returns `"Task completed"`.

### Smoking Gun #2: Python-style function call parser has the same bug

**`druppie/llm/deepinfra.py:446-467`** (the `_extract_python_style_tool_call` method):
```python
if tool_name == "done":
    summary_match = re.search(
        r'summary\s*=\s*["\']([^"\']*)["\']',
        args_str,
        re.DOTALL
    )
    if summary_match:
        args["summary"] = summary_match.group(1)
    else:
        args["summary"] = "Task completed"  # <--- SILENT DEFAULT
```

When Qwen outputs `done(summary="...")` as plain text instead of using native tool calling,
this parser kicks in. Same `[^"']*` regex that truncates at internal quotes, same
`"Task completed"` default.

### Smoking Gun #3: Multiple fallback paths ALL lead to "Task completed"

The tool call parsing has **4 layers of fallback**, and 3 of them default to "Task completed":

```
LLM Response
  ├─ Native tool_calls in API response (line 331)
  │   └─ json.loads(arguments) succeeds → GOOD
  │   └─ json.loads(arguments) FAILS → _parse_malformed_args() → "Task completed"
  │
  ├─ No native tool_calls → check text content (line 356)
  │   ├─ _extract_python_style_tool_call() (line 508)
  │   │   └─ Regex matches → captures summary (may truncate at quotes)
  │   │   └─ Regex fails → "Task completed"
  │   │
  │   └─ <tool_call> XML parsing (line 518)
  │       └─ json.loads succeeds → GOOD
  │       └─ json.loads fails → _parse_malformed_args() → "Task completed"
  │
  └─ Nothing found → no tool calls extracted → agent loops or hits max iterations
```

**Three out of four fallback paths produce "Task completed".**

### Smoking Gun #4: The `done()` tool description is too vague

**`druppie/agents/builtin_tools.py:85-101`**:
```python
"done": {
    "type": "function",
    "function": {
        "name": "done",
        "description": "Signal that you have completed your task. Call this when you
            are done with all your work. You MUST call this tool when finished - do
            not just output text.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "A brief summary of what was accomplished is required",
                },
            },
            "required": ["summary"],
        },
    },
},
```

The tool description says "A brief summary" which **actively encourages short summaries**.
The model sees this tool schema and the system prompt, and the schema is closer to the
actual tool call. "Brief" + LLM laziness = "Task completed".

---

## 2. Full Tool Call Parsing Pipeline

### How a tool call flows from LLM to execution

```
1. Agent runtime calls LLM
   runtime.py:539  →  response = await self.llm.achat(messages, openai_tools)

2. LLM provider parses response
   deepinfra.py:314-388  →  _parse_response()
   ├─ Extracts native tool_calls from API response (line 331)
   ├─ Falls back to text parsing if no native calls (line 356-367)
   └─ Returns LLMResponse with tool_calls list

3. Runtime iterates tool calls
   runtime.py:599-742  →  for each tool_call in response.tool_calls

4. Tool name is resolved (MCP prefix handling)
   runtime.py:603-618  →  Converts "coding_read_file" → "coding:read_file"

5. ToolCall record created in DB
   runtime.py:624  →  execution_repo.create_tool_call(...)

6. ToolExecutor executes the tool
   tool_executor.py:~495-541  →  execute_builtin() for "done"
   builtin_tools.py:511-559  →  done() function

7. Summary relayed to next agent
   builtin_tools.py:539-554  →  Prepends to next agent's planned_prompt

8. Result added to messages for LLM
   runtime.py:726-742  →  {"role": "tool", "content": json.dumps(result)}
```

### Where things can go wrong

| Step | What can fail | Result |
|------|--------------|--------|
| 2 - Native parsing | `json.loads(arguments)` fails on malformed JSON | Falls to `_parse_malformed_args` → "Task completed" |
| 2 - Text fallback | Qwen outputs `done(summary="...")` as text | `_extract_python_style_tool_call` regex may truncate |
| 2 - Text fallback | Qwen outputs `<tool_call>` with bad JSON | `_parse_malformed_args` → "Task completed" |
| 7 - Relay | Summary is "Task completed" | Next agent gets useless PREVIOUS AGENT SUMMARY |

### How tools are sent to the LLM

Tools are sent as proper OpenAI function-calling format in the API payload:

```python
# deepinfra.py:184-186
if effective_tools:
    payload["tools"] = effective_tools
    payload["tool_choice"] = "auto"
```

Both ZAI and DeepInfra send `tool_choice: "auto"`. This means the model can choose whether
to use native tool calling or output text. Qwen sometimes chooses text, which triggers all
the fallback parsing.

### Native tools support flags

| Provider | `supports_native_tools` | Effect on prompt |
|----------|------------------------|-----------------|
| DeepInfra (Qwen) | `True` | Minimal tool instructions appended |
| ZAI (GLM-4) | `False` (default) | XML format instructions + examples added to prompt |

Even though DeepInfra returns `True`, Qwen still sometimes outputs tool calls as text
(confirmed by the `_extract_python_style_tool_call` and `<tool_call>` XML parsing existing
in deepinfra.py specifically for this reason — see the comment at line 356-357:
`"Some models (like Qwen) output tool calls as text"`).

---

## 3. System Prompt Assembly Analysis

### How the final prompt is built

```
_build_system_prompt() [runtime.py:763-797]
  │
  ├─ 1. Load base prompt from YAML definition
  │     self.definition.system_prompt
  │
  ├─ 2. Replace [COMMON_INSTRUCTIONS] with _common.md content
  │     _load_common_prompt() [runtime.py:120-132]
  │
  ├─ 3. Replace [TOOL_DESCRIPTIONS_PLACEHOLDER] with MCP tool docs
  │     generate_tool_descriptions() + _inject_tool_descriptions()
  │
  └─ 4. Append tool usage instructions
        ├─ If supports_native_tools=True: minimal instructions [lines 817-847]
        └─ If supports_native_tools=False: full XML format guide [lines 849-916]
```

The user message is built by `_build_prompt()` [runtime.py:965-997]:
```
CONTEXT:
- project_id: ...
- project_name: ...
- intent: update_project
- repo_name: ...
- repo_url: ...

TASK:
PREVIOUS AGENT SUMMARY:
Agent developer: Created branch feature/add-counter...

---

{original planned_prompt from planner}
```

### Deployer.yaml analysis

The deployer prompt is **192 lines long** with these sections:

| Section | Lines | Content |
|---------|-------|---------|
| Tool warning header | 5-10 | "YOU MUST USE TOOL CALLS" |
| Resume check | 11-32 | 3 conditions to check CONTEXT for |
| [COMMON_INSTRUCTIONS] | 33 | Replaced with ~54 lines from _common.md |
| Branch selection | 36-45 | "branch is NOT auto-injected" |
| Project context | 47-57 | What's available from CONTEXT |
| Container naming | 75-85 | Preview vs production naming rules |
| Deployment workflow | 86-108 | 8-step process |
| Logs section | 109-126 | How to check logs and debug |
| Error recovery | 127-152 | Failure handling instructions |
| **COMPLETION** | **154-171** | **done() format requirements** |
| Approval overrides | 173-182 | Approval config |
| Model config | 184-192 | model, temperature, max_tokens |

**Problem**: The COMPLETION section (the most critical part) is at the **very end** of a
192-line system prompt. After `[COMMON_INSTRUCTIONS]` is expanded, the total system prompt
becomes ~250+ lines. The completion instructions are buried under deployment workflows, log
checking, and error recovery sections.

### Issues with current prompt structure

1. **Instructions at the bottom are deprioritized by weaker LLMs**. Qwen and similar models
   have attention patterns that weight the beginning and end of the prompt but can lose
   detail in the middle-to-late sections. The completion instructions should be at the TOP.

2. **`[COMMON_INSTRUCTIONS]` injects 54 lines early** (replacing the placeholder at line 33).
   This pushes all subsequent deployer-specific instructions further down.

3. **The COMPLETION section repeats what _common.md already says** but with deployer-specific
   examples. An LLM seeing the same instruction twice (once generically in _common.md, once
   specifically in COMPLETION) may weight the generic version more since it comes first.

4. **No structured "checklist before done()" section**. The instructions tell the agent what
   format to use, but don't give it a checklist like:
   ```
   BEFORE calling done(), verify your summary contains:
   □ Previous agent summaries (copied verbatim)
   □ Container name
   □ URL with port
   □ Branch name
   ```

5. **The planned_prompt (from planner) doesn't reinforce summary requirements**.
   `planner.yaml:60-71` shows the planner creates prompts like:
   ```
   "PREVIEW deploy [project] from the feature branch (get branch name from
    PREVIOUS AGENT SUMMARY). Use '-preview' suffix..."
   ```
   This tells the deployer what to DO but not what to put in its summary.

6. **The `done()` tool description contradicts the prompt**. The tool schema says
   "A brief summary" while the prompt says "DETAILED summary with URL, container, branch".
   When there's a conflict between tool schema and system prompt, models often follow the
   tool schema since it's structurally closer to the function call.

---

## 4. LangGraph Comparison & Migration Options

### What LangGraph provides (from llms.txt analysis)

| Feature | LangGraph | Druppie Current |
|---------|-----------|----------------|
| Tool calling loop | `StateGraph` with `ToolNode` + conditional edges | Manual `for` loop in `_run_loop()` (~260 lines) |
| LLM providers | `ChatOpenAI` with `base_url` for any OpenAI-compatible API | Custom `ChatZAI`, `ChatDeepInfra` classes (~800 lines) |
| Tool call parsing | Automatic via LangChain provider packages | Manual regex fallbacks (~300 lines) |
| Structured output | `response_format` with Pydantic models + auto-retry | Manual JSON extraction with 6 fallback strategies |
| HITL/interrupts | `interrupt()` function with state persistence | Custom pause/resume with DB state reconstruction |
| Multi-agent | Subagents, handoffs, routers as graph patterns | Sequential pipeline with planned_prompt relay |
| Retry | `RetryPolicy` per node | Custom retry in `achat()` and `_execute_tool_with_retry()` |

### Key LangGraph features relevant to the deployer bug

**1. Native tool calling eliminates regex parsing entirely**

With LangGraph + `ChatOpenAI`:
```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="Qwen/Qwen3-Next-80B-A3B-Instruct",
    api_key=os.getenv("DEEPINFRA_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
)
model_with_tools = model.bind_tools(tools)
```

LangChain's `ChatOpenAI` handles ALL tool call parsing natively. The 300+ lines of regex
parsing in `zai.py` and `deepinfra.py` would be eliminated. No more "Task completed"
defaults from failed regex.

**2. Structured output for the `done()` tool**

LangGraph supports Pydantic models as structured output with automatic retry:
```python
from pydantic import BaseModel, Field

class DoneSummary(BaseModel):
    previous_summaries: str = Field(description="Copy of all previous agent summaries")
    your_summary: str = Field(description="One sentence about what this agent did")
    deployment_url: str | None = Field(description="The deployment URL if applicable")
    container_name: str | None = Field(description="Container name if applicable")

agent = create_agent(model, tools=tools, response_format=DoneSummary)
```

If the model outputs invalid structured output, LangGraph **automatically retries** by
feeding the validation error back to the model. No silent defaults.

**3. `interrupt()` for HITL and approvals**

```python
from langgraph.types import interrupt

@tool
def hitl_ask_question(question: str):
    answer = interrupt({"question": question})
    return answer
```

This would replace the manual state serialization in `resume()`, `resume_from_approval()`,
`continue_run()`, and `_reconstruct_messages_from_db()` (~150 lines of state reconstruction).

**4. What LangGraph would NOT replace**

These are Druppie-specific and would need custom nodes/tools:
- MCP tool execution via HTTP (`MCPHttp` class)
- Approval workflows with role-based access
- Argument injection from `mcp_config.yaml`
- Database recording of all LLM calls and tool calls
- Agent access control per YAML definition

### Migration effort assessment

| Component | Replaceable | Custom needed |
|-----------|------------|---------------|
| `ChatZAI` (615 lines) | Yes → `ChatOpenAI` | None |
| `ChatDeepInfra` (786 lines) | Yes → `ChatOpenAI` | None |
| `BaseLLM` (146 lines) | Yes → `BaseChatModel` | None |
| `LLMService` (170 lines) | Yes → `init_chat_model()` | None |
| `Agent._run_loop()` (260 lines) | Yes → `StateGraph` | Approval/HITL nodes |
| `Agent._build_system_prompt()` (250 lines) | Partial | Prompt assembly stays |
| `ToolExecutor` (541 lines) | Partial | MCP routing + approvals |
| `builtin_tools.py` (636 lines) | Partial | done/plan stay as tools |

**Estimated reduction**: ~1,600 lines of LLM provider + parsing code eliminated,
replaced by ~200 lines of LangGraph graph definitions.

---

## 5. Concrete Improvement Proposals

### Proposal A: Fix the immediate bug (quick win, no architecture change)

**Changes needed:**

1. **Fix the `done()` tool description** (`builtin_tools.py:85-101`):
   Change `"A brief summary of what was accomplished is required"` to:
   ```
   "DETAILED summary of what was accomplished. MUST include: all previous agent
    summaries (copied verbatim from PREVIOUS AGENT SUMMARY), plus your own one-line
    summary with key outputs (URLs, branch names, container names, file paths).
    NEVER write just 'Task completed' or 'Done'."
   ```

2. **Remove "Task completed" defaults** from all regex fallbacks:
   - `deepinfra.py:664` — instead of defaulting to "Task completed", default to the
     raw `args_str` truncated to 500 chars, or raise a parse error
   - `deepinfra.py:456` — same
   - `zai.py:457` — same
   - Replace all `"Task completed"` defaults with the actual raw text the model produced

3. **Fix the regex to handle escaped quotes** in summaries:
   Change `[^"]*` to handle `\"` properly, or better yet, use `json.loads` with
   fallback to a proper JSON5/relaxed parser instead of regex.

4. **Move COMPLETION section to the top** of deployer.yaml (right after the tool warning):
   The model is more likely to follow instructions at the beginning of the prompt.

5. **Add summary requirements to the planner's prompts**:
   When `make_plan` creates deployer steps, append: "Your done() summary MUST include
   the deployment URL, container name, and all previous agent summaries."

### Proposal B: Auto-prepend previous summaries (medium effort, high impact)

**Changes to `builtin_tools.py:done()` function:**

The system already stores each agent's `done()` result. Instead of relying on the LLM to
copy previous summaries, the `done()` function should:

1. Query all completed agent runs for this session
2. Collect their summaries
3. Auto-prepend them to the current summary before relaying

```python
async def done(summary, session_id, agent_run_id, execution_repo):
    # Get all completed runs' summaries for this session
    completed_runs = execution_repo.get_completed_runs(session_id)
    previous_summaries = []
    for run in completed_runs:
        if run.id != agent_run_id and run.summary:
            previous_summaries.append(run.summary)

    # Build full accumulated summary
    full_summary = "\n".join(previous_summaries + [summary]) if previous_summaries else summary

    # Relay the full summary to next agent
    next_run = execution_repo.get_next_pending(session_id)
    if next_run and next_run.planned_prompt:
        new_prompt = f"PREVIOUS AGENT SUMMARY:\n{full_summary}\n\n---\n\n" + next_run.planned_prompt
        execution_repo.update_planned_prompt(next_run.id, new_prompt)

    return {"status": "completed", "summary": full_summary}
```

This removes the entire "copy previous summaries" burden from the LLM. Each agent only needs
to describe what IT did.

### Proposal C: Auto-extract deployment info from tool results (medium effort)

When the deployer calls `done()`, the system can inspect the deployer's tool call history
for that agent run and extract:
- From `docker:build` result → image name, branch
- From `docker:run` result → container name, port mapping, URL

If the summary is missing this info, auto-append it.

### Proposal D: Migrate LLM providers to LangChain (high effort, eliminates root cause)

Replace `ChatZAI` and `ChatDeepInfra` with `langchain_openai.ChatOpenAI`:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="Qwen/Qwen3-Next-80B-A3B-Instruct",
    api_key=os.getenv("DEEPINFRA_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
    temperature=0.1,
    max_tokens=16384,
)
```

This eliminates:
- All custom response parsing (~300 lines)
- All regex fallbacks for tool calls
- All malformed argument recovery
- The `supports_native_tools` flag and dual-mode handling

LangChain's `ChatOpenAI` is battle-tested with dozens of OpenAI-compatible providers.

### Proposal E: Full LangGraph migration (highest effort, most benefit)

Replace the custom agent runtime with LangGraph graphs:

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

def agent_node(state):
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def should_continue(state):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"
    return END

graph = StateGraph(MessagesState)
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools))
graph.add_conditional_edges("agent", should_continue, ["tools", END])
graph.add_edge("tools", "agent")
graph.add_edge(START, "agent")
```

With custom nodes for:
- Approval checking (using `interrupt()`)
- HITL questions (using `interrupt()`)
- MCP tool routing
- Summary validation before `done()` completes

### Recommended approach: Proposals A + B together

**Proposal A** fixes the immediate bugs (remove "Task completed" defaults, fix tool
description, improve prompt structure). This can be done in 30 minutes.

**Proposal B** makes summary relay bulletproof by removing the LLM's responsibility
to copy previous summaries. This can be done in an hour.

Together, these two changes eliminate the deployer summary bug without any architectural
changes. Proposals D and E can be pursued later as a larger refactor.

---

## Appendix: All "Task completed" default locations

| File | Line | Context |
|------|------|---------|
| `druppie/llm/deepinfra.py` | 456 | `_extract_python_style_tool_call` — done tool regex fallback |
| `druppie/llm/deepinfra.py` | 664 | `_parse_malformed_args` — done tool regex fallback |
| `druppie/llm/zai.py` | 457 | `_parse_malformed_args` — done tool regex fallback |
| `druppie/agents/runtime.py` | 718 | `result.get("summary", "Task completed")` — return value default |
| `druppie/llm/deepinfra.py` | 495 | `done(summary="Task completed successfully")` — comment/example |

## Appendix: Key file locations

| File | Purpose | Key lines |
|------|---------|-----------|
| `druppie/llm/deepinfra.py` | DeepInfra/Qwen LLM provider | 314-388 (parsing), 416-486 (python-style), 488-621 (XML), 623-682 (malformed args) |
| `druppie/llm/zai.py` | Z.AI/GLM LLM provider | 308-382 (parsing), 407-513 (malformed args), 515-598 (text tool calls) |
| `druppie/llm/base.py` | Base LLM class | 136-145 (`supports_native_tools`) |
| `druppie/agents/runtime.py` | Agent loop + prompt building | 484-747 (run loop), 763-797 (system prompt), 965-997 (user prompt) |
| `druppie/agents/builtin_tools.py` | Built-in tool defs + impl | 85-101 (done schema), 511-559 (done impl) |
| `druppie/execution/tool_executor.py` | Tool routing + execution | 495-541 (builtin execution) |
| `druppie/agents/definitions/deployer.yaml` | Deployer agent config | 154-171 (COMPLETION section) |
| `druppie/agents/definitions/_common.md` | Shared agent instructions | 1-54 (summary relay rules) |
