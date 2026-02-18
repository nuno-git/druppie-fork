"""Agent loop - the core tool-calling loop for agent execution."""

import asyncio
import json
import time
from typing import Any
from uuid import UUID

import structlog

from druppie.agents.builtin_tools import DEFAULT_BUILTIN_TOOLS, is_builtin_tool
from druppie.execution.tool_executor import ToolCallStatus
from druppie.llm.base import LLMError

logger = structlog.get_logger()

# Retry config for transient LLM errors (rate limits, server errors)
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 5  # seconds, doubles each retry


class AgentLoop:
    """Runs the LLM tool-calling loop for an agent.

    Each iteration: call LLM → process tool calls → repeat.
    Agent completes when it calls `done`, or pauses for HITL/approval.
    """

    def __init__(self, agent_id, definition, llm, tool_executor, db):
        self.agent_id = agent_id
        self.definition = definition
        self.llm = llm
        self.tool_executor = tool_executor
        self.db = db

    async def run(
        self,
        messages: list[dict],
        prompt: str,
        context: dict | None,
        session_id: UUID,
        agent_run_id: UUID,
        start_iteration: int,
    ) -> Any:
        """Run the tool-calling loop.

        All tool execution goes through ToolExecutor:
        1. Create ToolCall record
        2. Call ToolExecutor.execute(tool_call_id)
        3. Handle status (completed, waiting_approval, waiting_answer, failed)

        Agent only completes when calling the `done` tool.
        """
        from druppie.agents.runtime import AgentMaxIterationsError
        from druppie.repositories import ExecutionRepository

        execution_repo = ExecutionRepository(self.db)
        openai_tools, registry = self._prepare_tools()
        max_iterations = self.definition.max_iterations or 10

        if start_iteration == 0:
            logger.info(
                "agent_run_start",
                agent_id=self.agent_id,
                prompt_length=len(prompt),
                tools_count=len(openai_tools),
                session_id=str(session_id),
                agent_run_id=str(agent_run_id),
            )

        for iteration in range(start_iteration, max_iterations):
            response, llm_call_id = await self._call_llm(
                messages, openai_tools, execution_repo,
                session_id, agent_run_id, iteration,
            )

            # No tool calls — nudge or raise
            if not response.tool_calls:
                should_continue = self._nudge_no_tool_calls(
                    messages, response, iteration, max_iterations,
                )
                if should_continue:
                    continue
                raise AgentMaxIterationsError(
                    f"Agent '{self.agent_id}' exhausted {max_iterations} iterations "
                    f"without producing tool calls"
                    f"{' (response was truncated by token limit)' if response.finish_reason == 'length' else ''}"
                )

            # Process tool calls — may return early (done/pause)
            result = await self._process_tool_calls(
                response.tool_calls, messages, openai_tools, registry,
                execution_repo, session_id, agent_run_id, llm_call_id,
                iteration, prompt, context,
            )
            if result is not None:
                return result

        logger.warning("agent_max_iterations", agent_id=self.agent_id)
        raise AgentMaxIterationsError(
            f"Agent '{self.agent_id}' exceeded {max_iterations} iterations"
        )

    # ------------------------------------------------------------------
    # Tool preparation
    # ------------------------------------------------------------------

    def _prepare_tools(self):
        """Get tools from registry, build openai_tools list.

        If the agent has skills, the invoke_skill tool is added with an enum
        constraining skill_name to the agent's available skills, and skill
        descriptions in the tool description (not the system prompt).

        Returns:
            (openai_tools, registry) tuple
        """
        from druppie.core.tool_registry import get_tool_registry

        registry = get_tool_registry()
        builtin_tool_names = DEFAULT_BUILTIN_TOOLS + self.definition.extra_builtin_tools
        # Add invoke_skill tool if agent has skills defined
        if self.definition.skills:
            builtin_tool_names = builtin_tool_names + ["invoke_skill"]
        tools = registry.get_tools_for_agent(
            agent_mcps=self.definition.mcps,
            builtin_tool_names=builtin_tool_names,
        )
        openai_tools = registry.to_openai_format(tools)

        # Enrich invoke_skill with dynamic enum + descriptions from agent's skills
        if self.definition.skills:
            self._enrich_invoke_skill(openai_tools)

        return openai_tools, registry

    def _enrich_invoke_skill(self, openai_tools: list[dict]) -> None:
        """Replace the generic invoke_skill definition with one that lists
        the agent's available skills as an enum + descriptions.
        """
        from druppie.services import SkillService

        skill_service = SkillService()
        available = skill_service.get_skills_for_agent(self.definition.skills)
        if not available:
            return

        # Build enum + description
        skill_names = [s.name for s in available]
        skill_descriptions = ", ".join(
            f"{s.name} ({s.description})" for s in available
        )
        description = (
            f"Invoke a skill to load its instructions. "
            f"IMPORTANT: Call this BEFORE your first user-facing question "
            f"to load question guidelines. "
            f"Available: {skill_descriptions}"
        )

        # Find and replace the invoke_skill entry in openai_tools
        for tool in openai_tools:
            if tool.get("function", {}).get("name") == "invoke_skill":
                tool["function"]["description"] = description
                props = tool["function"]["parameters"]["properties"]
                props["skill_name"] = {
                    "type": "string",
                    "enum": skill_names,
                    "description": "Skill to invoke",
                }
                break

    # ------------------------------------------------------------------
    # LLM call with DB record keeping
    # ------------------------------------------------------------------

    async def _call_llm(
        self, messages, openai_tools, execution_repo,
        session_id, agent_run_id, iteration,
    ):
        """Call the LLM, record request/response in DB.

        Retries on transient errors (rate limits, server errors) with
        exponential backoff. Non-retryable errors propagate immediately.

        Returns:
            (response, llm_call_id) tuple
        """
        # Create LLM call record BEFORE calling LLM
        llm_call_id = execution_repo.create_llm_call(
            session_id=session_id,
            agent_run_id=agent_run_id,
            provider=self.llm.provider_name if hasattr(self.llm, 'provider_name') else "unknown",
            model=self.llm.model if hasattr(self.llm, 'model') else self.definition.model or "unknown",
            messages=messages,
            tools=openai_tools,
        )
        self.db.commit()

        start_time = time.time()
        retry_events = []

        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = await self.llm.achat(messages, openai_tools, max_tokens=self.definition.max_tokens)
                break  # Success
            except Exception as e:
                retryable = isinstance(e, LLMError) and e.retryable
                is_last_attempt = attempt >= LLM_MAX_RETRIES

                delay = LLM_RETRY_BASE_DELAY * (2 ** attempt)
                if hasattr(e, 'retry_after') and e.retry_after:
                    delay = max(delay, e.retry_after)

                retry_events.append({
                    "attempt": attempt + 1,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                    "delay_seconds": delay,
                })

                if not retryable or is_last_attempt:
                    # Non-retryable or exhausted retries — persist retries and raise
                    duration_ms = int((time.time() - start_time) * 1000)
                    error_msg = f"{type(e).__name__}: {e}"
                    execution_repo.update_llm_error(
                        llm_call_id=llm_call_id,
                        error_message=error_msg[:2000],
                        duration_ms=duration_ms,
                    )
                    if retry_events:
                        execution_repo.create_llm_retries(llm_call_id, retry_events)
                    self.db.commit()
                    logger.error(
                        "llm_call_failed",
                        agent_id=self.agent_id,
                        iteration=iteration,
                        attempt=attempt + 1,
                        retries=len(retry_events),
                        duration_ms=duration_ms,
                        error=error_msg[:500],
                    )
                    raise

                # Retryable — wait with exponential backoff
                logger.warning(
                    "llm_call_retrying",
                    agent_id=self.agent_id,
                    iteration=iteration,
                    attempt=attempt + 1,
                    delay_seconds=delay,
                    error=str(e)[:200],
                )
                await asyncio.sleep(delay)

        duration_ms = int((time.time() - start_time) * 1000)

        # Persist retry events if any occurred (even on eventual success)
        if retry_events:
            execution_repo.create_llm_retries(llm_call_id, retry_events)

        # Warn if response was truncated (hit token limit)
        if response.finish_reason == "length":
            logger.warning(
                "llm_response_truncated",
                agent_id=self.agent_id,
                iteration=iteration,
                completion_tokens=response.completion_tokens,
            )

        # Store the full raw response as JSON for debugging
        raw_response_json = json.dumps({
            "content": response.raw_content if hasattr(response, 'raw_content') else response.content,
            "tool_calls": response.raw_tool_calls if hasattr(response, 'raw_tool_calls') else response.tool_calls or [],
            "finish_reason": response.finish_reason or "",
            "prompt_tokens": response.prompt_tokens or 0,
            "completion_tokens": response.completion_tokens or 0,
            "total_tokens": response.total_tokens or 0,
        })
        execution_repo.update_llm_response(
            llm_call_id=llm_call_id,
            response_content=raw_response_json[:10000],
            response_tool_calls=[
                {
                    "id": tc.get("id", f"call_{iteration}_{idx}"),
                    "name": tc.get("name"),
                    "args": tc.get("args"),
                }
                for idx, tc in enumerate(response.tool_calls or [])
            ],
            prompt_tokens=response.prompt_tokens or 0,
            completion_tokens=response.completion_tokens or 0,
            duration_ms=duration_ms,
        )
        self.db.commit()

        logger.debug(
            "llm_call",
            agent_id=self.agent_id,
            iteration=iteration,
            duration_ms=duration_ms,
            has_tool_calls=bool(response.tool_calls),
            actual_provider=response.provider,
            actual_model=response.model,
        )

        return response, llm_call_id

    # ------------------------------------------------------------------
    # No-tool-call nudge
    # ------------------------------------------------------------------

    def _nudge_no_tool_calls(self, messages, response, iteration, max_iterations) -> bool:
        """Inject an error message when the LLM didn't produce tool calls.

        Returns:
            True if the loop should continue (retry), False if exhausted.
        """
        was_truncated = response.finish_reason == "length"

        if iteration < max_iterations - 1:
            logger.warning(
                "agent_no_tool_calls_retry",
                agent_id=self.agent_id,
                iteration=iteration,
                truncated=was_truncated,
            )
            messages.append({"role": "assistant", "content": response.content})
            truncation_hint = (
                " Your previous response was TRUNCATED (hit token limit). "
                "Keep your response shorter — call a tool immediately."
                if was_truncated else ""
            )
            messages.append({
                "role": "user",
                "content": (
                    "ERROR: You did not call any tools. You MUST use tool calls — "
                    "either OpenAI function calling format or "
                    "<tool_call>{\"name\": \"tool_name\", \"arguments\": {...}}</tool_call> XML format. "
                    "Do NOT output raw JSON or plain text. "
                    f"Call `done` when finished.{truncation_hint}"
                ),
            })
            return True

        # Final iteration exhausted
        logger.error(
            "agent_max_iterations_no_tool_calls",
            agent_id=self.agent_id,
            iteration=iteration,
            truncated=was_truncated,
        )
        return False

    # ------------------------------------------------------------------
    # Tool name parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_name(tool_name: str) -> tuple[str, str]:
        """Parse 'coding_write_file' → ('coding', 'write_file').

        Returns:
            (server, tool) tuple
        """
        if is_builtin_tool(tool_name):
            return "builtin", tool_name
        if ":" in tool_name:
            return tool_name.split(":", 1)
        # Convert coding_read_file -> coding:read_file
        parts = tool_name.split("_", 1)
        server = parts[0] if len(parts) > 1 else "coding"
        tool = parts[1] if len(parts) > 1 else tool_name
        return server, tool

    # ------------------------------------------------------------------
    # Tool message building (eliminates 4x duplication)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_messages(tool_call_id, tool_name, tool_args, content):
        """Build the assistant + tool message pair for a tool call.

        Returns:
            (assistant_msg, tool_msg) tuple
        """
        assistant_msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args),
                },
            }],
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content if isinstance(content, str) else json.dumps(content),
        }
        return assistant_msg, tool_msg

    # ------------------------------------------------------------------
    # Pause state building
    # ------------------------------------------------------------------

    def _build_pause_state(
        self, messages, prompt, context, iteration,
        tool_call_id, reason, db_tool_call_id,
    ):
        """Build the pause return dict for HITL/approval."""
        agent_state = {
            "agent_id": self.agent_id,
            "messages": messages,
            "prompt": prompt,
            "context": context,
            "iteration": iteration,
            "tool_call_id": tool_call_id,
        }
        return {
            "status": "paused",
            "paused": True,
            "reason": reason,
            "tool_call_id": str(db_tool_call_id),
            "agent_state": agent_state,
        }

    # ------------------------------------------------------------------
    # Process tool calls
    # ------------------------------------------------------------------

    async def _process_tool_calls(
        self, tool_calls, messages, openai_tools, registry,
        execution_repo, session_id, agent_run_id, llm_call_id,
        iteration, prompt, context,
    ) -> Any | None:
        """Iterate tool calls, execute each, handle status.

        Returns:
            A result dict if the loop should return (done/pause), or None to continue.
        """
        for tool_index, llm_tool_call in enumerate(tool_calls):
            tool_name = llm_tool_call.get("name", "")
            tool_args = llm_tool_call.get("args", {})
            llm_tool_call_str_id = llm_tool_call.get("id", f"call_{iteration}_{tool_index}")

            server, tool = self._parse_tool_name(tool_name)

            logger.debug(
                "agent_tool_call",
                agent_id=self.agent_id,
                tool=f"{server}:{tool}",
                iteration=iteration,
            )

            # Create ToolCall record (linked to the LLM call)
            tool_call_id = execution_repo.create_tool_call(
                session_id=session_id,
                agent_run_id=agent_run_id,
                mcp_server=server,
                tool_name=tool,
                arguments=tool_args,
                llm_call_id=llm_call_id,
                tool_call_index=tool_index,
            )
            self.db.commit()

            # Execute via ToolExecutor
            status = await self.tool_executor.execute(tool_call_id)

            # Get updated tool call for result
            tool_call_record = execution_repo.get_tool_call(tool_call_id)

            # Handle failed tool calls
            if status == ToolCallStatus.FAILED:
                error_msg = tool_call_record.error_message if tool_call_record else "Unknown error"
                result_str = json.dumps({
                    "success": False,
                    "error": error_msg,
                    "message": f"Tool call failed: {error_msg}. Please check your arguments and try again.",
                })
                logger.warning(
                    "tool_call_failed",
                    agent_id=self.agent_id,
                    tool=f"{server}:{tool}",
                    error=error_msg,
                )
                # Add error to messages so LLM sees it, then break
                assistant_msg, tool_msg = self._build_tool_messages(
                    llm_tool_call_str_id, tool_name, tool_args, result_str,
                )
                messages.append(assistant_msg)
                messages.append(tool_msg)
                break
            else:
                result_str = tool_call_record.result if tool_call_record else "{}"

            # Handle HITL pause
            if status == ToolCallStatus.WAITING_ANSWER:
                assistant_msg, _ = self._build_tool_messages(
                    llm_tool_call_str_id, tool_name, tool_args, "",
                )
                messages.append(assistant_msg)
                return self._build_pause_state(
                    messages, prompt, context, iteration,
                    llm_tool_call_str_id, "waiting_answer", tool_call_id,
                )

            # Handle approval pause
            if status == ToolCallStatus.WAITING_APPROVAL:
                assistant_msg, _ = self._build_tool_messages(
                    llm_tool_call_str_id, tool_name, tool_args, "",
                )
                messages.append(assistant_msg)
                return self._build_pause_state(
                    messages, prompt, context, iteration,
                    llm_tool_call_str_id, "waiting_approval", tool_call_id,
                )

            # Parse result
            try:
                result = json.loads(result_str) if result_str else {}
            except json.JSONDecodeError:
                result = {"content": result_str}

            # Check if invoke_skill returned allowed_tools — add them dynamically
            if tool == "invoke_skill" and result.get("success") and result.get("allowed_tools"):
                self._add_skill_tools(result, openai_tools, registry)

            # Check if agent called `done`
            if tool == "done" and result.get("status") == "completed":
                logger.info(
                    "agent_task_complete",
                    agent_id=self.agent_id,
                    summary=result.get("summary", "")[:100],
                )
                return {
                    "success": True,
                    "result": result.get("summary", "[NO_SUMMARY]"),
                }

            # Add tool result to messages for next LLM call
            assistant_msg, tool_msg = self._build_tool_messages(
                llm_tool_call_str_id, tool_name, tool_args, json.dumps(result),
            )
            messages.append(assistant_msg)
            messages.append(tool_msg)

        return None  # Continue the loop

    # ------------------------------------------------------------------
    # Skill tool expansion
    # ------------------------------------------------------------------

    def _add_skill_tools(self, result, openai_tools, registry):
        """Add dynamically-granted skill tools to openai_tools."""
        skill_allowed_tools = result["allowed_tools"]
        skill_tools = registry.get_tools_for_agent(
            agent_mcps=skill_allowed_tools,
            builtin_tool_names=[],
        )
        existing_tool_names = {t["function"]["name"] for t in openai_tools}
        new_tools = registry.to_openai_format(skill_tools)
        for new_tool in new_tools:
            if new_tool["function"]["name"] not in existing_tool_names:
                openai_tools.append(new_tool)
                existing_tool_names.add(new_tool["function"]["name"])
        logger.info(
            "skill_tools_added",
            skill_name=result.get("skill_name"),
            added_tools=[t["function"]["name"] for t in new_tools],
            total_tools=len(openai_tools),
        )
