"""LLM MCP Server - Business Logic Module.

Wraps Z.AI GLM (OpenAI-compatible) API for chat completion.
Falls back to DeepInfra if ZAI_API_KEY is not set.
"""

import logging
import os

from openai import OpenAI

logger = logging.getLogger("llm-mcp")

# Z.AI GLM defaults
ZAI_DEFAULT_MODEL = "glm-4.7"
ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

# DeepInfra fallback
DEEPINFRA_DEFAULT_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class LLMModule:
    """Business logic for LLM chat completion."""

    def __init__(self):
        # Prefer Z.AI, fall back to DeepInfra
        zai_key = os.environ.get("ZAI_API_KEY", "")
        deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")

        if zai_key:
            self._provider = "zai"
            self._client = OpenAI(
                api_key=zai_key,
                base_url=os.environ.get("ZAI_BASE_URL", ZAI_DEFAULT_BASE_URL),
            )
            self._default_model = os.environ.get("ZAI_MODEL") or ZAI_DEFAULT_MODEL
            logger.info("LLM provider: Z.AI (model=%s)", self._default_model)
        elif deepinfra_key:
            self._provider = "deepinfra"
            self._client = OpenAI(
                api_key=deepinfra_key,
                base_url=DEEPINFRA_BASE_URL,
            )
            self._default_model = DEEPINFRA_DEFAULT_MODEL
            logger.info("LLM provider: DeepInfra (model=%s)", self._default_model)
        else:
            self._provider = "none"
            self._client = None
            self._default_model = ""
            logger.warning("No LLM API key set (ZAI_API_KEY or DEEPINFRA_API_KEY) — chat calls will fail")

    @property
    def provider(self) -> str:
        return self._provider

    def chat(self, prompt: str, system: str = "You are a helpful assistant.", model: str | None = None) -> str:
        """LLM chat completion."""
        if not self._client:
            raise RuntimeError("No LLM provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        response = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content
