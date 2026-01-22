"""DeepInfra LLM provider implementation.

Supports various models via OpenAI-compatible API.
Default model: Qwen/Qwen3-Next-80B-A3B-Instruct
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


class ChatDeepInfra(BaseLLM):
    """DeepInfra Chat Model using OpenAI-compatible API.

    Alternative LLM provider for Druppie when Z.AI is unavailable.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "Qwen/Qwen3-Next-80B-A3B-Instruct",
        base_url: str = "https://api.deepinfra.com/v1/openai",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 300.0,
        max_retries: int = 3,
    ):
        """Initialize the DeepInfra client.

        Args:
            api_key: API key for authentication (DEEPINFRA_API_KEY)
            model: Model name to use (default: Qwen/Qwen3-Next-80B-A3B-Instruct)
            base_url: Base URL for the API
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds (default 300)
            max_retries: Maximum retries for transient errors (default 3)
        """
        self.api_key = api_key or os.getenv("DEEPINFRA_API_KEY", "")
        self.model = model or os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen3-Next-80B-A3B-Instruct")
        self.base_url = base_url or os.getenv(
            "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
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
        return "deepinfra"

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ChatDeepInfra":
        """Create new instance with tools bound."""
        new_instance = ChatDeepInfra(
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
            "provider": "deepinfra",
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
                "provider": "deepinfra",
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
                                "deepinfra_api_error_retrying",
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
                        "deepinfra_timeout_retrying",
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
                "DeepInfra API key is missing or invalid. Set DEEPINFRA_API_KEY environment variable.",
                provider="deepinfra",
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
                f"DeepInfra rate limit exceeded. Please wait and try again. Details: {error_text}",
                provider="deepinfra",
                retry_after=retry_after,
            )
        elif response.status_code >= 500:
            return ServerError(
                f"DeepInfra server error ({response.status_code}): {error_text}",
                provider="deepinfra",
            )
        else:
            return LLMError(
                f"DeepInfra API error {response.status_code}: {error_text}",
                provider="deepinfra",
            )

    def _parse_response(
        self, data: dict[str, Any], call_record: dict[str, Any]
    ) -> LLMResponse:
        """Parse API response into LLMResponse."""
        if not data.get("choices"):
            call_record["status"] = "error"
            call_record["error"] = "No choices in response"
            self.call_history.append(call_record)
            raise ValueError("No response from DeepInfra")

        choice = data["choices"][0]
        message = choice.get("message", {})
        raw_content = message.get("content", "")

        # Parse tool calls from OpenAI format first
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

        # If no tool calls from OpenAI format, check for <tool_call> tags in content
        # Some models (like Qwen) output tool calls as text
        if not tool_calls and raw_content:
            extracted_calls, cleaned_content = self._extract_tool_calls_from_text(raw_content)
            if extracted_calls:
                tool_calls = extracted_calls
                raw_content = cleaned_content
                logger.info(
                    "extracted_tool_calls_from_text",
                    count=len(tool_calls),
                    tool_names=[tc.get("name") for tc in tool_calls],
                )

        content = self._clean_response(raw_content)

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
            provider="deepinfra",
        )

    def _clean_response(self, text: str | None) -> str:
        """Clean the response text."""
        if text is None:
            return ""
        text = text.strip()

        # Remove <think>...</think> blocks (some models use this for reasoning)
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

    def _extract_tool_calls_from_text(self, content: str) -> tuple[list[dict], str]:
        """Extract tool calls from text content.

        Some models (like Qwen) output tool calls in text format like:
        <tool_call>{"name": "coding_write_file", "arguments": {...}}</tool_call>

        Args:
            content: Raw content from LLM response

        Returns:
            Tuple of (list of tool calls, cleaned content without tool call tags)
        """
        tool_calls = []
        cleaned_content = content

        # Pattern to match <tool_call>...</tool_call> blocks
        tool_call_pattern = re.compile(
            r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>',
            re.MULTILINE | re.DOTALL
        )

        matches = tool_call_pattern.findall(content)

        for i, match in enumerate(matches):
            try:
                # Try to parse the JSON
                tool_data = json.loads(match)

                name = tool_data.get("name", "")
                args = tool_data.get("arguments", {})

                # Handle case where arguments is a string
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                if name:
                    tool_calls.append({
                        "id": f"text_call_{i}",
                        "name": name,
                        "args": args if isinstance(args, dict) else {},
                    })
            except json.JSONDecodeError:
                logger.warning(
                    "failed_to_parse_text_tool_call",
                    match_preview=match[:200] if len(match) > 200 else match,
                )
                continue

        # Remove the tool_call tags from content if we found any
        if tool_calls:
            cleaned_content = tool_call_pattern.sub("", content).strip()

        return tool_calls, cleaned_content

    def _parse_malformed_args(self, args_str: str, tool_name: str) -> dict[str, Any]:
        """Attempt to parse malformed tool arguments from LLM."""
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

        # Fix unquoted keys
        cleaned = re.sub(r'{\s*(\w+):', r'{"\1":', cleaned)
        cleaned = re.sub(r',\s*(\w+):', r', "\1":', cleaned)

        # Try to find JSON object
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                result = json.loads(json_match.group())
                return result
            except json.JSONDecodeError:
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
