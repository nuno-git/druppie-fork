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
    CreatePullRequestParams,
    DeleteFileParams,
    ListDirParams,
    MakeDesignParams,
    MergePullRequestParams,
    ReadFileParams,
    RunGitParams,
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
    DockerComposeDownParams,
    DockerComposeUpParams,
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
    "MakeDesignParams",
    "BatchWriteFilesParams",
    "ListDirParams",
    "DeleteFileParams",
    "RunGitParams",
    "CreatePullRequestParams",
    "MergePullRequestParams",
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
    "DockerComposeUpParams",
    "DockerComposeDownParams",
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
