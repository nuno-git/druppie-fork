"""LLM v1 — MCP Tool Definitions.

Provides chat completion and embeddings backed by Z.AI GLM or DeepInfra.
"""

import asyncio
import time
from fastmcp import FastMCP
from .module import LLMModule

MODULE_ID = "llm"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "LLM v1",
    version=MODULE_VERSION,
    instructions="LLM chat completion and embeddings. Use for text generation, summarization, question answering, and generating text embeddings for semantic search.",
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


@mcp.tool(
    name="embed",
    description="Generate text embeddings for semantic search and similarity. Returns a list of embedding vectors.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def embed(
    texts: list[str],
    model: str | None = None,
) -> dict:
    start = time.time()
    embeddings = await asyncio.to_thread(module.embed, texts=texts, model=model)
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "embeddings": embeddings,
        "dimensions": len(embeddings[0]) if embeddings else 0,
        "count": len(embeddings),
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }
