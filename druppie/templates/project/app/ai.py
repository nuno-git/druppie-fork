"""DeepInfra AI integration using OpenAI-compatible API.

Usage:

    from app.ai import ai_chat, ocr_extract

    # Chat completion
    answer = ai_chat("What is the capital of France?")

    # Chat with custom system prompt
    answer = ai_chat("Summarize this text...", system="You are a summarizer.")

    # OCR: extract text from an image
    text = ocr_extract("https://example.com/receipt.png")
"""

from openai import OpenAI

from app.config import settings

ai_client = OpenAI(
    api_key=settings.deepinfra_api_key,
    base_url="https://api.deepinfra.com/v1/openai",
)

AI_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
OCR_MODEL = "openbmb/MiniCPM-o-2_6"


def ai_chat(prompt: str, system: str = "You are a helpful assistant.") -> str:
    """Simple chat completion."""
    response = ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def ocr_extract(image_url: str) -> str:
    """Extract text from an image using vision model."""
    response = ai_client.chat.completions.create(
        model=OCR_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract all text from this image. Return only the extracted text.",
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    )
    return response.choices[0].message.content
