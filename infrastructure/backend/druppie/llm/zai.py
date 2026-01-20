"""Z.AI LLM Provider for Druppie.

Implements the LangChain chat model interface for Z.AI's GLM models.
API is OpenAI-compatible.
"""

import json
from typing import Any, Iterator, List, Optional

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


class ChatZAI(BaseChatModel):
    """Z.AI Chat Model using GLM-4.7.

    Uses the OpenAI-compatible API at https://api.z.ai/api/coding/paas/v4
    """

    model: str = Field(default="GLM-4.7", description="Model name")
    base_url: str = Field(
        default="https://api.z.ai/api/coding/paas/v4",
        description="Base URL for Z.AI API",
    )
    api_key: str = Field(default="", description="Z.AI API key")
    temperature: float = Field(default=0.7, description="Temperature for generation")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens to generate")
    timeout: float = Field(default=120.0, description="Request timeout in seconds")

    @property
    def _llm_type(self) -> str:
        return "zai"

    @property
    def _identifying_params(self) -> dict:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }

    def _convert_messages(self, messages: List[BaseMessage]) -> List[dict]:
        """Convert LangChain messages to OpenAI format."""
        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})
            else:
                # Default to user for unknown types
                result.append({"role": "user", "content": str(msg.content)})
        return result

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a chat response."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        if stop:
            payload["stop"] = stop

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                raise ValueError(
                    f"Z.AI API error {response.status_code}: {response.text}"
                )

            data = response.json()

        # Parse response
        if not data.get("choices"):
            raise ValueError("No response from Z.AI")

        choice = data["choices"][0]
        content = choice.get("message", {}).get("content", "")

        # Clean response (remove thinking blocks, code fences)
        content = self._clean_response(content)

        # Extract usage
        usage = data.get("usage", {})
        usage_metadata = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)

        return ChatResult(
            generations=[generation],
            llm_output={"usage": usage_metadata},
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generate a chat response."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        if stop:
            payload["stop"] = stop

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                raise ValueError(
                    f"Z.AI API error {response.status_code}: {response.text}"
                )

            data = response.json()

        # Parse response
        if not data.get("choices"):
            raise ValueError("No response from Z.AI")

        choice = data["choices"][0]
        content = choice.get("message", {}).get("content", "")

        # Clean response
        content = self._clean_response(content)

        # Extract usage
        usage = data.get("usage", {})
        usage_metadata = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)

        return ChatResult(
            generations=[generation],
            llm_output={"usage": usage_metadata},
        )

    def _clean_response(self, text: str) -> str:
        """Clean the response text.

        Removes:
        - <think>...</think> blocks (reasoning traces)
        - Markdown code fences
        """
        text = text.strip()

        # Remove <think>...</think> blocks
        while "<think>" in text and "</think>" in text:
            start = text.find("<think>")
            end = text.find("</think>") + len("</think>")
            text = text[:start] + text[end:]

        text = text.strip()

        # Remove markdown code fences
        if text.startswith("```json"):
            text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
        elif text.startswith("```"):
            text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

        return text.strip()
