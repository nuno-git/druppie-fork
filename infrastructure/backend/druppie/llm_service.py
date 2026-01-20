"""Pure LLM Service for Druppie.

This module provides ONLY LLM chat capability. No business logic, no prompts.
All prompts are defined in registry/agents/*.yaml files.
All business logic is handled by AgentRuntime and WorkflowEngine.

Philosophy:
- LLM Service is PURE: only sends messages and returns responses
- No hardcoded prompts here - they live in YAML agent definitions
- No parsing, no business logic - that's for the runtime layer
"""

import json
import os
import re
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class ChatZAI:
    """Z.AI Chat Model using GLM API (OpenAI-compatible).

    This is the ONLY class that communicates with the LLM.
    It has no knowledge of agents, workflows, or business logic.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "GLM-4.7",
        base_url: str = "https://api.z.ai/api/coding/paas/v4",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 300.0,
    ):
        """Initialize the LLM client.

        Args:
            api_key: API key for authentication
            model: Model name to use
            base_url: Base URL for the API
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or os.getenv("ZAI_API_KEY", "")
        self.model = model or os.getenv("ZAI_MODEL", "GLM-4.7")
        self.base_url = base_url or os.getenv(
            "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Track LLM calls for debugging
        self.call_history: list[dict] = []

    def chat(
        self,
        messages: list[dict],
        call_name: str = "llm_call",
        **kwargs,
    ) -> str:
        """Send chat completion request and return content.

        This is the ONLY method that talks to the LLM.
        No parsing, no business logic - just send messages, get response.

        Args:
            messages: List of message dicts with role and content
            call_name: Name/label for this call (for debugging)

        Returns:
            The LLM's response content as a string
        """
        start_time = time.time()

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Track the call
        call_record = {
            "name": call_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "url": url,
            "request": {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            },
            "response": None,
            "raw_response": None,
            "duration_ms": None,
            "status": "pending",
            "error": None,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)

                call_record["duration_ms"] = int((time.time() - start_time) * 1000)

                if response.status_code != 200:
                    call_record["status"] = "error"
                    call_record["error"] = f"HTTP {response.status_code}: {response.text}"
                    self.call_history.append(call_record)
                    raise ValueError(
                        f"Z.AI API error {response.status_code}: {response.text}"
                    )

                data = response.json()
                call_record["raw_response"] = data

            if not data.get("choices"):
                call_record["status"] = "error"
                call_record["error"] = "No choices in response"
                self.call_history.append(call_record)
                raise ValueError("No response from Z.AI")

            content = data["choices"][0].get("message", {}).get("content", "")
            cleaned_content = self._clean_response(content)

            call_record["response"] = cleaned_content
            call_record["status"] = "success"
            call_record["usage"] = data.get("usage", {})
            self.call_history.append(call_record)

            return cleaned_content

        except Exception as e:
            call_record["duration_ms"] = int((time.time() - start_time) * 1000)
            if call_record["status"] == "pending":
                call_record["status"] = "error"
                call_record["error"] = str(e)
                self.call_history.append(call_record)
            raise

    def get_call_history(self) -> list[dict]:
        """Get the history of LLM calls for debugging."""
        return self.call_history.copy()

    def clear_call_history(self):
        """Clear the call history."""
        self.call_history = []

    def _clean_response(self, text: str) -> str:
        """Clean the response text.

        Removes:
        - <think>...</think> blocks (reasoning traces)
        - Markdown code fences around JSON
        """
        text = text.strip()

        # Remove <think>...</think> blocks
        while "<think>" in text and "</think>" in text:
            start = text.find("<think>")
            end = text.find("</think>") + len("</think>")
            text = text[:start] + text[end:]

        text = text.strip()

        # Remove markdown code fences for JSON
        if text.startswith("```json"):
            text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
        elif text.startswith("```"):
            text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

        return text.strip()


class LLMService:
    """Service wrapper for LLM operations.

    This class provides a clean interface for using the LLM.
    It does NOT contain business logic - that belongs in AgentRuntime.

    Usage:
        llm_service = LLMService()
        llm = llm_service.get_llm()
        response = llm.chat(messages, call_name="my_call")
    """

    def __init__(self):
        """Initialize the LLM service."""
        self._llm: ChatZAI | None = None

    def get_llm(self) -> ChatZAI:
        """Get or create the LLM client.

        Returns:
            The ChatZAI instance for making LLM calls
        """
        if self._llm is None:
            self._llm = ChatZAI(
                api_key=os.getenv("ZAI_API_KEY"),
                model=os.getenv("ZAI_MODEL", "GLM-4.7"),
                base_url=os.getenv(
                    "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
                ),
            )
        return self._llm

    def get_llm_calls(self) -> list[dict]:
        """Get the history of LLM API calls for debugging."""
        if self._llm is None:
            return []
        return self._llm.get_call_history()

    def clear_llm_calls(self):
        """Clear the LLM call history."""
        if self._llm is not None:
            self._llm.clear_call_history()

    def chat(
        self,
        messages: list[dict],
        call_name: str = "llm_call",
    ) -> str:
        """Send messages to the LLM and get a response.

        This is a convenience method that gets the LLM and calls chat.

        Args:
            messages: List of message dicts with role and content
            call_name: Name for this call (for debugging)

        Returns:
            The LLM response as a string
        """
        return self.get_llm().chat(messages, call_name)

    def parse_json_response(self, text: str) -> dict:
        """Parse JSON from an LLM response.

        This is a utility method for parsing structured responses.
        The actual parsing logic depends on the agent's output_schema.

        Args:
            text: The raw LLM response text

        Returns:
            Parsed dict, or empty dict if parsing fails
        """
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            return {}


# Global singleton for backward compatibility
# New code should use AgentRuntime instead
llm_service = LLMService()
