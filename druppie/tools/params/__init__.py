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
    InvokeSkillParams,
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
from .archimate import (
    GetElementParams,
    GetImpactParams,
    GetStatisticsParams,
    GetViewParams,
    ListElementsParams,
    ListViewsParams,
    SearchModelParams,
)
from .registry import (
    GetAgentParams,
    GetMcpServerParams,
    GetSkillParams,
    GetToolParams,
    ListComponentsParams,
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
from .testing import (
    GetCoverageReportParams,
    GetTestFrameworkParams,
    InstallTestDependenciesParams,
    RunTestsParams,
    ValidateTddParams,
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
    # Archimate
    "GetStatisticsParams",
    "ListElementsParams",
    "GetElementParams",
    "ListViewsParams",
    "GetViewParams",
    "SearchModelParams",
    "GetImpactParams",
    # Docker
    "DockerBuildParams",
    "DockerRunParams",
    "DockerStopParams",
    "DockerLogsParams",
    "DockerRemoveParams",
    "DockerListContainersParams",
    "DockerInspectParams",
    "DockerExecCommandParams",
    # Registry
    "ListComponentsParams",
    "GetAgentParams",
    "GetSkillParams",
    "GetMcpServerParams",
    "GetToolParams",
    # Builtin
    "DoneParams",
    "HitlAskQuestionParams",
    "HitlAskMultipleChoiceQuestionParams",
    "SetIntentParams",
    "MakePlanParams",
    "CreateMessageParams",
    "InvokeSkillParams",
    # Testing
    "GetTestFrameworkParams",
    "RunTestsParams",
    "GetCoverageReportParams",
    "InstallTestDependenciesParams",
    "ValidateTddParams",
]
