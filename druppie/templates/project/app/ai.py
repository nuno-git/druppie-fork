"""DeepInfra AI integration using OpenAI-compatible API.

Available functions:
    ai_chat(prompt, system) — LLM chat completion
    ocr_extract(image_url)  — OCR text extraction from image

Available models (change these constants as needed):
    AI_MODEL  — general-purpose LLM for chat, summarization, etc.
    OCR_MODEL — vision model optimized for OCR

Usage:

    from app.ai import ai_chat, ocr_extract

    # Chat completion
    answer = ai_chat("What is the capital of France?")

    # Chat with custom system prompt
    answer = ai_chat("Summarize this text...", system="You are a summarizer.")

    # OCR: extract text from an image URL
    text = ocr_extract("https://example.com/receipt.png")

The DEEPINFRA_API_KEY env var is injected at deploy time via docker-compose.
You never need to hardcode it.
"""

from openai import OpenAI

from app.config import settings

ai_client = OpenAI(
    api_key=settings.deepinfra_api_key,
    base_url="https://api.deepinfra.com/v1/openai",
)

AI_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
OCR_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"


def ai_chat(prompt: str, system: str = "You are a helpful assistant.") -> str:
    """LLM chat completion via DeepInfra."""
    response = ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def ocr_extract(image_url: str) -> str:
    """Extract text from an image using PaddleOCR vision model."""
    response = ai_client.chat.completions.create(
        model=OCR_MODEL,
        max_tokens=4092,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    )
    return response.choices[0].message.content
