"""Code Generation Service.

Handles code generation by executing the code_generator_agent through the LLM.
This service loads the agent prompt from YAML and generates code files.

Architecture:
- Loads system prompt from registry/agents/code_generator_agent.yaml
- Uses LLMService for LLM calls
- Writes generated files to workspace
- Integrates with ProjectService for Git operations
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import structlog
import yaml

from .llm_service import LLMService

logger = structlog.get_logger()


def load_code_generator_prompt() -> str:
    """Load the code generator system prompt from YAML."""
    registry_path = os.getenv("REGISTRY_PATH", "/app/registry")
    agent_file = Path(registry_path) / "agents" / "code_generator_agent.yaml"

    if agent_file.exists():
        try:
            with open(agent_file) as f:
                data = yaml.safe_load(f)
                if data and "system_prompt" in data:
                    return data["system_prompt"]
        except Exception as e:
            logger.warning("Failed to load code_generator agent YAML", error=str(e))

    # Fallback prompt
    return """You are an expert software developer. Generate complete, working code.

Respond with valid JSON:
{
    "files": [
        {"path": "relative/path/to/file.ext", "content": "file content"}
    ],
    "summary": "Brief description"
}"""


class CodeService:
    """Service for generating and modifying code.

    Uses the code_generator_agent prompt from YAML and executes
    code generation through the LLM.
    """

    def __init__(self, workspace_path: str | Path | None = None):
        """Initialize the code service.

        Args:
            workspace_path: Base path for project workspaces
        """
        self._workspace_path = Path(workspace_path) if workspace_path else None
        self._llm_service = LLMService()
        self._system_prompt = load_code_generator_prompt()

    def get_workspace_path(self) -> Path:
        """Get the workspace path from config."""
        if self._workspace_path is None:
            from flask import current_app
            self._workspace_path = Path(
                current_app.config.get("WORKSPACE_PATH", "/app/workspace")
            )
        return self._workspace_path

    def generate_app(
        self,
        plan_id: str,
        app_info: dict[str, Any],
        auto_commit: bool = True,
        auto_build: bool = False,
        auto_run: bool = False,
        created_by: str | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Generate application files using LLM.

        Args:
            plan_id: Unique plan/project ID
            app_info: App configuration with app_type, name, description, features
            auto_commit: Commit files to Git and push to Gitea
            auto_build: Build Docker image after generation
            auto_run: Run the Docker container after building
            created_by: User who created the project (Keycloak sub ID)
            username: Keycloak username for Gitea account
            email: User's email for Gitea account

        Returns:
            Result dict with success status, files, repo_url, app_url, etc.
        """
        from .project import project_service
        from .builder import builder_service

        workspace = self.get_workspace_path() / plan_id
        workspace.mkdir(parents=True, exist_ok=True)

        app_type = app_info.get("app_type", "generic")
        app_name = app_info.get("name", "my-app")
        description = app_info.get("description", "")
        features = app_info.get("features", [])

        logger.info(
            "generating_app",
            plan_id=plan_id,
            app_type=app_type,
            app_name=app_name,
        )

        # Generate code using LLM
        try:
            files_created = self._generate_code(
                workspace, app_type, app_name, description, features
            )
        except Exception as e:
            logger.error("code_generation_failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

        result = {
            "success": True,
            "workspace": str(workspace),
            "files_created": files_created,
            "app_info": app_info,
        }

        # Create project with Gitea repo
        if auto_commit:
            try:
                project = project_service.create_project(
                    name=app_name,
                    description=description,
                    created_by=created_by,
                    plan_id=plan_id,
                    username=username,
                    email=email,
                )

                # Commit and push to Gitea
                if project_service.commit_and_push(
                    project,
                    message=f"Initial commit: {app_name}",
                    author=created_by,
                ):
                    result["repo_url"] = project.repo_url
                    result["project"] = project.to_dict()

            except Exception as e:
                logger.error("git_commit_failed", error=str(e))
                result["git_error"] = str(e)

        # Build Docker image
        if auto_build:
            try:
                build_result = builder_service.build_project(plan_id)
                result["build"] = build_result

                # Run container if requested
                if auto_run and build_result.get("success"):
                    run_result = builder_service.run_project(plan_id)
                    result["run"] = run_result
                    if run_result.get("success"):
                        result["app_url"] = run_result.get("url")

            except Exception as e:
                logger.error("build_failed", error=str(e))
                result["build_error"] = str(e)

        logger.info(
            "app_generated",
            plan_id=plan_id,
            files_count=len(files_created),
            has_repo=bool(result.get("repo_url")),
        )

        return result

    def _generate_code(
        self,
        workspace: Path,
        app_type: str,
        app_name: str,
        description: str,
        features: list[str],
    ) -> list[str]:
        """Generate code using LLM."""
        # Build the generation prompt
        features_str = "\n".join(f"- {f}" for f in features) if features else "Basic functionality"

        user_prompt = f"""Create a complete {app_type} application called "{app_name}".

Description: {description}

Features:
{features_str}

Requirements:
- Generate a complete, working application
- Use modern best practices
- Make it visually appealing with CSS
- Include all necessary files to run the app
- For web apps, use React with Vite OR plain HTML/CSS/JS
- For Python apps, use Flask

Generate ALL the files needed."""

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("calling_llm_for_code_generation", app_type=app_type)
        response = self._llm_service.chat(messages, call_name="code_generator_agent")
        logger.debug("code_gen_response_length", length=len(response))

        # Parse the response
        data = self._llm_service.parse_json_response(response)
        files = data.get("files", [])

        if not files:
            raise ValueError("No files generated by LLM")

        # Write files to workspace
        files_created = []
        for file_info in files:
            file_path = file_info.get("path", "")
            content = file_info.get("content", "")

            if not file_path or not content:
                continue

            # Create directories if needed
            full_path = workspace / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            full_path.write_text(content)
            files_created.append(file_path)
            logger.debug("file_written", path=file_path)

        logger.info("files_generated", count=len(files_created))
        return files_created

    def update_app(
        self,
        project_id: str,
        update_description: str,
        app_info: dict[str, Any] | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing project with new changes.

        Creates a feature branch, applies updates, and returns preview info.

        Args:
            project_id: ID of the project to update
            update_description: Description of the changes to make
            app_info: Optional app info from router analysis
            username: Keycloak username for Git commits
            email: User's email for Git commits

        Returns:
            Result dict with branch, files_modified, preview_url, etc.
        """
        from .project import project_service
        from .builder import builder_service

        logger.info(
            "updating_app",
            project_id=project_id,
            update_description=update_description[:100],
        )

        # Get the project
        project = project_service.get_project_for_plan(project_id)
        if not project:
            return {
                "success": False,
                "error": f"Project not found: {project_id}",
            }

        # Get the workspace path
        workspace = self.get_workspace_path() / project_id

        if not workspace.exists():
            return {
                "success": False,
                "error": f"Project workspace not found: {workspace}",
            }

        # Generate timestamp for branch name
        timestamp = int(time.time())
        branch_name = f"feature/update-{timestamp}"

        try:
            # Read existing files to understand the codebase
            existing_files = self._read_project_files(workspace)

            if not existing_files:
                return {
                    "success": False,
                    "error": "No existing files found in project",
                }

            # Generate update code using LLM
            updated_files = self._generate_update_code(
                existing_files,
                update_description,
                app_info,
            )

            if not updated_files:
                return {
                    "success": False,
                    "error": "No updates generated by LLM",
                }

            # Write updated files
            files_modified = []
            for file_info in updated_files:
                file_path = file_info.get("path", "")
                content = file_info.get("content", "")

                if not file_path or not content:
                    continue

                full_path = workspace / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                files_modified.append(file_path)

            logger.info(
                "update_files_written",
                project_id=project_id,
                files_count=len(files_modified),
            )

            # Create feature branch and commit
            commit_result = project_service.commit_to_branch(
                project,
                branch=branch_name,
                message=f"feat: {update_description[:50]}",
                author=username,
            )

            if not commit_result.get("success"):
                return {
                    "success": False,
                    "error": f"Failed to commit: {commit_result.get('error')}",
                    "files_modified": files_modified,
                }

            # Build preview image
            preview_url = None
            try:
                build_result = builder_service.build_project(
                    project_id,
                    tag_suffix="-preview",
                )
                if build_result.get("success"):
                    # Run preview container on a different port
                    run_result = builder_service.run_project(
                        project_id,
                        container_suffix="-preview",
                        port_range=(9050, 9100),
                    )
                    if run_result.get("success"):
                        preview_url = run_result.get("url")
            except Exception as e:
                logger.warning("preview_build_failed", error=str(e))

            return {
                "success": True,
                "project_id": project.id,
                "project_name": project.name,
                "branch": branch_name,
                "files_modified": files_modified,
                "preview_url": preview_url,
            }

        except Exception as e:
            logger.error("update_app_failed", error=str(e), project_id=project_id)
            return {
                "success": False,
                "error": str(e),
            }

    def _read_project_files(self, workspace: Path) -> list[dict[str, str]]:
        """Read all relevant files from a project workspace."""
        files = []
        ignore_patterns = {
            "__pycache__", "node_modules", ".git", ".venv", "venv",
            "dist", "build", ".next", ".cache", "*.pyc", "*.pyo"
        }
        max_file_size = 100 * 1024  # 100KB max per file

        for file_path in workspace.rglob("*"):
            if file_path.is_file():
                # Check if path contains ignored pattern
                path_str = str(file_path)
                if any(pattern in path_str for pattern in ignore_patterns):
                    continue

                # Check file size
                if file_path.stat().st_size > max_file_size:
                    continue

                # Try to read as text
                try:
                    relative_path = file_path.relative_to(workspace)
                    content = file_path.read_text(encoding="utf-8")
                    files.append({
                        "path": str(relative_path),
                        "content": content,
                    })
                except (UnicodeDecodeError, Exception):
                    continue

        return files

    def _generate_update_code(
        self,
        existing_files: list[dict[str, str]],
        update_description: str,
        app_info: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Generate updated code using LLM."""
        # Build context from existing files
        files_context = ""
        for f in existing_files[:20]:  # Limit to 20 files for context
            files_context += f"\n--- {f['path']} ---\n{f['content'][:5000]}\n"

        update_prompt = f"""You are updating an existing application. Analyze the current codebase and apply the requested changes.

EXISTING FILES:
{files_context}

REQUESTED CHANGES:
{update_description}

{'Additional context: ' + str(app_info) if app_info else ''}

IMPORTANT:
- Only modify files that need to change
- Keep the existing code style and patterns
- Make minimal changes to achieve the goal
- Return COMPLETE file contents (not patches/diffs)

Respond with valid JSON containing the updated files:
{{
    "files": [
        {{
            "path": "path/to/file.ext",
            "content": "complete updated file content"
        }}
    ],
    "summary": "Brief description of changes made"
}}"""

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": update_prompt},
        ]

        logger.info("calling_llm_for_update", description=update_description[:100])
        try:
            response = self._llm_service.chat(messages, call_name="update_code_agent")
            logger.info("llm_update_response_received", response_length=len(response) if response else 0)
        except Exception as e:
            logger.error("llm_update_call_failed", error=str(e))
            return []

        # Parse the response
        data = self._llm_service.parse_json_response(response)
        files = data.get("files", [])
        logger.info("update_code_parsed", files_count=len(files), has_summary=bool(data.get("summary")))
        return files


# Global singleton for backward compatibility
code_service = CodeService()
