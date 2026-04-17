"""Analytics routes for test runs and assertions."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from druppie.api.deps import get_evaluation_service, require_admin
from druppie.services import EvaluationService

router = APIRouter()


@router.get("/evaluations/analytics/summary")
async def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Global analytics summary: totals, pass rate, avg duration."""
    return service.get_analytics_summary(days)


@router.get("/evaluations/analytics/trends")
async def get_analytics_trends(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Pass rate trends over time, grouped by day."""
    return service.get_analytics_trends(days)


@router.get("/evaluations/analytics/by-agent")
async def get_analytics_by_agent(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by agent."""
    return service.get_analytics_by_agent(batch_id)


@router.get("/evaluations/analytics/by-eval")
async def get_analytics_by_eval(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by eval name."""
    return service.get_analytics_by_eval(batch_id)


@router.get("/evaluations/analytics/by-tool")
async def get_analytics_by_tool(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by tool name."""
    return service.get_analytics_by_tool(batch_id)


@router.get("/evaluations/analytics/by-test")
async def get_analytics_by_test(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by test name."""
    return service.get_analytics_by_test(batch_id)


@router.get("/evaluations/analytics/batch/{batch_id}")
async def get_analytics_batch_detail(
    batch_id: str,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Detailed analytics for a single batch."""
    return service.get_analytics_batch_detail(batch_id)


@router.get("/evaluations/test-runs/{test_run_id}/assertions")
async def get_test_run_assertions(
    test_run_id: UUID,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get detailed assertion results for a test run."""
    return service.get_test_run_assertions(test_run_id)


@router.get("/evaluations/batch/{batch_id}/assertions")
async def get_batch_assertions(
    batch_id: str,
    assertion_type: str | None = Query(None),
    agent_id: str | None = Query(None),
    tool_name: str | None = Query(None),
    check_text: str | None = Query(None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get all assertion results for a batch, optionally filtered."""
    return service.get_batch_assertions(batch_id, assertion_type, agent_id, tool_name, check_text)


@router.get("/evaluations/batch/{batch_id}/filters")
async def get_batch_filters(
    batch_id: str,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get all unique filterable values for a batch."""
    return service.get_batch_filters(batch_id)
