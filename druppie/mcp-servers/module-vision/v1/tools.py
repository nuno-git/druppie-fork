"""Vision v1 — MCP Tool Definitions.

Provides OCR and image analysis backed by Z.AI MCP server or DeepInfra.
"""

from fastmcp import FastMCP
from .module import VisionModule

MODULE_ID = "vision"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Vision v1",
    version=MODULE_VERSION,
    instructions="Image understanding and OCR. Use for extracting text from images and analyzing visual content.",
)

module = VisionModule()


@mcp.tool(
    name="ocr",
    description="Extract text from an image (OCR). Accepts a local file path, URL, or base64 data URI.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def ocr(
    image_source: str,
    prompt: str = "",
) -> dict:
    """OCR — extract text from an image.

    Args:
        image_source: Local file path, URL, or base64 data URI of the image.
        prompt: Optional prompt to guide extraction (e.g. "Extract the recipe ingredients").
    """
    text = await module.ocr(image_source=image_source, prompt=prompt)
    return {"text": text}


@mcp.tool(
    name="analyze",
    description="Analyze and describe an image. Accepts a local file path, URL, or base64 data URI.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def analyze(
    image_source: str,
    prompt: str = "Describe this image.",
) -> dict:
    """Image analysis — describe or answer questions about an image.

    Args:
        image_source: Local file path, URL, or base64 data URI of the image.
        prompt: What to analyze or describe about the image.
    """
    description = await module.analyze(image_source=image_source, prompt=prompt)
    return {"description": description}
