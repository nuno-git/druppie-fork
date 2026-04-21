"""LLM v1 — MCP Tool Definitions.

Provides chat completion backed by Z.AI GLM or DeepInfra.
"""

from fastmcp import FastMCP
from .module import LLMModule

MODULE_ID = "llm"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "LLM v1",
    version=MODULE_VERSION,
    instructions="LLM chat completion. Use for text generation, summarization, and question answering.",
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
    """Chat completion.

    Args:
        prompt: The user message / question.
        system: System prompt to set the assistant's behavior.
        model: Optional model override.
    """
    answer = module.chat(prompt=prompt, system=system, model=model)
    return {"answer": answer}
