"""Testing MCP Server.

Testing operations - run tests, get coverage, validate TDD workflow.
Uses FastMCP framework for HTTP transport.

This service integrates with workspace system:
- detect_test_framework: Auto-detects test framework in workspace
- run_tests: Runs tests and returns results
- get_coverage: Gets test coverage if available
- validate_tdd: Validates TDD workflow results
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("testing-mcp")

# Initialize FastMCP server
mcp = FastMCP("Testing MCP Server")

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))

# Import the testing module
from module import TestingModule

# Initialize testing module
testing_module = TestingModule(str(WORKSPACE_ROOT))


def get_or_create_workspace(
    session_id: str,
    project_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> tuple[str, Path]:
    """Get or create a workspace from session_id.
    
    Simplified version for testing MCP - just creates workspace path.
    
    Args:
        session_id: Session ID (required)
        project_id: Optional project ID
        user_id: Optional user ID
        workspace_id: Optional explicit workspace ID
        
    Returns:
        Tuple of (workspace_id, workspace_path)
    """
    # Derive workspace_id from session_id if not provided
    derived_workspace_id = workspace_id or f"session-{session_id}"
    
    # Auto-create workspace path
    # Path structure: /workspaces/{user_id or "default"}/{project_id or "scratch"}/{session_id}
    user_part = user_id or "default"
    project_part = project_id or "scratch"
    workspace_path = WORKSPACE_ROOT / user_part / project_part / session_id
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(
        "Using workspace %s at %s (session_id=%s)",
        derived_workspace_id,
        workspace_path,
        session_id,
    )
    
    return derived_workspace_id, workspace_path


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def get_test_framework(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Detect test framework in workspace (alias for detect_test_framework)."""
    return await detect_test_framework(
        session_id=session_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
    )

@mcp.tool()
async def detect_test_framework(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Detect test framework in workspace.
    
    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        
    Returns:
        Dict with framework details, test command, and configuration info
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            # For backward compatibility, use workspace_id directly
            workspace_path = WORKSPACE_ROOT / workspace_id
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        
        # Update testing module with current workspace
        testing_module.workspace_root = workspace_path
        
        # Get framework info
        framework_info = testing_module.get_test_framework_info()
        
        if framework_info["framework"] == "unknown":
            return {
                "success": False,
                "error": "Could not auto-detect test framework.",
                "suggestion": "Check if your project has test configuration files (pytest.ini, jest.config.js, etc.)",
            }
        
        return {
            "success": True,
            **framework_info,
        }
        
    except Exception as e:
        logger.error("Error detecting test framework: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def run_tests(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    test_command: str | None = None,
    timeout: int = 300,
) -> dict:
    """Run tests in workspace.
    
    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        test_command: Optional custom test command (default: auto-detected)
        timeout: Timeout in seconds (default: 300)
        
    Returns:
        Dict with test results, pass/fail counts, and output
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            workspace_path = WORKSPACE_ROOT / workspace_id
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        
        # Update testing module with current workspace
        testing_module.workspace_root = workspace_path
        
        # Detect framework if command not provided
        if not test_command:
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {
                    "success": False,
                    "error": "Could not auto-detect test framework. Please specify test_command.",
                }
            test_command = framework_info["test_command"]
            framework = framework_info["framework"]
        else:
            # Try to infer framework from command
            framework = "unknown"
            if "pytest" in test_command:
                framework = "pytest"
            elif "jest" in test_command or "npm test" in test_command:
                framework = "jest"
            elif "vitest" in test_command:
                framework = "vitest"
            elif "go test" in test_command:
                framework = "go"
            elif "cargo test" in test_command:
                framework = "cargo"
        
        logger.info("Running tests in workspace %s: %s", workspace_path, test_command)
        
        # Run test command
        start_time = time.time()
        try:
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.time() - start_time
            
            # Parse output
            parsed_results = testing_module.parse_test_results(
                result.stdout + "\n" + result.stderr,
                framework,
            )
            
            # Get coverage if available
            coverage = None
            if framework in ["vitest", "jest", "pytest"]:
                coverage = testing_module.parse_coverage_json(framework)
                if coverage:
                    parsed_results["coverage"] = coverage
            
            return {
                "success": True,
                "framework": framework,
                "command": test_command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "elapsed_seconds": elapsed,
                "results": parsed_results,
                "coverage": coverage,
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Test execution timed out after {timeout} seconds",
                "framework": framework,
                "command": test_command,
            }
            
    except Exception as e:
        logger.error("Error running tests: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_coverage_report(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    framework: str | None = None,
) -> dict:
    """Get test coverage report for workspace (alias for get_coverage)."""
    return await get_coverage(
        session_id=session_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        framework=framework,
    )

@mcp.tool()
async def get_coverage(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    framework: str | None = None,
) -> dict:
    """Get test coverage for workspace.
    
    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        framework: Optional framework name (default: auto-detected)
        
    Returns:
        Dict with coverage information
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            workspace_path = WORKSPACE_ROOT / workspace_id
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        
        # Update testing module with current workspace
        testing_module.workspace_root = workspace_path
        
        # Detect framework if not provided
        if not framework:
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {
                    "success": False,
                    "error": "Could not auto-detect test framework.",
                }
            framework = framework_info["framework"]
        
        # Get coverage
        coverage = testing_module.parse_coverage_json(framework)
        
        if not coverage:
            return {
                "success": False,
                "error": f"No coverage data found for {framework}. Run tests with coverage first.",
                "framework": framework,
            }
        
        return {
            "success": True,
            "framework": framework,
            "coverage": coverage,
        }
        
    except Exception as e:
        logger.error("Error getting coverage: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def validate_tdd(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    coverage_threshold: float = 80.0,
) -> dict:
    """Validate TDD workflow results.
    
    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        coverage_threshold: Minimum coverage percentage (default: 80.0)
        
    Returns:
        Dict with validation results
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            workspace_path = WORKSPACE_ROOT / workspace_id
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        
        # Update testing module with current workspace
        testing_module.workspace_root = workspace_path
        
        # Run tests first
        test_result = await run_tests(
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
        )
        
        if not test_result.get("success"):
            return {
                "success": False,
                "error": "Failed to run tests for TDD validation",
                "test_error": test_result.get("error"),
            }
        
        # Get coverage
        framework_info = testing_module.get_test_framework_info()
        framework = framework_info["framework"]
        
        coverage = testing_module.parse_coverage_json(framework)
        coverage_percent = coverage.get("overall_percent", 0) if coverage else 0
        
        # Validate TDD workflow
        test_results = test_result.get("results", {})
        config = {"coverage_threshold": coverage_threshold}
        
        validation = testing_module.validate_tdd_workflow(test_results, config)
        
        return {
            "success": True,
            "framework": framework,
            "test_results": test_results,
            "coverage_percent": coverage_percent,
            "coverage_threshold": coverage_threshold,
            "validation": validation,
            "tdd_passed": validation["passed"],
        }
        
    except Exception as e:
        logger.error("Error validating TDD: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def install_test_dependencies(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    framework: str | None = None,
) -> dict:
    """Install missing test dependencies for workspace.
    
    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        framework: Optional framework name (default: auto-detected)
        
    Returns:
        Dict with installation results
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            workspace_path = WORKSPACE_ROOT / workspace_id
            workspace_path.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        
        # Update testing module with current workspace
        testing_module.workspace_root = workspace_path
        
        # Detect framework if not provided
        if not framework:
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {
                    "success": False,
                    "error": "Could not auto-detect test framework.",
                }
            framework = framework_info["framework"]
        
        # Check dependencies
        deps_check = testing_module._check_framework_dependencies(framework)
        missing = deps_check.get("missing", [])
        
        if not missing:
            return {
                "success": True,
                "framework": framework,
                "message": "All test dependencies are already installed.",
                "installed": deps_check.get("installed", []),
            }
        
        # Install missing dependencies
        logger.info("Installing missing dependencies for %s: %s", framework, missing)
        results = []
        
        if framework == "pytest":
            for dep in missing:
                try:
                    result = subprocess.run(
                        ["pip", "install", dep],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                    )
                    results.append({
                        "dependency": dep,
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({
                        "dependency": dep,
                        "success": False,
                        "error": str(e),
                    })
        
        elif framework in ["vitest", "jest"]:
            # Install via npm
            for dep in missing:
                try:
                    result = subprocess.run(
                        ["npm", "install", "--save-dev", dep],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                    )
                    results.append({
                        "dependency": dep,
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({
                        "dependency": dep,
                        "success": False,
                        "error": str(e),
                    })
        
        # Check installation results
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        return {
            "success": len(failed) == 0,
            "framework": framework,
            "installed": [r["dependency"] for r in successful],
            "failed": [r["dependency"] for r in failed],
            "results": results,
            "message": f"Installed {len(successful)}/{len(missing)} dependencies" if results else "No dependencies to install",
        }
        
    except Exception as e:
        logger.error("Error installing test dependencies: %s", str(e))
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
        return JSONResponse({"status": "healthy", "service": "testing-mcp"})
    
    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    
    port = int(os.getenv("MCP_PORT", "9006"))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )