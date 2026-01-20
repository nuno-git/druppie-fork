"""Pure LLM Service for Druppie.

This module provides ONLY LLM chat capability. No business logic, no prompts.
All prompts are defined in registry/agents/*.yaml files.
All business logic is handled by AgentRuntime and WorkflowEngine.

Philosophy:
- LLM Service is PURE: only sends messages and returns responses
- No hardcoded prompts here - they live in YAML agent definitions
- No parsing, no business logic - that's for the runtime layer

Supported Providers:
- Z.AI (GLM-4.7): Cloud-based, requires ZAI_API_KEY
- Ollama: Local inference, no API key required
"""

import json
import os
import re
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class ChatOllama:
    """Ollama Chat Model for local LLM inference.

    Uses Ollama's OpenAI-compatible API endpoint.
    No API key required - runs locally.
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 300.0,
    ):
        """Initialize the Ollama client.

        Args:
            model: Model name to use (must be pulled in Ollama)
            base_url: Base URL for Ollama API
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
        """
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.base_url = base_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Track LLM calls for debugging
        self.call_history: list[dict] = []

        # Bound tools for function calling (optional)
        self.bound_tools: list = []

    def chat(
        self,
        messages: list[dict],
        call_name: str = "llm_call",
        **kwargs,
    ) -> str:
        """Send chat completion request to Ollama.

        Args:
            messages: List of message dicts with role and content
            call_name: Name/label for this call (for debugging)

        Returns:
            The LLM's response content as a string
        """
        start_time = time.time()

        # Ollama's OpenAI-compatible endpoint
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        headers = {"Content-Type": "application/json"}

        # Track the call
        call_record = {
            "name": call_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "provider": "ollama",
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
                        f"Ollama API error {response.status_code}: {response.text}"
                    )

                data = response.json()
                call_record["raw_response"] = data

            if not data.get("choices"):
                call_record["status"] = "error"
                call_record["error"] = "No choices in response"
                self.call_history.append(call_record)
                raise ValueError("No response from Ollama")

            content = data["choices"][0].get("message", {}).get("content", "")
            cleaned_content = self._clean_response(content)

            call_record["response"] = cleaned_content
            call_record["response_raw"] = content
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

    def bind_tools(self, tools: list, **kwargs) -> "ChatOllama":
        """Bind tools to the LLM for function calling.

        Note: Ollama supports function calling for some models.
        This creates a new instance with tools bound.

        Args:
            tools: List of tool definitions

        Returns:
            New ChatOllama instance with tools bound
        """
        # Create a new instance with tools
        new_instance = ChatOllama(
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        new_instance.bound_tools = tools
        return new_instance

    def _clean_response(self, text: str) -> str:
        """Clean the response text."""
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
                    # Provide a more helpful error message
                    if response.status_code == 401:
                        error_msg = "Z.AI API key is missing or invalid. Set ZAI_API_KEY environment variable or switch to Ollama (LLM_PROVIDER=ollama)."
                    else:
                        error_msg = f"Z.AI API error {response.status_code}: {response.text}"
                    call_record["error"] = error_msg
                    self.call_history.append(call_record)
                    raise ValueError(error_msg)

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
            call_record["response_raw"] = content  # Raw unclean response for debugging
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

    Provider Selection:
    - If LLM_PROVIDER=ollama or ZAI_API_KEY is not set, uses Ollama
    - Otherwise uses Z.AI

    Usage:
        llm_service = LLMService()
        llm = llm_service.get_llm()
        response = llm.chat(messages, call_name="my_call")
    """

    def __init__(self):
        """Initialize the LLM service."""
        self._llm: ChatZAI | ChatOllama | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name."""
        if self._provider is None:
            provider = os.getenv("LLM_PROVIDER", "auto").lower()
            zai_key = os.getenv("ZAI_API_KEY", "")

            if provider == "ollama":
                self._provider = "ollama"
            elif provider == "zai" and zai_key:
                self._provider = "zai"
            elif provider == "auto":
                # Auto-detect: prefer Z.AI if key is set, otherwise Ollama
                self._provider = "zai" if zai_key else "ollama"
            else:
                # Default to Ollama if no Z.AI key
                self._provider = "ollama" if not zai_key else "zai"

            logger.info("LLM provider selected", provider=self._provider)

        return self._provider

    def get_llm(self) -> ChatZAI | ChatOllama:
        """Get or create the LLM client.

        Returns:
            The LLM instance (ChatZAI or ChatOllama) for making calls
        """
        if self._llm is None:
            provider = self.get_provider()

            if provider == "ollama":
                self._llm = ChatOllama(
                    model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                    base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
                )
                logger.info(
                    "Using Ollama LLM",
                    model=self._llm.model,
                    base_url=self._llm.base_url,
                )
            else:
                self._llm = ChatZAI(
                    api_key=os.getenv("ZAI_API_KEY"),
                    model=os.getenv("ZAI_MODEL", "GLM-4.7"),
                    base_url=os.getenv(
                        "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
                    ),
                )
                logger.info(
                    "Using Z.AI LLM",
                    model=self._llm.model,
                    base_url=self._llm.base_url,
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
