"""Autonomous Agent implementation.

An Agent receives a natural language task and uses MCPs autonomously
to complete it. It decides when it's done and reports results back.
"""

import json
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from druppie.core.models import AgentDefinition, AgentResult, TokenUsage
from druppie.mcp import MCPClient, MCPRegistry

logger = structlog.get_logger()


# --- Control Tool Schemas ---


class DoneArgs(BaseModel):
    """Arguments for the done() control tool."""

    summary: str = Field(description="Summary of what was accomplished")
    artifacts: list[str] = Field(
        default_factory=list, description="Paths to files created/modified"
    )
    data: dict[str, Any] = Field(
        default_factory=dict, description="Structured data to return"
    )


class FailArgs(BaseModel):
    """Arguments for the fail() control tool."""

    reason: str = Field(description="Reason why the task could not be completed")


class AskHumanArgs(BaseModel):
    """Arguments for the ask_human() control tool."""

    question: str = Field(description="Question to ask the human")


# --- Agent Implementation ---


class Agent:
    """Autonomous agent that uses MCPs to complete tasks.

    The agent:
    1. Receives a natural language task description
    2. Uses LLM + tools to accomplish the task
    3. Decides when it's done (or if it failed)
    4. Reports results back via AgentResult
    """

    def __init__(
        self,
        definition: AgentDefinition,
        mcp_client: MCPClient,
        mcp_registry: MCPRegistry,
        llm: BaseChatModel,
        emit_event: callable = None,
    ):
        """Initialize the Agent.

        Args:
            definition: Agent definition with system prompt and MCP list
            mcp_client: Client for invoking MCP tools
            mcp_registry: Registry of available MCP servers
            llm: LangChain chat model
            emit_event: Optional callback to emit real-time events
        """
        self.definition = definition
        self.mcp_client = mcp_client
        self.mcp_registry = mcp_registry
        self.llm = llm
        self.emit_event = emit_event
        self.total_usage = TokenUsage()
        self.logger = logger.bind(agent_id=definition.id)

        # Track all LLM calls with full details
        self.llm_calls: list[dict] = []

        # Build tools from agent's MCP list
        self.tools = self._build_tools()

        # Bind tools to LLM
        if self.tools:
            self.llm_with_tools = llm.bind_tools(self.tools)
        else:
            self.llm_with_tools = llm

    def _build_tools(self) -> list[StructuredTool]:
        """Build LangChain tools from agent's MCP definitions."""
        tools = []

        for mcp_id in self.definition.mcps:
            server = self.mcp_registry.get_server(mcp_id)
            if not server:
                self.logger.warning(f"MCP server not found: {mcp_id}")
                continue

            for tool_def in server.tools:
                tool_name = f"{mcp_id}.{tool_def.name}"
                try:
                    tool = self._create_mcp_tool(tool_name, tool_def)
                    tools.append(tool)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to create tool {tool_name}: {e}"
                    )

        # Add control tools (done, fail, ask_human)
        tools.extend(self._create_control_tools())

        self.logger.info(f"Agent initialized with {len(tools)} tools")
        return tools

    def _create_mcp_tool(self, tool_name: str, tool_def: Any) -> StructuredTool:
        """Create a LangChain tool from an MCP tool definition."""
        client = self.mcp_client

        async def invoke_tool(**kwargs: Any) -> str:
            try:
                result = await client.invoke(tool_name, kwargs)
                return json.dumps(result, default=str)
            except Exception as e:
                return json.dumps({"error": str(e)})

        # Create safe name for LangChain (no dots)
        safe_name = tool_name.replace(".", "__")

        return StructuredTool.from_function(
            coroutine=invoke_tool,
            name=safe_name,
            description=tool_def.description or f"Invoke {tool_name}",
        )

    def _create_control_tools(self) -> list[StructuredTool]:
        """Create control flow tools for the agent."""

        def done(summary: str, artifacts: list[str] = [], data: dict = {}) -> str:
            """Call this when your task is complete.
            Provide a summary of what you accomplished."""
            return f"__DONE__|{json.dumps({'summary': summary, 'artifacts': artifacts, 'data': data})}"

        def fail(reason: str) -> str:
            """Call this if you cannot complete the task.
            Explain why you cannot continue."""
            return f"__FAIL__|{json.dumps({'reason': reason})}"

        def ask_human(question: str) -> str:
            """Call this if you need clarification from a human.
            Ask a specific question."""
            return f"__ASK_HUMAN__|{json.dumps({'question': question})}"

        return [
            StructuredTool.from_function(
                func=done,
                name="done",
                description="Call when your task is complete. Provide a summary of accomplishments.",
                args_schema=DoneArgs,
            ),
            StructuredTool.from_function(
                func=fail,
                name="fail",
                description="Call if you cannot complete the task. Explain the reason.",
                args_schema=FailArgs,
            ),
            StructuredTool.from_function(
                func=ask_human,
                name="ask_human",
                description="Call if you need clarification from a human.",
                args_schema=AskHumanArgs,
            ),
        ]

    def _emit(self, event_type: str, title: str, description: str, status: str = "info", data: dict = None):
        """Emit a real-time event if callback is provided."""
        if self.emit_event:
            import time
            self.emit_event({
                "event_type": event_type,
                "title": title,
                "description": description,
                "status": status,
                "data": data or {},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "agent_id": self.definition.id,
            })

    def _record_llm_call(
        self,
        messages: list,
        response: Any,
        duration_ms: int,
        iteration: int,
        tool_calls: list = None,
    ):
        """Record an LLM call with full details for debugging."""
        import time

        # Extract content from response
        content = getattr(response, "content", "") or ""

        # Convert messages to serializable format
        serialized_messages = []
        for msg in messages:
            msg_dict = {"role": type(msg).__name__.replace("Message", "").lower()}
            if hasattr(msg, "content"):
                msg_dict["content"] = msg.content
            if hasattr(msg, "tool_call_id"):
                msg_dict["tool_call_id"] = msg.tool_call_id
            serialized_messages.append(msg_dict)

        # Extract usage
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.get("input_tokens", 0),
                "completion_tokens": response.usage_metadata.get("output_tokens", 0),
                "total_tokens": response.usage_metadata.get("input_tokens", 0) + response.usage_metadata.get("output_tokens", 0),
            }

        call_record = {
            "name": f"{self.definition.id} (iteration {iteration})",
            "agent_id": self.definition.id,
            "iteration": iteration,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": getattr(self.llm, "model", "unknown"),
            "duration_ms": duration_ms,
            "status": "success",
            "request": {"messages": serialized_messages},
            "response": content[:2000] if content else "",
            "tool_calls": [
                {"name": tc.get("name"), "args": tc.get("args")}
                for tc in (tool_calls or [])
            ],
            "usage": usage,
        }

        self.llm_calls.append(call_record)

    async def execute(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a task autonomously.

        Args:
            task_description: Natural language description of what to do
            context: Additional context (results from other agents, etc.)

        Returns:
            AgentResult with success/failure and outputs
        """
        import time as time_module

        context = context or {}
        self.total_usage = TokenUsage()
        self.llm_calls = []  # Reset for this execution

        self.logger.info(
            "Starting task execution",
            task=task_description[:100],
        )

        self._emit(
            "agent_started",
            f"Agent: {self.definition.name}",
            f"Starting task: {task_description[:80]}...",
            "working",
            {"agent_id": self.definition.id, "task": task_description[:200]},
        )

        # Build initial messages
        messages = [
            SystemMessage(content=self.definition.system_prompt),
            HumanMessage(content=self._format_task(task_description, context)),
        ]

        artifacts = []

        # Agent loop
        for iteration in range(self.definition.max_iterations):
            self.logger.debug(f"Agent iteration {iteration + 1}")

            self._emit(
                "llm_calling",
                f"LLM Call: {self.definition.id}",
                f"Iteration {iteration + 1}/{self.definition.max_iterations}",
                "working",
                {"agent_id": self.definition.id, "iteration": iteration + 1},
            )

            try:
                # Get LLM response with timing
                start_time = time_module.time()
                response = await self.llm_with_tools.ainvoke(messages)
                duration_ms = int((time_module.time() - start_time) * 1000)

                messages.append(response)

                # Track usage
                self._track_usage(response)

                # Get tool calls for recording
                tool_calls = getattr(response, "tool_calls", [])

                # Record this LLM call with full details
                self._record_llm_call(
                    messages=messages[:-1],  # Messages sent (excluding response)
                    response=response,
                    duration_ms=duration_ms,
                    iteration=iteration + 1,
                    tool_calls=tool_calls,
                )

                self._emit(
                    "llm_response",
                    f"LLM Response: {self.definition.id}",
                    f"Got response in {duration_ms}ms" + (f" with {len(tool_calls)} tool call(s)" if tool_calls else ""),
                    "success",
                    {
                        "agent_id": self.definition.id,
                        "duration_ms": duration_ms,
                        "tool_calls": [tc.get("name") for tc in tool_calls] if tool_calls else [],
                    },
                )

                if not tool_calls:
                    # No tool calls - agent might be done or confused
                    # Check if the response indicates completion
                    content = getattr(response, "content", "")
                    if content:
                        self.logger.info("Agent finished without explicit done()")
                        self._emit(
                            "agent_completed",
                            f"Agent: {self.definition.name}",
                            "Completed (no explicit done call)",
                            "success",
                            {"agent_id": self.definition.id},
                        )
                        return AgentResult(
                            success=True,
                            summary=content,
                            artifacts=artifacts,
                            token_usage=self.total_usage,
                            llm_calls=self.llm_calls,
                        )
                    else:
                        self._emit(
                            "agent_error",
                            f"Agent: {self.definition.name}",
                            "No output or tool calls",
                            "error",
                            {"agent_id": self.definition.id},
                        )
                        return AgentResult(
                            success=False,
                            summary="Agent stopped without calling done() or providing output",
                            error="No tool calls or content in response",
                            token_usage=self.total_usage,
                            llm_calls=self.llm_calls,
                        )

                # Execute tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "")

                    self.logger.debug(f"Executing tool: {tool_name}", args=tool_args)

                    self._emit(
                        "tool_executing",
                        f"Tool: {tool_name}",
                        f"Executing with args: {str(tool_args)[:100]}...",
                        "working",
                        {"agent_id": self.definition.id, "tool": tool_name, "args": tool_args},
                    )

                    # Execute the tool
                    tool_start = time_module.time()
                    result = await self._execute_tool(tool_name, tool_args)
                    tool_duration = int((time_module.time() - tool_start) * 1000)

                    # Check for control commands
                    if result.startswith("__DONE__|"):
                        data = json.loads(result.split("|", 1)[1])
                        self._emit(
                            "agent_completed",
                            f"Agent: {self.definition.name}",
                            data.get("summary", "Task completed")[:100],
                            "success",
                            {"agent_id": self.definition.id, "summary": data.get("summary"), "data": data.get("data")},
                        )
                        return AgentResult(
                            success=True,
                            summary=data.get("summary", "Task completed"),
                            artifacts=data.get("artifacts", []) + artifacts,
                            data=data.get("data", {}),
                            token_usage=self.total_usage,
                            llm_calls=self.llm_calls,
                        )

                    if result.startswith("__FAIL__|"):
                        data = json.loads(result.split("|", 1)[1])
                        self._emit(
                            "agent_failed",
                            f"Agent: {self.definition.name}",
                            data.get("reason", "Task failed")[:100],
                            "error",
                            {"agent_id": self.definition.id, "reason": data.get("reason")},
                        )
                        return AgentResult(
                            success=False,
                            summary=data.get("reason", "Task failed"),
                            error=data.get("reason"),
                            artifacts=artifacts,
                            token_usage=self.total_usage,
                            llm_calls=self.llm_calls,
                        )

                    if result.startswith("__ASK_HUMAN__|"):
                        # For now, treat as needing intervention
                        data = json.loads(result.split("|", 1)[1])
                        self._emit(
                            "agent_question",
                            f"Agent: {self.definition.name}",
                            f"Needs input: {data.get('question', '')[:80]}",
                            "warning",
                            {"agent_id": self.definition.id, "question": data.get("question")},
                        )
                        return AgentResult(
                            success=False,
                            summary=f"Need human input: {data.get('question')}",
                            error="Human intervention required",
                            data={"question": data.get("question")},
                            artifacts=artifacts,
                            token_usage=self.total_usage,
                            llm_calls=self.llm_calls,
                        )

                    self._emit(
                        "tool_completed",
                        f"Tool: {tool_name}",
                        f"Completed in {tool_duration}ms",
                        "success",
                        {"agent_id": self.definition.id, "tool": tool_name, "duration_ms": tool_duration},
                    )

                    # Add tool result to messages
                    messages.append(
                        ToolMessage(
                            content=result,
                            tool_call_id=tool_id,
                        )
                    )

                    # Track artifacts (files created/modified)
                    if "path" in tool_args:
                        artifacts.append(tool_args["path"])

            except Exception as e:
                self.logger.error(f"Error in iteration {iteration + 1}: {e}")
                self._emit(
                    "agent_error",
                    f"Agent: {self.definition.name}",
                    f"Error: {str(e)[:100]}",
                    "error",
                    {"agent_id": self.definition.id, "error": str(e)},
                )
                # Continue to next iteration unless it's a critical error
                if iteration == self.definition.max_iterations - 1:
                    return AgentResult(
                        success=False,
                        summary=f"Execution error: {e}",
                        error=str(e),
                        artifacts=artifacts,
                        token_usage=self.total_usage,
                        llm_calls=self.llm_calls,
                    )

        # Max iterations reached
        self.logger.warning("Max iterations reached")
        self._emit(
            "agent_error",
            f"Agent: {self.definition.name}",
            f"Max iterations ({self.definition.max_iterations}) reached",
            "error",
            {"agent_id": self.definition.id},
        )
        return AgentResult(
            success=False,
            summary=f"Max iterations ({self.definition.max_iterations}) reached",
            error="Max iterations exceeded",
            artifacts=artifacts,
            token_usage=self.total_usage,
            llm_calls=self.llm_calls,
        )

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute a tool by name."""
        # Find the tool
        for tool in self.tools:
            if tool.name == tool_name:
                try:
                    if tool.coroutine:
                        return await tool.coroutine(**arguments)
                    else:
                        return tool.func(**arguments)
                except Exception as e:
                    return json.dumps({"error": str(e)})

        return json.dumps({"error": f"Tool not found: {tool_name}"})

    def _track_usage(self, response: Any) -> None:
        """Track token usage from response."""
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            self.total_usage.prompt_tokens += response.usage_metadata.get(
                "input_tokens", 0
            )
            self.total_usage.completion_tokens += response.usage_metadata.get(
                "output_tokens", 0
            )
            self.total_usage.total_tokens = (
                self.total_usage.prompt_tokens + self.total_usage.completion_tokens
            )

    def _format_task(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> str:
        """Format the task message with context."""
        msg = f"## Task\n{task_description}\n"

        if context:
            msg += "\n## Context\n"
            for key, value in context.items():
                if isinstance(value, dict):
                    msg += f"- {key}:\n"
                    for k, v in value.items():
                        msg += f"  - {k}: {v}\n"
                else:
                    msg += f"- {key}: {value}\n"

        msg += "\n## Instructions\n"
        msg += "Use the available tools to complete this task.\n"
        msg += "When finished, call done() with a summary of what you accomplished.\n"
        msg += "If you cannot complete the task, call fail() with the reason.\n"
        msg += "If you need clarification, call ask_human() with your question.\n"

        return msg
