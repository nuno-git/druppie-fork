"""Built-in tools for agents.

These tools are built into the agent runtime and do not require a separate MCP server.

Tools:
- HITL (Human-in-the-Loop):
  - hitl_ask_question: Free-form text question (pauses for user response)
  - hitl_ask_multiple_choice_question: Multiple choice question (pauses for user response)

- Completion:
  - done: Signal that the agent has completed its task
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from druppie.core.execution_context import ExecutionContext

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS (OpenAI function format)
# =============================================================================

BUILTIN_TOOLS = [
    # HITL Tools
    {
        "type": "function",
        "function": {
            "name": "hitl_ask_question",
            "description": "Ask the user a free-form text question. Use this when you need clarification or input from the user. The workflow will pause until the user responds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hitl_ask_multiple_choice_question",
            "description": "Ask the user a multiple choice question. Use this when you want the user to select from predefined options. Can optionally allow a custom 'Other' answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of choices for the user to select from",
                    },
                    "allow_other": {
                        "type": "boolean",
                        "description": "Whether to allow a custom 'Other' answer (default: true)",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked",
                    },
                },
                "required": ["question", "choices"],
            },
        },
    },
    # Completion Tool
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that you have completed your task. Call this when you are done with all your work. You MUST call this tool when finished - do not just output text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "A brief summary of what was accomplished",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    # Planning Tool (for planner agent)
    {
        "type": "function",
        "function": {
            "name": "make_plan",
            "description": "Create an execution plan. Call this to define which agents should run and in what order. Each step specifies an agent and the prompt/task for that agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_id": {
                                    "type": "string",
                                    "description": "The agent to run (architect, developer, deployer)",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "The task description for the agent",
                                },
                            },
                            "required": ["agent_id", "prompt"],
                        },
                        "description": "List of steps to execute in order",
                    },
                },
                "required": ["steps"],
            },
        },
    },
]

# For backwards compatibility
HITL_TOOLS = BUILTIN_TOOLS


# =============================================================================
# HITL TOOL IMPLEMENTATIONS
# =============================================================================

async def ask_question(
    question: str,
    context: "ExecutionContext",
    agent_id: str,
    question_context: str | None = None,
) -> dict:
    """Ask the user a free-form text question.

    This saves the question to the database and returns a paused state.
    The workflow will resume when the user answers.
    """
    from druppie.api.deps import get_db
    from druppie.repositories import QuestionRepository

    session_id = context.session_id
    agent_run_id = context.current_agent_run_id

    logger.info(
        "hitl_ask_question",
        session_id=session_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        question=question[:100] + "..." if len(question) > 100 else question,
    )

    # Save question to database
    db = next(get_db())
    try:
        question_repo = QuestionRepository(db)
        hitl_question = question_repo.create(
            session_id=UUID(session_id),
            agent_run_id=UUID(agent_run_id) if agent_run_id else None,
            agent_id=agent_id,
            question=question,
            question_type="text",
            choices=None,
        )
        db.commit()

        question_id = str(hitl_question.id)

        logger.info(
            "hitl_question_created",
            question_id=question_id,
            session_id=session_id,
        )
    finally:
        db.close()

    # Emit event to frontend via WebSocket
    if context.emit_event:
        context.emit_event({
            "type": "question",
            "event_type": "question",
            "request_id": question_id,
            "question_id": question_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "question": question,
            "input_type": "text",
            "question_type": "text",
            "choices": None,
            "context": question_context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Also add to workflow events for persistence
    context.emit("question_asked", {
        "question_id": question_id,
        "agent_id": agent_id,
        "question": question,
        "question_type": "text",
    })

    return {
        "status": "paused",
        "reason": "waiting_for_answer",
        "question_id": question_id,
        "question": question,
        "question_type": "text",
    }


async def ask_multiple_choice_question(
    question: str,
    choices: list[str],
    context: "ExecutionContext",
    agent_id: str,
    allow_other: bool = True,
    question_context: str | None = None,
) -> dict:
    """Ask the user a multiple choice question.

    This saves the question to the database and returns a paused state.
    The workflow will resume when the user answers.
    """
    from druppie.api.deps import get_db
    from druppie.repositories import QuestionRepository

    session_id = context.session_id
    agent_run_id = context.current_agent_run_id

    logger.info(
        "hitl_ask_multiple_choice_question",
        session_id=session_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        question=question[:100] + "..." if len(question) > 100 else question,
        choices_count=len(choices),
        allow_other=allow_other,
    )

    # Save question to database - convert choices to format expected by repository
    choices_dicts = [{"text": c} for c in choices]
    db = next(get_db())
    try:
        question_repo = QuestionRepository(db)
        hitl_question = question_repo.create(
            session_id=UUID(session_id),
            agent_run_id=UUID(agent_run_id) if agent_run_id else None,
            agent_id=agent_id,
            question=question,
            question_type="choice",
            choices=choices_dicts,
        )
        db.commit()

        question_id = str(hitl_question.id)

        logger.info(
            "hitl_choice_question_created",
            question_id=question_id,
            session_id=session_id,
        )
    finally:
        db.close()

    # Emit event to frontend via WebSocket
    if context.emit_event:
        context.emit_event({
            "type": "question",
            "event_type": "question",
            "request_id": question_id,
            "question_id": question_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "question": question,
            "input_type": "choice",
            "question_type": "choice",
            "choices": choices,
            "allow_other": allow_other,
            "context": question_context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Also add to workflow events for persistence
    context.emit("question_asked", {
        "question_id": question_id,
        "agent_id": agent_id,
        "question": question,
        "question_type": "choice",
        "choices": choices,
        "allow_other": allow_other,
    })

    return {
        "status": "paused",
        "reason": "waiting_for_answer",
        "question_id": question_id,
        "question": question,
        "question_type": "choice",
        "choices": choices,
        "allow_other": allow_other,
    }


# =============================================================================
# PLANNING TOOL IMPLEMENTATION
# =============================================================================

async def make_plan(
    steps: list[dict],
    context: "ExecutionContext",
    agent_id: str,
) -> dict:
    """Create an execution plan as pending agent runs.

    Called by planner agent to create the plan. Creates AgentRun records
    with status='pending' that will be executed in sequence.

    Args:
        steps: List of steps, each with agent_id and prompt
        context: Execution context
        agent_id: ID of the calling agent (planner)

    Returns:
        Success message with plan details
    """
    from druppie.db.models import AgentRun
    from druppie.api.deps import get_db

    session_id = context.session_id
    session_uuid = UUID(session_id)

    logger.info(
        "make_plan",
        session_id=session_id,
        agent_id=agent_id,
        step_count=len(steps),
    )

    if not steps:
        return {
            "success": False,
            "error": "No steps provided",
        }

    # Create pending agent runs
    db = next(get_db())
    try:
        created_runs = []
        for i, step in enumerate(steps):
            step_agent_id = step.get("agent_id")
            step_prompt = step.get("prompt")

            if not step_agent_id or not step_prompt:
                logger.warning(
                    "invalid_plan_step",
                    step_index=i,
                    agent_id=step_agent_id,
                    has_prompt=bool(step_prompt),
                )
                continue

            agent_run = AgentRun(
                session_id=session_uuid,
                agent_id=step_agent_id,
                status="pending",
                planned_prompt=step_prompt,
                sequence_number=i,
            )
            db.add(agent_run)
            created_runs.append({
                "sequence": i,
                "agent_id": step_agent_id,
                "prompt_preview": step_prompt[:100] + "..." if len(step_prompt) > 100 else step_prompt,
            })

        db.commit()

        logger.info(
            "plan_created",
            session_id=session_id,
            step_count=len(created_runs),
        )
    finally:
        db.close()

    # Emit event
    context.emit("plan_created", {
        "agent_id": agent_id,
        "step_count": len(created_runs),
        "steps": created_runs,
    })

    return {
        "success": True,
        "message": f"Created plan with {len(created_runs)} steps",
        "steps": created_runs,
    }


# =============================================================================
# COMPLETION TOOL IMPLEMENTATION
# =============================================================================

async def done(
    summary: str,
    context: "ExecutionContext",
    agent_id: str,
) -> dict:
    """Signal that the agent has completed its task.

    This does NOT pause execution - it signals completion immediately.
    """
    logger.info(
        "agent_done",
        session_id=context.session_id,
        agent_id=agent_id,
        summary=summary[:200] if summary else "",
    )

    # Emit completion event
    context.emit("task_completed", {
        "agent_id": agent_id,
        "summary": summary,
    })

    return {
        "status": "completed",
        "summary": summary,
    }


# =============================================================================
# TOOL EXECUTION
# =============================================================================

async def execute_builtin_tool(
    tool_name: str,
    tool_args: dict,
    context: "ExecutionContext",
    agent_id: str,
) -> dict:
    """Execute a built-in tool.

    Args:
        tool_name: Tool name
        tool_args: Tool arguments
        context: Execution context
        agent_id: ID of the calling agent

    Returns:
        Tool result (paused state for HITL, completed state for done)
    """
    if tool_name == "hitl_ask_question":
        return await ask_question(
            question=tool_args.get("question", ""),
            context=context,
            agent_id=agent_id,
            question_context=tool_args.get("context"),
        )
    elif tool_name == "hitl_ask_multiple_choice_question":
        return await ask_multiple_choice_question(
            question=tool_args.get("question", ""),
            choices=tool_args.get("choices", []),
            context=context,
            agent_id=agent_id,
            allow_other=tool_args.get("allow_other", True),
            question_context=tool_args.get("context"),
        )
    elif tool_name == "done":
        return await done(
            summary=tool_args.get("summary", ""),
            context=context,
            agent_id=agent_id,
        )
    elif tool_name == "make_plan":
        return await make_plan(
            steps=tool_args.get("steps", []),
            context=context,
            agent_id=agent_id,
        )
    else:
        return {
            "success": False,
            "error": f"Unknown built-in tool: {tool_name}",
        }


def is_builtin_tool(tool_name: str) -> bool:
    """Check if a tool name is a built-in tool."""
    return tool_name in ("hitl_ask_question", "hitl_ask_multiple_choice_question", "done", "make_plan")


# Backwards compatibility aliases
execute_hitl_tool = execute_builtin_tool
is_hitl_tool = is_builtin_tool
