"""Z.AI LLM Provider for Druppie.

Implements the LangChain chat model interface for Z.AI's GLM models.
API is OpenAI-compatible.
"""

import json
from typing import Any, Iterator, List, Optional, Sequence, Union

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
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
    timeout: float = Field(default=300.0, description="Request timeout in seconds (5 minutes)")
    bound_tools: List[dict] = Field(default_factory=list, description="Bound tools in OpenAI format")

    def bind_tools(
        self,
        tools: Sequence[Union[dict, type, BaseTool]],
        **kwargs: Any,
    ) -> "ChatZAI":
        """Bind tools to the LLM for function calling.

        Args:
            tools: List of tools to bind (LangChain tools or OpenAI tool dicts)

        Returns:
            New ChatZAI instance with bound tools
        """
        # Convert tools to OpenAI format
        formatted_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            else:
                # Use LangChain's converter for BaseTool instances
                formatted_tools.append(convert_to_openai_tool(tool))

        # Return new instance with tools bound
        return ChatZAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            bound_tools=formatted_tools,
        )

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
                msg_dict = {"role": "assistant", "content": msg.content or ""}
                # Include tool calls if present
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(tc.get("args", {})),
                            },
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ]
                result.append(msg_dict)
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
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

        # Include tools if bound
        if self.bound_tools:
            payload["tools"] = self.bound_tools
            payload["tool_choice"] = "auto"

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
        msg_data = choice.get("message", {})
        content = msg_data.get("content", "")
        tool_calls = msg_data.get("tool_calls", [])

        # Clean response (remove thinking blocks, code fences)
        if content:
            content = self._clean_response(content)

        # Extract usage
        usage = data.get("usage", {})
        usage_metadata = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        # Build AIMessage with tool calls if present
        if tool_calls:
            # Convert to LangChain tool call format
            lc_tool_calls = []
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {"raw": args_str}

                lc_tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "args": args,
                })

            message = AIMessage(
                content=content or "",
                tool_calls=lc_tool_calls,
            )
        else:
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

        # Include tools if bound
        if self.bound_tools:
            payload["tools"] = self.bound_tools
            payload["tool_choice"] = "auto"

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
        msg_data = choice.get("message", {})
        content = msg_data.get("content", "")
        tool_calls = msg_data.get("tool_calls", [])

        # Clean response
        if content:
            content = self._clean_response(content)

        # Extract usage
        usage = data.get("usage", {})
        usage_metadata = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        # Build AIMessage with tool calls if present
        if tool_calls:
            lc_tool_calls = []
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {"raw": args_str}

                lc_tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "args": args,
                })

            message = AIMessage(
                content=content or "",
                tool_calls=lc_tool_calls,
            )
        else:
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
