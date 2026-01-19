"""Reusable node types for LangGraph workflows.

These are building blocks for creating workflows.
"""

from typing import Any, Callable
import structlog

from druppie.workflows.engine import WorkflowState

logger = structlog.get_logger()


class AgentNode:
    """A node that runs an LLM agent with access to tools.

    This is the main way to add AI reasoning to a workflow.
    """

    def __init__(
        self,
        llm: Any,  # LangChain LLM
        system_prompt: str,
        tools: list[Any] | None = None,
        name: str = "agent",
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.name = name

        # Bind tools to LLM if provided
        if self.tools:
            self.llm_with_tools = llm.bind_tools(self.tools)
        else:
            self.llm_with_tools = llm

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        """Execute the agent node."""
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [SystemMessage(content=self.system_prompt)]
        messages.extend(state.get("messages", []))

        # Add context from current item if available
        if state.get("current_item"):
            context_msg = f"Context: {state['current_item']}"
            messages.append(HumanMessage(content=context_msg))

        # Invoke LLM
        response = await self.llm_with_tools.ainvoke(messages)

        # Update messages
        new_messages = list(state.get("messages", []))
        new_messages.append(response)

        # Store result
        step_results = dict(state.get("step_results", {}))
        step_results[self.name] = {
            "content": response.content,
            "tool_calls": getattr(response, "tool_calls", []),
        }

        logger.debug(
            "Agent node completed",
            name=self.name,
            has_tool_calls=bool(getattr(response, "tool_calls", [])),
        )

        return {
            **state,
            "messages": new_messages,
            "step_results": step_results,
        }


class ToolNode:
    """A node that executes MCP tools based on LLM tool calls.

    Used after an AgentNode to execute any tools the agent requested.
    """

    def __init__(self, mcp_client: Any, name: str = "tools"):
        self.mcp_client = mcp_client
        self.name = name

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        """Execute pending tool calls."""
        from langchain_core.messages import ToolMessage

        messages = list(state.get("messages", []))

        # Get the last AI message with tool calls
        last_message = messages[-1] if messages else None
        tool_calls = getattr(last_message, "tool_calls", [])

        if not tool_calls:
            return state

        tool_results = {}
        new_messages = list(messages)

        for tool_call in tool_calls:
            tool_name = tool_call["name"].replace("__", ".")  # Convert back from LangChain format
            arguments = tool_call.get("args", {})

            logger.debug("Executing tool", tool=tool_name, arguments=arguments)

            try:
                result = await self.mcp_client.invoke(tool_name, arguments)
                tool_results[tool_name] = result

                # Add tool message
                new_messages.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"],
                    )
                )
            except Exception as e:
                logger.error("Tool execution failed", tool=tool_name, error=str(e))
                new_messages.append(
                    ToolMessage(
                        content=f"Error: {e}",
                        tool_call_id=tool_call["id"],
                    )
                )

        # Update step results
        step_results = dict(state.get("step_results", {}))
        step_results[self.name] = tool_results

        return {
            **state,
            "messages": new_messages,
            "step_results": step_results,
        }


class HumanReviewNode:
    """A node that pauses workflow for human review.

    The workflow will wait until a human approves or rejects.
    """

    def __init__(
        self,
        prompt: str,
        assigned_group: str | None = None,
        name: str = "review",
    ):
        self.prompt = prompt
        self.assigned_group = assigned_group
        self.name = name

    def __call__(self, state: WorkflowState) -> WorkflowState:
        """Set the workflow to pending review state."""
        logger.info(
            "Human review required",
            prompt=self.prompt,
            group=self.assigned_group,
        )

        step_results = dict(state.get("step_results", {}))
        step_results[self.name] = {
            "status": "pending",
            "prompt": self.prompt,
            "assigned_group": self.assigned_group,
        }

        return {
            **state,
            "pending_review": True,
            "step_results": step_results,
        }


class ConditionalNode:
    """A node that routes to different paths based on a condition.

    Use with graph.add_conditional_edges() to branch the workflow.
    """

    def __init__(
        self,
        condition: Callable[[WorkflowState], str],
        name: str = "router",
    ):
        """
        Args:
            condition: Function that takes state and returns the next node name
            name: Name of this node
        """
        self.condition = condition
        self.name = name

    def __call__(self, state: WorkflowState) -> str:
        """Evaluate condition and return next node."""
        result = self.condition(state)
        logger.debug("Conditional routing", node=self.name, next=result)
        return result


def should_continue(state: WorkflowState) -> str:
    """Standard condition to check if workflow should continue.

    Returns "continue" or "end" based on state.
    """
    if state.get("error"):
        return "end"
    if state.get("pending_review"):
        return "wait"
    if not state.get("should_continue", True):
        return "end"
    return "continue"


def has_tool_calls(state: WorkflowState) -> str:
    """Check if the last message has tool calls.

    Returns "tools" if there are tool calls, "continue" otherwise.
    """
    messages = state.get("messages", [])
    if not messages:
        return "continue"

    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", [])

    return "tools" if tool_calls else "continue"
