# Execution Engine

This document explains how Druppie's agent execution engine works -- from the
moment a user message arrives to the final `done()` call of the last agent.

---

## Table of Contents

1. [Orchestrator Flow](#1-orchestrator-flow)
2. [Agent Runtime Loop](#2-agent-runtime-loop)
3. [Tool Execution](#3-tool-execution)
4. [Summary Relay](#4-summary-relay)
5. [HITL Pause/Resume](#5-hitl-pauseresume)
6. [Approval Pause/Resume](#6-approval-pauseresume)
7. [MCP HTTP Communication](#7-mcp-http-communication)

---

## 1. Orchestrator Flow

**File:** `druppie/execution/orchestrator.py`

The `Orchestrator` is the top-level entry point. It is intentionally "dumb" --
it creates agent runs and executes them in order. All intelligent behavior
(intent classification, project creation, planning) is delegated to agents and
their built-in tools.

### 1.1 process_message()

`Orchestrator.process_message()` (line 80) is called when a user sends a
message. It performs five steps:

```
process_message(message, user_id, session_id?, project_id?)
    |
    |-- Step 1: Get or create session
    |-- Step 2: Save user message to timeline (role="user")
    |-- Step 3: Get user's projects, format for router injection
    |-- Step 4: Create two PENDING agent runs:
    |             Router  (sequence_number=0)
    |             Planner (sequence_number=1)
    |-- Step 5: Call execute_pending_runs(session_id)
```

**Key details:**

- The router's prompt includes a formatted list of the user's existing projects
  so it can decide whether to create a new project or update an existing one.
  (`_format_projects_for_router()`, line 172)
- The planner's initial prompt is just `USER REQUEST:\n{message}`. The router's
  `set_intent()` tool will enrich it later with intent context before the
  planner executes.
- Both runs are created as `AgentRunStatus.PENDING` before any execution begins.

### 1.2 execute_pending_runs()

`execute_pending_runs()` (line 186) is a while-loop that:

1. Queries the database for the next pending run (ordered by `sequence_number`).
2. Rebuilds project context from the database (`_build_project_context()`, line 242).
3. Marks the run as `RUNNING`.
4. Calls `_run_agent()` to execute it.
5. If the agent returns `"paused"`, stops the loop (the session waits for user
   input or approval).
6. If the agent returns `"completed"`, loops back to get the next pending run.
7. When no pending runs remain, marks the session as `COMPLETED`.

```
                    execute_pending_runs(session_id)
                              |
                              v
                    +--------------------+
                    | get_next_pending() |<-----------+
                    +--------------------+            |
                          |        |                  |
                       (none)   (found)               |
                          |        |                  |
                          v        v                  |
                     Mark Session  Build context      |
                     COMPLETED     Mark run RUNNING   |
                                   |                  |
                                   v                  |
                              _run_agent()            |
                                   |                  |
                          +--------+--------+         |
                          |                 |         |
                       "paused"        "completed"    |
                          |                 |         |
                          v                 +---------+
                     Return (stop loop)
```

**Context rebuilding** is critical: before each agent, `_build_project_context()`
(line 242) expires all cached SQLAlchemy objects and re-queries the database.
This ensures that when the router creates a project and Gitea repo, subsequent
agents (deployer, developer) see the `repo_name`, `repo_owner`, and `repo_url`
in their context.

### 1.3 _run_agent()

`_run_agent()` (line 299) instantiates an `Agent` object and calls `agent.run()`.
It interprets the result:

- If the result contains `status == "paused"` or `paused == True`:
  - `reason == "waiting_answer"` -> status set to `PAUSED_HITL`
  - Any other reason -> status set to `PAUSED_TOOL`
- Otherwise, status set to `COMPLETED`.

### 1.4 End-to-End Sequence Diagram

```
User            Orchestrator              DB                Agent(router)      Agent(planner)     Agent(architect)  ...
 |                  |                      |                     |                  |                  |
 |--message-------->|                      |                     |                  |                  |
 |                  |--create session------>|                     |                  |                  |
 |                  |--save user msg------->|                     |                  |                  |
 |                  |--create router run--->|                     |                  |                  |
 |                  |--create planner run-->|                     |                  |                  |
 |                  |                      |                     |                  |                  |
 |                  |====execute_pending_runs()=================  |                  |                  |
 |                  |                      |                     |                  |                  |
 |                  |--get_next_pending---->| (router, seq=0)    |                  |                  |
 |                  |--mark RUNNING-------->|                     |                  |                  |
 |                  |--_run_agent("router")-------------------->|                  |                  |
 |                  |                      |                     |                  |                  |
 |                  |                      |  set_intent() creates project,         |                  |
 |                  |                      |  updates planner prompt                |                  |
 |                  |                      |                     |                  |                  |
 |                  |<-----"completed"-----|----result-----------|                  |                  |
 |                  |--mark COMPLETED----->|                     |                  |                  |
 |                  |                      |                     |                  |                  |
 |                  |--get_next_pending---->| (planner, seq=1)   |                  |                  |
 |                  |--mark RUNNING-------->|                     |                  |                  |
 |                  |--_run_agent("planner")------------------------------------->|                  |
 |                  |                      |                     |                  |                  |
 |                  |                      |  make_plan() creates architect,        |                  |
 |                  |                      |  developer, deployer runs              |                  |
 |                  |                      |                     |                  |                  |
 |                  |<-----"completed"-----|------result---------|------------------|                  |
 |                  |--mark COMPLETED----->|                     |                  |                  |
 |                  |                      |                     |                  |                  |
 |                  |--get_next_pending---->| (architect, seq=0) |                  |                  |
 |                  |--mark RUNNING-------->|                     |                  |                  |
 |                  |--_run_agent("architect")---------------------------------------------->|
 |                  |                      |                     |                  |                  |
 |                  :                      :                     :                  :        (continues)
```

---

## 2. Agent Runtime Loop

**File:** `druppie/agents/runtime.py`

The `Agent` class encapsulates everything needed to run a single agent: loading
its YAML definition, building the system prompt, running the LLM tool-calling
loop, and handling pause/completion states.

### 2.1 Agent Initialization

```python
agent = Agent("developer", db=db_session)  # runtime.py:70
```

On construction, `Agent.__init__()` (line 70):

1. Sets `self.id` to the agent ID (e.g., `"developer"`).
2. Calls `_load_definition()` (line 100) which loads and caches
   `druppie/agents/definitions/{agent_id}.yaml` into an `AgentDefinition`
   Pydantic model.
3. Stores the database session for later use.
4. LLM client, MCP config, and ToolExecutor are lazy-loaded as properties.

### 2.2 Agent.run()

`Agent.run()` (line 176) is the main entry point for a fresh agent execution:

1. Converts string IDs to UUIDs.
2. Builds the initial message list:
   - `system` message from `_build_system_prompt()` (line 763)
   - `user` message from `_build_prompt(prompt, context)` (line 965)
3. Delegates to `_run_loop()` starting at `iteration=0`.

### 2.3 System Prompt Construction

`_build_system_prompt()` (line 763) assembles the system prompt in layers:

1. Starts with the raw `system_prompt` from the YAML definition.
2. Replaces the `[COMMON_INSTRUCTIONS]` placeholder with shared instructions
   from `druppie/agents/definitions/_common.md` (line 778-779).
3. Generates dynamic tool descriptions from `mcp_config.yaml` and injects
   them at `[TOOL_DESCRIPTIONS_PLACEHOLDER]` or the `AVAILABLE TOOLS:` section
   (line 783-786, `_inject_tool_descriptions()` at line 918).
4. For router/planner: optionally adds XML format instructions for LLMs without
   native tool calling support (line 789-793).
5. For other agents: appends shared tool usage instructions documenting the
   built-in tools (`hitl_ask_question`, `hitl_ask_multiple_choice_question`,
   `done`) (line 796-797).

### 2.4 The Core Loop: _run_loop()

`_run_loop()` (line 484) is the heart of the agent runtime. It implements an
iterative LLM tool-calling loop.

```
_run_loop(messages, prompt, context, session_id, agent_run_id, start_iteration)
    |
    |-- Load MCP tools from config (filtered by agent YAML's mcps field)
    |-- Convert to OpenAI format, add builtin tools
    |-- max_iterations = definition.max_iterations (default 10)
    |
    |-- FOR iteration in range(start_iteration, max_iterations):
    |     |
    |     |-- Create LLM call record in DB
    |     |-- Call LLM: response = await llm.achat(messages, tools, max_tokens)
    |     |-- Record response in DB (tokens, duration, tool_calls)
    |     |
    |     |-- IF no tool_calls in response:
    |     |     |-- Router/planner: parse JSON output, return
    |     |     |-- Other agents: add reminder message, retry
    |     |     |-- Last iteration: parse output and return
    |     |
    |     |-- FOR EACH tool_call in response.tool_calls:
    |     |     |
    |     |     |-- Parse server:tool from tool name
    |     |     |-- Create ToolCall record in DB
    |     |     |-- Execute via tool_executor.execute(tool_call_id)
    |     |     |
    |     |     |-- IF status == WAITING_ANSWER:
    |     |     |     Return {status: "paused", reason: "waiting_answer", ...}
    |     |     |
    |     |     |-- IF status == WAITING_APPROVAL:
    |     |     |     Return {status: "paused", reason: "waiting_approval", ...}
    |     |     |
    |     |     |-- IF tool == "done" and result.status == "completed":
    |     |     |     Return {success: true, result: summary}
    |     |     |
    |     |     |-- Otherwise: append assistant + tool messages to history
    |     |
    |-- Raise AgentMaxIterationsError if loop exhausted
```

**Key behaviors:**

- **Tool name parsing** (line 605-614): The LLM may return tool names in
  different formats. The runtime handles:
  - Builtin tools: `server = "builtin"`, `tool = tool_name`
  - Colon-separated: `"coding:read_file"` -> `server="coding"`, `tool="read_file"`
  - Underscore-separated: `"coding_read_file"` -> `server="coding"`, `tool="read_file"`

- **No-tool-call handling** (line 577-596): If the LLM responds with text
  instead of a tool call, the runtime adds a reminder:
  `"ERROR: You MUST use a tool call. Call 'done' when finished."` and retries.
  Router and planner are exempt (they output JSON directly).

- **Completion detection** (line 714): The agent is only considered complete
  when it calls the `done` tool and the result contains `status: "completed"`.
  This is the sole exit path for worker agents.

- **Max iterations** (line 744): If the agent exhausts its iteration budget
  (default 10, developer gets 100), an `AgentMaxIterationsError` is raised.

### 2.5 Tool Collection

Tools available to an agent come from two sources, merged at line 507-512:

1. **MCP tools**: Loaded from `mcp_config.yaml`, filtered by the agent's `mcps`
   field in its YAML definition. Hidden parameters (like `session_id`,
   `repo_name`) are stripped from the schema so the LLM never sees them.
   Converted to OpenAI function format via `_to_openai_tools()` (line 749).

2. **Builtin tools**: Every agent gets the defaults (`done`,
   `hitl_ask_question`, `hitl_ask_multiple_choice_question`). Agents can
   declare additional builtins via `extra_builtin_tools` in YAML (e.g., router
   adds `set_intent`, planner adds `make_plan`).

```python
# runtime.py:511-512
builtin_tool_names = DEFAULT_BUILTIN_TOOLS + self.definition.extra_builtin_tools
openai_tools.extend(get_builtin_tools(builtin_tool_names))
```

### 2.6 continue_run() -- Resuming from Database State

`continue_run()` (line 331) is used when an agent resumes after a pause (HITL
or approval). Instead of maintaining in-memory state, it reconstructs the full
conversation from the database:

1. Loads all `LLMCall` records for the agent run.
2. Calls `_reconstruct_messages_from_db()` (line 414) to rebuild the message
   history, including system prompt, user message, assistant tool calls, and
   tool results.
3. Sets `start_iteration = len(llm_calls)` so the loop continues from where it
   left off.
4. Calls `_run_loop()` with the reconstructed state.

This design means no in-memory state needs to survive across pauses -- the
database is the single source of truth.

---

## 3. Tool Execution

**File:** `druppie/execution/tool_executor.py`

The `ToolExecutor` is the single gateway for all tool execution. Every tool call
-- whether builtin, HITL, or MCP -- flows through `ToolExecutor.execute()`.

### 3.1 Classification and Routing

`ToolExecutor.execute(tool_call_id)` (line 245) follows this decision tree:

```
execute(tool_call_id)
    |
    |-- Load ToolCall from DB
    |
    |-- Is it a builtin tool? (mcp_server == "builtin" or name in BUILTIN_TOOLS)
    |     |
    |     |-- YES: Is it a HITL tool? (hitl_ask_question or hitl_ask_multiple_choice_question)
    |     |     |-- YES --> _execute_hitl_tool()    --> WAITING_ANSWER
    |     |     |-- NO  --> _execute_builtin_tool() --> COMPLETED/FAILED
    |     |
    |     +-- (skip approval check for builtins)
    |
    |-- NO (MCP tool):
    |     |
    |     |-- Load agent definition for access control
    |     |-- Check if agent is allowed to use this tool (mcps whitelist)
    |     |     |-- NOT ALLOWED --> FAILED with error
    |     |
    |     |-- Check if approval is needed (layered system):
    |     |     |-- Layer 1: Agent YAML approval_overrides
    |     |     |-- Layer 2: Global mcp_config.yaml defaults
    |     |     |
    |     |     |-- NEEDS APPROVAL --> _create_approval_and_wait() --> WAITING_APPROVAL
    |     |
    |     |-- No approval needed --> _execute_mcp_tool() --> COMPLETED/FAILED
```

### 3.2 Builtin Tool Categories

**File:** `druppie/agents/builtin_tools.py`

Builtin tools are defined in `BUILTIN_TOOL_DEFS` (line 33) and split into two
categories:

| Category | Tools | Behavior |
|----------|-------|----------|
| HITL | `hitl_ask_question`, `hitl_ask_multiple_choice_question` | Creates a `Question` record, sets status to `WAITING_ANSWER`, pauses the agent |
| Non-HITL | `done`, `make_plan`, `set_intent`, `create_message` | Executes immediately via `execute_builtin()` (line 666) |

Default builtins (every agent): `done`, `hitl_ask_question`,
`hitl_ask_multiple_choice_question` (line 30).

Extra builtins per agent:
- Router: `set_intent`
- Planner: `make_plan`

### 3.3 Approval Checking -- Layered System

The approval system (`MCPConfig.needs_approval()`, `druppie/core/mcp_config.py`
line 180) uses two layers:

1. **Agent-level overrides** (`approval_overrides` in agent YAML):
   ```yaml
   approval_overrides:
     coding:write_file:
       requires_approval: true
       required_role: architect
   ```
   If a matching override exists, it takes precedence.

2. **Global defaults** (`mcp_config.yaml`):
   ```yaml
   tools:
     - name: build
       requires_approval: true
       required_role: developer
   ```

Example: `docker:build` requires developer approval globally. No agent
overrides this, so all agents need developer approval to build Docker images.

### 3.4 Access Control

Before checking approval, `execute()` (line 284) validates that the agent is
allowed to use the tool at all. This is based on the `mcps` field in agent YAML:

```yaml
# developer.yaml -- only these coding tools are allowed
mcps:
  coding:
    - read_file
    - write_file
    - batch_write_files
    - commit_and_push
    # ...
```

If the agent tries to call a tool not in its whitelist, execution fails with a
descriptive error message.

### 3.5 Argument Injection

**Files:** `druppie/execution/tool_executor.py` (line 121),
`druppie/execution/tool_context.py`, `druppie/core/mcp_config.yaml`

Before executing an MCP tool, `_apply_injection_rules()` (tool_executor.py:121)
injects context values into the tool arguments. This replaces hardcoded
injection logic with a declarative system.

**How it works:**

1. `MCPConfig.get_injection_rules(server, tool_name)` loads rules from
   `mcp_config.yaml`:
   ```yaml
   coding:
     inject:
       session_id:
         from: session.id
         hidden: true
       repo_name:
         from: project.repo_name
         hidden: true
         tools: [read_file, write_file, ...]
   ```

2. A `ToolContext` object (tool_context.py:25) lazily loads database objects
   (Session, Project, User) and resolves dotted paths:
   - `session.id` -> the session's UUID
   - `project.repo_name` -> the project's Gitea repository name
   - `project.repo_owner` -> the Gitea username who owns the repo
   - `user.id` -> the user's UUID

3. For each rule:
   - **Hidden params**: Always override LLM-provided values (the LLM should
     never guess these).
   - **Non-hidden params**: Only inject if not already provided by the LLM.

```
Tool Argument Injection Flow:

    LLM calls: coding_write_file(path="index.html", content="<html>...")
                            |
                            v
                _apply_injection_rules("coding", "write_file", args, session_id)
                            |
                            |-- Rule: session_id <- session.id (hidden)
                            |-- Rule: repo_name <- project.repo_name (hidden)
                            |-- Rule: repo_owner <- project.repo_owner (hidden)
                            |
                            v
    Final args: {path: "index.html", content: "<html>...",
                 session_id: "abc-123", repo_name: "my-app-a1b2c3d4",
                 repo_owner: "admin"}
```

The `hidden: true` flag serves double duty:
1. At **prompt time**: hidden params are stripped from the tool schema the LLM
   sees (`MCPConfig.get_hidden_params()`, mcp_config.py:307), so the LLM never
   tries to fill them in.
2. At **execution time**: hidden params are always overridden with the real
   database values, even if the LLM hallucinated a value.

---

## 4. Summary Relay

**File:** `druppie/agents/builtin_tools.py` (line 569, `done()` function)

The summary relay mechanism is how agents pass information to each other in the
execution pipeline. Since agents run sequentially and cannot communicate
directly, the `done()` tool accumulates summaries and prepends them to the next
agent's prompt.

### 4.1 How done() Works

When an agent calls `done(summary="Agent developer: Pushed 3 files to feature/add-counter.")`:

1. **Collect previous summaries** (line 599-616):
   - Query all `COMPLETED` agent runs for this session.
   - For each, retrieve the `done` tool call's result summary.
   - Extract individual `"Agent <role>:"` lines to avoid duplication.

2. **Deduplicate** (line 620-628):
   - Strip any previously-accumulated lines that the current agent may have
     copied into its own summary.
   - Combine: previous summaries first, then this agent's own lines.

3. **Relay to next agent** (line 640-654):
   - Find the next `PENDING` agent run in the session.
   - Prepend `PREVIOUS AGENT SUMMARY:\n{accumulated_summary}\n\n---\n\n` to
     that agent's `planned_prompt`.

4. **Return** (line 656-659):
   ```python
   return {"status": "completed", "summary": accumulated_summary}
   ```

### 4.2 Example Accumulation

After three agents complete in sequence:

```
Agent architect: Designed counter app architecture, wrote architecture.md.
Agent developer: Implemented app on branch feature/add-counter, pushed 3 files.
Agent deployer: Built and deployed preview at http://localhost:9101 (container: counter-preview).
```

The deployer's `done()` call collected the architect's and developer's summaries
automatically, then added its own line. The full accumulated summary was
prepended to the summarizer's prompt so it could generate a user-friendly
completion message.

### 4.3 Shared Instructions (_common.md)

**File:** `druppie/agents/definitions/_common.md`

All worker agents include shared instructions via the `[COMMON_INSTRUCTIONS]`
placeholder. These instructions (loaded by `_load_common_prompt()`,
runtime.py:119) tell agents:

- How to read `PREVIOUS AGENT SUMMARY` in their prompt.
- That the system auto-prepends previous summaries -- they only write their own
  `"Agent <role>:"` line.
- Format requirements: one sentence, max ~30 words, include actionable details
  (branch names, URLs, container names).
- That the workspace is shared across agents (if a previous agent created a
  branch, the current agent is already on it).

---

## 5. HITL Pause/Resume

HITL (Human-in-the-Loop) allows agents to pause and ask the user a question.

### 5.1 Pause Flow

```
Agent._run_loop()                ToolExecutor                    DB
      |                               |                          |
      |--tool_call: hitl_ask_question--|                          |
      |                               |                          |
      |                               |--create ToolCall--------->|
      |                               |--execute(tool_call_id)--->|
      |                               |                          |
      |                               |  _execute_hitl_tool():   |
      |                               |    Create Question------->|
      |                               |    Update ToolCall------->| (status=WAITING_ANSWER)
      |                               |                          |
      |                               |<--WAITING_ANSWER----------|
      |                               |                          |
      |<--WAITING_ANSWER--------------|                          |
      |                                                          |
      |  Save agent_state (messages, iteration, tool_call_id)    |
      |  Return {status: "paused", reason: "waiting_answer"}     |
      |                                                          |
Orchestrator._run_agent()                                        |
      |                                                          |
      |  Receives "paused"                                       |
      |  update_status(agent_run_id, PAUSED_HITL)--------------->|
      |  Stop execute_pending_runs loop                          |
```

**HITL tool execution** (`_execute_hitl_tool()`, tool_executor.py:448):

1. Determines question type: `"text"` for `hitl_ask_question`, `"choice"` for
   `hitl_ask_multiple_choice_question`.
2. Creates a `Question` record via `QuestionRepository.create()` with the
   question text, choices (if any), and links to session/agent_run/tool_call.
3. Sets the tool call status to `WAITING_ANSWER`.

The question appears in the UI. The user types an answer and submits it.

### 5.2 Resume Flow

**File:** `druppie/execution/orchestrator.py`, `resume_after_answer()` (line 456)

```
User answers question
      |
      v
API endpoint calls Orchestrator.resume_after_answer(session_id, question_id, answer)
      |
      |-- Step 1: Get question from DB, find agent_run_id
      |-- Step 2: tool_executor.complete_after_answer(question_id, answer)
      |             |
      |             |-- Update Question with answer
      |             |-- Build result: {status: "answered", answer: "...", question: "..."}
      |             |-- Update ToolCall: status=COMPLETED, result=<answer>
      |             |
      |-- Step 3: Get the paused agent run
      |-- Step 4: Set agent run status back to RUNNING
      |-- Step 5: agent.continue_run(session_id, agent_run_id)
      |             |
      |             |-- Reconstruct messages from DB (including the answer as tool result)
      |             |-- Resume _run_loop() from where it left off
      |             |
      |-- Step 6: Handle result (completed or paused again)
      |-- Step 7: If completed, call execute_pending_runs() for remaining agents
```

The critical insight is that `continue_run()` (runtime.py:331) reconstructs
state entirely from the database. The HITL answer was saved as the `ToolCall`
result in step 2, so when messages are reconstructed in step 5, the answer
appears as a `tool` role message in the conversation -- the LLM sees it as if
the tool returned the user's answer.

---

## 6. Approval Pause/Resume

MCP tools that require approval (e.g., `docker:build`, `docker:run`,
`coding:merge_pull_request`) follow a similar pause/resume pattern but with
an approval gate instead of a question.

### 6.1 Pause Flow

```
Agent._run_loop()                ToolExecutor                          DB
      |                               |                                |
      |--tool_call: docker_build------|                                |
      |                               |                                |
      |                               |--create ToolCall-------------->|
      |                               |--execute(tool_call_id)-------->|
      |                               |                                |
      |                               |  needs_approval("docker","build") = (True, "developer")
      |                               |                                |
      |                               |  _create_approval_and_wait():  |
      |                               |    Create Approval record----->| (status=pending,
      |                               |                                |  required_role=developer)
      |                               |    Update ToolCall------------>| (status=WAITING_APPROVAL)
      |                               |                                |
      |                               |<--WAITING_APPROVAL-------------|
      |                               |                                |
      |<--WAITING_APPROVAL------------|                                |
      |                                                                |
      |  Save agent_state                                              |
      |  Return {status: "paused", reason: "waiting_approval"}         |
      |                                                                |
Orchestrator._run_agent()                                              |
      |                                                                |
      |  Receives "paused"                                             |
      |  update_status(agent_run_id, PAUSED_TOOL)--------------------->|
      |  Stop execute_pending_runs loop                                |
```

**Approval creation** (`_create_approval_and_wait()`, tool_executor.py:408):

1. Creates an `Approval` record via `ApprovalRepository.create()` with:
   - `session_id`, `agent_run_id`, `tool_call_id`
   - `mcp_server`, `tool_name`, `arguments`
   - `required_role` (e.g., `"developer"`)
2. Sets tool call status to `WAITING_APPROVAL`.

The approval appears in the UI. A user with the required role can approve or
reject it.

### 6.2 Resume Flow

**File:** `druppie/execution/orchestrator.py`, `resume_after_approval()` (line 361)

```
User approves the tool execution
      |
      v
API endpoint calls Orchestrator.resume_after_approval(session_id, approval_id)
      |
      |-- Step 1: Get approval from DB, find agent_run_id
      |-- Step 2: tool_executor.execute_after_approval(approval_id)
      |             |
      |             |-- Verify approval.status == "approved"
      |             |-- Get associated ToolCall
      |             |-- Execute the MCP tool (skip approval check)
      |             |-- Update ToolCall with result
      |             |
      |-- Step 3: Get the paused agent run
      |-- Step 4: Set agent run status back to RUNNING
      |-- Step 5: agent.continue_run(session_id, agent_run_id)
      |             |
      |             |-- Reconstruct messages from DB (including tool result)
      |             |-- Resume _run_loop()
      |             |
      |-- Step 6: Handle result (completed, or paused again for another approval)
      |-- Step 7: If completed, call execute_pending_runs() for remaining agents
```

Note that after approval, the actual MCP tool is executed via
`execute_after_approval()` (tool_executor.py:320), which calls
`_execute_mcp_tool()` directly -- skipping the approval check since it was
already granted.

### 6.3 Rejection

If the user rejects the approval, the tool call fails. The agent sees the
failure in its conversation history and can decide how to proceed (try a
different approach, ask the user, etc.).

---

## 7. MCP HTTP Communication

**File:** `druppie/execution/mcp_http.py`

MCP (Model Context Protocol) servers are separate microservices that provide
tool capabilities. Druppie communicates with them over HTTP using the FastMCP
client library.

### 7.1 Architecture

```
+-------------------+          HTTP/StreamableHttp         +------------------+
|                   |  --------------------------------->  |                  |
|  Druppie Backend  |  call("coding", "write_file", args)  |  MCP Coding     |
|  (FastAPI)        |  <---------------------------------  |  Server (:9001)  |
|                   |          JSON response                |                  |
+-------------------+                                      +------------------+
         |
         |  call("docker", "build", args)
         |
         v
+------------------+
|  MCP Docker      |
|  Server (:9002)  |
+------------------+
```

### 7.2 MCPHttp Client

`MCPHttp` (line 32) wraps the FastMCP `Client` with:
- Server URL resolution from `mcp_config.yaml`
- Timeout handling (default 60 seconds)
- Error classification (retryable vs non-retryable)
- Response parsing

**Initialization:**
```python
mcp_http = MCPHttp(mcp_config)  # mcp_http.py:40
```

### 7.3 Calling a Tool

`MCPHttp.call()` (line 57):

1. Gets the server URL from config: `self.config.get_server_url(server)`.
   URLs are normalized to end with `/mcp` for FastMCP's StreamableHttp
   transport (mcp_config.py:138).

2. Gets or creates a `Client` instance for the server
   (`_get_client()`, line 49). Each server gets a cached `Client` with a
   `StreamableHttpTransport`.

3. Executes the call within an async context manager with timeout:
   ```python
   async with client:
       result = await client.call_tool(tool, args)
   ```

4. Parses the FastMCP response via `_parse_result()` (line 134).

### 7.4 Response Parsing

FastMCP `call_tool()` returns a list of content items. `_parse_result()`
(line 134) handles multiple response formats:

- **List with text items**: Parses the first item's `.text` as JSON.
- **Object with `.data`**: Returns `.data` directly if dict, wraps otherwise.
- **Object with `.content` list**: Parses the first content item's text.
- **Fallback**: Wraps the result in `{"success": True, "result": str(result)}`.

### 7.5 Error Handling

`MCPHttpError` (line 22) carries:
- `server`: Which MCP server failed
- `tool`: Which tool was called
- `retryable`: Whether the error is transient

Retryable errors:
- `asyncio.TimeoutError` -> timeout, `retryable=True`
- `ConnectionError` -> server down/unreachable, `retryable=True`

Non-retryable errors:
- All other exceptions -> `retryable=False`

The `ToolExecutor._execute_mcp_tool()` (tool_executor.py:560) catches these
errors and records them on the `ToolCall` record in the database.

### 7.6 Server Configuration

**File:** `druppie/core/mcp_config.yaml`

Each MCP server is defined with:

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    description: "File operations and git within workspace sandbox"
    inject:
      session_id:
        from: session.id
        hidden: true
      # ...
    tools:
      - name: read_file
        requires_approval: false
        parameters: { ... }
      - name: write_file
        requires_approval: false
        parameters: { ... }
```

URLs support environment variable substitution with defaults
(`${VAR:-default}` syntax, handled by `MCPConfig._load_config()`,
mcp_config.py:100).

Currently configured servers:
- **coding** (port 9001): File operations, git, PRs within sandboxed workspaces
- **docker** (port 9002): Docker image build, container run/stop/logs

---

## Appendix: Status State Machines

### Agent Run Statuses

```
                            +----------+
                            |  PENDING |
                            +----+-----+
                                 |
                     execute_pending_runs picks it up
                                 |
                                 v
                            +----------+
                            | RUNNING  |
                            +----+-----+
                                 |
                    +------------+------------+
                    |            |            |
                    v            v            v
             +----------+  +-----------+  +-----------+
             |COMPLETED |  |PAUSED_TOOL|  |PAUSED_HITL|
             +----------+  +-----+-----+  +-----+-----+
                                 |              |
                           (approval)      (answer)
                                 |              |
                                 v              v
                            +----------+   +----------+
                            | RUNNING  |   | RUNNING  |
                            +----+-----+   +----+-----+
                                 |              |
                                 v              v
                              (continues loop...)
```

### Tool Call Statuses

```
             +----------+
             |  PENDING |
             +----+-----+
                  |
                  v
          +-------------+
          | (decision)  |
          +------+------+
                 |
       +---------+---------+---------+
       |         |         |         |
       v         v         v         v
  +---------+ +--------+ +-------+ +----------+
  |EXECUTING| |WAITING | |WAITING| |  FAILED  |
  |         | |APPROVAL| |ANSWER | |(access   |
  +---------+ +--------+ +-------+ | denied)  |
       |         |         |       +----------+
       |    (approved)  (answered)
       |         |         |
       v         v         v
  +---------+ +---------+ +---------+
  |COMPLETED| |EXECUTING| |COMPLETED|
  |or FAILED| +---------+ +---------+
  +---------+      |
                   v
             +---------+
             |COMPLETED|
             |or FAILED|
             +---------+
```

---

## Appendix: Key File Reference

| File | Purpose |
|------|---------|
| `druppie/execution/orchestrator.py` | Top-level message processing, pending run loop, resume handlers |
| `druppie/agents/runtime.py` | Agent class: YAML loading, system prompt building, LLM tool loop |
| `druppie/execution/tool_executor.py` | Tool routing (builtin/HITL/MCP), approval checks, injection |
| `druppie/agents/builtin_tools.py` | Built-in tool definitions and implementations (done, make_plan, set_intent, HITL) |
| `druppie/execution/mcp_http.py` | HTTP client for MCP servers using FastMCP |
| `druppie/execution/tool_context.py` | Context resolver for argument injection (session, project, user) |
| `druppie/core/mcp_config.py` | MCP configuration loader, approval rules, injection rules |
| `druppie/core/mcp_config.yaml` | Declarative config: server URLs, tool schemas, injection rules, approval defaults |
| `druppie/domain/agent_definition.py` | Pydantic model for agent YAML definitions |
| `druppie/domain/common.py` | Status enums (AgentRunStatus, ToolCallStatus, etc.) |
| `druppie/agents/definitions/_common.md` | Shared agent instructions (summary relay format, workspace state) |
| `druppie/agents/definitions/*.yaml` | Per-agent definitions (router, planner, developer, deployer, etc.) |
