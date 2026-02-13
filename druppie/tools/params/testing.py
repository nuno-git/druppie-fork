"""Parameter models for testing MCP tools.

These define the parameter types for validation. Descriptions come from
mcp_config.yaml - these models are purely for type-safe validation.

Hidden parameters (session_id, project_id, repo_name, repo_owner) are injected
at runtime and not included here - they're handled by the injection system.
"""

from pydantic import BaseModel, Field


class GetTestFrameworkParams(BaseModel):
    pass


class RunTestsParams(BaseModel):
    test_command: str | None = Field(default=None, description="Optional custom test command (default: auto-detected)")
    timeout: int | None = Field(default=None, description="Timeout in seconds (default: 300)")


class GetCoverageReportParams(BaseModel):
    framework: str | None = Field(default=None, description="Optional framework name (default: auto-detected)")


class InstallTestDependenciesParams(BaseModel):
    framework: str | None = Field(default=None, description="Optional framework name (default: auto-detected)")


class ValidateTddParams(BaseModel):
    coverage_threshold: float | None = Field(default=None, description="Minimum coverage percentage (default: 80.0)")
