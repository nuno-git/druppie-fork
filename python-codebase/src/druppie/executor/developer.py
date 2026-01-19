"""Developer executor for code-related actions."""

import json
import os
import re
import structlog
from typing import Any
from pathlib import Path

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from .base import Executor, ExecutorResult
from druppie.core.models import Step

logger = structlog.get_logger()


CODE_GENERATION_PROMPT = """You are an expert software developer. Generate clean, working code based on the requirements.

## Project Context:
{context}

## Task:
{task}

## Requirements:
{requirements}

## Instructions:
1. Generate complete, working code
2. Include all necessary imports
3. Add brief docstrings/comments where helpful
4. Follow best practices for the language

## Response Format:
Respond ONLY with valid JSON:
{{
    "files": [
        {{
            "path": "relative/path/to/file.py",
            "content": "full file content here"
        }}
    ]
}}

Generate all necessary files for a complete, working implementation."""


class DeveloperExecutor(Executor):
    """Executes developer actions like creating code and repositories.

    Handles actions:
    - create_repo: Create a new project/repository structure
    - create_file: Create a new file with content
    - modify_code: Modify existing code
    - delete_file: Delete a file
    - write_code: Generate and write code using LLM
    """

    HANDLED_ACTIONS = {
        "create_repo",
        "create_file",
        "modify_code",
        "delete_file",
        "write_code",
    }

    def __init__(self, base_path: str | None = None):
        """Initialize the DeveloperExecutor.

        Args:
            base_path: Base directory for creating files (default: current dir)
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.llm: BaseChatModel | None = None
        self.logger = logger.bind(executor="developer")

    def set_llm(self, llm: BaseChatModel | None) -> None:
        """Set the LLM for code generation."""
        self.llm = llm

    def can_handle(self, action: str) -> bool:
        """Check if this executor handles the action."""
        return action in self.HANDLED_ACTIONS

    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute a developer action."""
        context = context or {}
        action = step.action

        try:
            if action == "create_repo":
                return await self._create_repo(step, context)
            elif action == "create_file":
                return await self._create_file(step, context)
            elif action == "write_code":
                return await self._write_code(step, context)
            elif action == "modify_code":
                return await self._modify_code(step, context)
            elif action == "delete_file":
                return await self._delete_file(step, context)
            else:
                return ExecutorResult(
                    success=False,
                    error=f"Unknown action: {action}",
                )
        except Exception as e:
            self.logger.error("developer_action_failed", action=action, error=str(e))
            return ExecutorResult(success=False, error=str(e))

    async def _create_repo(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create a new project/repository structure."""
        params = step.params
        name = params.get("name", "new-project")
        language = params.get("language", "python")
        structure = params.get("structure", [])

        # Use workspace_path from context (set by TaskManager)
        workspace_path = context.get("workspace_path")
        if workspace_path:
            project_path = Path(workspace_path) / name
        else:
            project_path = context.get("project_path") or self.base_path / name
            project_path = Path(project_path)

        self.logger.info("creating_repo", name=name, path=str(project_path))

        # Create base directory
        project_path.mkdir(parents=True, exist_ok=True)

        # Create default structure based on language
        if language == "python":
            default_structure = [
                "src/",
                "tests/",
                "README.md",
                "pyproject.toml",
            ]
        elif language == "go":
            default_structure = [
                "cmd/",
                "internal/",
                "pkg/",
                "README.md",
                "go.mod",
            ]
        else:
            default_structure = [
                "src/",
                "README.md",
            ]

        # Use provided structure or default
        dirs_and_files = structure if structure else default_structure

        created = []
        for item in dirs_and_files:
            item_path = project_path / item
            if item.endswith("/"):
                item_path.mkdir(parents=True, exist_ok=True)
                created.append(f"dir: {item}")
            else:
                item_path.parent.mkdir(parents=True, exist_ok=True)
                if not item_path.exists():
                    item_path.touch()
                    created.append(f"file: {item}")

        return ExecutorResult(
            success=True,
            result={
                "project_path": str(project_path),
                "created": created,
            },
            output_messages=[f"Created project at {project_path}"],
        )

    async def _create_file(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create a new file with content."""
        params = step.params
        file_path = params.get("path") or params.get("file_path")
        content = params.get("content", "")

        if not file_path:
            return ExecutorResult(
                success=False,
                error="No file path provided",
            )

        # Resolve relative paths against project path
        if not os.path.isabs(file_path):
            project_path = context.get("project_path", self.base_path)
            file_path = Path(project_path) / file_path

        file_path = Path(file_path)

        self.logger.info("creating_file", path=str(file_path))

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        file_path.write_text(content)

        return ExecutorResult(
            success=True,
            result={"path": str(file_path), "size": len(content)},
            output_messages=[f"Created file: {file_path}"],
        )

    async def _write_code(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Generate and write code using LLM.

        Uses the LLM to generate complete, working code based on:
        - The task description in step params
        - Context from previous steps (architecture, user stories, etc.)
        """
        params = step.params

        # If path and content are provided, just create the file
        file_path = params.get("path") or params.get("file_path")
        content = params.get("content")
        if file_path and content:
            return await self._create_file(step, context)

        # Need to generate code using LLM
        if not self.llm:
            return ExecutorResult(
                success=False,
                error="LLM not available for code generation",
            )

        # Get project path - prioritize workspace, then step results, then context
        project_path = None

        # First, check workspace_path from context (set by TaskManager)
        workspace_path = context.get("workspace_path")

        # Then check step results for project_path from create_repo step
        for key, value in context.items():
            if key.startswith("step_") and key.endswith("_result") and value:
                if isinstance(value, dict) and value.get("project_path"):
                    project_path = value["project_path"]
                    break

        # If no project_path from step results, use workspace_path
        if not project_path:
            if workspace_path:
                project_path = workspace_path
            else:
                project_path = context.get("project_path") or self.base_path

        project_path = Path(project_path)

        # Build context from previous step results (format: step_{id}_result)
        context_parts = []
        for key, value in context.items():
            if key.startswith("step_") and key.endswith("_result") and value:
                context_parts.append(f"{key}: {json.dumps(value, indent=2)}")

        # Get task description
        task = params.get("description") or params.get("task") or "Implement the code"
        requirements = params.get("requirements") or params.get("specs") or []
        if isinstance(requirements, list):
            requirements = "\n".join(f"- {r}" for r in requirements)

        # Get language/framework hints
        language = params.get("language", "python")
        framework = params.get("framework", "")

        prompt_context = "\n".join(context_parts) if context_parts else "New project"
        if framework:
            prompt_context += f"\nFramework: {framework}"
        prompt_context += f"\nLanguage: {language}"
        prompt_context += f"\nProject path: {project_path}"

        prompt = CODE_GENERATION_PROMPT.format(
            context=prompt_context,
            task=task,
            requirements=requirements or "See task description",
        )

        self.logger.info("generating_code", task=task[:100], project_path=str(project_path))

        try:
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=f"Generate code for: {task}"),
            ]

            response = await self.llm.ainvoke(messages)
            response_text = response.content

            # Parse JSON response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                return ExecutorResult(
                    success=False,
                    error="Failed to parse code generation response",
                )

            data = json.loads(json_match.group())
            files = data.get("files", [])

            if not files:
                return ExecutorResult(
                    success=False,
                    error="No files generated",
                )

            # Write all generated files
            created_files = []
            for file_info in files:
                fp = file_info.get("path", "")
                fc = file_info.get("content", "")

                if not fp:
                    continue

                # Resolve relative path
                full_path = project_path / fp
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(fc)

                created_files.append(str(fp))
                self.logger.info("created_file", path=str(full_path))

            return ExecutorResult(
                success=True,
                result={
                    "project_path": str(project_path),
                    "files_created": created_files,
                    "file_count": len(created_files),
                },
                output_messages=[f"Generated {len(created_files)} files: {', '.join(created_files)}"],
            )

        except json.JSONDecodeError as e:
            self.logger.error("code_generation_json_error", error=str(e))
            return ExecutorResult(
                success=False,
                error=f"Failed to parse generated code: {e}",
            )
        except Exception as e:
            self.logger.error("code_generation_failed", error=str(e))
            return ExecutorResult(
                success=False,
                error=f"Code generation failed: {e}",
            )

    async def _modify_code(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Modify existing code."""
        params = step.params
        file_path = params.get("path") or params.get("file_path")
        modifications = params.get("modifications", [])
        new_content = params.get("content")

        if not file_path:
            return ExecutorResult(
                success=False,
                error="No file path provided",
            )

        # Resolve relative paths
        if not os.path.isabs(file_path):
            project_path = context.get("project_path", self.base_path)
            file_path = Path(project_path) / file_path

        file_path = Path(file_path)

        if not file_path.exists():
            return ExecutorResult(
                success=False,
                error=f"File not found: {file_path}",
            )

        self.logger.info("modifying_file", path=str(file_path))

        if new_content is not None:
            # Replace entire content
            file_path.write_text(new_content)
        elif modifications:
            # Apply modifications (simple find/replace)
            content = file_path.read_text()
            for mod in modifications:
                old_text = mod.get("old", "")
                new_text = mod.get("new", "")
                if old_text:
                    content = content.replace(old_text, new_text)
            file_path.write_text(content)

        return ExecutorResult(
            success=True,
            result={"path": str(file_path), "modified": True},
            output_messages=[f"Modified file: {file_path}"],
        )

    async def _delete_file(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Delete a file."""
        params = step.params
        file_path = params.get("path") or params.get("file_path")

        if not file_path:
            return ExecutorResult(
                success=False,
                error="No file path provided",
            )

        # Resolve relative paths
        if not os.path.isabs(file_path):
            project_path = context.get("project_path", self.base_path)
            file_path = Path(project_path) / file_path

        file_path = Path(file_path)

        if not file_path.exists():
            return ExecutorResult(
                success=True,
                result={"path": str(file_path), "already_deleted": True},
            )

        self.logger.info("deleting_file", path=str(file_path))

        file_path.unlink()

        return ExecutorResult(
            success=True,
            result={"path": str(file_path), "deleted": True},
            output_messages=[f"Deleted file: {file_path}"],
        )
