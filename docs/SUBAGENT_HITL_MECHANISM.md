# Druppie Subagent and HITL Mechanism Documentation

## 1. Planner Agent Creates Subagents

### How it works
The planner agent uses the **`make_plan`** builtin tool to create execution plans as pending agent runs.

**File:** `druppie/agents/builtin_tools.py` - `make_plan()` function (lines 579-704)

**Key Flow:**
1. Planner calls `make_plan()` with a list of steps
2. Each step specifies an `agent_id` and a `prompt`
3. `make_plan()` creates `AgentRun` records with status='pending' via `ExecutionRepository`
4. These pending runs are executed in sequence by `execute_pending_runs()`

**Example from planner.yaml (lines 36-39):**
```yaml
Your workflow is ALWAYS:
  Step 1: Call the make_plan tool with the steps array
  Step 2: Call the done tool with a summary
```

**Safety Features:**
- Max planner iterations: 30 (prevents infinite loops)
- Cancels stale pending runs from previous plans
- Plans MUST contain exactly ONE working agent at a time + planner re-evaluation

### Example Plan from planner.yaml

```yaml
For CREATE_PROJECT:
  Call make_plan with 2 steps:
    - Step 1: agent_id="business_analyst", prompt="Gather functional requirements..."
    - Step 2: agent_id="planner", prompt="BA completed. Evaluate output and decide next step."
```

---

## 2. execute_coding_task Spawns Sandboxes

### Tool Definition

**File:** `druppie/agents/builtin_tools.py` - `execute_coding_task` (lines 198-240)

```python
"execute_coding_task": {
  "type": "function",
  "function": {
    "name": "execute_coding_task",
    "description": (
      "Execute a coding task in an isolated sandbox. "
      "IMPORTANT: Each call spawns a FRESH container that clones the project repo from git. "
      "The sandbox is DESTROYED after the task completes. "
      "Any work NOT committed and pushed within the sandbox is LOST. "
      "There is NO persistent workspace between calls — each call starts from the latest git state. "
      "The sandbox agent will automatically commit and push its work. "
      "To build on previous work, simply call again — the new sandbox clones the repo with all previous pushes."
    ),
    "parameters": {
      "task": {
        "type": "string",
        "description": "The complete task prompt for the sandbox coding agent..."
      },
      "agent": {
        "type": "string",
        "description": "Which sandbox agent to use"
      },
      "repo_target": {
        "type": "string",
        "enum": ["project", "druppie_core"],
        "description": "Which repo the sandbox works on..."
      }
    },
    "required": ["task"]
  }
}
```

### Implementation

**File:** `druppie/agents/builtin_tools.py` - `execute_sandbox_coding_task()` (lines 1088-1252)

**Key Steps:**
1. **Load constraints**: Checks agent's `sandbox_constraints` from definition
   - `allowed_agents`: List of allowed sandbox agents (e.g., ["explore", "code", "debug"])
   - `allowed_repo_targets`: List of allowed repo targets (e.g., ["project", "druppie_core"])

2. **Determine parameters** (defaults to specific agents/repos if constraints not provided):
   - `agent`: Uses `DEFAULT_SANDBOX_AGENT` ("explore") or first from constraints
   - `repo_target`: Uses "project" or first from constraints

3. **Resolve repo context**: Gets git provider, owner, repo names from `resolve_repo_context()`

4. **Append git push instructions**: Adds mandatory git config and push instructions

5. **Create sandbox** via `create_and_start_sandbox()`:
   - Spawns fresh container
   - Clones repo from git
   - Executes the task
   - **Returns immediately** (does NOT poll for completion)
   - **Status**: `"waiting_sandbox"` - pauses the agent run

6. **Webhook callback**: When sandbox completes, webhook calls `/api/sandbox-sessions/{id}/complete`
   - Orchestrator resumes via `resume_after_sandbox()`
   - Agent reconstructs state from DB and continues

### Sandbox Constraints Example (architect.yaml)

```yaml
sandbox_constraints:
  allowed_agents: ["explore"]
  allowed_repo_targets: ["druppie_core"]
  # Restricts architect to only use explore agent on druppie_core repo
```

### Sandbox Flow

```
Agent calls execute_coding_task()
  ↓
ToolExecutor._execute_builtin_tool()
  ↓
execute_sandbox_coding_task() creates sandbox
  ↓
Returns {"status": "waiting_sandbox", "sandbox_session_id": "..."}
  ↓
ToolCallStatus.WAITING_SANDBOX
  ↓
Agent run PAUSED_SANDBOX
  ↓
Background webhook listener receives completion
  ↓
resume_after_sandbox() resumes agent
  ↓
Agent continues via continue_run() reconstructing state from DB
```

---

## 3. HITL in Sandboxed Subagents

### HITL Tool Definition

**File:** `druppie/agents/builtin_tools.py` - `hitl_ask_question` (lines 39-59)

```python
"hitl_ask_question": {
  "type": "function",
  "function": {
    "name": "hitl_ask_question",
    "description": "Ask the user a free-form text question. Use this when you need clarification or input from the user. The workflow will pause until the user responds.",
    "parameters": {
      "type": "object",
      "properties": {
        "question": {
          "type": "string",
          "description": "The question to ask the user",
        },
        "context": {
          "type": "string",
          "description": "Optional context explaining why this question is being asked",
        },
      },
      "required": ["question"],
    },
  },
},
```

### Implementation

**File:** `druppie/execution/tool_executor.py` - `_execute_hitl_tool()` (lines 750-796)

**Key Steps:**
1. **Create Question record** via `QuestionRepository`
2. **Set ToolCall status** to `WAITING_ANSWER`
3. **Agent run pauses** with status `PAUSED_HITL`
4. **Returns** `WAITING_ANSWER` - workflow waits for user response

**File:** `druppie/api/routes/questions.py` - Answer endpoint (lines 95-167)

**Answer Flow:**
```
POST /questions/{id}/answer
  ↓
Save answer to DB
  ↓
Background task: resume_after_answer()
  ↓
Agent continues via continue_run() with answer in tool response
```

### HITL in Sandbox

**Critical Question:** Can a sandboxed subagent call `hitl_ask_question`?

**Answer: YES** - The sandbox runs as a separate agent with its own tool access.

**Mechanism:**
1. Sandbox agent (e.g., "explore") is created via `execute_coding_task()`
2. Sandbox agent has FULL access to builtin tools including `hitl_ask_question`
3. When sandbox calls `hitl_ask_question()`:
   - Creates Question record
   - Pauses sandbox agent run
   - Status becomes `PAUSED_SANDBOX` + `PAUSED_HITL`
4. User answers via UI
5. Webhook resumes sandbox → agent continues

**Evidence from code:**
- `execute_coding_task()` returns immediately with `"status": "waiting_sandbox"`
- The sandbox runs as a separate agent run with its own agent_id
- It inherits all builtin tools from the caller's agent definition

**Note:** The sandbox agent's prompt and tools are determined by the **MCP server agent** (e.g., "explore" MCP server), NOT by the caller's agent definition. The caller only specifies `repo_target` and receives the result back.

---

## 4. Project Template Structure

**Directory:** `druppie/templates/project/`

```
project-template/
├── app/
│   ├── __init__.py          # Flask app setup
│   ├── agent.py             # Sandbox agent implementation
│   ├── ai.py                # AI integration (module-llm)
│   ├── chat.py              # Chat handling
│   ├── config.py            # App configuration
│   ├── database.py          # Database setup
│   ├── models.py            # Pydantic models
│   └── routes.py            # API routes (/api/ai/*)
├── frontend/                # React/Vite frontend
├── docs/                    # Project documentation
├── Dockerfile               # Docker container
├── docker-compose.yaml      # Docker compose for project
├── requirements.txt         # Python dependencies
└── .gitignore               # Git ignore rules
```

### Key Template Files

**`app/agent.py`:** Sandbox agent that receives the task and executes code
**`app/chat.py`:** Chat handler for user interaction
**`app/routes.py`:** API endpoints for frontend/backend communication
**`app/models.py`:** Pydantic models for request/response validation

### Example from routes.py

```python
@api.route("/ai/chat", methods=["POST"])
def ai_chat_endpoint():
    """LLM chat completion. Body: {"prompt": "...", "system": "..."}"""
    result = druppie.call("llm", "chat", {
        "prompt": data["prompt"],
        "system": data.get("system", "You are a helpful assistant."),
    })
    return jsonify(answer=result.get("answer", ""))
```

---

## 5. Agent Definitions Directory

**Directory:** `druppie/agents/definitions/`

**Total Files:** 29 (including system prompts)

### Core Agent Definitions

1. **planner.yaml** (26,496 bytes)
   - Creates execution plans via `make_plan` tool
   - Routes to correct agent based on intent
   - Handles TDD retry loops (up to 3 times)
   - Escalates to HITL after 3 failures

2. **business_analyst.yaml** (50,123 bytes)
   - Gathers functional requirements
   - Writes `docs/functional-design.md`
   - Uses `hitl_ask_question` for clarifications
   - Signals `DESIGN_APPROVED`, `DESIGN_FEEDBACK`, or `DESIGN_REJECTED`

3. **architect.yaml** (43,249 bytes)
   - Designs system architecture
   - Writes `docs/technical-design.md`
   - Uses `execute_coding_task` for sandbox exploration
   - Can use sandbox agents for deep codebase analysis

4. **builder_planner.yaml** (8,988 bytes)
   - Creates detailed implementation plans
   - Reads design docs, writes `builder_plan.md`
   - Defines code standards, test strategy, solution approach

5. **test_builder.yaml** (11,633 bytes)
   - Generates comprehensive tests (TDD Red Phase)
   - Writes test files
   - Sets up test framework
   - Does NOT run tests

6. **builder.yaml** (10,265 bytes)
   - TDD code implementer
   - Builds initial implementation based on tests
   - Uses `execute_coding_task` for sandbox coding

7. **test_executor.yaml** (6,787 bytes)
   - Runs tests and reports structured results (TDD Green Phase)
   - Classifies failures
   - Routes back to builder with detailed report

8. **developer.yaml** (3,888 bytes)
   - Branching, merging PRs
   - Improvement tasks based on user feedback
   - Does NOT do TDD implementation

9. **update_core_builder.yaml** (6,120 bytes)
   - Implements changes to Druppie's own codebase
   - Creates PR for developer review
   - Routed by architect via `next_agent`

10. **deployer.yaml** (8,357 bytes)
    - Docker build and deployment
    - Uses `hitl_ask_question` for user preview feedback
    - Signals `USER_FEEDBACK` in done() summary

11. **summarizer.yaml** (1,951 bytes)
    - Creates user-friendly completion message
    - Always used as final step

12. **router.yaml** (3,242 bytes)
    - Determines user intent (create_project, update_project, general_chat)
    - Calls `set_intent` builtin tool

### System Prompts

Directory: `druppie/agents/definitions/system_prompts/`

1. **tool_only_communication.yaml**
   - System prompt: All communication must go through tools
   - Never output JSON as text

2. **summary_relay.yaml**
   - System prompt: Relay previous agent summaries to planner

3. **done_tool_format.yaml**
   - System prompt: Always use done() tool for completion
   - Format: "Agent [role]: <summary>"

4. **workspace_state.yaml**
   - System prompt: Include current workspace context

### Other Config Files

1. **llm_profiles.yaml** (1,105 bytes)
   - LLM configuration for different agents
   - Example: `cheap`, `fast`, `best`

### HITL Usage Patterns

**Where HITL is used:**
- `business_analyst`: Clarification questions about requirements
- `architect`: Advisory questions about design decisions
- `deployer`: User preview feedback after deployment

**Pattern:**
```yaml
# In system prompt:
After deployment succeeds, you MUST ask the user for feedback
1. Call hitl_ask_question with a message like:
   "Your app is live at <URL>. Does this look good?"
2. Include USER FEEDBACK in done() summary
```

---

## 6. HITL Simulator for Parallel Testing

**File:** `druppie/testing/hitl_simulator.py` (265 lines)

### Purpose
Simulates human-in-the-loop answers using an LLM with a persona profile.

### Usage
```python
from druppie.testing.hitl_simulator import HITLSimulator
from druppie.testing.schema import HITLProfile

# Create simulator with persona
simulator = HITLSimulator(
    profile=HITLProfile(
        provider="zai",
        model="gpt-4",
        temperature=0.0,
        prompt="You are a rigorous code reviewer..."
    )
)

# Answer HITL questions
answer = simulator.answer(
    question_text="Does this design look good?",
    choices=[{"text": "Yes, looks good"}, {"text": "No, needs changes"}]
)

# Decide approvals
decision = simulator.decide_approval(
    tool_name="docker:compose_up",
    tool_arguments={"branch": "main", "compose_project_name": "todo-app"}
)
```

### Key Features
- **Answer questions**: Supports both open-ended and multiple-choice
- **Decide approvals**: Acts as session owner reviewing tool calls
- **Conversation context**: Maintains session transcript
- **Max interactions**: 100 (prevents infinite loops)
- **Error handling**: 5-retry LLM calls with exponential backoff

### HITL Flow in Testing

```
Parallel HITL Test Runner
  ↓
Launches multiple sessions in parallel
  ↓
Each session spawns HITL questions
  ↓
HITL Simulator answers based on persona
  ↓
Answers streamed back via webhook
  ↓
Agent runs continue automatically
```

---

## 7. Critical Rules & Best Practices

### Planner Rules
1. **Plan exactly one agent at a time** (except summarizer which is always alone)
2. **Mandatory sequences**: business_analyst → architect → builder_planner → test_builder → builder → test_executor → deployer → summarizer
3. **Never skip agents** — each performs critical functions
4. **TDD retry limit**: 3 automatic retries, then escalate to HITL
5. **Direct routing**: Only use `next_agent` parameter if routing is deterministic

### Sandbox Rules
1. **Fresh container each time** — no persistent workspace
2. **Must commit and push** — work is lost if not pushed
3. **Git push mandatory** — sandbox prompt includes instructions
4. **Agent-based**: sandbox agent is determined by MCP server config
5. **Repo target**: "project" or "druppie_core"

### HITL Rules
1. **All questions via hitl_ask_question** — never output directly
2. **Include context** — explain why asking
3. **Format USER FEEDBACK** — deployer signals `USER_FEEDBACK: <response>`
4. **Planner parses feedback** — routes based on approval/rejection
5. **No HITL for planner** — only use done() and make_plan()

### Tool Execution Flow
```
User request → Orchestrator.process_message()
  ↓
Create Session + Router + Planner (PENDING)
  ↓
Execute pending runs (sequential)
  ↓
Agent calls tool
  ↓
ToolExecutor.execute() validates & executes
  ↓
Builtin tools: execute_builtin()
MCP tools: _execute_mcp_tool()
HITL tools: _execute_hitl_tool() (creates Question, pauses)
  ↓
Return status (completed, waiting_approval, waiting_answer, waiting_sandbox)
  ↓
Agent continues or pauses
```

---

## 8. Key Files Reference

### Core Execution
- `druppie/execution/orchestrator.py` - Main entry point, agent run coordination
- `druppie/execution/tool_executor.py` - Tool execution (builtin, MCP, HITL)
- `druppie/execution/mcp_http.py` - MCP server communication
- `druppie/execution/human_input.py` - Language detection, input processing

### Agent Runtime
- `druppie/agents/runtime.py` - Agent class, run/continue/run methods
- `druppie/agents/loop.py` - Agent loop, tool calling
- `druppie/agents/builtin_tools.py` - Built-in tool implementations
- `druppie/agents/loop.py` - Agent loop implementation

### MCP Integration
- `druppie/core/mcp_config.py` - MCP configuration, approval rules
- `druppie/core/tool_registry.py` - Tool definitions, schema validation

### HITL & Questions
- `druppie/api/routes/questions.py` - Question answering endpoint
- `druppie/services/question_service.py` - Question operations

### Templates
- `druppie/templates/project/` - Project template structure
- `druppie/templates/project/app/` - Flask app, agent, routes

### Testing
- `druppie/testing/hitl_simulator.py` - HITL simulation
- `druppie/testing/runner.py` - Parallel test execution
- `druppie/testing/schema.py` - Test schemas and types

---

## 9. Common Patterns for Parallel HITL Testing

### Pattern 1: Simple Parallel Sessions
```python
from druppie.testing.runner import HITLTestRunner
from druppie.testing.schema import HITLTest

runner = HITLTestRunner()

tests = [
    HITLTest(
        name="test-create-project",
        session_title="Create Todo App",
        user_message="Create a todo app using React + FastAPI",
        hitl_profile=HITLProfile(provider="zai", model="gpt-4", temperature=0.0)
    ),
    HITLTest(
        name="test-update-project",
        session_title="Update Portfolio",
        user_message="Update my portfolio website with dark mode",
        hitl_profile=HITLProfile(provider="zai", model="gpt-4", temperature=0.0)
    )
]

results = runner.run_parallel(tests, num_workers=4)
```

### Pattern 2: Sandbox Testing
```python
# Architect uses sandbox for codebase exploration
hitl_simulator = HITLSimulator(profile=persona)

# Sandbox agent calls execute_coding_task
# Sandbox internally calls hitl_ask_question if it needs clarification
# HITL simulator answers based on persona
```

### Pattern 3: Approval Testing
```python
# Test that approval gates work correctly
decision = hitl_simulator.decide_approval(
    tool_name="docker:compose_up",
    tool_arguments={"branch": "main", "compose_project_name": "todo-app"}
)

assert decision["status"] == "approved"
```

---

## Summary

Druppie's subagent spawning mechanism uses a **plan-based orchestration**:
1. Planner calls `make_plan()` to create pending AgentRun records
2. Orchestrator executes them sequentially
3. Sandbox tasks use `execute_coding_task()` to spawn fresh containers
4. HITL pauses workflows with Question records
5. User answers via UI, triggering background resumption

**Key Insight:** Subagents (sandbox agents) are NOT true subprocesses — they're separate agent runs with their own state, executed via the same orchestrator. They can use HITL tools just like any other agent.

**For Parallel HITL Testing:**
- Use `HITLTestRunner` to launch multiple sessions in parallel
- Each session can spawn sandboxes with `execute_coding_task()`
- Sandbox agents can call `hitl_ask_question()` for clarification
- `HITLSimulator` answers questions based on a persona
- Full session transcript is passed to the simulator for context
