"""Evaluations API routes — barrel module.

Combines benchmark, test execution, and analytics sub-routers.
All URL paths are unchanged.
"""

from fastapi import APIRouter

from .evaluations_analytics import router as analytics_router
from .evaluations_benchmarks import router as benchmarks_router
from .evaluations_tests import router as tests_router

router = APIRouter()
router.include_router(benchmarks_router)
router.include_router(tests_router)
router.include_router(analytics_router)
