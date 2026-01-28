"""Agent runtime - clean abstraction for running agents.

Usage:
    result = await Agent("router").run("Create a todo app", session_id="...", agent_run_id="...")
    result = await Agent("developer").run("Implement the API", session_id="...", agent_run_id="...")

HITL (Human-in-the-Loop):
    Agents have built-in HITL tools that do NOT require a separate MCP server:
    - hitl_ask_question: Ask user a free-form text question
    - hitl_ask_multiple_choice_question: Ask user to select from choices

    When an agent calls these tools, execution pauses and the question is
    saved to the database. The workflow resumes when the user answers.
"""

import json
import os
import time
from typing import Any

import structlog
import yaml

from druppie.agents.models import AgentDefinition
from druppie.agents.builtin_tools import BUILTIN_TOOLS, execute_builtin_tool, is_builtin_tool
from druppie.llm import get_llm_service
from druppie.core.mcp_client import generate_tool_descriptions

logger = structlog.get_logger()


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class AgentNotFoundError(AgentError):
    """Agent definition not found."""
    pass


class AgentMaxIterationsError(AgentError):
    """Agent exceeded maximum iterations."""
    pass


class Agent:
    """Clean agent abstraction.

    Handles:
    - Loading YAML definition
    - Building messages with system prompt
    - Running tool-calling loop
    - Parsing output

    The agent can call any MCP tool. If it calls hitl:ask,
    execution pauses and saves state to database.

    Session and agent_run IDs are passed explicitly (no global state).
    """

    _definitions_path: str = None
    _cache: dict[str, "AgentDefinition"] = {}

    def __init__(self, agent_id: str):
        """Initialize agent by ID.

        Args:
            agent_id: Agent identifier (e.g., "router", "developer")
        """
        self.id = agent_id
        self.definition = self._load_definition(agent_id)
        self._llm = None
        self._mcp_client = None

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions."""
        cls._definitions_path = path
        cls._cache.clear()

    @classmethod
    def _get_definitions_path(cls) -> str:
        """Get the path to agent definitions."""
        if cls._definitions_path:
            return cls._definitions_path
        # Default: druppie/agents/definitions/
        return os.path.join(os.path.dirname(__file__), "definitions")

    @classmethod
    def _load_definition(cls, agent_id: str) -> AgentDefinition:
        """Load agent definition from YAML."""
        if agent_id in cls._cache:
            return cls._cache[agent_id]

        path = os.path.join(cls._get_definitions_path(), f"{agent_id}.yaml")

        if not os.path.exists(path):
            raise AgentNotFoundError(f"Agent '{agent_id}' not found at {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        definition = AgentDefinition(**data)
        cls._cache[agent_id] = definition

        logger.debug("agent_definition_loaded", agent_id=agent_id)
        return definition

    @classmethod
    def list_agents(cls) -> list[str]:
        """List available agent IDs."""
        path = cls._get_definitions_path()
        if not os.path.exists(path):
            return []
        return [
            f.replace(".yaml", "").replace(".yml", "")
            for f in os.listdir(path)
            if f.endswith((".yaml", ".yml"))
        ]

    @property
    def llm(self):
        """Get LLM service (lazy loaded).

        Note: Currently uses global LLM config from environment.
        Agent-specific model/temperature settings in YAML are ignored.
        """
        if self._llm is None:
            self._llm = get_llm_service().get_llm()
        return self._llm

    @property
    def mcp_client(self):
        """Get MCP client (lazy loaded)."""
        if self._mcp_client is None:
            from druppie.api.deps import get_db
            from druppie.core.mcp_client import get_mcp_client
            db = next(get_db())
            self._mcp_client = get_mcp_client(db)
        return self._mcp_client

    async def run(
        self,
        prompt: str,
        session_id: str,
        agent_run_id: str,
        context: dict = None,
    ) -> Any:
        """Run the agent with the given prompt.

        Args:
            prompt: User prompt or task description
            session_id: Session ID
            agent_run_id: Agent run ID for tracking
            context: Optional context dict (previous results, etc.)

        Returns:
            Parsed result from agent's final response, or paused state with agent_state

        Note:
            Built-in HITL tools (hitl_ask_question, hitl_ask_multiple_choice_question)
            cause execution to pause. The question is saved to the database and
            the workflow resumes when the user answers.
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_prompt(prompt, context)},
        ]

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=0,
        )

    async def resume(
        self,
        agent_state: dict,
        answer: str,
        session_id: str,
        agent_run_id: str,
    ) -> Any:
        """Resume the agent from a paused state with the user's answer.

        Args:
            agent_state: The saved agent state from when it paused
            answer: User's answer to the HITL question
            session_id: Session ID
            agent_run_id: Agent run ID for tracking

        Returns:
            Parsed result from agent's final response, or paused state
        """
        # Restore state
        messages = agent_state.get("messages", [])
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        question = agent_state.get("question", "")

        # Add the HITL answer as a tool response
        # The last assistant message should have the HITL tool call
        messages.append({
            "role": "tool",
            "tool_call_id": agent_state.get("tool_call_id", f"hitl_{start_iteration}"),
            "content": json.dumps({
                "status": "answered",
                "answer": answer,
                "question": question,
            }),
        })

        logger.info(
            "agent_resume",
            agent_id=self.id,
            iteration=start_iteration,
            answer_preview=answer[:50] if answer else "",
        )

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
        )

    async def resume_from_approval(
        self,
        agent_state: dict,
        tool_result: dict,
        session_id: str,
        agent_run_id: str,
    ) -> Any:
        """Resume the agent from a paused state after MCP tool approval.

        Args:
            agent_state: The saved agent state from when it paused
            tool_result: Result from the approved tool execution
            session_id: Session ID
            agent_run_id: Agent run ID for tracking

        Returns:
            Parsed result from agent's final response, or paused state
        """
        # Restore state
        messages = agent_state.get("messages", [])
        prompt = agent_state.get("prompt", "")
        context = agent_state.get("context", {})
        start_iteration = agent_state.get("iteration", 0)
        tool_call_id = agent_state.get("tool_call_id", f"call_{start_iteration}")

        # Add the tool result as a tool response
        # The last message should be the assistant message with the tool call
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(tool_result) if isinstance(tool_result, (dict, list)) else str(tool_result),
        })

        logger.info(
            "agent_resume_from_approval",
            agent_id=self.id,
            iteration=start_iteration,
            tool=agent_state.get("tool_name"),
            tool_result_preview=str(tool_result)[:100] if tool_result else "",
        )

        return await self._run_loop(
            messages=messages,
            prompt=prompt,
            context=context,
            session_id=session_id,
            agent_run_id=agent_run_id,
            start_iteration=start_iteration,
        )

    async def _run_loop(
        self,
        messages: list[dict],
        prompt: str,
        context: dict | None,
        session_id: str,
        agent_run_id: str,
        start_iteration: int,
    ) -> Any:
        """Internal tool-calling loop.

        Args:
            messages: Current message history
            prompt: Original prompt
            context: Original context
            session_id: Session ID
            agent_run_id: Agent run ID for tracking
            start_iteration: Iteration to start from

        Returns:
            Parsed result or paused state
        """
        # Get tools for this agent's MCPs with full schemas from servers
        # Filter out 'hitl' from MCP IDs - we use built-in HITL tools instead
        mcp_ids = self.definition.get_mcp_names() if hasattr(self.definition, 'get_mcp_names') else self.definition.mcps
        mcp_ids = [m for m in mcp_ids if m != "hitl"]
        tools = await self.mcp_client.to_openai_tools_async(mcp_ids)

        # Add built-in HITL tools (always available to all agents)
        tools.extend(BUILTIN_TOOLS)

        # Build a mapping of tool_name -> required_fields for validation
        tool_schemas: dict[str, dict] = {}
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                tool_name = func.get("name", "")
                params = func.get("parameters", {})
                tool_schemas[tool_name] = {
                    "required": params.get("required", []),
                    "properties": params.get("properties", {}),
                }

        max_iterations = self.definition.max_iterations or 10

        # Only log start on first iteration
        if start_iteration == 0:
            logger.info(
                "agent_run_start",
                agent_id=self.id,
                prompt_length=len(prompt),
                tools_count=len(tools),
                session_id=session_id,
                agent_run_id=agent_run_id,
            )

        for iteration in range(start_iteration, max_iterations):
            start_time = time.time()
            response = await self.llm.achat(messages, tools)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.debug(
                "llm_call",
                agent_id=self.id,
                iteration=iteration,
                duration_ms=duration_ms,
                has_tool_calls=bool(response.tool_calls),
            )

            # No tool calls - check if agent is trying to communicate without tools
            if not response.tool_calls:
                # Router and planner have special JSON output formats - don't retry them
                # They output their results directly without using tools
                agents_with_direct_output = ("router", "planner")

                # If agent output content without using tools, remind it and retry
                # (but not for router/planner which have special output formats)
                if (response.content
                    and iteration < max_iterations - 1
                    and self.id not in agents_with_direct_output):
                    logger.warning(
                        "agent_no_tool_calls_retry",
                        agent_id=self.id,
                        iteration=iteration,
                        content_preview=response.content[:100] if response.content else "",
                    )
                    # Add the agent's response and a reminder to use tools
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "ERROR: You output plain text instead of a tool call. Your text was ignored.\n\n"
                            "You MUST use a tool call. Use this exact format:\n"
                            '<tool_call>{"name": "tool_name", "arguments": {"key": "value"}}</tool_call>\n\n'
                            "Examples:\n"
                            '- To ask user: <tool_call>{"name": "hitl_ask_question", "arguments": {"question": "Your question?"}}</tool_call>\n'
                            '- When done: <tool_call>{"name": "done", "arguments": {"summary": "What you accomplished"}}</tool_call>\n\n'
                            "Try again with a proper tool call."
                        ),
                    })
                    continue  # Retry with reminder

                # Agent is done (no content or last iteration)
                logger.info(
                    "agent_run_complete",
                    agent_id=self.id,
                    iterations=iteration + 1,
                    session_id=session_id,
                )
                return self._parse_output(response.content)

            # Execute tools
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})

                logger.debug(
                    "agent_tool_call",
                    agent_id=self.id,
                    tool=tool_name,
                    iteration=iteration,
                    session_id=session_id,
                )

                # Check if this is a built-in HITL tool
                if is_builtin_tool(tool_name):
                    logger.info(
                        "agent_hitl_tool_call",
                        agent_id=self.id,
                        tool=tool_name,
                        question=tool_args.get("question", "")[:100],
                    )
                    result = await execute_builtin_tool(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        session_id=session_id,
                        agent_run_id=agent_run_id,
                        agent_id=self.id,
                    )

                    # Check if paused for question
                    if result.get("status") == "paused":
                        logger.info(
                            "agent_paused_for_question",
                            agent_id=self.id,
                            tool=tool_name,
                            question_id=result.get("question_id"),
                            session_id=session_id,
                        )

                        # Add the assistant message with the HITL tool call
                        # This is needed so when we resume, we can add the tool response
                        tool_call_id = tool_call.get("id", f"hitl_{iteration}")
                        messages.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                                },
                            }],
                        })

                        # Build agent state for resumption
                        agent_state = {
                            "agent_id": self.id,
                            "messages": messages,
                            "prompt": prompt,
                            "context": context,
                            "iteration": iteration,
                            "tool_call_id": tool_call_id,
                            "question": result.get("question"),
                        }

                        # Save agent_state to Question record for resumption
                        question_id = result.get("question_id")
                        if question_id:
                            try:
                                from druppie.api.deps import get_db
                                from druppie.repositories import QuestionRepository
                                from uuid import UUID

                                db = next(get_db())
                                question_repo = QuestionRepository(db)
                                question_repo.update_agent_state(
                                    UUID(question_id), agent_state
                                )
                                db.commit()
                                db.close()
                            except Exception as e:
                                logger.warning(
                                    "failed_to_save_question_agent_state",
                                    question_id=question_id,
                                    error=str(e),
                                )

                        # Return full state for resumption
                        return {
                            "paused": True,
                            "question_id": question_id,
                            "question": result.get("question"),
                            "question_type": result.get("question_type"),
                            "choices": result.get("choices"),
                            "tool": tool_name,
                            "agent_state": agent_state,
                        }

                    # Check if agent signaled task completion
                    if result.get("status") == "completed":
                        logger.info(
                            "agent_task_complete",
                            agent_id=self.id,
                            tool=tool_name,
                            summary=result.get("summary", "")[:100],
                            session_id=session_id,
                        )
                        return {
                            "success": True,
                            "result": result.get("summary", "Task completed"),
                        }

                    # Add tool result to messages
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": tool_call.get("id", f"call_{iteration}"),
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", f"call_{iteration}"),
                        "content": json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                    })
                    continue

                # Convert OpenAI format to MCP format (coding_read_file -> coding:read_file)
                # Only do the conversion if there's no colon already (LLM might output either format)
                if ":" in tool_name:
                    # Already in MCP format (coding:read_file)
                    mcp_tool_name = tool_name
                else:
                    # OpenAI format (coding_read_file) - convert first underscore to colon
                    mcp_tool_name = tool_name.replace("_", ":", 1)

                # Parse server:tool format
                if ":" in mcp_tool_name:
                    server, tool = mcp_tool_name.split(":", 1)
                else:
                    server = "coding"
                    tool = mcp_tool_name

                # Note: workspace_id injection will be handled by Coding MCP
                # using session_id to look up workspace info

                # Validate required arguments before MCP call
                schema = tool_schemas.get(tool_name, {})
                required_fields = schema.get("required", [])
                provided_args = set(tool_args.keys())
                missing_fields = [f for f in required_fields if f not in provided_args]

                if missing_fields:
                    missing_field = missing_fields[0]  # Report first missing field
                    logger.warning(
                        "agent_tool_validation_error",
                        agent_id=self.id,
                        tool=tool_name,
                        missing_field=missing_field,
                        missing_fields=missing_fields,
                        provided_args=list(provided_args),
                        required_args=required_fields,
                    )
                    result = {
                        "success": False,
                        "error": f"Missing required argument: {missing_field}",
                        "error_type": "validation",
                        "recoverable": True,
                        "tool": tool_name,
                        "provided_args": list(provided_args),
                        "required_args": list(required_fields),
                        "suggested_fix": f"Please call {tool_name} again with argument: {missing_field}",
                    }
                else:
                    # Execute tool via MCP client with agent definition for layered approval
                    result = await self.mcp_client.call_tool(
                        server, tool, tool_args,
                        session_id=session_id,
                        agent_run_id=agent_run_id,
                        agent_id=self.id,
                        agent_definition=self.definition,
                    )

                # Check if paused for approval
                if result.get("status") == "paused":
                    # Add the assistant message with the tool call before returning
                    # This is needed so when we resume, we can add the tool response
                    tool_call_id = tool_call.get("id", f"call_{iteration}")
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                            },
                        }],
                    })

                    # Return paused state with full agent_state for resumption
                    logger.info("agent_paused_for_approval", agent_id=self.id, tool=mcp_tool_name, session_id=session_id)
                    return {
                        "paused": True,
                        "approval_id": result.get("approval_id"),
                        "tool": mcp_tool_name,
                        "iteration": iteration,
                        "agent_state": {
                            "agent_id": self.id,
                            "messages": messages,
                            "prompt": prompt,
                            "context": context,
                            "iteration": iteration,
                            "tool_call_id": tool_call_id,
                            "tool_name": mcp_tool_name,
                            "tool_args": tool_args,
                        },
                    }

                # Check for MCP tool errors (success=False or error field)
                is_error = result.get("success") is False or "error" in result
                if is_error:
                    error_msg = result.get("error", "Unknown MCP tool error")
                    error_type = result.get("error_type", "mcp_error")
                    is_recoverable = result.get("recoverable", True)

                    logger.warning(
                        "agent_tool_error",
                        agent_id=self.id,
                        tool=mcp_tool_name,
                        error=error_msg,
                        error_type=error_type,
                        recoverable=is_recoverable,
                        iteration=iteration,
                        session_id=session_id,
                    )

                    # Format error result clearly for the agent
                    # This helps the agent understand what went wrong and decide how to proceed
                    result = {
                        "success": False,
                        "error": error_msg,
                        "error_type": error_type,
                        "recoverable": is_recoverable,
                        "tool": mcp_tool_name,
                        "original_args": tool_args,
                        "hint": "Check the error message and either retry with corrected arguments or try a different approach.",
                    }

                # Add tool result to messages
                # IMPORTANT: Use json.dumps for proper JSON format (not Python repr)
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": tool_call.get("id", f"call_{iteration}"),
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{iteration}"),
                    "content": json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                })

        logger.warning("agent_max_iterations", agent_id=self.id, session_id=session_id)
        raise AgentMaxIterationsError(
            f"Agent '{self.id}' exceeded {max_iterations} iterations"
        )

    def _build_system_prompt(self) -> str:
        """Build the system prompt with shared tool usage instructions.

        This method:
        1. Injects dynamic tool descriptions from mcp_config.yaml
        2. Adds shared tool usage instructions for non-router/planner agents

        Router and planner agents have special JSON output formats and don't
        need the built-in tools documentation.
        """
        base_prompt = self.definition.system_prompt

        # Generate dynamic tool descriptions from MCP config
        if self.definition.mcps:
            tool_descriptions = generate_tool_descriptions(self.definition.mcps)
            # Inject tool descriptions into the prompt
            base_prompt = self._inject_tool_descriptions(base_prompt, tool_descriptions)

        # Router and planner output JSON directly - no built-in tools needed
        if self.id in ("router", "planner"):
            return base_prompt

        shared_tool_instructions = """

###############################################################################
#                    CRITICAL: TOOL USAGE INSTRUCTIONS                        #
###############################################################################

You are an AI agent that can ONLY interact through TOOL CALLS.
You MUST NOT output plain text - always use a tool.

## TOOL CALL FORMAT

You MUST output tool calls in ONE of these two formats:

### Option 1: XML Format (recommended)
```
<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1", "arg2": "value2"}}</tool_call>
```

### Option 2: OpenAI Function Call Format
The API will handle this automatically if your response includes proper function calls.

## EXAMPLES OF CORRECT TOOL CALLS

### Asking the user a question:
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What database would you like me to use?"}}</tool_call>

### Asking a yes/no question:
<tool_call>{"name": "hitl_ask_multiple_choice_question", "arguments": {"question": "Should I proceed with this plan?", "choices": ["Yes", "No"]}}</tool_call>

### Signaling task completion:
<tool_call>{"name": "done", "arguments": {"summary": "Successfully created the todo application"}}</tool_call>

## BUILT-IN TOOLS (always available)

1. **hitl_ask_question** - Ask the user a free-form question
   Required: question (string)
   Optional: context (string)

2. **hitl_ask_multiple_choice_question** - Ask user to select from options
   Required: question (string), choices (array of strings)
   Optional: allow_other (boolean)

3. **done** - Signal that your task is complete
   Required: summary (string) - Brief description of what you accomplished

## CRITICAL RULES

1. NEVER output plain text to communicate - use hitl_ask_question instead
2. NEVER announce what you will do - just call the tool directly
3. ALWAYS call done() when you have finished your task
4. Tool names use UNDERSCORES not colons (e.g., hitl_ask_question not hitl:ask_question)

## WRONG vs RIGHT

WRONG (plain text output):
```
I'll now create a file for you. What name would you like?
```

RIGHT (tool call):
```
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What name would you like for the file?"}}</tool_call>
```

WRONG (announcing completion):
```
Done! I have completed the task.
```

RIGHT (tool call):
```
<tool_call>{"name": "done", "arguments": {"summary": "Created the requested file"}}</tool_call>
```
"""
        return base_prompt + shared_tool_instructions

    def _inject_tool_descriptions(self, prompt: str, tool_descriptions: str) -> str:
        """Inject dynamic tool descriptions into the system prompt.

        Looks for AVAILABLE TOOLS or TOOLS section and replaces/injects
        tool descriptions from mcp_config.yaml.

        Args:
            prompt: The base system prompt
            tool_descriptions: Generated tool descriptions from mcp_config

        Returns:
            Prompt with tool descriptions injected
        """
        # Check for placeholder pattern
        if "[TOOL_DESCRIPTIONS_PLACEHOLDER]" in prompt:
            return prompt.replace("[TOOL_DESCRIPTIONS_PLACEHOLDER]", tool_descriptions)

        # Check for AVAILABLE TOOLS or TOOLS section
        for marker in ["AVAILABLE TOOLS:", "TOOLS:"]:
            if marker in prompt:
                lines = prompt.split("\n")
                new_lines = []
                skip_until_next_section = False

                for line in lines:
                    if marker in line:
                        # Add the marker and then our dynamic descriptions
                        new_lines.append(line)
                        new_lines.append(tool_descriptions)
                        skip_until_next_section = True
                    elif skip_until_next_section:
                        # Skip lines until we hit another major section
                        # (starts with === or is a new section header ending with :)
                        stripped = line.strip()
                        if stripped.startswith("===") or (
                            stripped.endswith(":") and stripped.isupper()
                        ):
                            skip_until_next_section = False
                            new_lines.append(line)
                    else:
                        new_lines.append(line)

                return "\n".join(new_lines)

        # No marker found - return prompt unchanged
        return prompt

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        """Build the full prompt with context."""
        if not context:
            return prompt

        # Extract clarifications for natural inclusion
        clarifications = context.get("clarifications", [])

        # Build context string WITHOUT clarifications
        context_items = {k: v for k, v in context.items() if k != "clarifications"}
        context_str = "\n".join(
            f"- {key}: {value}" for key, value in context_items.items()
        )

        # Build user response section if present
        user_response_str = ""
        if clarifications:
            # Just show the most recent response naturally
            latest = clarifications[-1]
            question = latest.get("question", "")
            answer = latest.get("answer", "")
            user_response_str = f"""

USER RESPONSE:
You previously asked: {question[:200]}{'...' if len(question) > 200 else ''}
User's answer: {answer}
"""

        return f"""CONTEXT:
{context_str}

TASK:
{prompt}{user_response_str}"""

    def _parse_output(self, content: str) -> Any:
        """Parse agent's final output.

        Tries to parse as JSON using multiple extraction strategies,
        falls back to raw content.
        """
        import json
        import re

        if not content:
            return {}

        content = content.strip()

        # Strategy 1: Try direct JSON parse first (ideal case)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from markdown code blocks
        # Handles ```json ... ``` or ``` ... ```
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find the LAST valid JSON object in text (look for {...})
        # This handles cases where LLM adds thinking text before the actual JSON
        # We search backwards to find the last complete JSON object
        json_objects = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content))
        for match in reversed(json_objects):
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue

        # Strategy 3b: Try to find a JSON object with nested braces (more complex)
        # Look for JSON starting near the end of content
        last_brace = content.rfind("{")
        if last_brace >= 0:
            # Try to extract JSON from the last { to the matching }
            try:
                # Count braces to find the matching }
                brace_count = 0
                for i, char in enumerate(content[last_brace:]):
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_str = content[last_brace:last_brace + i + 1]
                            return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass

        # Strategy 4: Find JSON array in text (look for [...])
        array_match = re.search(r"\[[\s\S]*\]", content)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 5: Try to fix common JSON issues
        # Remove trailing commas before } or ]
        fixed_content = re.sub(r",\s*([}\]])", r"\1", content)
        try:
            return json.loads(fixed_content)
        except json.JSONDecodeError:
            pass

        # Fallback: Return as string content
        logger.debug(
            "json_parse_failed",
            agent_id=self.id,
            content_preview=content[:200] if len(content) > 200 else content,
        )
        return {"content": content}

    def __repr__(self) -> str:
        return f"Agent({self.id!r})"
