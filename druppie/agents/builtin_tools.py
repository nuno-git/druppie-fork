"""Built-in tools for agents.

These tools are built into the agent runtime and do not require a separate MCP server.

Tools:
- HITL (Human-in-the-Loop):
  - hitl_ask_question: Free-form text question (pauses for user response)
  - hitl_ask_multiple_choice_question: Multiple choice question (pauses for user response)

- Planning:
  - make_plan: Create an execution plan (pending agent runs)

- Completion:
  - done: Signal that the agent has completed its task

Note: HITL tool execution (Question record creation) is handled by ToolExecutor.
This module provides:
1. Tool definitions (BUILTIN_TOOLS) for LLM
2. execute_builtin() for non-HITL tools (done, make_plan)
"""

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

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



# =============================================================================
# PLANNING TOOL IMPLEMENTATION
# =============================================================================

async def make_plan(
    steps: list[dict],
    session_id: UUID,
    agent_run_id: UUID,
    db: "DBSession",
) -> dict:
    """Create an execution plan as pending agent runs.

    Called by planner agent to create the plan. Creates AgentRun records
    with status='pending' that will be executed in sequence.

    Args:
        steps: List of steps, each with agent_id and prompt
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        db: Database session (caller commits)

    Returns:
        Success message with plan details
    """
    from druppie.db.models import AgentRun

    logger.info(
        "make_plan",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        step_count=len(steps),
    )

    if not steps:
        return {
            "success": False,
            "error": "No steps provided",
        }

    # Create pending agent runs
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
            session_id=session_id,
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

    # Note: Caller (ToolExecutor) commits the transaction
    db.flush()

    logger.info(
        "plan_created",
        session_id=str(session_id),
        step_count=len(created_runs),
    )

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
    session_id: UUID,
    agent_run_id: UUID,
) -> dict:
    """Signal that the agent has completed its task.

    This does NOT pause execution - it signals completion immediately.

    Args:
        summary: Summary of what was accomplished
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking

    Returns:
        Completion status with summary
    """
    logger.info(
        "agent_done",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        summary=summary[:200] if summary else "",
    )

    return {
        "status": "completed",
        "summary": summary,
    }


# =============================================================================
# TOOL EXECUTION (called by ToolExecutor)
# =============================================================================

async def execute_builtin(
    tool_name: str,
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    db: "DBSession",
) -> dict:
    """Execute a non-HITL built-in tool.

    Called by ToolExecutor for builtin tools that are NOT HITL tools.
    HITL tools (hitl_ask_question, hitl_ask_multiple_choice_question)
    are handled separately by ToolExecutor._execute_hitl_tool().

    Args:
        tool_name: Tool name (done, make_plan)
        args: Tool arguments
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        db: Database session (caller commits)

    Returns:
        Tool result dict
    """
    if tool_name == "done":
        return await done(
            summary=args.get("summary", ""),
            session_id=session_id,
            agent_run_id=agent_run_id,
        )
    elif tool_name == "make_plan":
        return await make_plan(
            steps=args.get("steps", []),
            session_id=session_id,
            agent_run_id=agent_run_id,
            db=db,
        )
    else:
        return {
            "success": False,
            "error": f"Unknown built-in tool: {tool_name}",
        }


def is_builtin_tool(tool_name: str) -> bool:
    """Check if a tool name is a built-in tool."""
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
        "done",
        "make_plan",
    )


def is_hitl_tool(tool_name: str) -> bool:
    """Check if a tool name is a HITL tool (requires user answer)."""
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
    )
