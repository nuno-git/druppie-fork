"""Parameter models for coding MCP tools.

These define the parameter types for validation. Descriptions come from
mcp_config.yaml - these models are purely for type-safe validation.

Hidden parameters (session_id, repo_name, repo_owner) are injected at runtime
and not included here - they're handled by the injection system.
"""

from pydantic import BaseModel, Field

from druppie.core.config import DEFAULT_SANDBOX_AGENT, DEFAULT_SANDBOX_TESTER_AGENT


class ReadFileParams(BaseModel):
    path: str = Field(description="File path relative to workspace root")


class WriteFileParams(BaseModel):
    path: str = Field(description="File path relative to workspace root")
    content: str = Field(description="File content to write")


class FileEntry(BaseModel):
    path: str = Field(description="File path relative to workspace root")
    content: str = Field(description="File content to write")


class BatchWriteFilesParams(BaseModel):
    files: list[FileEntry] = Field(description="List of files to write, each with path and content")


class ListDirParams(BaseModel):
    path: str = Field(description="Directory path relative to workspace root (use '.' for root)")


class DeleteFileParams(BaseModel):
    path: str = Field(description="File path to delete")


class CommitAndPushParams(BaseModel):
    message: str = Field(description="Git commit message")


class CreateBranchParams(BaseModel):
    branch_name: str = Field(description="Name of the branch to create or switch to (e.g., feature/add-login)")


class MergeToMainParams(BaseModel):
    pass


class CreatePullRequestParams(BaseModel):
    title: str = Field(description="PR title")
    body: str | None = Field(default=None, description="PR description")


class MergePullRequestParams(BaseModel):
    pr_number: int = Field(description="PR number to merge")
    delete_branch: bool = Field(default=True, description="Delete source branch after merge")


class GetGitStatusParams(BaseModel):
    pass


class ExecuteCodingTaskParams(BaseModel):
    task: str = Field(description="The coding task description for the sandbox agent")
    agent: str = Field(
        default=DEFAULT_SANDBOX_AGENT,
        description=f"Which sandbox agent to use ({DEFAULT_SANDBOX_AGENT} for coding, {DEFAULT_SANDBOX_TESTER_AGENT} for testing)",
    )
