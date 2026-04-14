"""LLM MCP Server - Business Logic Module.

Wraps DeepInfra OpenAI-compatible API for chat and vision tools.
"""

import logging
import os

from openai import OpenAI

logger = logging.getLogger("llm-mcp")

DEFAULT_CHAT_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
DEFAULT_VISION_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"


class LLMModule:
    """Business logic for LLM operations via DeepInfra."""

    def __init__(self):
        api_key = os.environ.get("DEEPINFRA_API_KEY", "")
        if not api_key:
            logger.warning("DEEPINFRA_API_KEY not set — LLM calls will fail")
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepinfra.com/v1/openai",
        )

    def chat(self, prompt: str, system: str = "You are a helpful assistant.", model: str | None = None) -> str:
        """LLM chat completion."""
        response = self._client.chat.completions.create(
            model=model or DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content

    def vision(self, image_url: str, prompt: str = "", model: str | None = None) -> str:
        """Vision / OCR — extract text or describe an image."""
        content = [{"type": "image_url", "image_url": {"url": image_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})

        response = self._client.chat.completions.create(
            model=model or DEFAULT_VISION_MODEL,
            max_tokens=4092,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content
