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

from .base import BaseLLM, LLMResponse, LLMError, RateLimitError, AuthenticationError, ServerError

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
                    error = self._format_error(response)
                    call_record["status"] = "error"
                    call_record["error"] = str(error)
                    call_record["error_type"] = type(error).__name__
                    call_record["retryable"] = error.retryable
                    self.call_history.append(call_record)
                    raise error

                data = response.json()

            return self._parse_response(data, call_record)

        except LLMError:
            # Re-raise LLM errors as-is (already recorded)
            raise
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

                    # Retry on 500 errors (server issues)
                    if response.status_code >= 500:
                        error = self._format_error(response)
                        call_record["status"] = "retry"
                        call_record["error"] = str(error)
                        self.call_history.append(call_record)
                        last_error = error

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

                    # Handle other error status codes (429, 401, etc.)
                    # These are NOT retried - user should see the error and decide
                    if response.status_code != 200:
                        error = self._format_error(response)
                        call_record["status"] = "error"
                        call_record["error"] = str(error)
                        call_record["error_type"] = type(error).__name__
                        call_record["retryable"] = error.retryable
                        self.call_history.append(call_record)
                        raise error

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

    def _format_error(self, response: httpx.Response) -> LLMError:
        """Format error from response, returning appropriate exception."""
        error_text = response.text[:500] if response.text else "No details"

        if response.status_code == 401:
            return AuthenticationError(
                "Z.AI API key is missing or invalid. Set ZAI_API_KEY environment variable.",
                provider="zai",
            )
        elif response.status_code == 429:
            # Try to parse retry-after header
            retry_after = None
            if "retry-after" in response.headers:
                try:
                    retry_after = int(response.headers["retry-after"])
                except ValueError:
                    pass

            return RateLimitError(
                f"Z.AI rate limit exceeded. Please wait and try again. Details: {error_text}",
                provider="zai",
                retry_after=retry_after,
            )
        elif response.status_code >= 500:
            return ServerError(
                f"Z.AI server error ({response.status_code}): {error_text}",
                provider="zai",
            )
        else:
            return LLMError(
                f"Z.AI API error {response.status_code}: {error_text}",
                provider="zai",
            )

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

        # Parse tool calls from API response
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

        # Fallback: Parse tool calls from content text if not in API response
        # Some LLMs (like glm-4) output tool calls as <tool_call>...</tool_call> text
        if not tool_calls and content:
            text_tool_calls = self._parse_tool_calls_from_text(content)
            if text_tool_calls:
                tool_calls = text_tool_calls
                # Clean the tool call markup from content
                content = self._remove_tool_call_markup(content)
                logger.info(
                    "parsed_tool_calls_from_text",
                    count=len(tool_calls),
                    tool_names=[tc["name"] for tc in tool_calls],
                )

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

    def _parse_tool_calls_from_text(self, content: str) -> list[dict[str, Any]]:
        """Parse tool calls from text content (fallback for LLMs that output text format).

        Handles formats like:
        - <tool_call>"name": "tool_name", "arguments": {...}</tool_call>
        - <tool_call>{"name": "tool_name", "arguments": {...}}</tool_call>
        """
        tool_calls = []

        # Find all <tool_call>...</tool_call> blocks
        pattern = r"<tool_call>([\s\S]*?)</tool_call>"
        matches = re.findall(pattern, content, re.IGNORECASE)

        if not matches:
            # Also try without closing tag (some LLMs forget to close)
            pattern = r"<tool_call>([\s\S]+?)(?=<tool_call>|$)"
            matches = re.findall(pattern, content, re.IGNORECASE)

        for i, match in enumerate(matches):
            try:
                tool_call = self._parse_single_tool_call(match.strip(), i)
                if tool_call:
                    tool_calls.append(tool_call)
            except Exception as e:
                logger.warning(
                    "failed_to_parse_tool_call_from_text",
                    error=str(e),
                    content_preview=match[:200] if match else "",
                )

        return tool_calls

    def _parse_single_tool_call(self, text: str, index: int) -> dict[str, Any] | None:
        """Parse a single tool call from text."""
        if not text:
            return None

        # Try to parse as JSON first
        try:
            # Handle format: {"name": "...", "arguments": {...}}
            if text.strip().startswith("{"):
                data = json.loads(text)
                if "name" in data:
                    args = data.get("arguments", data.get("args", {}))
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    return {
                        "id": f"text_call_{index}",
                        "name": data["name"],
                        "args": args if isinstance(args, dict) else {},
                    }
        except json.JSONDecodeError:
            pass

        # Handle format: "name": "tool_name", "arguments": {...}
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        args_match = re.search(r'"arguments"\s*:\s*(\{[\s\S]*\})', text)

        if not args_match:
            # Try "args" instead of "arguments"
            args_match = re.search(r'"args"\s*:\s*(\{[\s\S]*\})', text)

        if name_match:
            tool_name = name_match.group(1)
            args = {}

            if args_match:
                args_str = args_match.group(1)
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    # Try to extract individual fields
                    args = self._parse_malformed_args(args_str, tool_name)

            return {
                "id": f"text_call_{index}",
                "name": tool_name,
                "args": args if isinstance(args, dict) else {},
            }

        return None

    def _remove_tool_call_markup(self, content: str) -> str:
        """Remove <tool_call>...</tool_call> markup from content."""
        # Remove complete tool_call blocks
        cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", content, flags=re.IGNORECASE)
        # Remove any leftover unclosed tags
        cleaned = re.sub(r"</?tool_call>", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def get_call_history(self) -> list[dict]:
        """Get history of LLM calls for debugging."""
        return self.call_history.copy()

    def clear_call_history(self) -> None:
        """Clear call history."""
        self.call_history = []
