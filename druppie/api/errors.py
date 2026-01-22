"""Standardized API error handling for Druppie platform.

Provides consistent error response models and exception handlers.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class ErrorCode(str, Enum):
    """Standard error codes for API responses."""

    # Authentication errors (1xxx)
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_INSUFFICIENT_PERMISSIONS"

    # Authorization errors (2xxx)
    FORBIDDEN = "FORBIDDEN"
    ROLE_REQUIRED = "ROLE_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"

    # Validation errors (3xxx)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_FIELD = "MISSING_FIELD"

    # Resource errors (4xxx)
    NOT_FOUND = "NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"

    # Conflict errors (5xxx)
    CONFLICT = "CONFLICT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    APPROVAL_ALREADY_PROCESSED = "APPROVAL_ALREADY_PROCESSED"
    SESSION_ALREADY_COMPLETED = "SESSION_ALREADY_COMPLETED"

    # External service errors (6xxx)
    LLM_ERROR = "LLM_ERROR"
    MCP_ERROR = "MCP_ERROR"
    GITEA_ERROR = "GITEA_ERROR"
    KEYCLOAK_ERROR = "KEYCLOAK_ERROR"

    # Server errors (7xxx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    TIMEOUT = "TIMEOUT"

    # Business logic errors (8xxx)
    EXECUTION_FAILED = "EXECUTION_FAILED"
    WORKSPACE_NOT_INITIALIZED = "WORKSPACE_NOT_INITIALIZED"
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"


class ErrorResponse(BaseModel):
    """Standardized error response model."""

    error_code: ErrorCode = Field(
        ...,
        description="Machine-readable error code",
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
    )
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional error details",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Error timestamp",
    )
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Request ID for tracking",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error_code": "NOT_FOUND",
                "message": "Session not found",
                "details": {"session_id": "abc-123"},
                "timestamp": "2024-01-22T10:30:00Z",
                "request_id": "req-456",
            }
        }


class APIError(Exception):
    """Base API exception with standardized response."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[dict[str, Any]] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)

    def to_response(self, request_id: Optional[str] = None) -> ErrorResponse:
        """Convert to error response model."""
        return ErrorResponse(
            error_code=self.error_code,
            message=self.message,
            details=self.details,
            request_id=request_id or str(uuid.uuid4()),
        )


# Convenience exception classes
class NotFoundError(APIError):
    """Resource not found error."""

    def __init__(
        self,
        resource: str,
        resource_id: str,
        message: Optional[str] = None,
    ):
        error_codes = {
            "session": ErrorCode.SESSION_NOT_FOUND,
            "project": ErrorCode.PROJECT_NOT_FOUND,
            "workspace": ErrorCode.WORKSPACE_NOT_FOUND,
            "approval": ErrorCode.APPROVAL_NOT_FOUND,
            "agent": ErrorCode.AGENT_NOT_FOUND,
        }
        error_code = error_codes.get(resource.lower(), ErrorCode.NOT_FOUND)
        super().__init__(
            error_code=error_code,
            message=message or f"{resource.capitalize()} not found: {resource_id}",
            status_code=404,
            details={f"{resource}_id": resource_id},
        )


class AuthenticationError(APIError):
    """Authentication error."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            error_code=ErrorCode.AUTH_REQUIRED,
            message=message,
            status_code=401,
        )


class AuthorizationError(APIError):
    """Authorization error."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        required_roles: Optional[list[str]] = None,
    ):
        super().__init__(
            error_code=ErrorCode.ROLE_REQUIRED,
            message=message,
            status_code=403,
            details={"required_roles": required_roles} if required_roles else None,
        )


class ValidationError(APIError):
    """Validation error."""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=422,
            details={"field": field} if field else None,
        )


class ConflictError(APIError):
    """Conflict error."""

    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.CONFLICT):
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=409,
        )


class ExternalServiceError(APIError):
    """External service error."""

    def __init__(
        self,
        service: str,
        message: str,
        original_error: Optional[str] = None,
    ):
        error_codes = {
            "llm": ErrorCode.LLM_ERROR,
            "mcp": ErrorCode.MCP_ERROR,
            "gitea": ErrorCode.GITEA_ERROR,
            "keycloak": ErrorCode.KEYCLOAK_ERROR,
        }
        super().__init__(
            error_code=error_codes.get(service.lower(), ErrorCode.INTERNAL_ERROR),
            message=message,
            status_code=502,
            details={"service": service, "original_error": original_error},
        )


# FastAPI exception handlers
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    logger.error(
        "api_error",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        request_id=request_id,
        path=request.url.path,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(request_id).model_dump(mode="json"),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle standard HTTPException with consistent format."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Map HTTP status codes to error codes
    status_to_code = {
        400: ErrorCode.INVALID_INPUT,
        401: ErrorCode.AUTH_REQUIRED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
        422: ErrorCode.VALIDATION_ERROR,
        500: ErrorCode.INTERNAL_ERROR,
        502: ErrorCode.MCP_ERROR,
        504: ErrorCode.TIMEOUT,
    }

    error_code = status_to_code.get(exc.status_code, ErrorCode.INTERNAL_ERROR)

    response = ErrorResponse(
        error_code=error_code,
        message=str(exc.detail),
        request_id=request_id,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(mode="json"),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    logger.exception(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=request_id,
        path=request.url.path,
    )

    response = ErrorResponse(
        error_code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred",
        request_id=request_id,
    )

    return JSONResponse(
        status_code=500,
        content=response.model_dump(mode="json"),
    )


def register_exception_handlers(app):
    """Register exception handlers with FastAPI app.

    Usage:
        from druppie.api.errors import register_exception_handlers
        app = FastAPI()
        register_exception_handlers(app)
    """
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
