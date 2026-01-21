# MCP Microservices Architecture Plan (Updated)

## Overview

Refactor MCP servers into **separate Docker containers** using **FastMCP framework**:
- **Coding MCP** - Combined file operations + git (workspace sandbox with auto-commit)
- **Docker MCP** - Container build/run operations
- **HITL MCP** - Human-in-the-loop with state persistence for approvals

## Key Changes from Previous Plan
1. **Combined Coding + Git MCP** - Git operations happen within workspace context
2. **MCP Configuration File** - Central `mcp_config.yaml` defines all MCPs and URLs
3. **Agent MCP Definitions** - Each agent YAML specifies which MCPs/tools it can use
4. **HITL State Persistence** - Approvals save state and resume agent after approval

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Druppie Backend (FastAPI)                       │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────────┐ │
│  │ Main Loop   │───▶│  MCP Client  │───▶│  HTTP + Bearer Token   │ │
│  │             │    │(mcp_config)  │    │                        │ │
│  └─────────────┘    └──────────────┘    └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
         ┌──────────────────┐    ┌──────────────────┐
         │  Coding MCP      │    │   Docker MCP     │
         │  (FastMCP)       │    │  (FastMCP)       │
         │  Port 9001       │    │  Port 9002       │
         │                  │    │                  │
         │  - Workspace     │    │  - build/run     │
         │  - File ops      │    │  - stop/logs     │
         │  - Git ops       │    │  - Docker socket │
         │  - Auto-commit   │    │                  │
         └──────────────────┘    └──────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  HITL MCP        │
         │  (FastMCP)       │
         │  Port 9003       │
         │                  │
         │  - ask (question)│
         │  - approve (role)│
         │  - progress      │
         │  - State persist │
         │  - Redis pub/sub │
         └──────────────────┘
```

---

## Directory Structure

```
druppie/
├── mcp-servers/
│   ├── coding/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py          # Combined coding + git
│   ├── docker/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   └── hitl/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── server.py          # With state persistence
│
├── core/
│   ├── loop.py                # Uses MCPClient
│   ├── mcp_client.py          # HTTP client
│   └── mcp_config.yaml        # MCP definitions
│
├── agents/
│   └── definitions/
│       └── developer.yaml     # Specifies mcps: [coding, hitl]
│
└── docker-compose.full.yml    # MCP containers
```

---

## MCP Configuration File

**File: `druppie/core/mcp_config.yaml`**

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    description: "File operations and git within workspace sandbox"
    tools:
      - name: initialize_workspace
        description: "Initialize workspace for user/project/session"
        requires_approval: false
      - name: read_file
        description: "Read file from workspace"
        requires_approval: false
      - name: write_file
        description: "Write file to workspace (auto-commits)"
        requires_approval: false
      - name: list_dir
        description: "List directory contents"
        requires_approval: false
      - name: delete_file
        description: "Delete file from workspace"
        requires_approval: false
      - name: run_command
        description: "Execute shell command in workspace"
        requires_approval: true
        required_roles: [developer]
      - name: commit_and_push
        description: "Commit and push changes to Gitea"
        requires_approval: false
      - name: create_branch
        description: "Create a new git branch"
        requires_approval: false
      - name: merge_to_main
        description: "Merge feature branch to main"
        requires_approval: true
        required_roles: [architect, admin]

  docker:
    url: ${MCP_DOCKER_URL:-http://mcp-docker:9002}
    description: "Docker container operations"
    tools:
      - name: build
        description: "Build Docker image"
        requires_approval: true
        required_roles: [developer]
      - name: run
        description: "Run Docker container"
        requires_approval: true
        required_roles: [developer]
      - name: stop
        description: "Stop running container"
        requires_approval: false
      - name: logs
        description: "Get container logs"
        requires_approval: false
      - name: remove
        description: "Remove container"
        requires_approval: true
        required_roles: [developer]

  hitl:
    url: ${MCP_HITL_URL:-http://mcp-hitl:9003}
    description: "Human-in-the-loop - ask user questions"
    tools:
      - name: ask_question
        description: "Ask user a free-form text question"
        requires_approval: false
      - name: ask_choice
        description: "Ask user a multiple choice question (with optional 'Other' text input)"
        requires_approval: false
```

---

## Agent Definition with MCP Tools

**File: `druppie/agents/definitions/developer.yaml`**

```yaml
name: developer
description: Senior developer that writes code
system_prompt: |
  You are a Senior Developer Agent for Druppie.

  CRITICAL: You can ONLY act through MCP tools. Never output code directly.

  WORKFLOW:
  1. Workspace is auto-initialized at conversation start
  2. Use coding:list_dir to see existing files
  3. Use coding:read_file to read files
  4. Use coding:write_file to create/modify files (auto-commits)
  5. Use hitl:progress to report progress
  6. When done, files are already committed to git

mcps:
  coding:
    - read_file
    - write_file
    - list_dir
    - delete_file
    - run_command  # Requires user approval
  hitl:
    - ask_question
    - ask_choice

settings:
  model: glm-4
  temperature: 0.1
```

---

## HITL MCP - Human-in-the-Loop (Simplified)

**Purpose**: Allow agent to ask user questions. Only two tools:
- `ask_question` - Free-form text input
- `ask_choice` - Multiple choice with optional "Other" text input

**Note**: Approval requests are handled by the Core, not HITL MCP. HITL is purely for agent-initiated questions.

**File: `druppie/mcp-servers/hitl/server.py`**

```python
from fastmcp import FastMCP
import redis
import json
import uuid
import os
from datetime import datetime

mcp = FastMCP("HITL MCP Server")
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))

@mcp.tool()
async def ask_question(
    session_id: str,
    question: str
) -> dict:
    """Ask user a free-form text question.

    Example: "What framework would you like to use?"
    User types their answer in a text box.
    """
    request_id = str(uuid.uuid4())

    # Publish question to frontend via Redis
    redis_client.publish(f"hitl:{session_id}", json.dumps({
        "type": "question",
        "request_id": request_id,
        "question": question,
        "input_type": "text"  # Free-form text input
    }))

    # Wait for response (blocking)
    response = redis_client.blpop(f"hitl:response:{request_id}", timeout=300)

    if response:
        data = json.loads(response[1])
        return {"success": True, "answer": data.get("answer")}

    return {"success": False, "error": "Timeout waiting for response"}


@mcp.tool()
async def ask_choice(
    session_id: str,
    question: str,
    choices: list[str],
    allow_other: bool = True
) -> dict:
    """Ask user a multiple choice question with optional free-text "Other".

    Example:
        question: "Which database should we use?"
        choices: ["PostgreSQL", "MySQL", "SQLite"]
        allow_other: True  # Shows "Other: [text input]" option

    User selects one choice OR types custom answer if allow_other=True.
    """
    request_id = str(uuid.uuid4())

    # Publish to frontend
    redis_client.publish(f"hitl:{session_id}", json.dumps({
        "type": "question",
        "request_id": request_id,
        "question": question,
        "input_type": "choice",
        "choices": choices,
        "allow_other": allow_other
    }))

    # Wait for response
    response = redis_client.blpop(f"hitl:response:{request_id}", timeout=300)

    if response:
        data = json.loads(response[1])
        return {
            "success": True,
            "selected": data.get("selected"),  # The choice or "other"
            "answer": data.get("answer")  # Custom text if "other" selected
        }

    return {"success": False, "error": "Timeout waiting for response"}


# Endpoint for frontend to submit responses
@mcp.tool()
async def submit_response(
    request_id: str,
    answer: str,
    selected: str = None  # For choice questions
) -> dict:
    """Submit user response (called by backend API when user answers)."""
    redis_client.lpush(f"hitl:response:{request_id}", json.dumps({
        "answer": answer,
        "selected": selected
    }))
    return {"success": True}


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9003)
```

### Frontend Integration for HITL Questions

```javascript
// In Chat.jsx - handle HITL question events
socket.on('question', (data) => {
    if (data.input_type === 'text') {
        // Show text input dialog
        setQuestionDialog({
            requestId: data.request_id,
            question: data.question,
            type: 'text'
        });
    } else if (data.input_type === 'choice') {
        // Show choice dialog with options
        setQuestionDialog({
            requestId: data.request_id,
            question: data.question,
            type: 'choice',
            choices: data.choices,
            allowOther: data.allow_other
        });
    }
});

// Submit answer
const submitAnswer = async (requestId, answer, selected = null) => {
    await api.post('/api/hitl/response', {
        request_id: requestId,
        answer,
        selected
    });
    setQuestionDialog(null);
};
```

---

## Combined Coding + Git MCP

**File: `druppie/mcp-servers/coding/server.py`**

```python
from fastmcp import FastMCP
from pathlib import Path
import subprocess
import os
import uuid
import httpx

mcp = FastMCP("Coding MCP Server")

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")

# In-memory workspace registry (in production, use Redis/DB)
workspaces = {}

async def create_gitea_repo(repo_name: str, description: str) -> dict:
    """Create repository in Gitea."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITEA_URL}/api/v1/orgs/{GITEA_ORG}/repos",
            json={
                "name": repo_name,
                "description": description,
                "private": False,
                "auto_init": True
            },
            headers={"Authorization": f"token {GITEA_TOKEN}"}
        )
        return response.json()

@mcp.tool()
async def initialize_workspace(
    user_id: str,
    project_id: str | None,
    session_id: str,
    project_name: str | None = None
) -> dict:
    """Initialize workspace for a conversation.

    - New project (project_id=None): Create repo on main branch
    - Existing project: Clone and create feature branch
    """
    workspace_id = f"{user_id}-{session_id}"

    if project_id is None:
        # New project
        project_id = str(uuid.uuid4())
        repo_name = f"project-{project_id[:8]}"

        # Create Gitea repo
        await create_gitea_repo(repo_name, project_name or "New Project")
        branch = "main"
    else:
        # TODO: Get repo_name from DB
        repo_name = f"project-{project_id[:8]}"
        branch = f"session-{session_id[:8]}"

    # Create workspace directory
    workspace_path = WORKSPACE_ROOT / user_id / project_id / session_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Clone repo
    repo_url = f"{GITEA_URL}/{GITEA_ORG}/{repo_name}.git"

    try:
        subprocess.run(
            ["git", "clone", repo_url, str(workspace_path)],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        # Repo might be empty, init locally
        subprocess.run(["git", "init"], cwd=workspace_path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", repo_url],
            cwd=workspace_path, check=True
        )

    # Create feature branch if not main
    if branch != "main":
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=workspace_path, check=True
        )

    # Register workspace
    workspaces[workspace_id] = {
        "path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
        "repo_name": repo_name
    }

    return {
        "success": True,
        "workspace_id": workspace_id,
        "workspace_path": str(workspace_path),
        "project_id": project_id,
        "branch": branch
    }

def get_workspace(workspace_id: str) -> dict:
    if workspace_id not in workspaces:
        raise ValueError(f"Workspace not found: {workspace_id}")
    return workspaces[workspace_id]

@mcp.tool()
async def read_file(path: str, workspace_id: str) -> dict:
    """Read file from workspace."""
    ws = get_workspace(workspace_id)
    file_path = Path(ws["path"]) / path

    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}

    return {"success": True, "content": file_path.read_text()}

@mcp.tool()
async def write_file(
    path: str,
    content: str,
    workspace_id: str,
    auto_commit: bool = True
) -> dict:
    """Write file and auto-commit to git."""
    ws = get_workspace(workspace_id)
    file_path = Path(ws["path"]) / path

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    if auto_commit:
        await commit_and_push(workspace_id, f"Update {path}")

    return {"success": True, "path": path}

@mcp.tool()
async def list_dir(path: str = "", workspace_id: str = None) -> dict:
    """List directory contents."""
    ws = get_workspace(workspace_id)
    dir_path = Path(ws["path"]) / path

    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {path}"}

    files = []
    for item in dir_path.iterdir():
        if item.name.startswith(".git"):
            continue
        files.append({
            "name": item.name,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else 0
        })

    return {"success": True, "files": files}

@mcp.tool()
async def delete_file(path: str, workspace_id: str, auto_commit: bool = True) -> dict:
    """Delete file from workspace."""
    ws = get_workspace(workspace_id)
    file_path = Path(ws["path"]) / path

    if not file_path.exists():
        return {"success": False, "error": f"File not found: {path}"}

    file_path.unlink()

    if auto_commit:
        await commit_and_push(workspace_id, f"Delete {path}")

    return {"success": True, "deleted": path}

@mcp.tool()
async def run_command(command: str, workspace_id: str) -> dict:
    """Run shell command in workspace (requires approval)."""
    ws = get_workspace(workspace_id)

    result = subprocess.run(
        command, shell=True, cwd=ws["path"],
        capture_output=True, text=True, timeout=60
    )

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode
    }

@mcp.tool()
async def commit_and_push(workspace_id: str, message: str) -> dict:
    """Commit all changes and push to Gitea."""
    ws = get_workspace(workspace_id)
    cwd = ws["path"]

    # Configure git user
    subprocess.run(["git", "config", "user.email", "agent@druppie.local"], cwd=cwd)
    subprocess.run(["git", "config", "user.name", "Druppie Agent"], cwd=cwd)

    # Stage all
    subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)

    # Check for changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd, capture_output=True, text=True
    )

    if not result.stdout.strip():
        return {"success": True, "message": "No changes to commit"}

    # Commit
    subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

    # Push
    subprocess.run(
        ["git", "push", "-u", "origin", ws["branch"]],
        cwd=cwd, check=True
    )

    return {"success": True, "message": f"Committed: {message}"}

@mcp.tool()
async def create_branch(workspace_id: str, branch_name: str) -> dict:
    """Create and checkout a new branch."""
    ws = get_workspace(workspace_id)

    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=ws["path"], check=True
    )

    ws["branch"] = branch_name

    return {"success": True, "branch": branch_name}

@mcp.tool()
async def merge_to_main(workspace_id: str) -> dict:
    """Merge current branch to main (requires approval)."""
    ws = get_workspace(workspace_id)
    cwd = ws["path"]
    current_branch = ws["branch"]

    if current_branch == "main":
        return {"success": False, "error": "Already on main branch"}

    # Checkout main and merge
    subprocess.run(["git", "checkout", "main"], cwd=cwd, check=True)
    subprocess.run(["git", "merge", current_branch], cwd=cwd, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True)

    ws["branch"] = "main"

    return {"success": True, "merged": current_branch}

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9001)
```

---

## Approval Flow: How Core Detects, Pauses, and Resumes

### Overview

When an agent tries to call a tool that requires approval:
1. **Core checks** `mcp_config.yaml` for `requires_approval: true`
2. **Core pauses** execution and saves full agent state
3. **Frontend shows** approval request to user
4. **User approves** via API endpoint
5. **Core resumes** execution from saved state

### Flow Diagram

**Key principle**: AI agent executes tools, so user ALWAYS confirms (even if they have the role).

```
Agent calls: coding:run_command("npm install")
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│                    MainLoop._execute_tool()                  │
│  1. Parse tool: server="coding", tool="run_command"         │
│  2. Check mcp_config: requires_approval=true, roles=[dev]   │
│  3. ALWAYS pause and ask user for confirmation              │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│  Create Approval Request (ALWAYS for approval-required tools) │
│  - Save agent state (full LangGraph checkpoint)              │
│  - Save pending tool call                                    │
│  - Store in DB                                               │
│  - Emit "approval_required" to frontend                      │
│  - Return PAUSED status                                      │
└──────────────────────────────────────────────────────────────┘
                    │
                    ▼
         Session status = "waiting_approval"
         Frontend shows: "Agent wants to run: npm install"
         User clicks [Approve] or [Reject]
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│           POST /api/approvals/{id}/approve                    │
│  1. Validate user has required role (can self-approve)       │
│  2. Mark approval as approved/rejected                       │
│  3. If approved: Call resume_execution(session_id)           │
└──────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│           MainLoop.resume_execution(session_id)               │
│  1. Load saved agent state from DB                           │
│  2. Execute the pending tool call                            │
│  3. Continue agent execution from where it paused            │
└──────────────────────────────────────────────────────────────┘
```

**Self-approval vs External approval:**
- `required_roles: [developer]` + user is developer → User can self-approve
- `required_roles: [architect]` + user is developer → Needs architect to approve
- **Both cases**: AI pauses and asks for confirmation first

### Core Implementation: MCPClient with Approval Check

**File: `druppie/core/mcp_client.py`**

```python
import httpx
import yaml
import os
from pathlib import Path

class MCPClient:
    """HTTP client for MCP servers with approval checking."""

    def __init__(self, db, redis_client):
        self.db = db
        self.redis = redis_client
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load MCP configuration."""
        config_path = Path(__file__).parent / "mcp_config.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def get_tool_config(self, server: str, tool: str) -> dict:
        """Get tool configuration including approval requirements."""
        mcp = self.config["mcps"].get(server, {})
        for t in mcp.get("tools", []):
            if t["name"] == tool:
                return t
        return {}

    def requires_approval(self, server: str, tool: str) -> tuple[bool, list[str]]:
        """Check if tool requires approval and what roles can approve."""
        config = self.get_tool_config(server, tool)
        return (
            config.get("requires_approval", False),
            config.get("required_roles", [])
        )

    def user_has_role(self, user_roles: list[str], required_roles: list[str]) -> bool:
        """Check if user has any of the required roles."""
        return any(role in user_roles for role in required_roles)

    async def call_tool(
        self,
        server: str,
        tool: str,
        args: dict,
        context: "ExecutionContext"
    ) -> dict:
        """Call MCP tool, checking for approval requirements.

        IMPORTANT: AI executes tools, so user ALWAYS confirms for
        approval-required tools (even if user has the role).
        """
        needs_approval, required_roles = self.requires_approval(server, tool)

        if needs_approval:
            # ALWAYS request approval - AI is executing, user must confirm
            # User's role determines if they can self-approve or need another user
            return await self._request_approval(
                server, tool, args, required_roles, context
            )

        # No approval needed for this tool
        return await self._execute_tool(server, tool, args, context)

    async def _execute_tool(
        self,
        server: str,
        tool: str,
        args: dict,
        context: "ExecutionContext"
    ) -> dict:
        """Actually execute the tool via HTTP."""
        url = self.config["mcps"][server]["url"]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{url}/tools/{tool}",
                json=args,
                headers={"Authorization": f"Bearer {context.user_token}"}
            )
            return response.json()

    async def _request_approval(
        self,
        server: str,
        tool: str,
        args: dict,
        required_roles: list[str],
        context: "ExecutionContext"
    ) -> dict:
        """Request approval and pause execution."""
        from db import crud

        # Create approval record in DB
        approval = crud.create_approval(
            self.db,
            session_id=context.session_id,
            tool_name=f"{server}:{tool}",
            tool_args=args,
            required_roles=required_roles,
            agent_state=context.agent_state,  # Full LangGraph state
            status="pending"
        )

        # Update session status
        crud.update_session_status(
            self.db,
            context.session_id,
            status="waiting_approval",
            pending_approval_id=approval.id
        )

        # Emit event to frontend via WebSocket
        await self._emit_approval_request(context.session_id, approval)

        # Return special PAUSED status
        return {
            "status": "paused",
            "reason": "approval_required",
            "approval_id": approval.id,
            "tool": f"{server}:{tool}",
            "required_roles": required_roles
        }

    async def _emit_approval_request(self, session_id: str, approval):
        """Emit approval request via Redis pub/sub."""
        import json
        self.redis.publish(
            f"session:{session_id}",
            json.dumps({
                "type": "approval_required",
                "approval_id": approval.id,
                "tool": approval.tool_name,
                "args": approval.tool_args,
                "required_roles": approval.required_roles
            })
        )
```

### API Endpoints for Approvals

**File: `druppie/api/routes/approvals.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db import crud, get_db
from core.auth import get_current_user
from core.loop import MainLoop

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

@router.get("")
async def list_approvals(
    status: str = "pending",
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List approvals (filtered by user's roles if not admin)."""
    user_roles = user.get("roles", [])

    if "admin" in user_roles:
        # Admin sees all
        approvals = crud.list_approvals(db, status=status)
    else:
        # User sees only approvals they can approve
        approvals = crud.list_approvals_for_roles(db, user_roles, status=status)

    return {"approvals": approvals}

@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get approval details."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    return approval

@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Approve a pending request and resume execution."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    if approval.status != "pending":
        raise HTTPException(400, f"Approval already {approval.status}")

    # Check user has required role
    user_roles = user.get("roles", [])
    if not any(role in user_roles for role in approval.required_roles):
        raise HTTPException(403, "You don't have permission to approve this")

    # Mark as approved
    crud.update_approval(
        db, approval_id,
        status="approved",
        approved_by=user.get("sub"),
        approved_at=datetime.utcnow()
    )

    # Resume execution
    main_loop = MainLoop(db)
    result = await main_loop.resume_execution(
        session_id=approval.session_id,
        approval_id=approval_id
    )

    return {
        "success": True,
        "message": "Approved and execution resumed",
        "result": result
    }

@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str,
    reason: str = None,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reject a pending request."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    # Check user has required role
    user_roles = user.get("roles", [])
    if not any(role in user_roles for role in approval.required_roles):
        raise HTTPException(403, "You don't have permission to reject this")

    # Mark as rejected
    crud.update_approval(
        db, approval_id,
        status="rejected",
        rejected_by=user.get("sub"),
        rejection_reason=reason
    )

    # Update session status
    crud.update_session_status(
        db, approval.session_id,
        status="rejected",
        error="Approval rejected: " + (reason or "No reason provided")
    )

    return {"success": True, "message": "Rejected"}
```

### MainLoop Resume Execution

**File: `druppie/core/loop.py`** (additions)

```python
class MainLoop:
    async def resume_execution(
        self,
        session_id: str,
        approval_id: str
    ) -> dict:
        """Resume execution after approval is granted."""
        # Load approval with saved state
        approval = crud.get_approval(self.db, approval_id)

        # Load session
        session = crud.get_session(self.db, session_id)

        # Restore agent state (LangGraph checkpoint)
        agent_state = approval.agent_state

        # Execute the pending tool that was waiting for approval
        server, tool = approval.tool_name.split(":")
        result = await self.mcp_client._execute_tool(
            server=server,
            tool=tool,
            args=approval.tool_args,
            context=ExecutionContext(
                session_id=session_id,
                user_token=session.user_token,
                user_roles=session.user_roles,
                workspace_id=session.workspace_id
            )
        )

        # Add tool result to agent state
        agent_state["tool_results"].append({
            "tool": approval.tool_name,
            "result": result
        })

        # Continue LangGraph execution from saved checkpoint
        # The agent will see the tool result and continue
        final_result = await self._continue_agent_execution(
            session_id=session_id,
            agent_state=agent_state
        )

        # Update session status
        crud.update_session_status(self.db, session_id, status="completed")

        return final_result

    async def _continue_agent_execution(
        self,
        session_id: str,
        agent_state: dict
    ) -> dict:
        """Continue LangGraph agent from saved state."""
        # Load the LangGraph graph
        graph = self._build_graph()

        # Create config with checkpoint
        config = {
            "configurable": {
                "thread_id": session_id,
            }
        }

        # Restore checkpoint and continue
        # LangGraph will continue from where it left off
        result = await graph.ainvoke(
            agent_state,
            config=config
        )

        return result
```

### Database Models for Approvals

**File: `druppie/db/models.py`** (additions)

```python
class Approval(Base):
    """Pending approval for a tool call."""
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    tool_name = Column(String, nullable=False)  # e.g., "coding:run_command"
    tool_args = Column(JSON)  # Arguments for the tool
    required_roles = Column(JSON)  # ["developer", "admin"]
    agent_state = Column(JSON)  # Full LangGraph state for resume
    status = Column(String, default="pending")  # pending, approved, rejected
    approved_by = Column(String)  # User ID who approved
    approved_at = Column(DateTime)
    rejected_by = Column(String)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Frontend Integration

The frontend receives WebSocket events for approval requests:

```javascript
// In Chat.jsx or dedicated ApprovalHandler
socket.on('approval_required', (data) => {
    // Show approval UI
    setApprovalRequests(prev => [...prev, {
        id: data.approval_id,
        tool: data.tool,
        args: data.args,
        requiredRoles: data.required_roles
    }]);
});

// Approve handler
const handleApprove = async (approvalId) => {
    const response = await api.post(`/api/approvals/${approvalId}/approve`);
    // Remove from pending list
    setApprovalRequests(prev => prev.filter(a => a.id !== approvalId));
};
```

---

## Files to Create

| Path | Description |
|------|-------------|
| `druppie/mcp-servers/coding/server.py` | Combined coding + git MCP |
| `druppie/mcp-servers/coding/Dockerfile` | Coding MCP container |
| `druppie/mcp-servers/coding/requirements.txt` | Dependencies |
| `druppie/mcp-servers/docker/server.py` | Docker operations MCP |
| `druppie/mcp-servers/docker/Dockerfile` | Docker MCP container |
| `druppie/mcp-servers/docker/requirements.txt` | Dependencies |
| `druppie/mcp-servers/hitl/server.py` | HITL MCP (questions, progress) |
| `druppie/mcp-servers/hitl/Dockerfile` | HITL MCP container |
| `druppie/mcp-servers/hitl/requirements.txt` | Dependencies |
| `druppie/core/mcp_config.yaml` | MCP definitions with approval rules |
| `druppie/core/mcp_client.py` | HTTP client with approval checking |
| `druppie/api/routes/approvals.py` | Approval API endpoints |

## Files to Modify

| Path | Changes |
|------|---------|
| `druppie/core/loop.py` | Use MCPClient, add resume_execution(), save/restore agent state |
| `druppie/db/models.py` | Add Approval model |
| `druppie/db/crud.py` | Add CRUD for approvals |
| `druppie/api/routes/__init__.py` | Register approvals router |
| `druppie/docker-compose.full.yml` | Add MCP containers |
| `druppie/agents/definitions/*.yaml` | Add mcps section with tool list |
| `frontend/src/pages/Chat.jsx` | Handle approval_required events |

## Files to Remove

| Path | Reason |
|------|--------|
| `druppie/mcps/coding.py` | Moved to mcp-servers/coding |
| `druppie/mcps/git.py` | Merged into mcp-servers/coding |
| `druppie/mcps/docker.py` | Moved to mcp-servers/docker |
| `druppie/mcps/hitl.py` | Moved to mcp-servers/hitl |
| `druppie/mcps/registry.py` | Replaced by mcp_config.yaml |

---

## Implementation Order

1. **Create MCP server directories** - `mcp-servers/{coding,docker,hitl}/`
2. **Create Coding MCP** - Combined file ops + git with FastMCP
3. **Create Docker MCP** - Build/run containers with FastMCP
4. **Create HITL MCP** - Questions, progress via Redis pub/sub
5. **Create mcp_config.yaml** - Define MCPs, tools, approval requirements
6. **Create MCPClient** - HTTP client with approval checking logic
7. **Add Approval model** - Database model for pending approvals
8. **Add CRUD for approvals** - Create, list, update approval records
9. **Create approvals API** - `/api/approvals` endpoints
10. **Update loop.py** - Use MCPClient, add `resume_execution()`
11. **Update docker-compose.full.yml** - Add MCP containers
12. **Update agent definitions** - Add mcps section with tool lists
13. **Update frontend** - Handle approval_required WebSocket events
14. **Remove old mcps/** - Clean up legacy module-based MCPs
15. **Test** - E2E flow with approval

---

## Verification

### 1. Test MCP Servers Individually
```bash
# Start MCP containers
docker compose -f docker-compose.full.yml up mcp-coding mcp-docker mcp-hitl

# Test coding MCP
curl http://localhost:9001/tools
curl -X POST http://localhost:9001/tools/list_dir \
  -H "Content-Type: application/json" \
  -d '{"path": "", "workspace_id": "test"}'
```

### 2. Test Approval Flow
```bash
# 1. Login and get token
TOKEN=$(curl -X POST "http://localhost:8180/realms/druppie/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=druppie-frontend&username=juniordev&password=Junior123!" \
  | jq -r .access_token)

# 2. Send chat that triggers run_command (requires approval)
# As junior dev, this should pause for approval

# 3. List pending approvals as admin/developer
curl http://localhost:8100/api/approvals \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 4. Approve as senior developer
curl -X POST http://localhost:8100/api/approvals/{id}/approve \
  -H "Authorization: Bearer $SENIOR_TOKEN"

# 5. Verify execution resumed
```

### 3. E2E Test: Full Chat Flow with Approval
1. Login as `juniordev` (has limited roles)
2. Send chat: "Run npm install in the project"
3. Verify: Approval request appears in UI
4. Switch to `seniordev` account
5. Approve the request
6. Verify: Command executes and result shown
7. Verify: Agent continues from where it paused

### 4. Test Git-First Workflow
1. Send chat: "Create a todo app"
2. Verify: Gitea repo created
3. Verify: Files committed to main branch
4. Send chat to same project: "Add dark mode"
5. Verify: Feature branch created
6. Verify: merge_to_main requires approval
7. Approve merge
8. Verify: Changes merged to main
