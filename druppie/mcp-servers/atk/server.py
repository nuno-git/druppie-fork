"""ATK CLI MCP Server.

Wraps Microsoft's ATK CLI (M365 Agents Toolkit) for programmatic
creation, deployment, and management of declarative agents in
Copilot Studio / M365 Copilot.

This is a STANDALONE service:
- scaffold: Creates new declarative agent projects
- provision: Deploys agents to M365 environments
- share: Shares agents with specific users
- update/uninstall: Lifecycle management
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("atk-mcp")

# Initialize FastMCP server
mcp = FastMCP("ATK MCP Server")

# Configuration
ATK_PROJECTS_DIR = Path(os.getenv("ATK_PROJECTS_DIR", "/atk-projects"))
M365_TENANT_ID = os.getenv("M365_TENANT_ID", "")
M365_CLIENT_ID = os.getenv("M365_CLIENT_ID", "")
M365_CLIENT_SECRET = os.getenv("M365_CLIENT_SECRET", "")


def _run_atk(args: list[str], cwd: str | None = None, timeout: int = 120) -> dict:
    """Run an ATK CLI command and return structured result.

    Args:
        args: ATK CLI arguments (e.g., ["new", "-c", "declarative-agent"])
        cwd: Working directory for the command
        timeout: Command timeout in seconds

    Returns:
        Dict with success, stdout, stderr
    """
    cmd = ["atk", *args]
    env = {
        **os.environ,
        "M365_TENANT_ID": M365_TENANT_ID,
        "M365_CLIENT_ID": M365_CLIENT_ID,
        "M365_CLIENT_SECRET": M365_CLIENT_SECRET,
    }

    logger.info("Running ATK command: %s (cwd: %s)", " ".join(cmd), cwd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )

        if result.returncode != 0:
            logger.warning("ATK command failed: %s", result.stderr)
            return {
                "success": False,
                "error": result.stderr or f"ATK command exited with code {result.returncode}",
                "stdout": result.stdout,
            }

        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"ATK command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "ATK CLI not found. Is @microsoft/m365agentstoolkit-cli installed?"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def scaffold_agent(
    name: str,
    description: str | None = None,
) -> dict:
    """Scaffold a new declarative agent project using ATK CLI.

    Creates a new ATK project directory with the declarative-agent template.

    Args:
        name: Agent name (used as project directory name)
        description: Optional agent description

    Returns:
        Dict with success, project_path, message
    """
    try:
        ATK_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

        project_path = ATK_PROJECTS_DIR / name
        if project_path.exists():
            return {
                "success": False,
                "error": f"Project directory already exists: {name}",
            }

        result = _run_atk(
            ["new", "-c", "declarative-agent", "-i", "false", "-n", name],
            cwd=str(ATK_PROJECTS_DIR),
            timeout=60,
        )

        if not result["success"]:
            return result

        # Update description in manifest if provided
        if description and project_path.exists():
            manifest_path = project_path / "appPackage" / "declarativeAgent.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                manifest["description"] = description
                manifest_path.write_text(json.dumps(manifest, indent=2))

        return {
            "success": True,
            "project_path": str(project_path),
            "name": name,
            "message": f"Scaffolded declarative agent '{name}' at {project_path}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def configure_manifest(
    name: str,
    instructions: str | None = None,
    description: str | None = None,
    capabilities: list[str] | None = None,
) -> dict:
    """Read or update the declarativeAgent.json manifest for a project.

    Args:
        name: Agent project name (directory name in /atk-projects/)
        instructions: New instructions text for the agent
        description: New description for the agent
        capabilities: List of capability names to enable

    Returns:
        Dict with success, manifest content
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        manifest_path = project_path / "appPackage" / "declarativeAgent.json"

        if not manifest_path.exists():
            return {
                "success": False,
                "error": f"Manifest not found for project '{name}'. Run scaffold_agent first.",
            }

        manifest = json.loads(manifest_path.read_text())

        # Apply updates if any
        updated = False
        if instructions is not None:
            manifest["instructions"] = instructions
            updated = True
        if description is not None:
            manifest["description"] = description
            updated = True
        if capabilities is not None:
            manifest["capabilities"] = [{"name": c} for c in capabilities]
            updated = True

        if updated:
            manifest_path.write_text(json.dumps(manifest, indent=2))

        return {
            "success": True,
            "manifest": manifest,
            "updated": updated,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def provision(
    name: str,
    environment: str = "dev",
) -> dict:
    """Provision (deploy) an ATK agent to a M365 environment.

    This registers the agent package with M365 Copilot.

    Args:
        name: Agent project name
        environment: Target environment (dev, staging, production)

    Returns:
        Dict with success, provisioning output
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        if not project_path.exists():
            return {
                "success": False,
                "error": f"Project not found: {name}",
            }

        result = _run_atk(
            ["provision", "--env", environment, "-i", "false"],
            cwd=str(project_path),
            timeout=180,
        )

        if result["success"]:
            result["name"] = name
            result["environment"] = environment
            result["message"] = f"Provisioned '{name}' to {environment} environment"

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def share_agent(
    name: str,
    emails: list[str],
    scope: str = "users",
) -> dict:
    """Share a provisioned agent with specific users.

    Args:
        name: Agent project name
        emails: List of email addresses to share with
        scope: Sharing scope (users, organization)

    Returns:
        Dict with success, sharing details
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        if not project_path.exists():
            return {
                "success": False,
                "error": f"Project not found: {name}",
            }

        results = []
        for email in emails:
            result = _run_atk(
                ["share", "--scope", scope, "--email", email, "-i", "false"],
                cwd=str(project_path),
                timeout=60,
            )
            results.append({
                "email": email,
                "success": result["success"],
                "error": result.get("error"),
            })

        all_success = all(r["success"] for r in results)
        return {
            "success": all_success,
            "name": name,
            "shares": results,
            "message": f"Shared '{name}' with {len(emails)} user(s)" if all_success else "Some shares failed",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def update_manifest(
    name: str,
) -> dict:
    """Push manifest updates to a provisioned agent.

    Args:
        name: Agent project name

    Returns:
        Dict with success, update output
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        if not project_path.exists():
            return {
                "success": False,
                "error": f"Project not found: {name}",
            }

        result = _run_atk(
            ["update"],
            cwd=str(project_path),
            timeout=120,
        )

        if result["success"]:
            result["name"] = name
            result["message"] = f"Updated manifest for '{name}'"

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def uninstall_agent(
    name: str,
) -> dict:
    """Uninstall an agent from M365 Copilot.

    Args:
        name: Agent project name

    Returns:
        Dict with success, uninstall output
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        if not project_path.exists():
            return {
                "success": False,
                "error": f"Project not found: {name}",
            }

        result = _run_atk(
            ["uninstall"],
            cwd=str(project_path),
            timeout=120,
        )

        if result["success"]:
            result["name"] = name
            result["message"] = f"Uninstalled agent '{name}' from M365 Copilot"

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_agent_status(
    name: str,
) -> dict:
    """Get status of an ATK agent project.

    Reads the project directory and environment files to determine current state.

    Args:
        name: Agent project name

    Returns:
        Dict with success, project info, environment state
    """
    try:
        project_path = ATK_PROJECTS_DIR / name
        if not project_path.exists():
            return {
                "success": False,
                "error": f"Project not found: {name}",
            }

        # Read manifest
        manifest_path = project_path / "appPackage" / "declarativeAgent.json"
        manifest = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())

        # Check for env files (created by provision)
        env_files = list(project_path.glob("env/.env.*"))
        environments = [f.name.replace(".env.", "") for f in env_files]

        # Read app ID from env if available
        m365_app_id = None
        for env_file in env_files:
            content = env_file.read_text()
            for line in content.split("\n"):
                if line.startswith("M365_APP_ID="):
                    m365_app_id = line.split("=", 1)[1].strip()
                    break

        return {
            "success": True,
            "name": name,
            "project_path": str(project_path),
            "manifest": manifest,
            "environments": environments,
            "m365_app_id": m365_app_id,
            "has_manifest": manifest is not None,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_agents() -> dict:
    """List all ATK agent projects.

    Returns:
        Dict with success, list of agent projects
    """
    try:
        ATK_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

        agents = []
        for item in sorted(ATK_PROJECTS_DIR.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                manifest_path = item / "appPackage" / "declarativeAgent.json"
                manifest = None
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text())

                agents.append({
                    "name": item.name,
                    "path": str(item),
                    "has_manifest": manifest is not None,
                    "description": manifest.get("description", "") if manifest else "",
                })

        return {
            "success": True,
            "agents": agents,
            "count": len(agents),
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
        return JSONResponse({"status": "healthy", "service": "atk-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9010"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
