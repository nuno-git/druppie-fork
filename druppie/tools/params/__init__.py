"""Pydantic parameter models for all tools.

Each tool has a corresponding Pydantic model that:
1. Defines the parameters with proper types
2. Provides descriptions via Field()
3. Auto-generates JSON Schema for LLM function calling
4. Validates arguments at runtime

Usage:
    from druppie.tools.params import WriteFileParams

    # Validate arguments
    params = WriteFileParams.model_validate({"path": "test.txt", "content": "hello"})

    # Get JSON Schema for LLM
    schema = WriteFileParams.model_json_schema()
"""

from .builtin import (
    CreateMessageParams,
    DoneParams,
    HitlAskMultipleChoiceQuestionParams,
    HitlAskQuestionParams,
    MakePlanParams,
    SetIntentParams,
)
from .coding import (
    BatchWriteFilesParams,
    CommitAndPushParams,
    CreateBranchParams,
    CreatePullRequestParams,
    DeleteFileParams,
    GetGitStatusParams,
    ListDirParams,
    MergePullRequestParams,
    MergeToMainParams,
    ReadFileParams,
    WriteFileParams,
)
from .docker import (
    DockerBuildParams,
    DockerExecCommandParams,
    DockerInspectParams,
    DockerListContainersParams,
    DockerLogsParams,
    DockerRemoveParams,
    DockerRunParams,
    DockerStopParams,
)

__all__ = [
    # Coding
    "ReadFileParams",
    "WriteFileParams",
    "BatchWriteFilesParams",
    "ListDirParams",
    "DeleteFileParams",
    "CommitAndPushParams",
    "CreateBranchParams",
    "MergeToMainParams",
    "CreatePullRequestParams",
    "MergePullRequestParams",
    "GetGitStatusParams",
    # Docker
    "DockerBuildParams",
    "DockerRunParams",
    "DockerStopParams",
    "DockerLogsParams",
    "DockerRemoveParams",
    "DockerListContainersParams",
    "DockerInspectParams",
    "DockerExecCommandParams",
    # Builtin
    "DoneParams",
    "HitlAskQuestionParams",
    "HitlAskMultipleChoiceQuestionParams",
    "SetIntentParams",
    "MakePlanParams",
    "CreateMessageParams",
]
