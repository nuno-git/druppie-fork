"""
TDD Configuration Module

This module provides configuration for Test-Driven Development workflows.
Uses Pydantic Settings for validation and environment variable support.
"""
from typing import Dict, Optional
from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog

logger = structlog.get_logger()


class TestFramework(str, Enum):
    """Supported test frameworks."""
    PYTEST = "pytest"
    VITEST = "vitest"
    JEST = "jest"
    PLAYWRIGHT = "playwright"
    GOTEST = "gotest"
    UNKNOWN = "unknown"


class ProjectType(str, Enum):
    """Supported project types."""
    PYTHON = "python"
    FRONTEND = "frontend"
    NODEJS = "nodejs"
    GO = "go"
    UNKNOWN = "unknown"


class FrameworkSettings(BaseSettings):
    """Framework-specific configuration."""
    
    model_config = SettingsConfigDict(env_prefix="TDD_FRAMEWORK_")
    
    # Framework detection
    default_framework: TestFramework = Field(
        default=TestFramework.UNKNOWN,
        description="Default test framework to use when auto-detection fails",
    )
    
    # Framework-specific settings
    pytest_command: str = Field(
        default="pytest",
        description="Pytest command to run tests",
    )
    pytest_coverage_command: str = Field(
        default="pytest --cov --cov-report=json",
        description="Pytest command with coverage",
    )
    pytest_min_version: str = Field(
        default="7.4.0",
        description="Minimum pytest version required",
    )
    
    vitest_command: str = Field(
        default="npm test -- --run",
        description="Vitest command to run tests",
    )
    vitest_coverage_command: str = Field(
        default="npm test -- --run --coverage",
        description="Vitest command with coverage",
    )
    vitest_min_version: str = Field(
        default="1.1.0",
        description="Minimum vitest version required",
    )
    
    jest_command: str = Field(
        default="npm test",
        description="Jest command to run tests",
    )
    jest_coverage_command: str = Field(
        default="npm test -- --coverage",
        description="Jest command with coverage",
    )
    jest_min_version: str = Field(
        default="29.0.0",
        description="Minimum jest version required",
    )
    
    playwright_command: str = Field(
        default="npx playwright test",
        description="Playwright command to run tests",
    )
    playwright_min_version: str = Field(
        default="1.40.0",
        description="Minimum playwright version required",
    )
    
    gotest_command: str = Field(
        default="go test ./...",
        description="Go test command",
    )
    gotest_coverage_command: str = Field(
        default="go test ./... -coverprofile=coverage.out && go tool cover -func=coverage.out",
        description="Go test command with coverage",
    )
    gotest_min_version: str = Field(
        default="1.21",
        description="Minimum Go version required",
    )


class CoverageSettings(BaseSettings):
    """Coverage configuration."""
    
    model_config = SettingsConfigDict(env_prefix="TDD_COVERAGE_")
    
    # Global coverage thresholds
    default_threshold: float = Field(
        default=80.0,
        description="Default coverage threshold percentage",
        ge=0.0,
        le=100.0,
    )
    
    # Project-type specific thresholds
    python_threshold: float = Field(
        default=80.0,
        description="Python project coverage threshold",
        ge=0.0,
        le=100.0,
    )
    frontend_threshold: float = Field(
        default=70.0,
        description="Frontend project coverage threshold",
        ge=0.0,
        le=100.0,
    )
    nodejs_threshold: float = Field(
        default=75.0,
        description="Node.js project coverage threshold",
        ge=0.0,
        le=100.0,
    )
    go_threshold: float = Field(
        default=85.0,
        description="Go project coverage threshold",
        ge=0.0,
        le=100.0,
    )
    
    # Coverage requirements
    require_coverage: bool = Field(
        default=True,
        description="Whether coverage reports are required",
    )
    fail_on_low_coverage: bool = Field(
        default=True,
        description="Whether to fail workflow on low coverage",
    )
    
    # Coverage report settings
    coverage_report_dir: str = Field(
        default="coverage",
        description="Directory for coverage reports",
    )
    coverage_report_format: str = Field(
        default="json",
        description="Coverage report format (json, html, lcov)",
    )


class RetrySettings(BaseSettings):
    """Retry configuration for TDD workflows."""
    
    model_config = SettingsConfigDict(env_prefix="TDD_RETRY_")
    
    # Retry limits
    max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts",
        ge=0,
        le=10,
    )
    
    # Retry delays (seconds)
    initial_delay: int = Field(
        default=5,
        description="Initial delay before first retry (seconds)",
        ge=0,
    )
    max_delay: int = Field(
        default=30,
        description="Maximum delay between retries (seconds)",
        ge=0,
    )
    backoff_factor: float = Field(
        default=2.0,
        description="Exponential backoff factor",
        ge=1.0,
    )
    
    # Retry conditions
    retry_on_test_failure: bool = Field(
        default=True,
        description="Retry when tests fail",
    )
    retry_on_low_coverage: bool = Field(
        default=False,
        description="Retry when coverage is below threshold",
    )
    retry_on_timeout: bool = Field(
        default=True,
        description="Retry when test execution times out",
    )


class WorkflowSettings(BaseSettings):
    """TDD workflow configuration."""
    
    model_config = SettingsConfigDict(env_prefix="TDD_WORKFLOW_")
    
    # Workflow modes
    enable_tdd: bool = Field(
        default=True,
        description="Enable TDD workflows globally",
    )
    
    # Step configuration
    max_test_timeout: int = Field(
        default=300,
        description="Maximum test execution time (seconds)",
        ge=10,
        le=3600,
    )
    
    # Validation settings
    strict_validation: bool = Field(
        default=True,
        description="Enable strict validation of test results",
    )
    require_test_output: bool = Field(
        default=True,
        description="Require test output for validation",
    )
    
    # Feedback settings
    include_feedback: bool = Field(
        default=True,
        description="Include detailed feedback in retry steps",
    )
    feedback_max_length: int = Field(
        default=2000,
        description="Maximum length of feedback messages",
        ge=100,
        le=10000,
    )


class TDDSettings(BaseSettings):
    """Main TDD settings container aggregating all configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Sub-settings
    framework: FrameworkSettings = Field(default_factory=FrameworkSettings)
    coverage: CoverageSettings = Field(default_factory=CoverageSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    
    # Project type detection
    project_type: ProjectType = Field(
        default=ProjectType.UNKNOWN,
        description="Project type for framework-specific settings",
    )
    
    @field_validator("project_type", mode="before")
    @classmethod
    def parse_project_type(cls, v):
        if isinstance(v, str):
            try:
                return ProjectType(v.lower())
            except ValueError:
                return ProjectType.UNKNOWN
        return v
    
    def get_coverage_threshold(self, project_type: Optional[ProjectType] = None) -> float:
        """Get coverage threshold for project type."""
        pt = project_type or self.project_type
        if pt == ProjectType.PYTHON:
            return self.coverage.python_threshold
        elif pt == ProjectType.FRONTEND:
            return self.coverage.frontend_threshold
        elif pt == ProjectType.NODEJS:
            return self.coverage.nodejs_threshold
        elif pt == ProjectType.GO:
            return self.coverage.go_threshold
        else:
            return self.coverage.default_threshold
    
    def get_test_command(self, framework: TestFramework, with_coverage: bool = False) -> str:
        """Get test command for framework."""
        if framework == TestFramework.PYTEST:
            return self.framework.pytest_coverage_command if with_coverage else self.framework.pytest_command
        elif framework == TestFramework.VITEST:
            return self.framework.vitest_coverage_command if with_coverage else self.framework.vitest_command
        elif framework == TestFramework.JEST:
            return self.framework.jest_coverage_command if with_coverage else self.framework.jest_command
        elif framework == TestFramework.PLAYWRIGHT:
            return self.framework.playwright_command  # Playwright doesn't have built-in coverage
        elif framework == TestFramework.GOTEST:
            return self.framework.gotest_coverage_command if with_coverage else self.framework.gotest_command
        else:
            return ""
    
    def get_min_version(self, framework: TestFramework) -> str:
        """Get minimum version for framework."""
        if framework == TestFramework.PYTEST:
            return self.framework.pytest_min_version
        elif framework == TestFramework.VITEST:
            return self.framework.vitest_min_version
        elif framework == TestFramework.JEST:
            return self.framework.jest_min_version
        elif framework == TestFramework.PLAYWRIGHT:
            return self.framework.playwright_min_version
        elif framework == TestFramework.GOTEST:
            return self.framework.gotest_min_version
        else:
            return ""
    
    def log_config(self):
        """Log TDD configuration (masking sensitive values)."""
        logger.info(
            "tdd_config_loaded",
            enable_tdd=self.workflow.enable_tdd,
            project_type=self.project_type.value,
            max_retries=self.retry.max_retries,
            default_coverage_threshold=self.coverage.default_threshold,
            require_coverage=self.coverage.require_coverage,
            strict_validation=self.workflow.strict_validation,
        )


# Global settings instance
_settings_instance: Optional[TDDSettings] = None


def get_tdd_settings() -> TDDSettings:
    """Get TDD settings instance.
    
    Call this function to access TDD configuration throughout the application.
    
    Example:
        from druppie.config.tdd_config import get_tdd_settings
        
        settings = get_tdd_settings()
        max_retries = settings.retry.max_retries
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = TDDSettings()
        _settings_instance.log_config()
    return _settings_instance


# Convenience functions for common settings access patterns
def get_max_retries() -> int:
    """Get maximum retry attempts."""
    return get_tdd_settings().retry.max_retries


def get_coverage_threshold(project_type: Optional[ProjectType] = None) -> float:
    """Get coverage threshold for project type."""
    return get_tdd_settings().get_coverage_threshold(project_type)


def is_tdd_enabled() -> bool:
    """Check if TDD workflows are enabled."""
    return get_tdd_settings().workflow.enable_tdd


def get_test_command(framework: TestFramework, with_coverage: bool = False) -> str:
    """Get test command for framework."""
    return get_tdd_settings().get_test_command(framework, with_coverage)


# Export enums for use in other modules
__all__ = [
    "TestFramework",
    "ProjectType",
    "TDDSettings",
    "get_tdd_settings",
    "get_max_retries",
    "get_coverage_threshold",
    "is_tdd_enabled",
    "get_test_command",
]