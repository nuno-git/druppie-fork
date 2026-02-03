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

    @property
    def supports_native_tools(self) -> bool:
        """DeepInfra models support native OpenAI-style tool calling."""
        return True

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
        print(f"[DEEPINFRA LLM] === SYNC CHAT START ===")
        print(f"[DEEPINFRA LLM] Model: {self.model}")
        print(f"[DEEPINFRA LLM] URL: {self.base_url}")
        print(f"[DEEPINFRA LLM] Messages count: {len(messages)}")
        print(f"[DEEPINFRA LLM] API key present: {bool(self.api_key)}")

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
            print(f"[DEEPINFRA LLM] Tools: {len(effective_tools)} tools bound")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        call_record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "provider": "deepinfra",
            "status": "pending",
        }

        print(f"[DEEPINFRA LLM] Sending request to {url}")
        print(f"[DEEPINFRA LLM] Payload size: {len(str(payload))} chars")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)

                call_record["duration_ms"] = int((time.time() - start_time) * 1000)
                print(f"[DEEPINFRA LLM] Response status: {response.status_code}")
                print(f"[DEEPINFRA LLM] Response time: {call_record['duration_ms']}ms")

                if response.status_code != 200:
                    print(f"[DEEPINFRA LLM] ERROR response: {response.text[:500]}")
                    error = self._format_error(response)
                    call_record["status"] = "error"
                    call_record["error"] = str(error)
                    call_record["error_type"] = type(error).__name__
                    call_record["retryable"] = error.retryable
                    self.call_history.append(call_record)
                    raise error

                data = response.json()
                print(f"[DEEPINFRA LLM] Response data keys: {list(data.keys())}")

            print(f"[DEEPINFRA LLM] === PARSING RESPONSE ===")
            return self._parse_response(data, call_record)

        except LLMError as e:
            print(f"[DEEPINFRA LLM] LLMError: {type(e).__name__}: {e}")
            # Re-raise LLM errors as-is (already recorded)
            raise
        except Exception as e:
            print(f"[DEEPINFRA LLM] Exception: {type(e).__name__}: {e}")
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
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send asynchronous chat completion request with retry logic."""
        import asyncio

        print(f"[DEEPINFRA LLM] === ASYNC CHAT START ===")
        print(f"[DEEPINFRA LLM] Model: {self.model}")
        print(f"[DEEPINFRA LLM] URL: {self.base_url}")
        print(f"[DEEPINFRA LLM] Messages count: {len(messages)}")
        print(f"[DEEPINFRA LLM] Max retries: {self.max_retries}")
        print(f"[DEEPINFRA LLM] Timeout: {self.timeout}s")

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        # Use bound tools or passed tools
        effective_tools = tools or self._bound_tools

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        # Per-call max_tokens overrides instance default
        effective_max_tokens = max_tokens or self.max_tokens
        if effective_max_tokens:
            payload["max_tokens"] = effective_max_tokens

        if effective_tools:
            payload["tools"] = effective_tools
            payload["tool_choice"] = "auto"
            print(f"[DEEPINFRA LLM] Tools: {len(effective_tools)} tools bound")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error = None

        for attempt in range(self.max_retries):
            print(f"[DEEPINFRA LLM] Attempt {attempt + 1}/{self.max_retries}")
            start_time = time.time()
            call_record = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "model": self.model,
                "provider": "deepinfra",
                "status": "pending",
                "attempt": attempt + 1,
            }

            try:
                print(f"[DEEPINFRA LLM] Sending async request to {url}")
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    call_record["duration_ms"] = int((time.time() - start_time) * 1000)
                    print(f"[DEEPINFRA LLM] Response status: {response.status_code}")
                    print(f"[DEEPINFRA LLM] Response time: {call_record['duration_ms']}ms")

                    # Retry on 500 errors (server issues)
                    if response.status_code >= 500:
                        print(f"[DEEPINFRA LLM] Server error {response.status_code}, retrying...")
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
                            print(f"[DEEPINFRA LLM] Waiting {wait_time}s before retry...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            call_record["status"] = "error"
                            raise last_error

                    # Handle other error status codes (429, 401, etc.)
                    # These are NOT retried - user should see error and decide
                    if response.status_code != 200:
                        print(f"[DEEPINFRA LLM] ERROR response: {response.text[:500]}")
                        error = self._format_error(response)
                        call_record["status"] = "error"
                        call_record["error"] = str(error)
                        call_record["error_type"] = type(error).__name__
                        call_record["retryable"] = error.retryable
                        self.call_history.append(call_record)
                        raise error

                    data = response.json()
                    print(f"[DEEPINFRA LLM] Response data keys: {list(data.keys())}")

                print(f"[DEEPINFRA LLM] === PARSING RESPONSE ===")
                return self._parse_response(data, call_record)

            except httpx.TimeoutException as e:
                print(f"[DEEPINFRA LLM] TimeoutException: {e}")
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
                    print(f"[DEEPINFRA LLM] Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    continue
                raise

            except Exception as e:
                print(f"[DEEPINFRA LLM] Exception: {type(e).__name__}: {e}")
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
        original_content = message.get("content") or ""  # Preserve original (handle None)
        raw_content = original_content

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
            raw_content=original_content,  # Preserve original for debugging
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
        # Use greedy match for everything between tags, then parse JSON
        tool_call_pattern = re.compile(
            r'<tool_call>\s*([\s\S]*?)\s*</tool_call>',
            re.MULTILINE | re.DOTALL
        )

        matches = tool_call_pattern.findall(content)

        for i, match in enumerate(matches):
            try:
                # Clean up the match - it should be JSON
                json_str = match.strip()

                # Handle malformed JSON - missing opening brace
                # e.g., '"name": "hitl_ask_question", "arguments": {...}'
                if not json_str.startswith('{') and '"name"' in json_str:
                    json_str = '{' + json_str
                    # Find or add closing brace
                    if not json_str.rstrip().endswith('}'):
                        # Count braces to see if we need to add one
                        open_braces = json_str.count('{')
                        close_braces = json_str.count('}')
                        if open_braces > close_braces:
                            json_str = json_str + '}' * (open_braces - close_braces)
                    logger.debug(
                        "fixed_malformed_json_tool_call",
                        fixed_json_preview=json_str[:200] if len(json_str) > 200 else json_str,
                    )

                # Try to find valid JSON by finding matching braces
                if json_str.startswith('{'):
                    brace_count = 0
                    end_idx = 0
                    for j, char in enumerate(json_str):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = j + 1
                                break
                    if end_idx > 0:
                        json_str = json_str[:end_idx]

                # Try to parse the JSON
                tool_data = json.loads(json_str)

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
            except json.JSONDecodeError as e:
                logger.warning(
                    "failed_to_parse_text_tool_call",
                    error=str(e),
                    match_preview=match[:200] if len(match) > 200 else match,
                    json_str_preview=json_str[:200] if json_str else None,
                )
                # Try to extract tool name and use malformed args parser
                name_match = re.search(r'"name"\s*:\s*"([^"]+)"', json_str)
                if name_match:
                    tool_name = name_match.group(1)
                    # Try to extract arguments section
                    args_match = re.search(r'"arguments"\s*:\s*(\{[\s\S]*)', json_str)
                    if args_match:
                        args_str = args_match.group(1)
                        args = self._parse_malformed_args(args_str, tool_name)
                        if args:
                            tool_calls.append({
                                "id": f"text_call_{i}",
                                "name": tool_name,
                                "args": args,
                            })
                            logger.info(
                                "recovered_malformed_tool_call",
                                tool_name=tool_name,
                                args_keys=list(args.keys()) if args else [],
                            )
                            continue
                continue
            except Exception as e:
                logger.warning(
                    "unexpected_error_parsing_tool_call",
                    error=str(e),
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
                r'"?summary"?\s*:\s*"((?:[^"\\]|\\.)*)"', args_str, re.IGNORECASE
            )
            return {
                "summary": summary_match.group(1) if summary_match else f"[PARSE_ERROR] Raw: {args_str[:500]}",
                "artifacts": [],
                "data": {},
            }

        if tool_name == "fail":
            reason_match = re.search(
                r'"?reason"?\s*:\s*"([^"]*)"', args_str, re.IGNORECASE
            )
            return {"reason": reason_match.group(1) if reason_match else args_str[:100]}

        # Handle batch_write_files - try to extract files dictionary
        if tool_name in ("coding_batch_write_files", "batch_write_files"):
            return self._parse_batch_write_files_args(args_str)

        logger.warning(
            "could_not_parse_malformed_args", tool_name=tool_name, args=args_str[:200]
        )
        return {}

    def _parse_batch_write_files_args(self, args_str: str) -> dict[str, Any]:
        """Parse malformed batch_write_files arguments.

        This is a specialized parser for batch_write_files which often has
        issues with JSON escaping in file content.
        """
        result = {"files": {}}

        # Try to extract workspace_id first
        ws_match = re.search(r'"workspace_id"\s*:\s*"([^"]+)"', args_str)
        if ws_match:
            result["workspace_id"] = ws_match.group(1)

        # Try to find the files object
        files_match = re.search(r'"files"\s*:\s*\{', args_str)
        if not files_match:
            logger.warning("batch_write_files_no_files_key", args_preview=args_str[:200])
            return result

        # Start from the files object
        files_start = files_match.end() - 1  # Include the opening brace
        files_str = args_str[files_start:]

        # Try to extract individual file entries using pattern matching
        # Look for "filename": "content" patterns
        file_pattern = re.compile(
            r'"([^"]+\.[a-zA-Z0-9]+)"\s*:\s*"',  # filename with extension
            re.MULTILINE
        )

        files = {}
        last_end = 0

        for match in file_pattern.finditer(files_str):
            filename = match.group(1)
            content_start = match.end()

            # Find the end of this file content
            # Look for closing quote that's not escaped
            i = content_start
            content_chars = []
            escape_next = False

            while i < len(files_str):
                char = files_str[i]

                if escape_next:
                    # Handle escaped character
                    if char == 'n':
                        content_chars.append('\n')
                    elif char == 't':
                        content_chars.append('\t')
                    elif char == 'r':
                        content_chars.append('\r')
                    elif char == '"':
                        content_chars.append('"')
                    elif char == '\\':
                        content_chars.append('\\')
                    else:
                        content_chars.append(char)
                    escape_next = False
                elif char == '\\':
                    escape_next = True
                elif char == '"':
                    # End of content
                    break
                else:
                    content_chars.append(char)

                i += 1

            if content_chars:
                content = ''.join(content_chars)
                files[filename] = content
                logger.debug(
                    "batch_write_files_extracted_file",
                    filename=filename,
                    content_length=len(content),
                )

        if files:
            result["files"] = files
            logger.info(
                "batch_write_files_recovery_success",
                file_count=len(files),
                filenames=list(files.keys()),
            )
        else:
            logger.warning(
                "batch_write_files_recovery_failed",
                args_preview=args_str[:500],
            )

        return result

    def get_call_history(self) -> list[dict]:
        """Get history of LLM calls for debugging."""
        return self.call_history.copy()

    def clear_call_history(self) -> None:
        """Clear call history."""
        self.call_history = []
