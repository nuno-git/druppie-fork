# Sandbox Webhook + Pause/Resume Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 25-hour blocking HTTP timeout with a webhook callback + pause/resume pattern so `execute_coding_task` returns instantly and the agent resumes when the sandbox completes.

**Architecture:** The MCP tool becomes a built-in tool that creates a sandbox session, sends the prompt, and pauses the agent with `WAITING_SANDBOX`. The control plane POSTs a webhook on completion. Druppie receives it, fetches results, and resumes the agent via `continue_run()`.

**Tech Stack:** Python/FastAPI (Druppie backend), TypeScript (background-agents control plane), httpx (async HTTP), HMAC-SHA256 (webhook auth)

**Design doc:** `docs/plans/2026-03-02-sandbox-webhook-pause-resume-design.md`

---

### Task 1: Add WAITING_SANDBOX / PAUSED_SANDBOX Statuses

**Files:**
- Modify: `druppie/domain/common.py:13-31`
- Modify: `druppie/execution/tool_executor.py:38-45`

**Step 1: Add PAUSED_SANDBOX to SessionStatus**

In `druppie/domain/common.py`, add after `PAUSED_HITL`:

```python
class SessionStatus(str, Enum):
    """Session execution status."""
    ACTIVE = "active"
    PAUSED_APPROVAL = "paused_approval"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"  # Waiting for user answer
    PAUSED_SANDBOX = "paused_sandbox"  # Waiting for sandbox completion
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Step 2: Add PAUSED_SANDBOX to AgentRunStatus**

In the same file, add after `PAUSED_HITL`:

```python
class AgentRunStatus(str, Enum):
    """Agent run execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED_TOOL = "paused_tool"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"  # Waiting for user answer
    PAUSED_SANDBOX = "paused_sandbox"  # Waiting for sandbox completion
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Step 3: Add WAITING_SANDBOX to ToolCallStatus**

In `druppie/execution/tool_executor.py`:

```python
class ToolCallStatus:
    """Tool call status constants."""
    PENDING = "pending"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_ANSWER = "waiting_answer"
    WAITING_SANDBOX = "waiting_sandbox"
    COMPLETED = "completed"
    FAILED = "failed"
```

**Step 4: Commit**

```bash
git add druppie/domain/common.py druppie/execution/tool_executor.py
git commit -m "feat: add WAITING_SANDBOX / PAUSED_SANDBOX statuses"
```

---

### Task 2: Register execute_coding_task as Built-in Tool

**Files:**
- Modify: `druppie/agents/builtin_tools.py:31,49-57,34-194,797-861`
- Modify: `druppie/core/tool_registry.py:88-125`
- Modify: `druppie/core/mcp_config.yaml:245-258` (delete section)

**Step 1: Add to BUILTIN_TOOLS set and DEFAULT_BUILTIN_TOOLS**

In `druppie/agents/builtin_tools.py`, add `"execute_coding_task"` to `BUILTIN_TOOLS`:

```python
BUILTIN_TOOLS = {
    "done",
    "make_plan",
    "set_intent",
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
    "create_message",
    "invoke_skill",
    "execute_coding_task",
}
```

Do NOT add to `DEFAULT_BUILTIN_TOOLS` — it's only available to agents that explicitly list it (builder, tester).

**Step 2: Add tool definition to BUILTIN_TOOL_DEFS**

Add to the `BUILTIN_TOOL_DEFS` dict (after `invoke_skill`):

```python
"execute_coding_task": {
    "type": "function",
    "function": {
        "name": "execute_coding_task",
        "description": (
            "Execute a coding task in an isolated sandbox using an external coding agent. "
            "Sends a prompt to a sandbox that clones the repo, runs a coding agent, and "
            "returns results. Use this for implementation tasks that benefit from an isolated "
            "environment. The sandbox automatically clones the project from Gitea, implements "
            "changes, and pushes back. Changes are synced to the workspace via git pull."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The coding task description / prompt for the sandbox agent. "
                        "Be specific about what to implement, which files to modify, "
                        "and what tests should pass."
                    ),
                },
                "agent": {
                    "type": "string",
                    "description": "Which sandbox agent to use",
                },
            },
            "required": ["task"],
        },
    },
},
```

Note: the `agent` enum values are injected dynamically by `_enrich_execute_coding_task` in `loop.py` (already exists, no change needed).

**Step 3: Move PARAMS_MODEL_MAP entry from coding to builtin**

In `druppie/core/tool_registry.py`, change:

```python
# Before:
("coding", "execute_coding_task"): ExecuteCodingTaskParams,

# After:
("builtin", "execute_coding_task"): ExecuteCodingTaskParams,
```

**Step 4: Remove execute_coding_task from mcp_config.yaml**

In `druppie/core/mcp_config.yaml`, delete the entire `execute_coding_task` tool definition block (lines ~245-258). Also remove `execute_coding_task` from all injection rule `tools:` lists (lines ~30-36, remove from the `repo_name`, `repo_owner`, `session_id`, `user_id`, `project_id` injection tool lists).

**Step 5: Remove execute_coding_task from agent MCP tool lists**

In `druppie/agents/definitions/builder.yaml`, remove `- execute_coding_task` from the `mcps.coding` list (~line 221). Add it to a new `builtin` section if one doesn't exist, or add it to `builtin_tools` if that key is used. Check how other builtin tools (like `invoke_skill`) are declared in agent definitions.

Do the same for `druppie/agents/definitions/tester.yaml` (~line 644).

**Step 6: Commit**

```bash
git add druppie/agents/builtin_tools.py druppie/core/tool_registry.py druppie/core/mcp_config.yaml druppie/agents/definitions/builder.yaml druppie/agents/definitions/tester.yaml
git commit -m "feat: register execute_coding_task as built-in tool"
```

---

### Task 3: Implement the Built-in Tool Logic

**Files:**
- Modify: `druppie/agents/builtin_tools.py` (add `execute_sandbox_coding_task` function and wire into `execute_builtin`)

**Step 1: Add sandbox config constants**

At the top of `druppie/agents/builtin_tools.py`, add:

```python
import os
import time
import hashlib
import hmac
import httpx
import structlog

logger = structlog.get_logger()

# Sandbox configuration
SANDBOX_CONTROL_PLANE_URL = os.getenv("SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787")
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", "sandbox-dev-secret")
BACKEND_URL = os.getenv("BACKEND_URL", "http://druppie-backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-secret-key")


def _generate_sandbox_auth_token() -> str:
    """Generate HMAC-SHA256 auth token for the background-agents control-plane."""
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        SANDBOX_API_SECRET.encode(),
        timestamp.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{timestamp}.{signature}"
```

**Step 2: Implement execute_sandbox_coding_task function**

Add this function. It does only the quick work (create session, send prompt, register ownership) and returns a result dict with `"status": "waiting_sandbox"` so the caller knows to pause.

```python
async def execute_sandbox_coding_task(
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Create a sandbox session, send the prompt, register ownership, return immediately.

    Does NOT poll for completion. The control plane will send a webhook
    to /api/sandbox-sessions/{id}/complete when done.

    Returns:
        Dict with status="waiting_sandbox" and sandbox_session_id on success.
        The caller (tool_executor) should set ToolCallStatus.WAITING_SANDBOX.
    """
    task = args.get("task", "")
    agent = args.get("agent", "druppie-builder")
    model = "zai-coding-plan/glm-4.7"

    if not task:
        return {"success": False, "error": "task is required"}

    if not SANDBOX_CONTROL_PLANE_URL:
        return {"success": False, "error": "SANDBOX_CONTROL_PLANE_URL not configured"}

    # Resolve repo info from the session's project context
    from druppie.repositories import SessionRepository
    db = execution_repo.db
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        return {"success": False, "error": f"Session {session_id} not found"}

    project = session.project
    repo_name = project.repo_name if project else None
    repo_owner = project.repo_owner if project else None
    user_id = str(session.user_id) if session.user_id else None

    # Build Gitea clone URL
    gitea_base = os.getenv("GITEA_URL", "http://gitea:3000")
    gitea_token = os.getenv("GITEA_TOKEN", "")
    gitea_clone_url = None
    if repo_name and repo_owner:
        if gitea_token:
            gitea_clone_url = f"{gitea_base}/{repo_owner}/{repo_name}.git"
            gitea_clone_url = gitea_clone_url.replace("://", f"://druppie-bot:{gitea_token}@")
        else:
            gitea_clone_url = f"{gitea_base}/{repo_owner}/{repo_name}.git"

    base_url = SANDBOX_CONTROL_PLANE_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0) as client:
        auth_headers = {
            "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
            "Content-Type": "application/json",
        }

        # Build callback URL for this specific sandbox session
        # We'll fill in the sandbox_session_id after creation
        callback_secret = SANDBOX_API_SECRET

        # Step 1: Create sandbox session
        create_body = {
            "repoOwner": repo_owner or "druppie",
            "repoName": repo_name or "unknown",
            "model": model,
            "title": f"Druppie sandbox: {task[:80]}",
        }
        if gitea_clone_url:
            create_body["gitUrl"] = gitea_clone_url

        resp = await client.post(
            f"{base_url}/sessions",
            json=create_body,
            headers=auth_headers,
        )

        if resp.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"Failed to create sandbox session: {resp.status_code} {resp.text}",
            }

        sandbox_session_id = resp.json().get("sessionId")
        if not sandbox_session_id:
            return {"success": False, "error": "No sessionId in create response"}

        logger.info(
            "execute_coding_task: created sandbox session",
            sandbox_session_id=sandbox_session_id,
        )

        # Now update session with callbackUrl (PATCH or via prompt metadata)
        # The callbackUrl includes the sandbox_session_id
        callback_url = f"{BACKEND_URL}/api/sandbox-sessions/{sandbox_session_id}/complete"

        # Step 2: Send the task prompt with callback info
        prompt_body = {
            "content": task,
            "authorId": "druppie-agent",
            "source": "api",
            "agent": agent,
            "callbackUrl": callback_url,
            "callbackSecret": callback_secret,
        }

        resp = await client.post(
            f"{base_url}/sessions/{sandbox_session_id}/prompt",
            json=prompt_body,
            headers={
                "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"Failed to send prompt: {resp.status_code} {resp.text}",
                "sandbox_session_id": sandbox_session_id,
            }

        prompt_message_id = resp.json().get("messageId", "")

        # Step 3: Register ownership with Druppie backend
        if user_id:
            try:
                reg_body = {
                    "sandbox_session_id": sandbox_session_id,
                    "user_id": user_id,
                }
                if session_id:
                    reg_body["session_id"] = str(session_id)
                reg_resp = await client.post(
                    f"{BACKEND_URL}/api/sandbox-sessions/internal/register",
                    json=reg_body,
                    headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                    timeout=5.0,
                )
                reg_resp.raise_for_status()
                logger.info(
                    "execute_coding_task: registered ownership",
                    sandbox_session_id=sandbox_session_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(
                    "execute_coding_task: failed to register ownership",
                    error=str(e),
                )

        # Return with waiting_sandbox status — caller will pause the agent
        return {
            "success": True,
            "status": "waiting_sandbox",
            "sandbox_session_id": sandbox_session_id,
            "message_id": prompt_message_id,
        }
```

**Step 3: Wire into execute_builtin dispatcher**

In the `execute_builtin` function, add before the final `else`:

```python
elif tool_name == "execute_coding_task":
    return await execute_sandbox_coding_task(
        args=args,
        session_id=session_id,
        agent_run_id=agent_run_id,
        execution_repo=execution_repo,
    )
```

**Step 4: Commit**

```bash
git add druppie/agents/builtin_tools.py
git commit -m "feat: implement execute_coding_task as built-in tool with sandbox delegation"
```

---

### Task 4: Handle WAITING_SANDBOX in Tool Executor and Agent Loop

**Files:**
- Modify: `druppie/execution/tool_executor.py:677-744` (`_execute_builtin_tool`)
- Modify: `druppie/agents/loop.py:578-598` (`_process_tool_calls`)

**Step 1: Handle waiting_sandbox result in _execute_builtin_tool**

In `druppie/execution/tool_executor.py`, modify `_execute_builtin_tool` to detect when the built-in tool returns `"status": "waiting_sandbox"` and set the tool call status to `WAITING_SANDBOX` instead of `COMPLETED`:

```python
async def _execute_builtin_tool(self, tool_call) -> str:
    """Execute a non-HITL builtin tool."""
    from druppie.agents.builtin_tools import execute_builtin

    args = tool_call.arguments or {}

    try:
        self.execution_repo.update_tool_call(
            tool_call.id,
            status=ToolCallStatus.EXECUTING,
        )

        result = await execute_builtin(
            tool_name=tool_call.tool_name,
            args=args,
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            execution_repo=self.execution_repo,
        )

        # Handle sandbox delegation — tool is waiting for external callback
        if isinstance(result, dict) and result.get("status") == "waiting_sandbox":
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.WAITING_SANDBOX,
                result=result,  # Store sandbox_session_id for resume
            )
            self.db.commit()
            logger.info(
                "builtin_tool_waiting_sandbox",
                tool_call_id=str(tool_call.id),
                sandbox_session_id=result.get("sandbox_session_id"),
            )
            return ToolCallStatus.WAITING_SANDBOX

        is_success = result.get("success", True) if isinstance(result, dict) else True
        status = ToolCallStatus.COMPLETED if is_success else ToolCallStatus.FAILED

        self.execution_repo.update_tool_call(
            tool_call.id,
            status=status,
            result=result if is_success else None,
            error=result.get("error") if not is_success else None,
        )
        self.db.commit()

        return status

    except Exception as e:
        logger.error(
            "builtin_tool_error",
            tool_call_id=str(tool_call.id),
            tool_name=tool_call.tool_name,
            error=str(e),
        )
        self.execution_repo.update_tool_call(
            tool_call.id,
            status=ToolCallStatus.FAILED,
            error=str(e),
        )
        self.db.commit()
        return ToolCallStatus.FAILED
```

**Step 2: Handle WAITING_SANDBOX in agent loop _process_tool_calls**

In `druppie/agents/loop.py`, add a new elif block after the `WAITING_ANSWER` handler (after line ~598):

```python
# Handle sandbox pause
if status == ToolCallStatus.WAITING_SANDBOX:
    assistant_msg, _ = self._build_tool_messages(
        llm_tool_call_str_id, tool_name, tool_args, "",
    )
    messages.append(assistant_msg)
    return self._build_pause_state(
        messages, prompt, context, iteration,
        llm_tool_call_str_id, "waiting_sandbox", tool_call_id,
    )
```

**Step 3: Remove the 90,000s timeout hack**

In `druppie/execution/tool_executor.py`, in the `_execute_mcp_tool` method, remove the special-case timeout for `execute_coding_task` (lines ~795-798):

```python
# Delete these lines:
# timeout = 60.0
# if tool_call.tool_name == "execute_coding_task":
#     timeout = 90000.0  # 25 hours — sandbox has its own internal timeout

# Keep just:
timeout = 60.0
```

**Step 4: Commit**

```bash
git add druppie/execution/tool_executor.py druppie/agents/loop.py
git commit -m "feat: handle WAITING_SANDBOX in tool executor and agent loop"
```

---

### Task 5: Add Webhook Receiver Endpoint

**Files:**
- Modify: `druppie/api/routes/sandbox.py`

**Step 1: Add webhook completion endpoint**

Add the following endpoint to `druppie/api/routes/sandbox.py`. This is called by the control plane when a sandbox session completes.

```python
import hashlib
import hmac as hmac_lib
import time as time_mod

from druppie.execution.tool_executor import ToolCallStatus


class SandboxCompleteRequest(BaseModel):
    """Webhook payload from control plane on sandbox completion."""
    sessionId: str
    messageId: str = ""
    success: bool = True
    timestamp: int = 0


def _verify_webhook_signature(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from control plane webhook."""
    expected = hmac_lib.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac_lib.compare_digest(expected, signature)


@router.post("/sandbox-sessions/{sandbox_session_id}/complete")
async def sandbox_complete_webhook(
    sandbox_session_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook called by the control plane when a sandbox session completes.

    Verifies HMAC signature, fetches final events, extracts results,
    completes the tool call, and resumes the paused agent.
    """
    api_secret = os.environ.get("SANDBOX_API_SECRET", "sandbox-dev-secret")

    # Verify HMAC signature
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")
    if not _verify_webhook_signature(raw_body, signature, api_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = SandboxCompleteRequest.model_validate_json(raw_body)

    logger.info(
        "sandbox_webhook_received",
        sandbox_session_id=sandbox_session_id,
        success=body.success,
    )

    # Find the WAITING_SANDBOX tool call for this sandbox session
    from druppie.repositories import ExecutionRepository
    execution_repo = ExecutionRepository(db)
    tool_call = execution_repo.find_by_sandbox_session_id(sandbox_session_id)
    if not tool_call:
        logger.warning(
            "sandbox_webhook_no_tool_call",
            sandbox_session_id=sandbox_session_id,
        )
        raise HTTPException(status_code=404, detail="No waiting tool call found")

    # Fetch final events from control plane
    control_plane_url = os.environ.get(
        "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
    ).rstrip("/")
    changed_files = []
    agent_output = ""
    event_count = 0

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Generate auth token
            timestamp_ms = str(int(time_mod.time() * 1000))
            sig = hmac_lib.new(
                api_secret.encode(), timestamp_ms.encode(), hashlib.sha256
            ).hexdigest()
            auth_token = f"{timestamp_ms}.{sig}"

            events_resp = await client.get(
                f"{control_plane_url}/sessions/{sandbox_session_id}/events?limit=500",
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            if events_resp.status_code == 200:
                events_data = events_resp.json()
                events = events_data.get("events", [])
                event_count = len(events)
                changed_files = _extract_changed_files(events)
                agent_output = _extract_agent_output(events)
    except Exception as e:
        logger.warning("sandbox_webhook_event_fetch_failed", error=str(e))

    # Git pull to sync sandbox changes into workspace
    git_pull_result = None
    if body.success and tool_call.session_id:
        git_pull_result = await _git_pull_workspace(tool_call.session_id, db)

    # Build the final tool result
    result = {
        "success": body.success,
        "sandbox_session_id": sandbox_session_id,
        "status": "completed" if body.success else "failed",
        "event_count": event_count,
        "changed_files": changed_files,
        "agent_output": agent_output[-5000:] if agent_output else "",
    }
    if git_pull_result:
        result["git_pull"] = git_pull_result

    # Complete the tool call
    execution_repo.update_tool_call(
        tool_call.id,
        status=ToolCallStatus.COMPLETED if body.success else ToolCallStatus.FAILED,
        result=result if body.success else None,
        error=result.get("error") if not body.success else None,
    )
    db.commit()

    # Resume the agent
    from druppie.execution.orchestrator import Orchestrator
    orchestrator = Orchestrator(db)
    await orchestrator.resume_after_sandbox(tool_call.id)

    return {"status": "ok"}
```

**Step 2: Add helper functions for event extraction**

These are extracted from the existing logic in `server.py`. Add to `sandbox.py`:

```python
def _extract_changed_files(events: list[dict]) -> list[dict]:
    """Extract changed files from sandbox events (tool_call events with write operations)."""
    files = []
    seen_paths = set()
    for event in events:
        if event.get("type") != "tool_call":
            continue
        data = event.get("data", {})
        tool = data.get("tool", "")
        args = data.get("args", {})
        path = args.get("filePath") or args.get("path") or ""
        if tool in ("write", "write_file", "batch_write_files") and path and path not in seen_paths:
            seen_paths.add(path)
            files.append({"path": path, "action": tool})
    return files


def _extract_agent_output(events: list[dict]) -> str:
    """Extract agent text output from token events, sorted chronologically."""
    parts = []
    for event in events:
        if event.get("type") == "token":
            content = (event.get("data") or {}).get("content", "")
            if content:
                ts = event.get("createdAt") or event.get("created_at") or ""
                parts.append((ts, content))
        elif event.get("type") == "agent_message":
            content = event.get("content", "")
            if content:
                ts = event.get("createdAt") or event.get("created_at") or ""
                parts.append((ts, content))
    parts.sort(key=lambda x: x[0])
    return "\n".join(c for _, c in parts).strip()


async def _git_pull_workspace(session_id, db) -> dict | None:
    """Git pull to sync sandbox changes into the workspace."""
    # Reuse existing git pull logic from the coding MCP server.
    # The workspace path is derived from the session's project.
    # This may need adaptation based on how workspaces are mounted.
    try:
        from druppie.repositories import SessionRepository
        session_repo = SessionRepository(db)
        session = session_repo.get_by_id(session_id)
        if not session or not session.project:
            return None

        workspace_dir = f"/workspaces/{session.project.repo_owner}/{session.project.repo_name}"
        import subprocess
        result = subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }
    except Exception as e:
        logger.warning("git_pull_failed", error=str(e))
        return {"success": False, "error": str(e)}
```

**Step 3: Commit**

```bash
git add druppie/api/routes/sandbox.py
git commit -m "feat: add sandbox webhook receiver endpoint with event extraction and git pull"
```

---

### Task 6: Add find_by_sandbox_session_id Repository Method

**Files:**
- Modify: `druppie/repositories/execution_repository.py` (or wherever ExecutionRepository is)

**Step 1: Find the ExecutionRepository file**

Run: `grep -r "class ExecutionRepository" druppie/` to locate it.

**Step 2: Add the lookup method**

Add to `ExecutionRepository`:

```python
def find_by_sandbox_session_id(self, sandbox_session_id: str):
    """Find a tool call in WAITING_SANDBOX status by its sandbox_session_id.

    The sandbox_session_id is stored in tool_call.result['sandbox_session_id']
    when the built-in tool returns waiting_sandbox status.
    """
    from druppie.db.models import ToolCall

    # Query tool calls with WAITING_SANDBOX status and matching sandbox_session_id in result
    tool_calls = (
        self.db.query(ToolCall)
        .filter(ToolCall.status == "waiting_sandbox")
        .all()
    )
    for tc in tool_calls:
        result = tc.result or {}
        if isinstance(result, dict) and result.get("sandbox_session_id") == sandbox_session_id:
            return tc
    return None
```

Note: This scans WAITING_SANDBOX tool calls (should be very few at any time). If performance becomes an issue, add a `sandbox_session_id` column to the `tool_calls` table later.

**Step 3: Commit**

```bash
git add druppie/repositories/
git commit -m "feat: add find_by_sandbox_session_id to ExecutionRepository"
```

---

### Task 7: Add resume_after_sandbox to Orchestrator

**Files:**
- Modify: `druppie/execution/orchestrator.py` (add method after `resume_after_answer`, ~line 695)

**Step 1: Implement resume_after_sandbox**

This mirrors `resume_after_approval` (lines 484-582). The tool call is already completed by the webhook handler, so this method just resumes the agent:

```python
async def resume_after_sandbox(self, tool_call_id: UUID) -> UUID:
    """Resume execution after a sandbox task completes.

    Called by the webhook handler after the control plane notifies
    that a sandbox session finished. The tool call result is already
    populated by the webhook handler.

    This method:
    1. Finds the paused agent run from the tool call
    2. Sets statuses back to RUNNING/ACTIVE
    3. Continues the agent (it reconstructs state from DB)
    4. Executes any remaining pending runs
    """
    from druppie.agents.runtime import Agent

    # Find the tool call and its agent run
    tool_call = self.execution_repo.get_tool_call_by_id(tool_call_id)
    if not tool_call or not tool_call.agent_run_id:
        logger.error("sandbox_resume_tool_call_not_found", tool_call_id=str(tool_call_id))
        return None

    agent_run = self.execution_repo.get_by_id(tool_call.agent_run_id)
    if not agent_run:
        logger.error("sandbox_resume_agent_run_not_found", agent_run_id=str(tool_call.agent_run_id))
        return None

    session_id = agent_run.session_id

    logger.info(
        "resume_after_sandbox",
        tool_call_id=str(tool_call_id),
        agent_run_id=str(agent_run.id),
        session_id=str(session_id),
    )

    # Set statuses back to running
    self.execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
    self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
    self.execution_repo.commit()

    # Build fresh context and continue the agent
    context = self._build_project_context(session_id)
    agent = Agent(agent_run.agent_id, db=self.execution_repo.db)
    result = await agent.continue_run(
        session_id=session_id,
        agent_run_id=agent_run.id,
        context=context,
    )

    # Handle result — agent may pause again (approval, hitl, or another sandbox call)
    if result.get("status") == "paused" or result.get("paused"):
        pause_reason = result.get("reason", "unknown")
        if pause_reason == "waiting_answer":
            self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_HITL)
            self.session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
        elif pause_reason == "waiting_sandbox":
            self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_SANDBOX)
            self.session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
        else:
            self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_TOOL)
            self.session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
        self.execution_repo.commit()
        return session_id

    # Agent completed — mark and continue with pending runs
    self.execution_repo.update_status(agent_run.id, AgentRunStatus.COMPLETED)
    self.execution_repo.commit()

    logger.info(
        "agent_resumed_after_sandbox_completed",
        agent_run_id=str(agent_run.id),
        agent_id=agent_run.agent_id,
    )

    await self.execute_pending_runs(session_id)
    return session_id
```

**Step 2: Also handle PAUSED_SANDBOX in the existing resume methods**

Check `resume_after_approval` and `resume_after_answer` — in their result handling blocks (the if/elif for pause reasons), add handling for `"waiting_sandbox"`:

```python
# In both resume_after_approval and resume_after_answer,
# in the result handling block:
elif pause_reason == "waiting_sandbox":
    self.execution_repo.update_status(agent_run.id, AgentRunStatus.PAUSED_SANDBOX)
    self.session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
```

**Step 3: Commit**

```bash
git add druppie/execution/orchestrator.py
git commit -m "feat: add resume_after_sandbox to orchestrator"
```

---

### Task 8: Remove execute_coding_task from MCP Coding Server

**Files:**
- Modify: `druppie/mcp-servers/coding/server.py`

**Step 1: Delete the execute_coding_task function**

Remove the entire `@mcp.tool() async def execute_coding_task(...)` function and all its helper code. This is approximately lines 1610-2023 in server.py:

- Config constants: `SANDBOX_CONTROL_PLANE_URL`, `SANDBOX_API_SECRET`, `BACKEND_URL`, `INTERNAL_API_KEY` (~lines 1610-1614)
- `_generate_sandbox_auth_token()` function (~lines 1617-1632)
- `execute_coding_task()` function (~lines 1635-2000)
- `_extract_changed_files_from_events()` helper (~lines 2000-2015)
- `_async_sleep()` helper (~lines 2020-2023)

Keep everything else in the file unchanged.

**Step 2: Verify the MCP server still starts**

Run: `cd druppie/mcp-servers/coding && python -c "import server; print('OK')"`

**Step 3: Commit**

```bash
git add druppie/mcp-servers/coding/server.py
git commit -m "refactor: remove execute_coding_task from MCP coding server (moved to built-in)"
```

---

### Task 9: Control Plane — Accept callbackUrl on Session Creation

**Repo:** background-agents fork
**Files:**
- Modify: `packages/control-plane/src/session/types.ts`
- Modify: `packages/control-plane/src/router.ts`
- Modify: `packages/control-plane/src/session/session-instance.ts`

**Step 1: Add callback fields to session types**

In `types.ts`, add to the `SessionRow` interface:

```typescript
callback_url?: string | null;
callback_secret?: string | null;
```

**Step 2: Accept callbackUrl in router.ts**

In the POST /sessions handler, accept the new fields from the request body:

```typescript
const { repoOwner, repoName, model, title, gitUrl, callbackUrl, callbackSecret } = body;
```

Pass them through to session creation.

**Step 3: Store on session in session-instance.ts**

When creating the session record, include:

```typescript
callback_url: callbackUrl ?? null,
callback_secret: callbackSecret ?? null,
```

**Step 4: If using D1/SQLite, add columns**

Add `callback_url TEXT` and `callback_secret TEXT` columns to the sessions table. Check how migrations work in the control plane (D1 migrations or direct schema).

**Step 5: Commit in background-agents repo**

```bash
git add packages/control-plane/src/
git commit -m "feat: accept callbackUrl and callbackSecret on session creation"
```

---

### Task 10: Control Plane — Send Webhook on Completion

**Repo:** background-agents fork
**Files:**
- Modify: `packages/control-plane/src/session/callback-notification-service.ts`

**Step 1: Add direct HTTP callback path in notifyComplete**

At the beginning of `notifyComplete()`, before the source-based routing, add:

```typescript
async notifyComplete(messageId: string, success: boolean): Promise<void> {
    // Check for direct callback URL first (used by Druppie)
    const session = this.repository.getSession();
    if (session?.callback_url) {
        await this.sendDirectCallback(session, messageId, success);
        return;
    }

    // ... existing Slack/Linear routing below
}
```

**Step 2: Implement sendDirectCallback**

```typescript
private async sendDirectCallback(
    session: SessionRow,
    messageId: string,
    success: boolean,
): Promise<void> {
    const sessionId = this.getSessionId();
    const timestamp = Date.now();

    const payloadData = {
        sessionId,
        messageId,
        success,
        timestamp,
    };

    // Sign with callback_secret if provided, else use INTERNAL_CALLBACK_SECRET
    const secret = session.callback_secret || this.env.INTERNAL_CALLBACK_SECRET || "";
    const signature = secret ? await this.signPayload(payloadData, secret) : "";

    const body = JSON.stringify(payloadData);

    // Retry up to 2 times
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const response = await fetch(session.callback_url!, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                },
                body,
            });

            if (response.ok) {
                this.log.info("Direct callback succeeded", {
                    session_id: sessionId,
                    callback_url: session.callback_url,
                });
                return;
            }

            const responseText = await response.text();
            this.log.error("Direct callback failed", {
                session_id: sessionId,
                status: response.status,
                response_text: responseText,
            });
        } catch (e) {
            this.log.error("Direct callback attempt failed", {
                session_id: sessionId,
                attempt: attempt + 1,
                error: e instanceof Error ? e.message : String(e),
            });
        }

        if (attempt < 1) {
            await new Promise((r) => setTimeout(r, 1000));
        }
    }

    this.log.error("Failed to send direct callback after retries", {
        session_id: sessionId,
        callback_url: session.callback_url,
    });
}
```

**Step 3: Commit in background-agents repo**

```bash
git add packages/control-plane/src/session/callback-notification-service.ts
git commit -m "feat: send direct HTTP webhook when callbackUrl is set on session"
```

---

### Task 11: Update Submodule and Docker Compose

**Repo:** Druppie (back to main repo)
**Files:**
- Modify: `vendor/open-inspect` (submodule pointer)
- Possibly modify: `docker-compose.yml` (if env vars needed)

**Step 1: Update the submodule to include the new control plane changes**

After committing in background-agents fork and pushing:

```bash
cd /home/nuno/Documents/cleaner-druppie
cd vendor/open-inspect
git pull origin feature/docker-compose-local-dev
cd ../..
git add vendor/open-inspect
```

**Step 2: Verify env vars in docker-compose.yml**

Check that `SANDBOX_API_SECRET` is passed to the `druppie-backend` service (needed by the webhook receiver). It's already passed to `mcp-coding`. Add to backend if missing:

```yaml
druppie-backend:
  environment:
    - SANDBOX_API_SECRET=${SANDBOX_API_SECRET:-sandbox-dev-secret}
    - SANDBOX_CONTROL_PLANE_URL=${SANDBOX_CONTROL_PLANE_URL:-http://sandbox-control-plane:8787}
```

**Step 3: Commit**

```bash
git add vendor/open-inspect docker-compose.yml
git commit -m "chore: update submodule with webhook support, wire sandbox env vars to backend"
```

---

### Task 12: Integration Test

**Files:** No new files — manual testing

**Step 1: Start environment**

```bash
docker compose --profile dev --profile init up -d --build
```

**Step 2: Verify services are healthy**

```bash
docker compose logs sandbox-control-plane sandbox-manager druppie-backend-dev
```

**Step 3: Test the flow**

1. Create a project in the UI
2. Trigger the builder agent with a coding task
3. Verify the agent calls `execute_coding_task` (check backend logs)
4. Verify sandbox session is created (check control plane logs)
5. Verify the session status is `PAUSED_SANDBOX` in the UI
6. Wait for sandbox to complete (check control plane logs for callback)
7. Verify webhook is received by Druppie backend (check backend logs for `sandbox_webhook_received`)
8. Verify agent resumes and completes
9. Verify git pull synced changes

**Step 4: Test error cases**

1. Kill the sandbox mid-execution — verify webhook arrives with `success=false`
2. Verify the agent sees the failure and can decide to retry or report

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: sandbox webhook pause/resume — complete implementation"
```

---

### Task 13: Update Documentation

**Files:**
- Modify: `docs/TECHNICAL.md`
- Modify: `docs/FEATURES.md`

**Step 1: Update TECHNICAL.md**

In the Sandbox Infrastructure section (Section 10), update to describe the webhook + pause/resume pattern instead of the polling loop. Key changes:
- `execute_coding_task` is now a built-in tool, not an MCP tool
- Completion is detected via webhook callback, not polling
- New statuses: `WAITING_SANDBOX`, `PAUSED_SANDBOX`
- New endpoint: `POST /api/sandbox-sessions/{id}/complete`

**Step 2: Update FEATURES.md**

Update the Sandbox Coding section to mention that the agent pauses while the sandbox runs and resumes automatically on completion.

**Step 3: Commit**

```bash
git add docs/TECHNICAL.md docs/FEATURES.md
git commit -m "docs: update sandbox docs for webhook pause/resume architecture"
```
