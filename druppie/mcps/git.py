"""Git MCP Server.

Provides Git version control and Gitea repository operations.
"""

import os
import subprocess
from typing import Any

import httpx
import structlog

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

GIT_TOOLS = [
    MCPTool(
        id="git:clone",
        name="Clone Repository",
        description="Clone a git repository to workspace",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "repo_url": {"type": "string", "description": "Repository URL"},
                "path": {"type": "string", "description": "Target path"},
                "branch": {"type": "string", "description": "Branch to clone"},
            },
            "required": ["repo_url", "path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:init",
        name="Initialize Repository",
        description="Initialize a new git repository",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to initialize"},
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:status",
        name="Repository Status",
        description="Get repository status",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:add",
        name="Stage Files",
        description="Add files to staging",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "files": {
                    "type": "string",
                    "description": "Files to add (default: '.')",
                    "default": ".",
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:commit",
        name="Commit Changes",
        description="Commit staged changes",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["path", "message"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:push",
        name="Push to Remote",
        description="Push commits to remote repository",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "branch": {"type": "string", "description": "Branch to push"},
                "remote": {
                    "type": "string",
                    "description": "Remote name",
                    "default": "origin",
                },
            },
            "required": ["path", "branch"],
        },
        allowed_roles=["developer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="git:pull",
        name="Pull from Remote",
        description="Pull changes from remote",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "remote": {
                    "type": "string",
                    "description": "Remote name",
                    "default": "origin",
                },
                "branch": {"type": "string", "description": "Branch to pull"},
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:branch",
        name="Create Branch",
        description="Create or list branches",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "name": {"type": "string", "description": "Branch name to create"},
                "checkout": {
                    "type": "boolean",
                    "description": "Checkout after creating",
                    "default": True,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:checkout",
        name="Checkout Branch",
        description="Checkout a branch",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "branch": {"type": "string", "description": "Branch to checkout"},
                "create": {
                    "type": "boolean",
                    "description": "Create if doesn't exist",
                    "default": False,
                },
            },
            "required": ["path", "branch"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:diff",
        name="Show Diff",
        description="Show changes between commits or working tree",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "staged": {
                    "type": "boolean",
                    "description": "Show staged changes",
                    "default": False,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:log",
        name="Show Log",
        description="Show commit log",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"},
                "count": {
                    "type": "integer",
                    "description": "Number of commits",
                    "default": 10,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="git:create_repo",
        name="Create Repository (Gitea)",
        description="Create a new repository on Gitea",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "description": {"type": "string", "description": "Repository description"},
                "private": {
                    "type": "boolean",
                    "description": "Private repository",
                    "default": False,
                },
            },
            "required": ["name"],
        },
        approval_type=ApprovalType.SELF,
        danger_level="low",
    ),
    MCPTool(
        id="git:merge_branch",
        name="Merge Branch (Gitea)",
        description="Create a pull request and merge on Gitea",
        category="git",
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "source_branch": {"type": "string", "description": "Source branch"},
                "target_branch": {
                    "type": "string",
                    "description": "Target branch",
                    "default": "main",
                },
                "title": {"type": "string", "description": "PR title"},
            },
            "required": ["repo", "source_branch", "title"],
        },
        allowed_roles=["developer", "admin"],
        approval_type=ApprovalType.ROLE,
        approval_roles=["developer", "admin"],
        danger_level="high",
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _run_git(args: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_gitea_config() -> tuple[str, str]:
    """Get Gitea URL and token from environment."""
    url = os.getenv("GITEA_URL", "http://localhost:3000")
    token = os.getenv("GITEA_TOKEN", "")
    return url, token


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================


async def clone(
    repo_url: str,
    path: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Clone a git repository."""
    args = ["clone"]
    if branch:
        args.extend(["-b", branch])
    args.extend([repo_url, path])

    result = _run_git(args)
    if result["success"]:
        logger.info("repo_cloned", url=repo_url, path=path)
    return result


async def init(path: str) -> dict[str, Any]:
    """Initialize a new git repository."""
    os.makedirs(path, exist_ok=True)
    result = _run_git(["init"], cwd=path)
    if result["success"]:
        logger.info("repo_initialized", path=path)
    return result


async def status(path: str) -> dict[str, Any]:
    """Get repository status."""
    result = _run_git(["status", "--porcelain"], cwd=path)
    if result["success"]:
        files = []
        for line in result["stdout"].strip().split("\n"):
            if line:
                status_code = line[:2].strip()
                filename = line[3:]
                files.append({"status": status_code, "file": filename})
        result["files"] = files
    return result


async def add(path: str, files: str = ".") -> dict[str, Any]:
    """Add files to staging."""
    return _run_git(["add", files], cwd=path)


async def commit(path: str, message: str) -> dict[str, Any]:
    """Commit staged changes."""
    result = _run_git(["commit", "-m", message], cwd=path)
    if result["success"]:
        logger.info("committed", path=path, message=message[:50])
    return result


async def push(
    path: str,
    branch: str,
    remote: str = "origin",
) -> dict[str, Any]:
    """Push commits to remote."""
    result = _run_git(["push", "-u", remote, branch], cwd=path)
    if result["success"]:
        logger.info("pushed", path=path, branch=branch)
    return result


async def pull(
    path: str,
    remote: str = "origin",
    branch: str | None = None,
) -> dict[str, Any]:
    """Pull changes from remote."""
    args = ["pull", remote]
    if branch:
        args.append(branch)
    return _run_git(args, cwd=path)


async def branch(
    path: str,
    name: str | None = None,
    checkout: bool = True,
) -> dict[str, Any]:
    """Create or list branches."""
    if name:
        if checkout:
            result = _run_git(["checkout", "-b", name], cwd=path)
        else:
            result = _run_git(["branch", name], cwd=path)
        if result["success"]:
            logger.info("branch_created", path=path, branch=name)
    else:
        result = _run_git(["branch"], cwd=path)
        if result["success"]:
            branches = [
                b.strip().lstrip("* ") for b in result["stdout"].split("\n") if b.strip()
            ]
            result["branches"] = branches
    return result


async def checkout(
    path: str,
    branch: str,
    create: bool = False,
) -> dict[str, Any]:
    """Checkout a branch."""
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(branch)
    return _run_git(args, cwd=path)


async def diff(path: str, staged: bool = False) -> dict[str, Any]:
    """Show changes."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    return _run_git(args, cwd=path)


async def log(path: str, count: int = 10) -> dict[str, Any]:
    """Show commit log."""
    result = _run_git(
        ["log", f"-{count}", "--oneline", "--format=%H|%s|%an|%ai"],
        cwd=path,
    )
    if result["success"]:
        commits = []
        for line in result["stdout"].strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3],
                    })
        result["commits"] = commits
    return result


async def create_repo(
    name: str,
    description: str = "",
    private: bool = False,
) -> dict[str, Any]:
    """Create a repository on Gitea."""
    gitea_url, gitea_token = _get_gitea_config()
    if not gitea_token:
        return {"success": False, "error": "Gitea token not configured"}

    url = f"{gitea_url}/api/v1/user/repos"
    headers = {
        "Authorization": f"token {gitea_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code in (200, 201):
                data = response.json()
                logger.info("gitea_repo_created", name=name)
                return {
                    "success": True,
                    "repo": {
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "clone_url": data.get("clone_url"),
                        "html_url": data.get("html_url"),
                    },
                }
            else:
                return {
                    "success": False,
                    "error": f"Gitea API error: {response.status_code}",
                }

    except Exception as e:
        logger.error("gitea_create_repo_error", name=name, error=str(e))
        return {"success": False, "error": str(e)}


async def merge_branch(
    repo: str,
    source_branch: str,
    target_branch: str = "main",
    title: str = "",
) -> dict[str, Any]:
    """Create a pull request and merge on Gitea."""
    gitea_url, gitea_token = _get_gitea_config()
    if not gitea_token:
        return {"success": False, "error": "Gitea token not configured"}

    # Get current user for owner
    owner = os.getenv("GITEA_OWNER", "druppie")

    # Create PR
    pr_url = f"{gitea_url}/api/v1/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"token {gitea_token}",
        "Content-Type": "application/json",
    }
    pr_payload = {
        "title": title,
        "head": source_branch,
        "base": target_branch,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(pr_url, json=pr_payload, headers=headers)

            if response.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Failed to create PR: {response.status_code}",
                }

            pr_data = response.json()
            pr_number = pr_data.get("number")

            # Merge PR
            merge_url = f"{gitea_url}/api/v1/repos/{owner}/{repo}/pulls/{pr_number}/merge"
            merge_response = await client.post(
                merge_url,
                json={"Do": "merge"},
                headers=headers,
            )

            if merge_response.status_code in (200, 201):
                logger.info(
                    "branch_merged",
                    repo=repo,
                    source=source_branch,
                    target=target_branch,
                )
                return {
                    "success": True,
                    "pr_number": pr_number,
                    "merged": True,
                }
            else:
                return {
                    "success": True,
                    "pr_number": pr_number,
                    "merged": False,
                    "message": "PR created but merge failed",
                }

    except Exception as e:
        logger.error("gitea_merge_error", repo=repo, error=str(e))
        return {"success": False, "error": str(e)}


# =============================================================================
# REGISTRATION
# =============================================================================


def register(registry: MCPRegistry) -> None:
    """Register the git MCP server."""
    server = MCPServer(
        id="git",
        name="Git",
        description="Git version control and Gitea operations",
        tools=GIT_TOOLS,
    )

    # Register handlers
    server.register_handler("clone", clone)
    server.register_handler("init", init)
    server.register_handler("status", status)
    server.register_handler("add", add)
    server.register_handler("commit", commit)
    server.register_handler("push", push)
    server.register_handler("pull", pull)
    server.register_handler("branch", branch)
    server.register_handler("checkout", checkout)
    server.register_handler("diff", diff)
    server.register_handler("log", log)
    server.register_handler("create_repo", create_repo)
    server.register_handler("merge_branch", merge_branch)

    registry.register_server(server)
