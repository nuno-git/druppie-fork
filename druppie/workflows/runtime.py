"""Workflow runtime - execute pre-defined sequences of agents and MCP tools.

Usage:
    result = await Workflow("feature_dev").run(
        session_id="...",
        agent_run_id="...",
        inputs={"project_path": "/workspace/myapp", "feature_description": "..."},
    )
"""

import os
import re
from typing import Any

import structlog
import yaml

from druppie.agents import Agent
from druppie.core.models import WorkflowDefinition, StepType

logger = structlog.get_logger()


class WorkflowError(Exception):
    """Base exception for workflow errors."""
    pass


class WorkflowNotFoundError(WorkflowError):
    """Workflow definition not found."""
    pass


class WorkflowStepError(WorkflowError):
    """Error executing a workflow step."""
    pass


class Workflow:
    """Execute pre-defined sequences of agents and MCP tools.

    Workflows are defined in YAML and can:
    - Call agents with templated prompts
    - Call MCP tools directly
    - Use flow control (on_success, on_failure)
    - Template variables using {{ variable }} syntax
    """

    _definitions_path: str = None
    _cache: dict[str, "WorkflowDefinition"] = {}

    def __init__(self, workflow_id: str):
        """Initialize workflow by ID.

        Args:
            workflow_id: Workflow identifier (e.g., "feature_dev", "deploy")
        """
        self.id = workflow_id
        self.definition = self._load_definition(workflow_id)
        self._mcp_client = None

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to workflow definitions."""
        cls._definitions_path = path
        cls._cache.clear()

    @classmethod
    def _get_definitions_path(cls) -> str:
        """Get the path to workflow definitions."""
        if cls._definitions_path:
            return cls._definitions_path
        # Default: druppie/workflows/definitions/
        return os.path.join(os.path.dirname(__file__), "definitions")

    @classmethod
    def _load_definition(cls, workflow_id: str) -> WorkflowDefinition:
        """Load workflow definition from YAML."""
        if workflow_id in cls._cache:
            return cls._cache[workflow_id]

        path = os.path.join(cls._get_definitions_path(), f"{workflow_id}.yaml")

        if not os.path.exists(path):
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found at {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        definition = WorkflowDefinition(**data)
        cls._cache[workflow_id] = definition

        logger.debug("workflow_definition_loaded", workflow_id=workflow_id)
        return definition

    @classmethod
    def list_workflows(cls) -> list[str]:
        """List available workflow IDs."""
        path = cls._get_definitions_path()
        if not os.path.exists(path):
            return []
        return [
            f.replace(".yaml", "").replace(".yml", "")
            for f in os.listdir(path)
            if f.endswith((".yaml", ".yml"))
        ]

    @property
    def mcp_client(self):
        """Get MCP client (lazy loaded)."""
        if self._mcp_client is None:
            from druppie.api.deps import get_db
            from druppie.core.mcp_client import get_mcp_client
            db = next(get_db())
            self._mcp_client = get_mcp_client(db)
        return self._mcp_client

    async def run(
        self,
        session_id: str,
        agent_run_id: str,
        inputs: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """Run the workflow with given inputs.

        Args:
            session_id: Session ID
            agent_run_id: Agent run ID for tracking
            inputs: Input variables for the workflow (used in templates)

        Returns:
            Dict with results from all steps and final context
        """
        inputs = inputs or {}
        context = {**inputs}
        self._session_id = session_id
        self._agent_run_id = agent_run_id
        results = []

        # Validate required inputs
        for required_input in self.definition.inputs:
            if required_input not in inputs:
                raise WorkflowError(f"Missing required input: {required_input}")

        logger.info(
            "workflow_run_start",
            workflow_id=self.id,
            inputs=list(inputs.keys()),
        )

        # Start from entry point
        current_step_id = self.definition.entry_point
        max_steps = 50  # Safety limit

        for step_num in range(max_steps):
            if not current_step_id:
                break

            step_data = self.definition.steps.get(current_step_id)
            if not step_data:
                raise WorkflowStepError(f"Step not found: {current_step_id}")

            logger.info(
                "workflow_step_start",
                workflow_id=self.id,
                step_id=current_step_id,
                step_num=step_num + 1,
            )

            try:
                result = await self._execute_step(step_data, context)
                results.append({
                    "step_id": current_step_id,
                    "success": True,
                    "result": result,
                })

                # Store result in context for next steps
                context[f"step_{current_step_id}"] = result

                # Determine next step
                current_step_id = step_data.get("on_success")

            except Exception as e:
                logger.error(
                    "workflow_step_error",
                    workflow_id=self.id,
                    step_id=current_step_id,
                    error=str(e),
                )
                results.append({
                    "step_id": current_step_id,
                    "success": False,
                    "error": str(e),
                })

                # Check for failure handler
                failure_step = step_data.get("on_failure")
                if failure_step:
                    current_step_id = failure_step
                else:
                    raise WorkflowStepError(
                        f"Step '{current_step_id}' failed: {e}"
                    ) from e

        logger.info(
            "workflow_run_complete",
            workflow_id=self.id,
            steps_executed=len(results),
        )

        return {
            "workflow_id": self.id,
            "success": all(r.get("success", False) for r in results),
            "results": results,
            "context": context,
        }

    async def _execute_step(
        self, step_data: dict[str, Any], context: dict[str, Any]
    ) -> Any:
        """Execute a single workflow step."""
        step_type = step_data.get("type", "agent")

        if step_type == "agent":
            return await self._execute_agent_step(step_data, context)
        elif step_type == "mcp":
            return await self._execute_mcp_step(step_data, context)
        else:
            raise WorkflowStepError(f"Unknown step type: {step_type}")

    async def _execute_agent_step(
        self, step_data: dict[str, Any], context: dict[str, Any]
    ) -> Any:
        """Execute an agent step."""
        agent_id = step_data.get("agent_id")
        if not agent_id:
            raise WorkflowStepError("Agent step missing 'agent_id'")

        prompt_template = step_data.get("prompt", "")
        prompt = self._render_template(prompt_template, context)

        agent = Agent(agent_id)
        return await agent.run(
            prompt,
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            context=context,
        )

    async def _execute_mcp_step(
        self, step_data: dict[str, Any], context: dict[str, Any]
    ) -> Any:
        """Execute an MCP tool step."""
        tool = step_data.get("tool")
        if not tool:
            raise WorkflowStepError("MCP step missing 'tool'")

        # Render inputs with templates
        inputs_template = step_data.get("inputs", {})
        inputs = {}
        for key, value in inputs_template.items():
            if isinstance(value, str):
                inputs[key] = self._render_template(value, context)
            else:
                inputs[key] = value

        # Parse tool name (format: server:tool_name)
        if ":" in tool:
            server, tool_name = tool.split(":", 1)
        else:
            server = "coding"
            tool_name = tool

        # Call via MCP client
        return await self.mcp_client.call_tool(
            server, tool_name, inputs,
            session_id=self._session_id,
            agent_run_id=self._agent_run_id,
            agent_id="workflow",  # Workflow-level MCP calls
        )

    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        """Render a template string with context variables.

        Supports {{ variable }} syntax.
        """
        def replace_var(match):
            var_name = match.group(1).strip()
            # Support nested access like step_create_branch.result
            parts = var_name.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = getattr(value, part, "")
            return str(value) if value else ""

        return re.sub(r"\{\{\s*(.+?)\s*\}\}", replace_var, template)

    def __repr__(self) -> str:
        return f"Workflow({self.id!r})"
