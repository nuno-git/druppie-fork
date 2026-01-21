"""Mock LLM provider for testing.

Returns predefined responses based on agent type.
"""

import json
import time
from typing import Any

from .base import BaseLLM, LLMResponse


class ChatMock(BaseLLM):
    """Mock LLM for testing without external API calls."""

    def __init__(self, temperature: float = 0.7, max_tokens: int | None = None):
        """Initialize mock LLM."""
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.call_history: list[dict] = []
        self._bound_tools: list[dict] = []

    @property
    def model_name(self) -> str:
        return "mock"

    @property
    def provider_name(self) -> str:
        return "mock"

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ChatMock":
        """Create new instance with tools bound."""
        new_instance = ChatMock(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        new_instance._bound_tools = tools
        return new_instance

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Return mock response based on system prompt analysis."""
        start_time = time.time()

        # Analyze messages to determine response type
        system_prompt = ""
        user_message = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
            elif msg.get("role") == "user":
                user_message = msg.get("content", "")

        # Generate mock response
        content, tool_calls = self._generate_response(system_prompt, user_message)

        call_record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": "mock",
            "provider": "mock",
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": "success",
        }
        self.call_history.append(call_record)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=len(str(messages)) // 4,
            completion_tokens=len(content) // 4,
            total_tokens=len(str(messages)) // 4 + len(content) // 4,
            model="mock",
            provider="mock",
        )

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Async version - just calls sync version."""
        return self.chat(messages, tools)

    def _generate_response(
        self, system_prompt: str, user_message: str
    ) -> tuple[str, list[dict]]:
        """Generate mock response based on context."""
        system_lower = system_prompt.lower()
        user_lower = user_message.lower()

        # Extract app type for dynamic responses
        app_type = "todo"
        if "calculator" in user_lower:
            app_type = "calculator"
        elif "notes" in user_lower:
            app_type = "notes"
        elif "weather" in user_lower:
            app_type = "weather"
        elif "blog" in user_lower:
            app_type = "blog"

        # Router agent response
        if "router" in system_lower or "intent" in system_lower:
            data = {
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
                    "features": ["CRUD operations", "basic UI"],
                },
                "deploy_context": None,
            }
            return "", [
                {
                    "id": "mock_call_001",
                    "name": "done",
                    "args": {
                        "summary": data["prompt"],
                        "artifacts": [],
                        "data": data,
                    },
                }
            ]

        # Planner agent response
        if "planner" in system_lower or "plan" in system_lower:
            data = {
                "plan_type": "workflow",
                "workflow_id": "development_workflow",
                "reasoning": "Using development workflow for new project creation",
            }
            return "", [
                {
                    "id": "mock_call_002",
                    "name": "done",
                    "args": {
                        "summary": "Created execution plan",
                        "artifacts": [],
                        "data": data,
                    },
                }
            ]

        # Developer/code generator response
        if (
            "developer" in system_lower
            or "code" in system_lower
            or "implement" in system_lower
        ):
            data = {
                "status": "success",
                "files_created": [
                    "app.py",
                    "templates/index.html",
                    "static/style.css",
                ],
                "summary": f"Created Flask {app_type} application with basic CRUD operations",
            }
            return "", [
                {
                    "id": "mock_call_003",
                    "name": "done",
                    "args": {
                        "summary": data["summary"],
                        "artifacts": data["files_created"],
                        "data": data,
                    },
                }
            ]

        # Default response
        return json.dumps(
            {"status": "success", "message": "Mock response for testing"}
        ), []

    def get_call_history(self) -> list[dict]:
        """Get history of LLM calls."""
        return self.call_history.copy()

    def clear_call_history(self) -> None:
        """Clear call history."""
        self.call_history = []
