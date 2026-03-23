"""Structured logging for LLM Integration Module.

Uses structlog for JSON-formatted logging with metadata.
"""

import logging
import sys
from typing import Any

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structured logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "llm-integration") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name.

    Returns:
        Configured structlog logger.
    """
    return structlog.get_logger(name)


def log_llm_request(
    logger: structlog.stdlib.BoundLogger,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    status: str,
    error: str | None = None,
) -> None:
    """Log LLM request metadata.

    Logs only metadata, never content or API keys.

    Args:
        logger: Logger instance.
        provider: Provider name.
        model: Model identifier.
        prompt_tokens: Number of prompt tokens.
        completion_tokens: Number of completion tokens.
        status: Request status (success, error, etc.).
        error: Optional error message.
    """
    log_data = {
        "event": "llm_request",
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "status": status,
    }

    if error:
        log_data["error"] = error

    logger.info("LLM request completed", **log_data)


def log_provider_failover(
    logger: structlog.stdlib.BoundLogger,
    failed_provider: str,
    next_provider: str,
    reason: str,
) -> None:
    """Log provider failover event.

    Args:
        logger: Logger instance.
        failed_provider: Provider that failed.
        next_provider: Provider being tried next.
        reason: Reason for failover.
    """
    logger.warning(
        "Provider failover triggered",
        event="provider_failover",
        failed_provider=failed_provider,
        next_provider=next_provider,
        reason=reason,
    )
