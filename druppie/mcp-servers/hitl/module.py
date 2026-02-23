"""HITL (Human-in-the-Loop) MCP Server - Business Logic Module.

Contains all business logic for agent-to-human interaction.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
import redis

logger = logging.getLogger("hitl-mcp")


class HITLModule:
    """Business logic module for HITL operations."""

    def __init__(self, redis_url, backend_url, internal_api_key, request_timeout):
        self.redis_client = redis.from_url(redis_url)
        self.backend_url = backend_url
        self.internal_api_key = internal_api_key
        self.request_timeout = request_timeout

    def safe_json_parse(self, data: bytes | str, context: str = "unknown") -> dict | None:
        """Safely parse JSON data with validation and logging."""
        if data is None:
            logger.warning("Received None data in %s", context)
            return None

        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            parsed = json.loads(data)

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
        self,
        question_id: str,
        session_id: str,
        question: str,
        question_type: str = "text",
        choices: list[str] | None = None,
        agent_id: str = "unknown",
    ) -> bool:
        """Persist a HITL question to backend database."""
        try:
            logger.debug(
                "Persisting question %s for session %s (type: %s)",
                question_id,
                session_id,
                question_type,
            )
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.backend_url}/api/questions/internal/create",
                    json={
                        "question_id": question_id,
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "question": question,
                        "question_type": question_type,
                        "choices": choices,
                    },
                    headers={"X-Internal-API-Key": self.internal_api_key},
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

    async def ask_question(
        self,
        session_id: str,
        question: str,
        context: str | None = None,
        agent_id: str = "unknown",
    ) -> dict:
        """Ask user a free-form text question."""
        request_id = str(uuid.uuid4())

        logger.info(
            "ask_question: session=%s, request_id=%s, agent=%s, question=%s",
            session_id,
            request_id,
            agent_id,
            question[:100] + "..." if len(question) > 100 else question,
        )

        await self.persist_question(
            question_id=request_id,
            session_id=session_id,
            question=question,
            question_type="text",
            agent_id=agent_id,
        )

        self.redis_client.publish(
            f"hitl:{session_id}",
            json.dumps({
                "type": "question",
                "request_id": request_id,
                "question": question,
                "input_type": "text",
                "context": context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        logger.debug("Published question %s to Redis channel hitl:%s", request_id, session_id)

        response = self.redis_client.blpop(
            f"hitl:response:{request_id}",
            timeout=self.request_timeout,
        )

        if response:
            data = self.safe_json_parse(
                response[1],
                context=f"ask_question response for request_id={request_id}",
            )
            if data is None:
                logger.error(
                    "Failed to parse response for question %s in session %s",
                    request_id,
                    session_id,
                )
                return {
                    "success": False,
                    "error": "Invalid response format received",
                    "request_id": request_id,
                }

            logger.info(
                "Received answer for question %s in session %s",
                request_id,
                session_id,
            )
            return {
                "success": True,
                "answer": data.get("answer"),
                "request_id": request_id,
            }

        logger.warning(
            "Timeout waiting for answer to question %s in session %s (timeout=%ds)",
            request_id,
            session_id,
            self.request_timeout,
        )
        return {
            "success": False,
            "error": "Timeout waiting for response",
            "request_id": request_id,
        }

    async def ask_choice(
        self,
        session_id: str,
        question: str,
        choices: list[str],
        allow_other: bool = True,
        context: str | None = None,
        agent_id: str = "unknown",
    ) -> dict:
        """Ask user a multiple choice question with optional free-text "Other"."""
        request_id = str(uuid.uuid4())

        logger.info(
            "ask_choice: session=%s, request_id=%s, agent=%s, question=%s, choices=%d",
            session_id,
            request_id,
            agent_id,
            question[:100] + "..." if len(question) > 100 else question,
            len(choices),
        )

        await self.persist_question(
            question_id=request_id,
            session_id=session_id,
            question=question,
            question_type="choice",
            choices=choices,
            agent_id=agent_id,
        )

        self.redis_client.publish(
            f"hitl:{session_id}",
            json.dumps({
                "type": "question",
                "request_id": request_id,
                "question": question,
                "input_type": "choice",
                "choices": choices,
                "allow_other": allow_other,
                "context": context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        logger.debug("Published choice question %s to Redis channel hitl:%s", request_id, session_id)

        response = self.redis_client.blpop(
            f"hitl:response:{request_id}",
            timeout=self.request_timeout,
        )

        if response:
            data = self.safe_json_parse(
                response[1],
                context=f"ask_choice response for request_id={request_id}",
            )
            if data is None:
                logger.error(
                    "Failed to parse response for choice question %s in session %s",
                    request_id,
                    session_id,
                )
                return {
                    "success": False,
                    "error": "Invalid response format received",
                    "request_id": request_id,
                }

            logger.info(
                "Received choice answer for question %s in session %s: selected=%s",
                request_id,
                session_id,
                data.get("selected"),
            )
            return {
                "success": True,
                "selected": data.get("selected"),
                "answer": data.get("answer"),
                "request_id": request_id,
            }

        logger.warning(
            "Timeout waiting for answer to choice question %s in session %s (timeout=%ds)",
            request_id,
            session_id,
            self.request_timeout,
        )
        return {
            "success": False,
            "error": "Timeout waiting for response",
            "request_id": request_id,
        }

    def progress(
        self,
        session_id: str,
        message: str,
        percent: int | None = None,
        step: str | None = None,
    ) -> dict:
        """Send progress update to user (non-blocking)."""
        logger.debug(
            "progress: session=%s, percent=%s, step=%s, message=%s",
            session_id,
            percent,
            step,
            message[:50] + "..." if len(message) > 50 else message,
        )

        self.redis_client.publish(
            f"hitl:{session_id}",
            json.dumps({
                "type": "progress",
                "message": message,
                "percent": percent,
                "step": step,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        return {"success": True, "acknowledged": True}

    def submit_response(
        self,
        request_id: str,
        answer: str,
        selected: str | None = None,
    ) -> dict:
        """Submit user response (called by backend API when user answers)."""
        logger.info(
            "submit_response: request_id=%s, selected=%s, answer_length=%d",
            request_id,
            selected,
            len(answer) if answer else 0,
        )

        self.redis_client.lpush(
            f"hitl:response:{request_id}",
            json.dumps({
                "answer": answer,
                "selected": selected,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        logger.debug("Pushed response to Redis queue hitl:response:%s", request_id)

        return {"success": True}

    def notify(
        self,
        session_id: str,
        title: str,
        message: str,
        level: str = "info",
    ) -> dict:
        """Send notification to user (non-blocking)."""
        logger.info(
            "notify: session=%s, level=%s, title=%s",
            session_id,
            level,
            title,
        )

        self.redis_client.publish(
            f"hitl:{session_id}",
            json.dumps({
                "type": "notification",
                "title": title,
                "message": message,
                "level": level,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )

        return {"success": True}

    def health_check(self) -> dict:
        """Health check."""
        try:
            self.redis_client.ping()
            redis_ok = True
        except Exception as e:
            logger.warning("Redis health check failed: %s", str(e))
            redis_ok = False

        status = "healthy" if redis_ok else "degraded"
        if not redis_ok:
            logger.warning("HITL MCP health status: %s (Redis disconnected)", status)

        return {
            "status": status,
            "service": "hitl-mcp",
            "redis": "connected" if redis_ok else "disconnected",
        }
