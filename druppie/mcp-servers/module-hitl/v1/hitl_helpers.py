"""HITL helper functions — persistence and JSON utilities.

No FastMCP dependency. Pure business logic extracted from server.py.
"""

import json
import logging
import os

import httpx

logger = logging.getLogger("hitl-mcp")

BACKEND_URL = os.getenv("BACKEND_URL", "http://druppie-backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-key")


def safe_json_parse(data: bytes | str, context: str = "unknown") -> dict | None:
    """Safely parse JSON data with validation and logging.

    Args:
        data: JSON bytes or string to parse
        context: Description of where this data came from (for logging)

    Returns:
        Parsed dict or None if parsing failed
    """
    if data is None:
        logger.warning("Received None data in %s", context)
        return None

    try:
        # Handle bytes
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        parsed = json.loads(data)

        # Validate it's a dict (expected format for all our responses)
        if not isinstance(parsed, dict):
            logger.warning(
                "JSON parsed but not a dict in %s: got %s",
                context,
                type(parsed).__name__,
            )
            return None

        return parsed

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(
            "JSON parse error in %s: %s (data preview: %s)",
            context,
            str(e),
            str(data)[:100] if data else "empty",
        )
        return None
    except Exception as e:
        logger.error(
            "Unexpected error parsing JSON in %s: %s",
            context,
            str(e),
        )
        return None


async def persist_question(
    question_id: str,
    session_id: str,
    question: str,
    question_type: str = "text",
    choices: list[str] | None = None,
    agent_id: str = "unknown",
) -> bool:
    """Persist a HITL question to the backend database.

    This ensures questions survive service restarts and can be
    retrieved by the frontend even if the user refreshes the page.

    Returns True if successful, False otherwise.
    """
    try:
        logger.debug(
            "Persisting question %s for session %s (type: %s)",
            question_id,
            session_id,
            question_type,
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_URL}/api/questions/internal/create",
                json={
                    "question_id": question_id,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "question": question,
                    "question_type": question_type,
                    "choices": choices,
                },
                headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                timeout=10.0,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Successfully persisted question %s for session %s",
                    question_id,
                    session_id,
                )
                return True
            else:
                logger.error(
                    "Failed to persist question %s: HTTP %d - %s",
                    question_id,
                    response.status_code,
                    response.text[:200] if response.text else "no body",
                )
                return False
    except httpx.TimeoutException:
        logger.error(
            "Timeout persisting question %s for session %s",
            question_id,
            session_id,
        )
        return False
    except Exception as e:
        logger.error(
            "Error persisting question %s to backend: %s",
            question_id,
            str(e),
        )
        return False
