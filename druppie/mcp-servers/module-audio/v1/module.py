"""Audio MCP Server - Business Logic Module.

Wraps Z.AI GLM-ASR-2512 for audio transcription (speech-to-text).
Uses the OpenAI-compatible /audio/transcriptions endpoint.
"""

import logging
import os
import base64
from pathlib import Path

import httpx

logger = logging.getLogger("audio-mcp")

ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
ZAI_ASR_MODEL = "glm-asr-2512"


class AudioModule:
    """Business logic for audio transcription."""

    def __init__(self):
        self._api_key = os.environ.get("ZAI_API_KEY", "")
        self._base_url = os.environ.get("ZAI_BASE_URL", ZAI_DEFAULT_BASE_URL)

        if not self._api_key:
            logger.warning("ZAI_API_KEY not set — audio transcription will fail")
        else:
            logger.info("Audio provider: Z.AI (model=%s)", ZAI_ASR_MODEL)

    @property
    def provider(self) -> str:
        return "zai" if self._api_key else "none"

    def transcribe(
        self,
        file_path: str | None = None,
        file_base64: str | None = None,
        prompt: str = "",
        hotwords: list[str] | None = None,
    ) -> str:
        """Transcribe audio to text.

        Either file_path or file_base64 must be provided.
        Supported formats: .wav, .mp3. Max 25 MB, max 30 seconds.
        """
        if not self._api_key:
            raise RuntimeError("No audio provider configured — set ZAI_API_KEY")

        url = f"{self._base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        if file_path:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            with open(path, "rb") as f:
                files = {"file": (path.name, f, "audio/mpeg")}
                data = {"model": ZAI_ASR_MODEL}
                if prompt:
                    data["prompt"] = prompt
                if hotwords:
                    data["hotwords"] = ",".join(hotwords)

                response = httpx.post(url, headers=headers, files=files, data=data, timeout=60)

        elif file_base64:
            json_body = {
                "model": ZAI_ASR_MODEL,
                "file_base64": file_base64,
            }
            if prompt:
                json_body["prompt"] = prompt
            if hotwords:
                json_body["hotwords"] = hotwords

            response = httpx.post(url, headers=headers, json=json_body, timeout=60)

        else:
            raise ValueError("Either file_path or file_base64 must be provided")

        response.raise_for_status()
        result = response.json()
        return result.get("text", "")
