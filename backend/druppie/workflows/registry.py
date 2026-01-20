"""Workflow Registry.

Loads workflow definitions from YAML files.
"""

from pathlib import Path

import structlog
import yaml

from druppie.core.models import WorkflowDefinition, WorkflowStep, WorkflowStepType

logger = structlog.get_logger()


class WorkflowRegistry:
    """Registry for workflow definitions.

    Loads workflow definitions from YAML files in the registry directory.
    """

    def __init__(self, registry_path: str | Path | None = None):
        """Initialize the WorkflowRegistry.

        Args:
            registry_path: Path to the registry directory
        """
        self.registry_path = Path(registry_path) if registry_path else None
        self._workflows: dict[str, WorkflowDefinition] = {}

    def load(self, registry_path: str | Path | None = None) -> None:
        """Load workflow definitions from YAML files."""
        path = Path(registry_path) if registry_path else self.registry_path
        if not path:
            logger.warning("No registry path configured")
            return

        workflows_path = path / "workflows"
        if not workflows_path.exists():
            logger.warning(
                "Workflows registry directory not found", path=str(workflows_path)
            )
            # Create the directory
            workflows_path.mkdir(parents=True, exist_ok=True)
            return

        self._workflows.clear()

        for file_path in workflows_path.glob("*.yaml"):
            try:
                self._load_workflow_file(file_path)
            except Exception as e:
                logger.error(
                    "Failed to load workflow", file=str(file_path), error=str(e)
                )

        logger.info("Workflow registry loaded", workflows=len(self._workflows))

    def _load_workflow_file(self, file_path: Path) -> None:
        """Load a single workflow definition file."""
        with open(file_path) as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # Handle single workflow or list of workflows
        workflows = data if isinstance(data, list) else [data]

        for wf_data in workflows:
            # Parse steps
            steps = {}
            for step_id, step_data in wf_data.get("steps", {}).items():
                # Map type string to enum
                step_type = WorkflowStepType.AGENT
                type_str = step_data.get("type", "agent")
                if type_str == "mcp":
                    step_type = WorkflowStepType.MCP
                elif type_str == "condition":
                    step_type = WorkflowStepType.CONDITION

                steps[step_id] = WorkflowStep(
                    id=step_id,
                    name=step_data.get("name", step_id),
                    type=step_type,
                    mcp_tool=step_data.get("tool"),
                    params=step_data.get("params", {}),
                    agent_id=step_data.get("agent_id"),
                    task_template=step_data.get("task"),
                    on_success=step_data.get("on_success"),
                    on_failure=step_data.get("on_failure"),
                    max_retries=step_data.get("max_retries", 3),
                )

            workflow = WorkflowDefinition(
                id=wf_data["id"],
                name=wf_data.get("name", wf_data["id"]),
                description=wf_data.get("description", ""),
                trigger_keywords=wf_data.get("trigger_keywords", []),
                required_mcps=wf_data.get("required_mcps", []),
                entry_point=wf_data.get("entry_point", ""),
                steps=steps,
            )
            self._workflows[workflow.id] = workflow

    def register_workflow(self, workflow: WorkflowDefinition) -> None:
        """Programmatically register a workflow."""
        self._workflows[workflow.id] = workflow

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> list[WorkflowDefinition]:
        """List all registered workflows."""
        return list(self._workflows.values())

    def as_dict(self) -> dict[str, WorkflowDefinition]:
        """Get all workflows as a dictionary."""
        return dict(self._workflows)

    def find_workflow_by_keywords(self, text: str) -> WorkflowDefinition | None:
        """Find a workflow that matches keywords in the text.

        Args:
            text: Text to search for keywords

        Returns:
            First matching workflow or None
        """
        text_lower = text.lower()
        for workflow in self._workflows.values():
            for keyword in workflow.trigger_keywords:
                if keyword.lower() in text_lower:
                    return workflow
        return None
