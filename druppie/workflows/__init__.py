"""Workflow module - execute pre-defined sequences of agents and MCP tools.

Usage:
    from druppie.workflows import Workflow

    result = await Workflow("feature_dev").run({
        "project_path": "/workspace/myapp",
        "feature_description": "Add user authentication",
        "branch_name": "feature/auth"
    })
"""

from druppie.workflows.runtime import Workflow, WorkflowError, WorkflowNotFoundError

__all__ = [
    "Workflow",
    "WorkflowError",
    "WorkflowNotFoundError",
]
