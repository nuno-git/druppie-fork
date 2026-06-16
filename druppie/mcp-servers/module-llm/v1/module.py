"""LLM MCP Server - Business Logic Module.

Wraps Z.AI GLM (OpenAI-compatible) API for chat completion and embeddings.
Falls back to DeepInfra if ZAI_API_KEY is not set.

Embeddings can use a separate provider via EMBEDDING_API_KEY / EMBEDDING_BASE_URL /
EMBEDDING_MODEL — useful when the chat provider (e.g. Z.AI coding API) doesn't
expose an embeddings endpoint.
"""

import logging
import os
from typing import Any

from openai import AzureOpenAI, OpenAI

logger = logging.getLogger("llm-mcp")

# Z.AI GLM defaults
ZAI_DEFAULT_MODEL = "glm-4.7"
ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

# DeepInfra fallback
DEEPINFRA_DEFAULT_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"


class LLMModule:
    """Business logic for LLM chat completion and embeddings."""

    def __init__(self):
        zai_key = os.environ.get("ZAI_API_KEY", "")
        deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")

        # --- Chat provider ---
        if zai_key:
            self._provider = "zai"
            self._client = OpenAI(
                api_key=zai_key,
                base_url=os.environ.get("ZAI_BASE_URL", ZAI_DEFAULT_BASE_URL),
            )
            self._default_model = os.environ.get("ZAI_MODEL") or ZAI_DEFAULT_MODEL
            logger.info("Chat provider: Z.AI (model=%s)", self._default_model)
        elif deepinfra_key:
            self._provider = "deepinfra"
            self._client = OpenAI(
                api_key=deepinfra_key,
                base_url=DEEPINFRA_BASE_URL,
            )
            self._default_model = DEEPINFRA_DEFAULT_MODEL
            logger.info("Chat provider: DeepInfra (model=%s)", self._default_model)
        else:
            self._provider = "none"
            self._client = None
            self._default_model = ""
            logger.warning("No LLM API key set (ZAI_API_KEY or DEEPINFRA_API_KEY) — chat calls will fail")

        # --- Embedding provider (can differ from chat) ---
        self._embedding_client, self._default_embedding_model, self._embedding_dimensions = self._init_embedding_provider(
            deepinfra_key,
        )

    def _init_embedding_provider(self, deepinfra_key: str) -> tuple[OpenAI | None, str, int | None]:
        """Set up the embedding client.

        Priority:
        1. Explicit EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL
        2. DeepInfra (if DEEPINFRA_API_KEY is set — free embedding tier)
        3. Same client as chat (may not support embeddings)
        """
        explicit_key = os.environ.get("EMBEDDING_API_KEY", "")
        dim_str = os.environ.get("EMBEDDING_DIMENSIONS", "")
        dimensions = int(dim_str) if dim_str else None

        if explicit_key:
            base_url = os.environ.get("EMBEDDING_BASE_URL", DEEPINFRA_BASE_URL)
            model = os.environ.get("EMBEDDING_MODEL", DEEPINFRA_DEFAULT_EMBEDDING_MODEL)
            api_version = os.environ.get("EMBEDDING_API_VERSION", "")

            if api_version and "azure" in base_url:
                client = AzureOpenAI(
                    api_key=explicit_key,
                    azure_endpoint=base_url,
                    api_version=api_version,
                )
                logger.info("Embedding provider: Azure OpenAI (model=%s, endpoint=%s, dim=%s)", model, base_url, dimensions)
            else:
                client = OpenAI(api_key=explicit_key, base_url=base_url)
                logger.info("Embedding provider: explicit (model=%s, base_url=%s, dim=%s)", model, base_url, dimensions)
            return client, model, dimensions

        if deepinfra_key:
            client = OpenAI(api_key=deepinfra_key, base_url=DEEPINFRA_BASE_URL)
            logger.info("Embedding provider: DeepInfra (model=%s)", DEEPINFRA_DEFAULT_EMBEDDING_MODEL)
            return client, DEEPINFRA_DEFAULT_EMBEDDING_MODEL, None

        logger.warning("No embedding provider configured — embed calls will use the chat provider (may not support embeddings)")
        return self._client, os.environ.get("ZAI_EMBEDDING_MODEL", "embedding-3"), None

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

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not self._embedding_client:
            raise RuntimeError("No embedding provider configured — set EMBEDDING_API_KEY, DEEPINFRA_API_KEY, or ZAI_API_KEY")

        kwargs: dict[str, Any] = {
            "model": model or self._default_embedding_model,
            "input": texts,
        }
        if self._embedding_dimensions:
            kwargs["dimensions"] = self._embedding_dimensions

        response = self._embedding_client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]
