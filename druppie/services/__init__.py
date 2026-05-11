"""Service layer for business logic.

Services handle business logic and coordinate repositories.
They are injected into routes via FastAPI's dependency injection.

Architecture:
    Route ──▶ Service ──▶ Repository ──▶ Database

Special services:
    - WorkflowService: Wraps MainLoop for workflow resumption
      (does not use repositories, uses execution engine instead)
"""

from .session_service import SessionService
from .approval_service import ApprovalService
from .question_service import QuestionService
from .project_service import ProjectService
from .deployment_service import DeploymentService
from .workflow_service import WorkflowService
from .skill_service import SkillService
from .revert_service import RevertService
from .github_app_service import GitHubAppService, get_github_app_service
from .evaluation_service import EvaluationService

__all__ = [
    "SessionService",
    "ApprovalService",
    "QuestionService",
    "ProjectService",
    "DeploymentService",
    "WorkflowService",
    "SkillService",
    "RevertService",
    "GitHubAppService",
    "get_github_app_service",
    "EvaluationService",
]
