"""LLM v1 — MCP Tool Definitions.

Provides chat and vision tools backed by DeepInfra's OpenAI-compatible API.
"""

from fastmcp import FastMCP
from .module import LLMModule

MODULE_ID = "llm"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "LLM v1",
    version=MODULE_VERSION,
    instructions="LLM chat completion and vision/OCR. Use for text generation, summarization, and image understanding.",
)

module = LLMModule()


@mcp.tool(
    name="chat",
    description="LLM chat completion. Returns a text response for a given prompt.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def chat(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str | None = None,
) -> dict:
    """Chat completion via DeepInfra.

    Args:
        prompt: The user message / question.
        system: System prompt to set the assistant's behavior.
        model: Optional model override (defaults to Llama-4-Maverick).
    """
    answer = module.chat(prompt=prompt, system=system, model=model)
    return {"answer": answer}


@mcp.tool(
    name="vision",
    description="Vision / OCR — extract text or describe an image from a URL.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def vision(
    image_url: str,
    prompt: str = "",
    model: str | None = None,
) -> dict:
    """Vision understanding via DeepInfra.

    Args:
        image_url: URL of the image to analyze.
        prompt: Optional prompt to guide the analysis (e.g. "Extract all text").
        model: Optional model override (defaults to PaddleOCR).
    """
    text = module.vision(image_url=image_url, prompt=prompt, model=model)
    return {"text": text}
