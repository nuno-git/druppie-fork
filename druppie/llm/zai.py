"""Z.AI LLM provider implementation.

Supports GLM-4.7 and other Z.AI models via OpenAI-compatible API.
"""

import json
import os
import re
import time
from typing import Any

import httpx
import structlog

from .base import BaseLLM, LLMResponse

logger = structlog.get_logger()


class ChatZAI(BaseLLM):
    """Z.AI Chat Model using GLM API (OpenAI-compatible).

    This is the primary LLM provider for Druppie.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "GLM-4.7",
        base_url: str = "https://api.z.ai/api/coding/paas/v4",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 500.0,
        max_retries: int = 3,
    ):
        """Initialize the Z.AI client.

        Args:
            api_key: API key for authentication
            model: Model name to use
            base_url: Base URL for the API
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds (default 500)
            max_retries: Maximum retries for transient errors (default 3)
        """
        self.api_key = api_key or os.getenv("ZAI_API_KEY", "")
        self.model = model or os.getenv("ZAI_MODEL", "GLM-4.7")
        self.base_url = base_url or os.getenv(
            "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

        # Track calls for debugging
        self.call_history: list[dict] = []

        # Bound tools
        self._bound_tools: list[dict] = []

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def provider_name(self) -> str:
        return "zai"

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ChatZAI":
        """Create new instance with tools bound."""
        new_instance = ChatZAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )
        new_instance._bound_tools = tools
        return new_instance

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send synchronous chat completion request."""
        start_time = time.time()
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        # Use bound tools or passed tools
        effective_tools = tools or self._bound_tools

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        if effective_tools:
            payload["tools"] = effective_tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        call_record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "provider": "zai",
            "status": "pending",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)

                call_record["duration_ms"] = int((time.time() - start_time) * 1000)

                if response.status_code != 200:
                    error_msg = self._format_error(response)
                    call_record["status"] = "error"
                    call_record["error"] = error_msg
                    self.call_history.append(call_record)
                    raise ValueError(error_msg)

                data = response.json()

            return self._parse_response(data, call_record)

        except Exception as e:
            call_record["duration_ms"] = int((time.time() - start_time) * 1000)
            if call_record["status"] == "pending":
                call_record["status"] = "error"
                call_record["error"] = str(e)
                self.call_history.append(call_record)
            raise

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send asynchronous chat completion request with retry logic."""
        import asyncio

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        # Use bound tools or passed tools
        effective_tools = tools or self._bound_tools

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        if effective_tools:
            payload["tools"] = effective_tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error = None

        for attempt in range(self.max_retries):
            start_time = time.time()
            call_record = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "model": self.model,
                "provider": "zai",
                "status": "pending",
                "attempt": attempt + 1,
            }

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    call_record["duration_ms"] = int((time.time() - start_time) * 1000)

                    # Retry on 500 errors
                    if response.status_code >= 500:
                        error_msg = self._format_error(response)
                        call_record["status"] = "retry"
                        call_record["error"] = error_msg
                        self.call_history.append(call_record)
                        last_error = ValueError(error_msg)

                        if attempt < self.max_retries - 1:
                            wait_time = (attempt + 1) * 5  # 5s, 10s, 15s backoff
                            logger.warning(
                                "zai_api_error_retrying",
                                attempt=attempt + 1,
                                max_retries=self.max_retries,
                                wait_seconds=wait_time,
                                status_code=response.status_code,
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            call_record["status"] = "error"
                            raise last_error

                    if response.status_code != 200:
                        error_msg = self._format_error(response)
                        call_record["status"] = "error"
                        call_record["error"] = error_msg
                        self.call_history.append(call_record)
                        raise ValueError(error_msg)

                    data = response.json()

                return self._parse_response(data, call_record)

            except httpx.TimeoutException as e:
                call_record["duration_ms"] = int((time.time() - start_time) * 1000)
                call_record["status"] = "retry" if attempt < self.max_retries - 1 else "error"
                call_record["error"] = f"Timeout: {str(e)}"
                self.call_history.append(call_record)
                last_error = e

                if attempt < self.max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    logger.warning(
                        "zai_timeout_retrying",
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        wait_seconds=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                raise

            except Exception as e:
                call_record["duration_ms"] = int((time.time() - start_time) * 1000)
                if call_record["status"] == "pending":
                    call_record["status"] = "error"
                    call_record["error"] = str(e)
                    self.call_history.append(call_record)
                raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise ValueError("Max retries exceeded")

    def _format_error(self, response: httpx.Response) -> str:
        """Format error message from response."""
        if response.status_code == 401:
            return "Z.AI API key is missing or invalid. Set ZAI_API_KEY environment variable."
        return f"Z.AI API error {response.status_code}: {response.text}"

    def _parse_response(
        self, data: dict[str, Any], call_record: dict[str, Any]
    ) -> LLMResponse:
        """Parse API response into LLMResponse."""
        if not data.get("choices"):
            call_record["status"] = "error"
            call_record["error"] = "No choices in response"
            self.call_history.append(call_record)
            raise ValueError("No response from Z.AI")

        choice = data["choices"][0]
        message = choice.get("message", {})
        content = self._clean_response(message.get("content", ""))

        # Parse tool calls
        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = self._parse_malformed_args(args_str, func.get("name", ""))

                # Ensure args is always a dict
                if not isinstance(args, dict):
                    logger.warning(
                        "tool_args_not_dict",
                        tool_name=func.get("name", ""),
                        args_type=type(args).__name__,
                        args_value=str(args)[:100] if args else None,
                    )
                    args = {"value": args} if args else {}

                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "args": args,
                })

        # Extract usage
        usage = data.get("usage", {})

        call_record["status"] = "success"
        call_record["content"] = content[:200] if content else ""
        call_record["tool_calls_count"] = len(tool_calls)
        self.call_history.append(call_record)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            model=self.model,
            provider="zai",
        )

    def _clean_response(self, text: str) -> str:
        """Clean the response text."""
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

    def _parse_malformed_args(self, args_str: str, tool_name: str) -> dict[str, Any]:
        """Attempt to parse malformed tool arguments from LLM.

        Some LLMs return malformed JSON with XML-like tags or other issues.
        """
        if not args_str:
            return {}

        logger.debug("parsing_malformed_args", tool_name=tool_name, args_len=len(args_str))

        # Clean up common issues
        cleaned = args_str

        # Remove XML-like tags (but preserve content inside)
        cleaned = re.sub(r"</?\w+(?:_\w+)*>", "", cleaned)

        # Fix assignment syntax (key="value" -> "key": "value")
        cleaned = re.sub(r'(\w+)="([^"]*)"', r'"\1": "\2"', cleaned)

        # Remove duplicate colons
        cleaned = re.sub(r":+\s*:", ":", cleaned)

        # Fix missing commas between fields
        cleaned = re.sub(r'"\s+"', '", "', cleaned)

        # Fix unquoted keys: {path: "..." -> {"path": "..."
        cleaned = re.sub(r'{\s*(\w+):', r'{"\1":', cleaned)
        cleaned = re.sub(r',\s*(\w+):', r', "\1":', cleaned)

        # Try to find JSON object
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                result = json.loads(json_match.group())
                if "data" in result and isinstance(result["data"], str):
                    try:
                        result["data"] = json.loads(result["data"])
                    except json.JSONDecodeError:
                        pass
                return result
            except json.JSONDecodeError:
                # Try to extract key-value pairs manually for common tools
                pass

        # Tool-specific fallbacks
        if tool_name == "done":
            summary_match = re.search(
                r'"?summary"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            return {
                "summary": summary_match.group(1) if summary_match else "Task completed",
                "artifacts": [],
                "data": {},
            }

        if tool_name == "fail":
            reason_match = re.search(
                r'"?reason"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            return {"reason": reason_match.group(1) if reason_match else args_str[:100]}

        if tool_name == "ask_human" or tool_name == "hitl_ask":
            question_match = re.search(
                r'"?question"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            return {
                "question": question_match.group(1) if question_match else args_str[:100]
            }

        # Handle coding:write_file and similar tools
        if "write_file" in tool_name or tool_name == "coding_write_file":
            path_match = re.search(
                r'"?path"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            # Try to extract content - could be between quotes or in a code block
            content_match = re.search(
                r'"?content"?\s*[=:]\s*"([\s\S]*?)"(?:\s*[,}]|$)', args_str, re.IGNORECASE
            )
            if not content_match:
                # Try code block format
                content_match = re.search(
                    r'"?content"?\s*[=:]\s*```[\w]*\n?([\s\S]*?)```', args_str, re.IGNORECASE
                )
            if path_match and content_match:
                return {
                    "path": path_match.group(1),
                    "content": content_match.group(1),
                }
            elif path_match:
                logger.warning(
                    "write_file_missing_content",
                    tool_name=tool_name,
                    path=path_match.group(1),
                )

        # Handle coding:read_file
        if "read_file" in tool_name or tool_name == "coding_read_file":
            path_match = re.search(
                r'"?path"?\s*[=:]\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            if path_match:
                return {"path": path_match.group(1)}

        logger.warning(
            "could_not_parse_malformed_args", tool_name=tool_name, args=args_str[:200]
        )
        return {}

    def get_call_history(self) -> list[dict]:
        """Get history of LLM calls for debugging."""
        return self.call_history.copy()

    def clear_call_history(self) -> None:
        """Clear call history."""
        self.call_history = []
