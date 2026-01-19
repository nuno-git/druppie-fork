"""LangGraph-based workflow engine.

This is the core execution engine for Druppie workflows.
Uses LangGraph's StateGraph for defining and executing workflows.
"""

from datetime import datetime
from typing import Any, Callable, TypedDict
import uuid

from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import structlog

from druppie.core.models import Plan, PlanStatus, Step, StepStatus, WorkflowDefinition
from druppie.mcp import MCPClient, MCPRegistry

logger = structlog.get_logger()


class WorkflowState(TypedDict, total=False):
    """State that flows through the workflow graph.

    This is the standard state structure for all Druppie workflows.
    """

    # Messages for chat-based workflows
    messages: list[BaseMessage]

    # Current item being processed (for batch workflows)
    current_item: dict[str, Any]

    # Results from previous steps
    step_results: dict[str, Any]

    # Control flow
    next_step: str | None
    should_continue: bool

    # Human-in-the-loop
    pending_review: bool
    review_result: str | None

    # Error handling
    error: str | None


class WorkflowEngine:
    """Engine for executing LangGraph workflows.

    Provides:
    - Graph building from workflow definitions
    - Execution with state management
    - Integration with MCP tools
    - Human-in-the-loop support
    """

    def __init__(
        self,
        mcp_registry: MCPRegistry,
        mcp_client: MCPClient | None = None,
    ):
        self.mcp_registry = mcp_registry
        self.mcp_client = mcp_client
        self._compiled_graphs: dict[str, Any] = {}

    def create_graph(
        self,
        nodes: dict[str, Callable],
        edges: list[tuple[str, str]],
        conditional_edges: dict[str, tuple[Callable, dict[str, str]]] | None = None,
        entry_point: str = "start",
    ) -> StateGraph:
        """Create a LangGraph StateGraph from nodes and edges.

        Args:
            nodes: Dict of node_name -> node_function
            edges: List of (from_node, to_node) tuples
            conditional_edges: Dict of node_name -> (condition_func, mapping)
            entry_point: Starting node name

        Returns:
            Compiled StateGraph ready for execution
        """
        graph = StateGraph(WorkflowState)

        # Add nodes
        for name, func in nodes.items():
            graph.add_node(name, func)

        # Set entry point
        graph.set_entry_point(entry_point)

        # Add edges
        for from_node, to_node in edges:
            if to_node == "END":
                graph.add_edge(from_node, END)
            else:
                graph.add_edge(from_node, to_node)

        # Add conditional edges
        if conditional_edges:
            for node_name, (condition_func, mapping) in conditional_edges.items():
                # Convert "END" strings to actual END
                resolved_mapping = {
                    k: END if v == "END" else v for k, v in mapping.items()
                }
                graph.add_conditional_edges(node_name, condition_func, resolved_mapping)

        return graph.compile()

    async def execute(
        self,
        graph: Any,  # Compiled StateGraph
        initial_state: WorkflowState | None = None,
        plan: Plan | None = None,
    ) -> WorkflowState:
        """Execute a workflow graph.

        Args:
            graph: Compiled LangGraph StateGraph
            initial_state: Initial state to start with
            plan: Optional Plan to track execution

        Returns:
            Final workflow state
        """
        state: WorkflowState = initial_state or {
            "messages": [],
            "step_results": {},
            "should_continue": True,
            "pending_review": False,
        }

        if plan:
            plan.status = PlanStatus.RUNNING
            plan.updated_at = datetime.utcnow()

        logger.info("Starting workflow execution", plan_id=plan.id if plan else None)

        try:
            # Run the graph
            final_state = await graph.ainvoke(state)

            if plan:
                plan.status = PlanStatus.COMPLETED
                plan.output_data = final_state.get("step_results", {})
                plan.updated_at = datetime.utcnow()

            logger.info(
                "Workflow completed",
                plan_id=plan.id if plan else None,
            )

            return final_state

        except Exception as e:
            logger.error(
                "Workflow failed",
                plan_id=plan.id if plan else None,
                error=str(e),
            )

            if plan:
                plan.status = PlanStatus.FAILED
                plan.updated_at = datetime.utcnow()

            raise

    def create_tool_node(
        self,
        tool_name: str,
        result_key: str | None = None,
    ) -> Callable[[WorkflowState], WorkflowState]:
        """Create a node that invokes an MCP tool.

        Args:
            tool_name: The MCP tool to invoke
            result_key: Key to store result in step_results

        Returns:
            Node function for the graph
        """
        result_key = result_key or tool_name.replace(".", "_")

        async def tool_node(state: WorkflowState) -> WorkflowState:
            if not self.mcp_client:
                raise RuntimeError("MCP client not configured")

            # Get tool arguments from current_item or step_results
            arguments = state.get("current_item", {})

            logger.debug("Executing tool node", tool=tool_name, arguments=arguments)

            result = await self.mcp_client.invoke(tool_name, arguments)

            # Store result
            step_results = dict(state.get("step_results", {}))
            step_results[result_key] = result

            return {**state, "step_results": step_results}

        return tool_node

    def create_llm_node(
        self,
        llm: Any,  # LangChain LLM
        system_prompt: str,
        tools: list[str] | None = None,
        result_key: str = "llm_response",
    ) -> Callable[[WorkflowState], WorkflowState]:
        """Create a node that uses an LLM (optionally with tools).

        Args:
            llm: LangChain LLM instance
            system_prompt: System prompt for the LLM
            tools: Optional list of MCP tool names to make available
            result_key: Key to store result in step_results

        Returns:
            Node function for the graph
        """
        from langchain_core.messages import SystemMessage

        # Bind tools if provided
        if tools and self.mcp_client:
            from druppie.mcp.client import get_langchain_tools

            langchain_tools = get_langchain_tools(self.mcp_client, tools)
            llm_with_tools = llm.bind_tools(langchain_tools)
        else:
            llm_with_tools = llm

        async def llm_node(state: WorkflowState) -> WorkflowState:
            messages = [SystemMessage(content=system_prompt)]
            messages.extend(state.get("messages", []))

            # Add context from current_item
            if state.get("current_item"):
                context = f"Current item: {state['current_item']}"
                messages.append(HumanMessage(content=context))

            response = await llm_with_tools.ainvoke(messages)

            # Update state
            new_messages = list(state.get("messages", []))
            new_messages.append(response)

            step_results = dict(state.get("step_results", {}))
            step_results[result_key] = response.content

            return {
                **state,
                "messages": new_messages,
                "step_results": step_results,
            }

        return llm_node

    def create_human_review_node(
        self,
        review_prompt: str,
        assigned_group: str | None = None,
    ) -> Callable[[WorkflowState], WorkflowState]:
        """Create a node that requires human review.

        The workflow will pause at this node until review is completed.

        Args:
            review_prompt: Prompt to show the reviewer
            assigned_group: Group that should review

        Returns:
            Node function for the graph
        """

        def review_node(state: WorkflowState) -> WorkflowState:
            logger.info(
                "Human review required",
                prompt=review_prompt,
                group=assigned_group,
            )

            return {
                **state,
                "pending_review": True,
                "review_prompt": review_prompt,
                "assigned_group": assigned_group,
            }

        return review_node


def create_simple_workflow(
    name: str,
    steps: list[dict[str, Any]],
    mcp_registry: MCPRegistry,
) -> tuple[StateGraph, WorkflowDefinition]:
    """Helper to create a simple linear workflow from step definitions.

    Args:
        name: Workflow name
        steps: List of step definitions, each with:
            - name: Step name
            - type: "tool", "llm", or "review"
            - tool/prompt/etc: Type-specific config

    Returns:
        Tuple of (compiled graph, workflow definition)
    """
    engine = WorkflowEngine(mcp_registry)

    nodes = {}
    edges = []
    prev_node = None

    for i, step_def in enumerate(steps):
        node_name = step_def["name"]

        if step_def["type"] == "tool":
            nodes[node_name] = engine.create_tool_node(
                step_def["tool"],
                result_key=step_def.get("result_key"),
            )
        elif step_def["type"] == "review":
            nodes[node_name] = engine.create_human_review_node(
                step_def.get("prompt", "Please review"),
                step_def.get("assigned_group"),
            )
        # Add more types as needed

        if prev_node:
            edges.append((prev_node, node_name))
        prev_node = node_name

    # Add final edge to END
    if prev_node:
        edges.append((prev_node, "END"))

    # Compile graph
    entry = steps[0]["name"] if steps else "END"
    graph = engine.create_graph(nodes, edges, entry_point=entry)

    # Create definition
    definition = WorkflowDefinition(
        id=name.lower().replace(" ", "_"),
        name=name,
        graph_definition={"steps": steps},
        required_tools=[s["tool"] for s in steps if s.get("type") == "tool"],
    )

    return graph, definition
