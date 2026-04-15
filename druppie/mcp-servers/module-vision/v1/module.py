"""Vision MCP Server - Business Logic Module.

Wraps Z.AI GLM-4.6V for image analysis and OCR.
Falls back to DeepInfra PaddleOCR if ZAI_API_KEY is not set.
"""

import logging
import os

from openai import OpenAI

logger = logging.getLogger("vision-mcp")

# Z.AI GLM vision defaults
ZAI_DEFAULT_VISION_MODEL = "glm-4.6v"
ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

# DeepInfra fallback
DEEPINFRA_DEFAULT_VISION_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class VisionModule:
    """Business logic for vision/OCR operations."""

    def __init__(self):
        zai_key = os.environ.get("ZAI_API_KEY", "")
        deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")

        if zai_key:
            self._provider = "zai"
            self._client = OpenAI(
                api_key=zai_key,
                base_url=os.environ.get("ZAI_BASE_URL", ZAI_DEFAULT_BASE_URL),
            )
            self._default_model = os.environ.get("ZAI_VISION_MODEL", ZAI_DEFAULT_VISION_MODEL)
            logger.info("Vision provider: Z.AI (model=%s)", self._default_model)
        elif deepinfra_key:
            self._provider = "deepinfra"
            self._client = OpenAI(
                api_key=deepinfra_key,
                base_url=DEEPINFRA_BASE_URL,
            )
            self._default_model = DEEPINFRA_DEFAULT_VISION_MODEL
            logger.info("Vision provider: DeepInfra (model=%s)", self._default_model)
        else:
            self._provider = "none"
            self._client = None
            self._default_model = ""
            logger.warning("No vision API key set (ZAI_API_KEY or DEEPINFRA_API_KEY) — vision calls will fail")

    @property
    def provider(self) -> str:
        return self._provider

    def ocr(self, image_url: str, prompt: str = "", model: str | None = None) -> str:
        """Extract text from an image (OCR)."""
        if not self._client:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        content = [{"type": "image_url", "image_url": {"url": image_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        else:
            content.append({"type": "text", "text": "Extract all text from this image."})

        response = self._client.chat.completions.create(
            model=model or self._default_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content

    def analyze(self, image_url: str, prompt: str = "Describe this image.", model: str | None = None) -> str:
        """Analyze and describe an image."""
        if not self._client:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        content = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ]

        response = self._client.chat.completions.create(
            model=model or self._default_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content
