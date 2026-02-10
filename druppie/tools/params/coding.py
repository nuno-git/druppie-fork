"""Parameter models for coding MCP tools.

These models define the parameters for file operations and git commands.
Hidden parameters (session_id, repo_name, repo_owner) are injected at runtime
and not included here - they're handled by the injection system.
"""

from pydantic import BaseModel, Field


class ReadFileParams(BaseModel):
    """Read a file from the workspace."""

    path: str = Field(description="File path relative to workspace root")


class WriteFileParams(BaseModel):
    """Write a file to the workspace (auto-commits)."""

    path: str = Field(description="File path relative to workspace root")
    content: str = Field(description="File content to write")


class BatchWriteFilesParams(BaseModel):
    """Write multiple files at once. Use commit_and_push to commit."""

    files: dict[str, str] = Field(description="Map of file path to content")


class ListDirParams(BaseModel):
    """List directory contents."""

    path: str = Field(description="Directory path relative to workspace root (use '.' for root)")


class DeleteFileParams(BaseModel):
    """Delete a file from the workspace."""

    path: str = Field(description="File path to delete")


class CommitAndPushParams(BaseModel):
    """Commit and push changes to Gitea."""

    message: str = Field(description="Git commit message")


class CreateBranchParams(BaseModel):
    """Create and switch to a git branch."""

    branch_name: str = Field(description="Name of the branch to create or switch to (e.g., feature/add-login)")


class MergeToMainParams(BaseModel):
    """Merge feature branch to main (direct git merge, no PR)."""

    # No parameters needed - merges current branch to main
    pass


class CreatePullRequestParams(BaseModel):
    """Create a pull request from current branch to main on Gitea."""

    title: str = Field(description="PR title")
    body: str | None = Field(default=None, description="PR description")


class MergePullRequestParams(BaseModel):
    """Merge a pull request on Gitea and delete the source branch."""

    pr_number: int = Field(description="PR number to merge")
    delete_branch: bool = Field(default=True, description="Delete source branch after merge")


class GetGitStatusParams(BaseModel):
    """Get git status for workspace."""

    # No parameters needed
    pass
