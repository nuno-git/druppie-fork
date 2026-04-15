"""Audio v1 — MCP Tool Definitions.

Provides audio transcription (speech-to-text) backed by Z.AI GLM-ASR-2512.
"""

from fastmcp import FastMCP
from .module import AudioModule

MODULE_ID = "audio"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Audio v1",
    version=MODULE_VERSION,
    instructions="Audio transcription (speech-to-text). Use for converting audio files to text.",
)

module = AudioModule()


@mcp.tool(
    name="transcribe",
    description="Transcribe audio to text (speech-to-text). Supports .wav and .mp3 files up to 25 MB / 30 seconds.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def transcribe(
    file_path: str | None = None,
    file_base64: str | None = None,
    prompt: str = "",
    hotwords: list[str] | None = None,
) -> dict:
    """Transcribe audio to text.

    Args:
        file_path: Path to a local audio file (.wav or .mp3).
        file_base64: Base64-encoded audio file (alternative to file_path).
        prompt: Optional context from previous transcription for long audio.
        hotwords: Optional list of domain-specific words to improve accuracy.
    """
    text = module.transcribe(
        file_path=file_path,
        file_base64=file_base64,
        prompt=prompt,
        hotwords=hotwords,
    )
    return {"text": text}
