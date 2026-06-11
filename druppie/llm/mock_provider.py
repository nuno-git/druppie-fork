"""Simulated LLM provider for load testing and autoscaling verification.

When LLM_PROVIDER=mock, all LLM calls return fake responses after a random delay.
This exercises the full API stack (sessions, agents, DB, tools) without real LLM costs.

Environment variables:
    MOCK_LLM_MIN_DELAY: Minimum delay in seconds (default: 0.5)
    MOCK_LLM_MAX_DELAY: Maximum delay in seconds (default: 5.0)
"""

import asyncio
import os
import random
import time
import uuid
from typing import Any

import structlog

from .base import BaseLLM, LLMResponse

logger = structlog.get_logger()


class MockLLM(BaseLLM):
    """Simulated LLM that returns fake responses after a random delay.

    The delay range is configurable via MOCK_LLM_MIN_DELAY and MOCK_LLM_MAX_DELAY env vars.
    Each achat() call sleeps for a random duration then returns a response that calls "done"
    with a generic summary, simulating a completed agent turn.
    """

    def __init__(self, model: str = "mock/model", temperature: float = 0.7):
        self._model = model
        self._temperature = temperature
        self._min_delay = float(os.getenv("MOCK_LLM_MIN_DELAY", "0.5"))
        self._max_delay = float(os.getenv("MOCK_LLM_MAX_DELAY", "5.0"))
        self._call_count = 0
        self._call_history: list[dict[str, Any]] = []
        logger.info(
            "mock_llm_initialized",
            model=self._model,
            delay_range=f"{self._min_delay}s-{self._max_delay}s",
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        delay = random.uniform(self._min_delay, self._max_delay)
        time.sleep(delay)
        return self._generate_response(delay)

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        delay = random.uniform(self._min_delay, self._max_delay)
        self._call_count += 1
        logger.debug("mock_llm_sleeping", delay=f"{delay:.2f}s", call=self._call_count)
        await asyncio.sleep(delay)
        response = self._generate_response(delay)
        self._call_history.append({
            "call_count": self._call_count,
            "delay": delay,
            "tokens": response.total_tokens,
        })
        return response

    def _generate_response(self, delay: float) -> LLMResponse:
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        prompt_tokens = random.randint(200, 800)
        completion_tokens = random.randint(50, 200)

        return LLMResponse(
            content="",
            raw_content="",
            tool_calls=[
                {
                    "id": call_id,
                    "name": "done",
                    "args": {
                        "summary": f"Mock LLM response (simulated {delay:.1f}s delay). Task completed successfully."
                    },
                }
            ],
            raw_tool_calls=[
                {
                    "id": call_id,
                    "name": "done",
                    "args": f'{{"summary": "Mock LLM response (simulated {delay:.1f}s delay). Task completed successfully."}}',
                }
            ],
            finish_reason="tool_calls",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=self._model,
            provider="mock",
        )

    def bind_tools(self, tools: list[dict[str, Any]]) -> "MockLLM":
        return self

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def get_call_history(self) -> list[dict[str, Any]]:
        return list(self._call_history)

    def clear_call_history(self) -> None:
        self._call_history.clear()
