"""Coding MCP Server.

Combined file operations and git functionality for workspace sandbox.
Uses FastMCP framework for HTTP transport.
"""

import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("coding-mcp")

# Initialize FastMCP server
mcp = FastMCP("Coding MCP Server")

# =============================================================================
# SECURITY: COMMAND BLOCKLIST
# =============================================================================

# Dangerous command patterns that should never be executed
BLOCKED_COMMAND_PATTERNS = [
    # Destructive file operations
    r"rm\s+(-[rf]+\s+)*\s*/\s*$",  # rm -rf / or rm /
    r"rm\s+(-[rf]+\s+)*\s*/\*",  # rm -rf /*
    r"rm\s+(-[rf]+\s+)+\s*/",  # rm -rf /anything at root
    # Disk/filesystem operations
    r"\bmkfs\b",  # mkfs (format filesystem)
    r"\bdd\s+if=",  # dd if= (disk operations)
    r"\bfdisk\b",  # fdisk (partition management)
    r"\bparted\b",  # parted (partition management)
    # Privilege escalation
    r"\bsudo\b",  # sudo commands
    r"\bsu\s+-",  # su - (switch user)
    r"\bsu\s+root",  # su root
    # Dangerous permission changes
    r"\bchmod\s+777\b",  # chmod 777 (world-writable)
    r"\bchmod\s+-R\s+777\b",  # chmod -R 777
    r"\bchown\s+.*\s+/",  # chown on system directories
    # System modification
    r"\bshutdown\b",  # shutdown
    r"\breboot\b",  # reboot
    r"\binit\s+[0-6]",  # init runlevel changes
    r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|network)",  # Critical service disruption
    # Network attacks
    r":\(\)\s*{\s*:\|\s*:&\s*}\s*;",  # Fork bomb
    r">\s*/dev/sd[a-z]",  # Write to disk devices
    r">\s*/dev/null\s*2>&1\s*&",  # Background with hidden output (often malicious)
    # Sensitive file access
    r">\s*/etc/passwd",  # Overwrite passwd
    r">\s*/etc/shadow",  # Overwrite shadow
    r">\s*/etc/sudoers",  # Overwrite sudoers
    # Reverse shells and remote execution
    r"\bnc\s+-[elp]",  # netcat listener
    r"\bbash\s+-i\s+>&\s+/dev/tcp",  # Bash reverse shell
    r"\bcurl\s+.*\|\s*bash",  # Piping curl to bash
    r"\bwget\s+.*\|\s*bash",  # Piping wget to bash
    r"\bcurl\s+.*\|\s*sh",  # Piping curl to sh
    r"\bwget\s+.*\|\s*sh",  # Piping wget to sh
]

# Compile patterns for performance
BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMAND_PATTERNS]


def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches any blocked patterns.

    Args:
        command: The command string to check

    Returns:
        Tuple of (is_blocked, matched_pattern_description)
    """
    for i, pattern in enumerate(BLOCKED_PATTERNS_COMPILED):
        if pattern.search(command):
            return True, BLOCKED_COMMAND_PATTERNS[i]
    return False, None

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")

# In-memory workspace registry (in production, use Redis/DB)
workspaces: dict[str, dict] = {}


async def create_gitea_repo(repo_name: str, description: str) -> dict:
    """Create repository in Gitea."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{GITEA_URL}/api/v1/orgs/{GITEA_ORG}/repos",
                json={
                    "name": repo_name,
                    "description": description,
                    "private": False,
                    "auto_init": True,
                },
                headers={"Authorization": f"token {GITEA_TOKEN}"},
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
            else:
                return {"error": response.text, "status_code": response.status_code}
        except Exception as e:
            return {"error": str(e)}


def get_workspace(workspace_id: str) -> dict:
    """Get workspace by ID."""
    if workspace_id not in workspaces:
        raise ValueError(f"Workspace not found: {workspace_id}")
    return workspaces[workspace_id]


def resolve_path(path: str, workspace_path: Path) -> Path:
    """Resolve a path relative to workspace root.

    Security: blocks path traversal attempts.
    """
    p = Path(path)

    # Block absolute paths (except if under workspace)
    if p.is_absolute():
        try:
            p.relative_to(workspace_path)
            return p
        except ValueError:
            return workspace_path / p.name

    # Resolve relative path within workspace
    resolved = (workspace_path / p).resolve()

    # Security: ensure it's still under workspace root
    try:
        resolved.relative_to(workspace_path.resolve())
    except ValueError:
        raise ValueError(f"Path traversal not allowed: {path}")

    return resolved


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def register_workspace(
    workspace_id: str,
    workspace_path: str,
    project_id: str,
    branch: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Register an existing workspace (created by backend).

    This is used when the backend has already initialized the workspace
    (cloned repo, created branch, etc.) and just needs to register it
    with the MCP server so tools can access it.

    Args:
        workspace_id: Workspace ID (from backend)
        workspace_path: Absolute path to the workspace
        project_id: Project ID
        branch: Current git branch
        user_id: Optional user ID for context
        session_id: Optional session ID for context

    Returns:
        Dict with success status
    """
    # Validate the path exists
    path = Path(workspace_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"Workspace path does not exist: {workspace_path}",
        }

    # Register workspace in memory
    workspaces[workspace_id] = {
        "path": str(path),
        "project_id": project_id,
        "branch": branch,
        "user_id": user_id,
        "session_id": session_id,
    }

    return {
        "success": True,
        "workspace_id": workspace_id,
        "workspace_path": str(path),
        "message": f"Workspace registered: {workspace_id}",
    }


@mcp.tool()
async def initialize_workspace(
    user_id: str,
    session_id: str,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Initialize workspace for a conversation.

    - New project (project_id=None): Create repo on main branch
    - Existing project: Clone and create feature branch

    Note: Prefer using register_workspace if the backend has already
    set up the workspace with git operations.

    Args:
        user_id: User ID
        session_id: Session ID
        project_id: Optional existing project ID
        project_name: Optional name for new project

    Returns:
        Dict with workspace_id, workspace_path, project_id, branch
    """
    workspace_id = f"{user_id}-{session_id}"

    if project_id is None:
        # New project
        project_id = str(uuid.uuid4())
        repo_name = f"project-{project_id[:8]}"

        # Create Gitea repo
        if GITEA_TOKEN:
            await create_gitea_repo(repo_name, project_name or "New Project")
        branch = "main"
    else:
        repo_name = f"project-{project_id[:8]}"
        branch = f"session-{session_id[:8]}"

    # Create workspace directory
    workspace_path = WORKSPACE_ROOT / user_id / project_id / session_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Clone repo if Gitea is configured
    if GITEA_TOKEN:
        repo_url = f"{GITEA_URL}/{GITEA_ORG}/{repo_name}.git"
        try:
            subprocess.run(
                ["git", "clone", repo_url, str(workspace_path)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.CalledProcessError:
            # Repo might be empty, init locally
            subprocess.run(["git", "init"], cwd=workspace_path, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", repo_url],
                cwd=workspace_path,
                check=True,
            )

        # Create feature branch if not main
        if branch != "main":
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=workspace_path,
                check=True,
            )
    else:
        # No Gitea - just init local git
        subprocess.run(["git", "init"], cwd=workspace_path, check=True)

    # Register workspace
    workspaces[workspace_id] = {
        "path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
        "repo_name": repo_name,
        "user_id": user_id,
        "session_id": session_id,
    }

    return {
        "success": True,
        "workspace_id": workspace_id,
        "workspace_path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
    }


@mcp.tool()
async def read_file(workspace_id: str, path: str) -> dict:
    """Read file from workspace.

    Args:
        workspace_id: Workspace ID
        path: File path relative to workspace

    Returns:
        Dict with success, content, path, size
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        logger.info("Reading file in workspace %s: %s", workspace_id, path)

        if not file_path.exists():
            logger.debug("File not found in workspace %s: %s", workspace_id, path)
            return {"success": False, "error": f"File not found: {path}"}

        if not file_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check size limit (10MB)
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            logger.warning(
                "File too large in workspace %s: %s (%d bytes)",
                workspace_id,
                path,
                size,
            )
            return {"success": False, "error": f"File too large: {size} bytes"}

        try:
            content = file_path.read_text(encoding="utf-8")
            logger.debug(
                "Successfully read file in workspace %s: %s (%d bytes)",
                workspace_id,
                path,
                size,
            )
            return {
                "success": True,
                "content": content,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
            }
        except UnicodeDecodeError:
            logger.debug(
                "Binary file detected in workspace %s: %s",
                workspace_id,
                path,
            )
            return {
                "success": True,
                "binary": True,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
                "message": "File is binary",
            }

    except ValueError as e:
        logger.warning(
            "Path resolution error in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error reading file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool()
async def write_file(
    workspace_id: str,
    path: str,
    content: str,
    auto_commit: bool = True,
    commit_message: str | None = None,
) -> dict:
    """Write file to workspace (auto-commits to git).

    Args:
        workspace_id: Workspace ID
        path: File path relative to workspace
        content: File content
        auto_commit: Whether to auto-commit (default: True)
        commit_message: Optional commit message

    Returns:
        Dict with success, path, committed
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        logger.info(
            "Writing file in workspace %s: %s (%d bytes)",
            workspace_id,
            path,
            len(content),
        )

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_text(content, encoding="utf-8")

        logger.debug(
            "Successfully wrote file in workspace %s: %s",
            workspace_id,
            path,
        )

        result = {
            "success": True,
            "path": str(file_path.relative_to(workspace_path)),
            "size": len(content),
        }

        # Auto-commit
        if auto_commit:
            commit_result = await _do_commit_and_push(
                workspace_id,
                commit_message or f"Update {path}",
            )
            result["committed"] = commit_result.get("success", False)
            if commit_result.get("success"):
                result["commit_message"] = commit_message or f"Update {path}"

        return result

    except ValueError as e:
        logger.warning(
            "Path resolution error writing file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error writing file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_dir(
    workspace_id: str,
    path: str = ".",
    recursive: bool = False,
) -> dict:
    """List directory contents.

    Args:
        workspace_id: Workspace ID
        path: Directory path (default: ".")
        recursive: Whether to list recursively

    Returns:
        Dict with files and directories
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        dir_path = resolve_path(path, workspace_path)

        if not dir_path.exists():
            return {"success": False, "error": f"Directory not found: {path}"}

        if not dir_path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        files = []
        directories = []

        if recursive:
            for item in dir_path.rglob("*"):
                if item.name.startswith(".git"):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "directory",
                    })
        else:
            for item in dir_path.iterdir():
                if item.name.startswith(".git"):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "directory",
                    })

        return {
            "success": True,
            "path": str(dir_path.relative_to(workspace_path)) if dir_path != workspace_path else ".",
            "files": files,
            "directories": directories,
            "count": len(files) + len(directories),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def delete_file(
    workspace_id: str,
    path: str,
    auto_commit: bool = True,
) -> dict:
    """Delete file from workspace.

    Args:
        workspace_id: Workspace ID
        path: File path to delete
        auto_commit: Whether to auto-commit (default: True)

    Returns:
        Dict with success, deleted path
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        logger.info("Deleting file in workspace %s: %s", workspace_id, path)

        if not file_path.exists():
            logger.debug("File not found for deletion in workspace %s: %s", workspace_id, path)
            return {"success": False, "error": f"File not found: {path}"}

        if file_path.is_dir():
            return {"success": False, "error": f"Path is a directory: {path}"}

        file_path.unlink()

        logger.info("Successfully deleted file in workspace %s: %s", workspace_id, path)

        result = {
            "success": True,
            "deleted": str(file_path.relative_to(workspace_path)),
        }

        if auto_commit:
            commit_result = await _do_commit_and_push(workspace_id, f"Delete {path}")
            result["committed"] = commit_result.get("success", False)

        return result

    except ValueError as e:
        logger.warning(
            "Path resolution error deleting file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error deleting file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool()
async def run_command(
    workspace_id: str,
    command: str,
    timeout: int = 60,
) -> dict:
    """Execute shell command in workspace (requires approval).

    Args:
        workspace_id: Workspace ID
        command: Shell command to execute
        timeout: Timeout in seconds (default: 60)

    Returns:
        Dict with success, stdout, stderr, return_code
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = ws["path"]

        # Security: Check command against blocklist
        is_blocked, matched_pattern = is_command_blocked(command)
        if is_blocked:
            logger.warning(
                "Blocked dangerous command in workspace %s: %s (matched pattern: %s)",
                workspace_id,
                command,
                matched_pattern,
            )
            return {
                "success": False,
                "error": "Command blocked for security reasons",
                "blocked": True,
                "reason": "This command matches a dangerous pattern and cannot be executed",
            }

        logger.info(
            "Executing command in workspace %s: %s",
            workspace_id,
            command[:200] + "..." if len(command) > 200 else command,
        )

        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        logger.info(
            "Command completed in workspace %s with return code %d",
            workspace_id,
            result.returncode,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "cwd": workspace_path,
        }

    except subprocess.TimeoutExpired:
        logger.warning(
            "Command timed out after %ds in workspace %s: %s",
            timeout,
            workspace_id,
            command[:100],
        )
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        logger.error(
            "Command execution failed in workspace %s: %s",
            workspace_id,
            str(e),
        )
        return {"success": False, "error": str(e)}


def _detect_test_framework(workspace_path: Path) -> tuple[str | None, str | None]:
    """Detect test framework from project files.

    Returns:
        Tuple of (framework_name, test_command)
    """
    # Check for Node.js/npm project
    package_json = workspace_path / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                # Check for common test frameworks
                test_script = scripts["test"]
                if "jest" in test_script:
                    return ("jest", "npm test")
                elif "mocha" in test_script:
                    return ("mocha", "npm test")
                elif "vitest" in test_script:
                    return ("vitest", "npm test")
                elif "ava" in test_script:
                    return ("ava", "npm test")
                else:
                    return ("npm", "npm test")
        except (json.JSONDecodeError, KeyError):
            pass

    # Check for Python pytest
    pytest_ini = workspace_path / "pytest.ini"
    pyproject_toml = workspace_path / "pyproject.toml"
    setup_py = workspace_path / "setup.py"

    # Check for test files
    has_pytest_files = list(workspace_path.glob("test_*.py")) or list(workspace_path.glob("**/test_*.py"))
    has_tests_dir = (workspace_path / "tests").exists()

    if pytest_ini.exists() or has_pytest_files or has_tests_dir:
        return ("pytest", "pytest -v")

    # Check pyproject.toml for pytest config
    if pyproject_toml.exists():
        try:
            content = pyproject_toml.read_text()
            if "[tool.pytest" in content:
                return ("pytest", "pytest -v")
        except Exception:
            pass

    # Check for Go tests
    go_test_files = list(workspace_path.glob("*_test.go")) or list(workspace_path.glob("**/*_test.go"))
    go_mod = workspace_path / "go.mod"
    if go_test_files or go_mod.exists():
        return ("go", "go test -v ./...")

    # Check for Rust tests
    cargo_toml = workspace_path / "Cargo.toml"
    if cargo_toml.exists():
        return ("cargo", "cargo test")

    # Check for Ruby/RSpec
    gemfile = workspace_path / "Gemfile"
    spec_dir = workspace_path / "spec"
    if spec_dir.exists():
        return ("rspec", "bundle exec rspec")
    elif gemfile.exists():
        try:
            content = gemfile.read_text()
            if "rspec" in content.lower():
                return ("rspec", "bundle exec rspec")
            elif "minitest" in content.lower():
                return ("minitest", "bundle exec rake test")
        except Exception:
            pass

    # Check for Java/Maven
    pom_xml = workspace_path / "pom.xml"
    if pom_xml.exists():
        return ("maven", "mvn test")

    # Check for Java/Gradle
    build_gradle = workspace_path / "build.gradle"
    build_gradle_kts = workspace_path / "build.gradle.kts"
    if build_gradle.exists() or build_gradle_kts.exists():
        return ("gradle", "./gradlew test")

    return (None, None)


def _parse_test_output(stdout: str, stderr: str, framework: str) -> dict:
    """Parse test output to extract pass/fail counts.

    Returns:
        Dict with total, passed, failed, skipped, failed_tests
    """
    result = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failed_tests": [],
    }

    combined = stdout + "\n" + stderr

    if framework == "pytest":
        # pytest output: "5 passed, 2 failed, 1 skipped in 1.23s"
        match = re.search(
            r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?",
            combined,
        )
        if match:
            result["passed"] = int(match.group(1))
            result["failed"] = int(match.group(2)) if match.group(2) else 0
            result["skipped"] = int(match.group(3)) if match.group(3) else 0
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Extract failed test names
        failed_matches = re.findall(r"FAILED\s+([\w:]+)", combined)
        result["failed_tests"] = failed_matches

    elif framework in ("jest", "vitest"):
        # Jest/Vitest: "Tests: 2 failed, 5 passed, 7 total"
        match = re.search(
            r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total",
            combined,
        )
        if match:
            result["failed"] = int(match.group(1)) if match.group(1) else 0
            result["skipped"] = int(match.group(2)) if match.group(2) else 0
            result["passed"] = int(match.group(3)) if match.group(3) else 0
            result["total"] = int(match.group(4))

        # Extract failed test names
        failed_matches = re.findall(r"FAIL\s+(.+)", combined)
        result["failed_tests"] = failed_matches

    elif framework == "mocha":
        # Mocha: "5 passing (1s)\n2 failing"
        passing = re.search(r"(\d+)\s+passing", combined)
        failing = re.search(r"(\d+)\s+failing", combined)
        pending = re.search(r"(\d+)\s+pending", combined)

        if passing:
            result["passed"] = int(passing.group(1))
        if failing:
            result["failed"] = int(failing.group(1))
        if pending:
            result["skipped"] = int(pending.group(1))
        result["total"] = result["passed"] + result["failed"] + result["skipped"]

    elif framework == "go":
        # Go test: "ok  \tpackage\t0.123s" or "FAIL\tpackage\t0.123s"
        # Also: "--- FAIL: TestName"
        ok_count = len(re.findall(r"^ok\s+", combined, re.MULTILINE))
        fail_count = len(re.findall(r"^FAIL\s+", combined, re.MULTILINE))
        skip_count = len(re.findall(r"^SKIP\s+", combined, re.MULTILINE))

        # Try to get individual test counts
        pass_match = re.search(r"PASS", combined)
        individual_fails = re.findall(r"--- FAIL:\s+(\w+)", combined)

        result["passed"] = ok_count if ok_count else (1 if pass_match else 0)
        result["failed"] = len(individual_fails) if individual_fails else fail_count
        result["skipped"] = skip_count
        result["total"] = result["passed"] + result["failed"] + result["skipped"]
        result["failed_tests"] = individual_fails

    elif framework == "cargo":
        # Rust/Cargo: "test result: ok. 5 passed; 0 failed; 0 ignored"
        match = re.search(
            r"(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+ignored",
            combined,
        )
        if match:
            result["passed"] = int(match.group(1))
            result["failed"] = int(match.group(2))
            result["skipped"] = int(match.group(3))
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Extract failed test names
        failed_matches = re.findall(r"---- (\S+) stdout ----", combined)
        result["failed_tests"] = failed_matches

    elif framework == "rspec":
        # RSpec: "10 examples, 2 failures, 1 pending"
        match = re.search(
            r"(\d+)\s+examples?,\s*(\d+)\s+failures?(?:,\s*(\d+)\s+pending)?",
            combined,
        )
        if match:
            result["total"] = int(match.group(1))
            result["failed"] = int(match.group(2))
            result["skipped"] = int(match.group(3)) if match.group(3) else 0
            result["passed"] = result["total"] - result["failed"] - result["skipped"]

    elif framework in ("maven", "gradle"):
        # Maven/Gradle: "Tests run: 10, Failures: 2, Errors: 1, Skipped: 1"
        match = re.search(
            r"Tests\s+run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
            combined,
        )
        if match:
            result["total"] = int(match.group(1))
            result["failed"] = int(match.group(2)) + int(match.group(3))  # failures + errors
            result["skipped"] = int(match.group(4))
            result["passed"] = result["total"] - result["failed"] - result["skipped"]

    else:
        # Generic npm test or unknown - try common patterns
        # Try "X passing, Y failing" pattern
        match = re.search(r"(\d+)\s+(?:passing|passed)", combined)
        if match:
            result["passed"] = int(match.group(1))
        match = re.search(r"(\d+)\s+(?:failing|failed)", combined)
        if match:
            result["failed"] = int(match.group(1))
        match = re.search(r"(\d+)\s+(?:pending|skipped)", combined)
        if match:
            result["skipped"] = int(match.group(1))
        result["total"] = result["passed"] + result["failed"] + result["skipped"]

    return result


@mcp.tool()
async def run_tests(
    workspace_id: str,
    test_command: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run tests in the workspace and return structured results.

    If test_command is not provided, auto-detects the test framework
    and runs the appropriate command (npm test, pytest, etc.).

    Args:
        workspace_id: Workspace to run tests in
        test_command: Optional test command to run
        timeout: Timeout in seconds (default 120)

    Returns:
        {
            "success": true/false,
            "framework": "pytest",
            "command_used": "pytest -v",
            "total": 10,
            "passed": 8,
            "failed": 2,
            "skipped": 0,
            "failed_tests": ["test_foo", "test_bar"],
            "stdout": "...",
            "stderr": "...",
            "duration_seconds": 5.2
        }
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])

        # Auto-detect test framework if command not provided
        framework = None
        command = test_command

        if command is None:
            framework, command = _detect_test_framework(workspace_path)
            if command is None:
                return {
                    "success": False,
                    "error": "Could not detect test framework. Please provide test_command.",
                    "hint": "Supported frameworks: pytest, jest, mocha, vitest, go test, cargo test, rspec, maven, gradle",
                }
        else:
            # Try to determine framework from command
            if "pytest" in command:
                framework = "pytest"
            elif "jest" in command:
                framework = "jest"
            elif "vitest" in command:
                framework = "vitest"
            elif "mocha" in command:
                framework = "mocha"
            elif "go test" in command:
                framework = "go"
            elif "cargo test" in command:
                framework = "cargo"
            elif "rspec" in command:
                framework = "rspec"
            elif "mvn test" in command or "maven" in command:
                framework = "maven"
            elif "gradle" in command:
                framework = "gradle"
            elif "npm test" in command:
                # Try to detect from package.json
                framework, _ = _detect_test_framework(workspace_path)
                if framework is None:
                    framework = "npm"
            else:
                framework = "unknown"

        # Run the test command
        start_time = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_time

            # Parse test output
            parsed = _parse_test_output(result.stdout, result.stderr, framework)

            return {
                "success": result.returncode == 0,
                "framework": framework,
                "command_used": command,
                "total": parsed["total"],
                "passed": parsed["passed"],
                "failed": parsed["failed"],
                "skipped": parsed["skipped"],
                "failed_tests": parsed["failed_tests"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "duration_seconds": round(duration, 2),
            }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return {
                "success": False,
                "framework": framework,
                "command_used": command,
                "error": f"Test command timed out after {timeout} seconds",
                "duration_seconds": round(duration, 2),
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _do_commit_and_push(workspace_id: str, message: str) -> dict:
    """Internal function to commit all changes and push to Gitea.

    This is separate from the MCP tool to allow internal calls.
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]
        branch = ws["branch"]

        # Configure git user
        subprocess.run(
            ["git", "config", "user.email", "agent@druppie.local"],
            cwd=cwd,
            check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "Druppie Agent"],
            cwd=cwd,
            check=False,
        )

        # Stage all changes
        subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)

        # Check for changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        if not result.stdout.strip():
            return {"success": True, "message": "No changes to commit"}

        # Commit
        subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

        # Push (only if Gitea is configured)
        if GITEA_TOKEN:
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", branch],
                    cwd=cwd,
                    check=True,
                    timeout=60,
                )
                return {"success": True, "message": f"Committed and pushed: {message}", "pushed": True}
            except subprocess.CalledProcessError as e:
                return {"success": True, "message": f"Committed: {message}", "pushed": False, "push_error": str(e)}

        return {"success": True, "message": f"Committed: {message}", "pushed": False}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def batch_write_files(
    workspace_id: str,
    files: dict[str, str],
    commit_message: str = "Create multiple files",
) -> dict:
    """Write multiple files to workspace in a single operation with one git commit.

    This is more efficient than calling write_file multiple times when creating
    a project structure or scaffolding multiple files at once.

    Args:
        workspace_id: Workspace ID
        files: Dict mapping file paths (relative to workspace) to their contents
        commit_message: Commit message for all files (default: "Create multiple files")

    Returns:
        Dict with success, files_created list, committed status, and commit_message

    Example:
        batch_write_files(
            workspace_id="...",
            files={
                "src/index.js": "console.log('hello');",
                "src/utils.js": "export const add = (a, b) => a + b;",
                "package.json": '{"name": "myapp"}'
            },
            commit_message="Create initial project structure"
        )
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])

        files_created = []
        errors = []

        # Write all files
        for path, content in files.items():
            try:
                file_path = resolve_path(path, workspace_path)

                # Ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Write file
                file_path.write_text(content, encoding="utf-8")
                files_created.append(str(file_path.relative_to(workspace_path)))

            except Exception as e:
                errors.append({"path": path, "error": str(e)})

        # If no files were created, return error
        if not files_created:
            return {
                "success": False,
                "error": "No files were created",
                "errors": errors,
            }

        result = {
            "success": True,
            "files_created": files_created,
            "file_count": len(files_created),
        }

        # Add errors if any files failed
        if errors:
            result["errors"] = errors
            result["partial_success"] = True

        # Commit all changes with a single commit
        commit_result = await _do_commit_and_push(workspace_id, commit_message)
        result["committed"] = commit_result.get("success", False)
        if commit_result.get("success"):
            result["commit_message"] = commit_message

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def commit_and_push(workspace_id: str, message: str) -> dict:
    """Commit all changes and push to Gitea.

    Args:
        workspace_id: Workspace ID
        message: Commit message

    Returns:
        Dict with success, message
    """
    return await _do_commit_and_push(workspace_id, message)


@mcp.tool()
async def create_branch(workspace_id: str, branch_name: str) -> dict:
    """Create and checkout a new git branch.

    Args:
        workspace_id: Workspace ID
        branch_name: Name of the new branch

    Returns:
        Dict with success, branch name
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]

        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=cwd,
            check=True,
        )

        # Update workspace record
        ws["branch"] = branch_name

        return {"success": True, "branch": branch_name}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def merge_to_main(workspace_id: str) -> dict:
    """Merge current branch to main (requires approval).

    Args:
        workspace_id: Workspace ID

    Returns:
        Dict with success, merged branch
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]
        current_branch = ws["branch"]

        if current_branch == "main":
            return {"success": False, "error": "Already on main branch"}

        # Checkout main and merge
        subprocess.run(["git", "checkout", "main"], cwd=cwd, check=True)
        subprocess.run(["git", "merge", current_branch], cwd=cwd, check=True)

        # Push if Gitea is configured
        if GITEA_TOKEN:
            subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True)

        # Update workspace
        ws["branch"] = "main"

        return {"success": True, "merged": current_branch}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_git_status(workspace_id: str) -> dict:
    """Get git status for workspace.

    Args:
        workspace_id: Workspace ID

    Returns:
        Dict with branch, status, files
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]

        # Get current branch
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        branch = branch_result.stdout.strip() or ws["branch"]

        # Get status
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        # Parse status
        files = []
        for line in status_result.stdout.strip().split("\n"):
            if line:
                status = line[:2].strip()
                filename = line[3:]
                files.append({"status": status, "file": filename})

        return {
            "success": True,
            "branch": branch,
            "files": files,
            "has_changes": len(files) > 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "coding-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9001"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
