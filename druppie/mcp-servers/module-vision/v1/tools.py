"""Vision v1 — MCP Tool Definitions.

Provides OCR and image analysis backed by Z.AI GLM-4.6V or DeepInfra.
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
    description="Extract text from an image (OCR). Returns the extracted text content.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def ocr(
    image_url: str,
    prompt: str = "",
    model: str | None = None,
) -> dict:
    """OCR — extract text from an image.

    Args:
        image_url: URL of the image to extract text from.
        prompt: Optional prompt to guide extraction (e.g. "Extract the recipe ingredients").
        model: Optional model override.
    """
    text = module.ocr(image_url=image_url, prompt=prompt, model=model)
    return {"text": text}


@mcp.tool(
    name="analyze",
    description="Analyze and describe an image. Returns a description of the visual content.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def analyze(
    image_url: str,
    prompt: str = "Describe this image.",
    model: str | None = None,
) -> dict:
    """Image analysis — describe or answer questions about an image.

    Args:
        image_url: URL of the image to analyze.
        prompt: What to analyze or describe about the image.
        model: Optional model override.
    """
    description = module.analyze(image_url=image_url, prompt=prompt, model=model)
    return {"description": description}
