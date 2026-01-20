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


class ChatMock:
    """Mock Chat Model for testing without external LLM.

    Returns predefined responses based on agent type for testing.
    """

    def __init__(self, temperature: float = 0.7, max_tokens: int | None = None):
        """Initialize the mock client."""
        self.model = "mock"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.call_history: list[dict] = []
        self.bound_tools: list = []

    def chat(
        self,
        messages: list[dict],
        call_name: str = "llm_call",
        **kwargs,
    ) -> str:
        """Return mock responses based on agent type."""
        start_time = time.time()

        # Analyze the system prompt to determine agent type
        system_prompt = ""
        user_message = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
            elif msg.get("role") == "user":
                user_message = msg.get("content", "")

        # Generate mock response based on agent type
        response = self._generate_mock_response(system_prompt, user_message, call_name)

        call_record = {
            "name": call_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": "mock",
            "provider": "mock",
            "request": {"messages": messages},
            "response": response,
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": "success",
        }
        self.call_history.append(call_record)

        return response

    def _generate_mock_response(self, system_prompt: str, user_message: str, call_name: str) -> str:
        """Generate appropriate mock response."""
        system_lower = system_prompt.lower()

        # Extract app type from user message for dynamic responses
        user_lower = user_message.lower()
        app_type = "todo"
        if "calculator" in user_lower:
            app_type = "calculator"
        elif "notes" in user_lower:
            app_type = "notes"
        elif "weather" in user_lower:
            app_type = "weather"
        elif "blog" in user_lower:
            app_type = "blog"

        # Router agent response - must match expected schema exactly
        if "router" in system_lower or "intent" in system_lower:
            # The router expects a done() tool call, but we return the data directly
            # The agent runtime will parse this as the result
            return json.dumps({
                "action": "create_project",
                "prompt": f"Create a {app_type} application",
                "answer": None,
                "clarification_needed": False,
                "clarification_question": None,
                "project_context": {
                    "project_name": f"{app_type}-app",
                    "target_project_id": None,
                    "app_type": app_type,
                    "technologies": ["python", "flask"],
                    "features": ["CRUD operations", "basic UI"]
                },
                "deploy_context": None
            })

        # Planner agent response
        if "planner" in system_lower or "plan" in system_lower:
            return json.dumps({
                "plan_type": "workflow",
                "workflow_id": "development_workflow",
                "reasoning": "Using development workflow for new project creation"
            })

        # Developer/code generator response
        if "developer" in system_lower or "code" in system_lower or "implement" in system_lower:
            return json.dumps({
                "status": "success",
                "files_created": ["app.py", "templates/index.html", "static/style.css"],
                "summary": f"Created Flask {app_type} application with basic CRUD operations"
            })

        # Default response
        return json.dumps({
            "status": "success",
            "message": "Task completed successfully",
            "reasoning": "Mock response for testing"
        })

    def get_call_history(self) -> list[dict]:
        """Get the history of LLM calls for debugging."""
        return self.call_history.copy()

    def clear_call_history(self):
        """Clear the call history."""
        self.call_history = []

    def bind_tools(self, tools: list, **kwargs) -> "ChatMock":
        """Bind tools to the LLM."""
        new_instance = ChatMock(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        new_instance.bound_tools = tools
        return new_instance

    async def ainvoke(self, messages: list, **kwargs):
        """Async invoke method compatible with LangChain interface."""
        from langchain_core.messages import AIMessage

        # Convert messages to analyze
        system_prompt = ""
        user_message = ""
        for msg in messages:
            if hasattr(msg, "content"):
                content = msg.content
                if hasattr(msg, "type"):
                    if msg.type == "system":
                        system_prompt = content
                    elif msg.type == "human":
                        user_message = content
            elif isinstance(msg, dict):
                if msg.get("role") == "system":
                    system_prompt = msg.get("content", "")
                elif msg.get("role") == "user":
                    user_message = msg.get("content", "")

        # Generate mock response data
        response_data = json.loads(self._generate_mock_response(system_prompt, user_message, "ainvoke"))

        # Create tool call to done() with the response data
        tool_calls = [{
            "id": "mock_call_001",
            "name": "done",
            "args": {
                "summary": response_data.get("prompt", "Completed analysis"),
                "artifacts": [],
                "data": response_data
            }
        }]

        call_record = {
            "name": "ainvoke",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": "mock",
            "provider": "mock",
            "request": {"messages_count": len(messages)},
            "response": json.dumps(response_data),
            "tool_calls": tool_calls,
            "duration_ms": 1,
            "status": "success",
        }
        self.call_history.append(call_record)

        return AIMessage(
            content="",
            tool_calls=tool_calls,
            response_metadata={"model": "mock", "provider": "mock"},
        )


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
            tools: List of tool definitions (LangChain StructuredTool objects)

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

    def _convert_messages_for_ollama(self, messages: list) -> list[dict]:
        """Convert LangChain messages to Ollama format."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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
                                "name": tc.get("name"),
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
            elif isinstance(msg, dict):
                result.append(msg)
            else:
                # Fallback for unknown message types
                result.append({"role": "user", "content": str(msg)})
        return result

    def _convert_tools_for_ollama(self) -> list[dict]:
        """Convert LangChain tools to Ollama/OpenAI format."""
        if not self.bound_tools:
            return []

        tools = []
        for tool in self.bound_tools:
            # LangChain StructuredTool has name, description, and args_schema
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }

            # Extract parameters from args_schema if available
            if hasattr(tool, "args_schema") and tool.args_schema:
                schema = tool.args_schema.model_json_schema()
                tool_def["function"]["parameters"] = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                }

            tools.append(tool_def)

        return tools

    async def ainvoke(self, messages: list, **kwargs):
        """Async invoke method compatible with LangChain interface.

        Args:
            messages: List of LangChain message objects

        Returns:
            AIMessage with content and optional tool_calls
        """
        from langchain_core.messages import AIMessage

        start_time = time.time()

        # Convert messages to Ollama format
        ollama_messages = self._convert_messages_for_ollama(messages)

        # Ollama's OpenAI-compatible endpoint
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        # Add tools if bound
        tools = self._convert_tools_for_ollama()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}

        # Track the call
        call_record = {
            "name": "ainvoke",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "provider": "ollama",
            "url": url,
            "request": {
                "model": self.model,
                "messages": ollama_messages,
                "temperature": self.temperature,
                "tools": tools if tools else None,
            },
            "response": None,
            "raw_response": None,
            "duration_ms": None,
            "status": "pending",
            "error": None,
        }

        try:
            # Use httpx async client
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

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

            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")

            # Extract tool calls if present
            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    func = tc.get("function", {})
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "args": json.loads(func.get("arguments", "{}")),
                    })

            call_record["response"] = content
            call_record["tool_calls"] = tool_calls
            call_record["status"] = "success"
            call_record["usage"] = data.get("usage", {})
            self.call_history.append(call_record)

            # Return LangChain AIMessage
            return AIMessage(
                content=content,
                tool_calls=tool_calls,
                response_metadata={
                    "model": self.model,
                    "provider": "ollama",
                    "usage": data.get("usage", {}),
                },
            )

        except Exception as e:
            call_record["duration_ms"] = int((time.time() - start_time) * 1000)
            if call_record["status"] == "pending":
                call_record["status"] = "error"
                call_record["error"] = str(e)
                self.call_history.append(call_record)
            raise

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

        # Bound tools for function calling (optional)
        self.bound_tools: list = []

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

    def bind_tools(self, tools: list, **kwargs) -> "ChatZAI":
        """Bind tools to the LLM for function calling.

        Args:
            tools: List of tool definitions (LangChain StructuredTool objects)

        Returns:
            New ChatZAI instance with tools bound
        """
        new_instance = ChatZAI(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        new_instance.bound_tools = tools
        return new_instance

    def _convert_messages_for_zai(self, messages: list) -> list[dict]:
        """Convert LangChain messages to Z.AI format."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                msg_dict = {"role": "assistant", "content": msg.content or ""}
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
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
            elif isinstance(msg, dict):
                result.append(msg)
            else:
                result.append({"role": "user", "content": str(msg)})
        return result

    def _convert_tools_for_zai(self) -> list[dict]:
        """Convert LangChain tools to Z.AI/OpenAI format."""
        if not hasattr(self, "bound_tools") or not self.bound_tools:
            return []

        tools = []
        for tool in self.bound_tools:
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }

            if hasattr(tool, "args_schema") and tool.args_schema:
                schema = tool.args_schema.model_json_schema()
                tool_def["function"]["parameters"] = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                }

            tools.append(tool_def)

        return tools

    async def ainvoke(self, messages: list, **kwargs):
        """Async invoke method compatible with LangChain interface.

        Args:
            messages: List of LangChain message objects

        Returns:
            AIMessage with content and optional tool_calls
        """
        from langchain_core.messages import AIMessage

        start_time = time.time()

        # Convert messages to Z.AI format
        zai_messages = self._convert_messages_for_zai(messages)

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.model,
            "messages": zai_messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        # Add tools if bound
        tools = self._convert_tools_for_zai()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        call_record = {
            "name": "ainvoke",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": self.model,
            "provider": "zai",
            "url": url,
            "request": {
                "model": self.model,
                "messages": zai_messages,
                "temperature": self.temperature,
                "tools": tools if tools else None,
            },
            "response": None,
            "raw_response": None,
            "duration_ms": None,
            "status": "pending",
            "error": None,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                call_record["duration_ms"] = int((time.time() - start_time) * 1000)

                if response.status_code != 200:
                    call_record["status"] = "error"
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

            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")

            # Extract tool calls if present
            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    func = tc.get("function", {})
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "args": json.loads(func.get("arguments", "{}")),
                    })

            call_record["response"] = content
            call_record["tool_calls"] = tool_calls
            call_record["status"] = "success"
            call_record["usage"] = data.get("usage", {})
            self.call_history.append(call_record)

            return AIMessage(
                content=content,
                tool_calls=tool_calls,
                response_metadata={
                    "model": self.model,
                    "provider": "zai",
                    "usage": data.get("usage", {}),
                },
            )

        except Exception as e:
            call_record["duration_ms"] = int((time.time() - start_time) * 1000)
            if call_record["status"] == "pending":
                call_record["status"] = "error"
                call_record["error"] = str(e)
                self.call_history.append(call_record)
            raise

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
    - If LLM_PROVIDER=mock, uses mock provider (for testing)
    - If LLM_PROVIDER=ollama or ZAI_API_KEY is not set, uses Ollama
    - Otherwise uses Z.AI

    Usage:
        llm_service = LLMService()
        llm = llm_service.get_llm()
        response = llm.chat(messages, call_name="my_call")
    """

    def __init__(self):
        """Initialize the LLM service."""
        self._llm: ChatZAI | ChatOllama | ChatMock | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name."""
        if self._provider is None:
            provider = os.getenv("LLM_PROVIDER", "auto").lower()
            zai_key = os.getenv("ZAI_API_KEY", "")

            if provider == "mock":
                self._provider = "mock"
            elif provider == "ollama":
                self._provider = "ollama"
            elif provider == "zai" and zai_key:
                self._provider = "zai"
            elif provider == "auto":
                # Auto-detect: prefer Z.AI if key is set, otherwise check Ollama, finally mock
                if zai_key:
                    self._provider = "zai"
                else:
                    # Check if Ollama is available
                    try:
                        import httpx
                        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                        with httpx.Client(timeout=2.0) as client:
                            response = client.get(f"{ollama_host}/api/tags")
                            if response.status_code == 200:
                                self._provider = "ollama"
                            else:
                                self._provider = "mock"
                    except Exception:
                        logger.warning("Ollama not available, using mock provider")
                        self._provider = "mock"
            else:
                # Default to Ollama if no Z.AI key
                self._provider = "ollama" if not zai_key else "zai"

            logger.info("LLM provider selected", provider=self._provider)

        return self._provider

    def get_llm(self) -> ChatZAI | ChatOllama | ChatMock:
        """Get or create the LLM client.

        Returns:
            The LLM instance (ChatZAI, ChatOllama, or ChatMock) for making calls
        """
        if self._llm is None:
            provider = self.get_provider()

            if provider == "mock":
                self._llm = ChatMock()
                logger.info("Using Mock LLM (for testing)")
            elif provider == "ollama":
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
