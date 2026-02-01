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
    from druppie.repositories import ExecutionRepository

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
    # Intent Tool (for router agent)
    {
        "type": "function",
        "function": {
            "name": "set_intent",
            "description": "Set the intent for this session. Call this to declare what the user wants to do. This must be called before done().",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": ["create_project", "update_project", "general_chat"],
                        "description": "The type of user intent",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "For update_project: the ID of the project to update",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "For create_project: the name for the new project",
                    },
                },
                "required": ["intent"],
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
# INTENT TOOL IMPLEMENTATION
# =============================================================================

async def set_intent(
    intent: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Set the intent for the current session.

    Called by router agent to declare the user's intent. Handles all setup:
    - create_project: Creates Project record + Gitea repo
    - update_project: Links existing project to session
    - general_chat: Just sets the intent

    Also updates the pending planner's prompt with intent context.

    Args:
        intent: Intent type (create_project, update_project, general_chat)
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository (used to derive db and other repos)
        project_id: For update_project - the project to update
        project_name: For create_project - name for new project

    Returns:
        Success message with project details
    """
    from druppie.repositories import SessionRepository, ProjectRepository, UserRepository
    from druppie.core.gitea import get_gitea_client

    db = execution_repo.db
    session_repo = SessionRepository(db)
    project_repo = ProjectRepository(db)
    user_repo = UserRepository(db)

    logger.info(
        "set_intent",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        intent=intent,
        project_id=project_id,
        project_name=project_name,
    )

    # Validate intent
    valid_intents = ("create_project", "update_project", "general_chat")
    if intent not in valid_intents:
        return {
            "success": False,
            "error": f"Invalid intent: {intent}. Must be one of: {valid_intents}",
        }

    # Get session
    session = session_repo.get_by_id(session_id)
    if not session:
        return {
            "success": False,
            "error": f"Session not found: {session_id}",
        }

    session_repo.update_intent(session_id, intent)
    result = {
        "success": True,
        "intent": intent,
    }

    final_project_id = None

    if intent == "create_project":
        # Create new project
        if not project_name:
            project_name = "new-project"

        new_project = project_repo.create(name=project_name, user_id=session.user_id)

        session_repo.update_project(session_id, new_project.id)
        final_project_id = new_project.id
        result["project_id"] = str(new_project.id)
        result["project_name"] = project_name

        logger.info(
            "project_created",
            project_id=str(new_project.id),
            project_name=project_name,
        )

        # Create Gitea repo - REQUIRED for coding and docker workflows
        gitea_error = None
        try:
            user = user_repo.get_by_id(session.user_id)
            if not user:
                gitea_error = f"User {session.user_id} not found in database"
            else:
                gitea_username = user.username
                gitea_email = user.email or f"{gitea_username}@druppie.local"
                short_id = str(new_project.id)[:8]
                repo_name = f"{project_name}-{short_id}"

                gitea = get_gitea_client()

                # Ensure Gitea user exists
                user_result = await gitea.ensure_user_exists(
                    username=gitea_username,
                    email=gitea_email,
                )

                if user_result.get("success"):
                    # Create repo under user's account
                    repo_result = await gitea.create_repo(
                        name=repo_name,
                        description=f"Project: {project_name}",
                        auto_init=True,
                        owner=gitea_username,
                    )

                    if repo_result.get("success"):
                        repo_owner = repo_result.get("owner", gitea_username)
                        repo_url = repo_result.get("repo_url")

                        project_repo.update_repo(
                            project_id=new_project.id,
                            repo_name=repo_name,
                            repo_url=repo_url,
                            repo_owner=repo_owner,
                        )

                        result["repo_name"] = repo_name
                        result["repo_url"] = repo_url
                        result["repo_owner"] = repo_owner

                        logger.info(
                            "gitea_repo_created",
                            project_id=str(new_project.id),
                            repo_name=repo_name,
                            repo_owner=repo_owner,
                        )
                    else:
                        gitea_error = f"Gitea repo creation failed: {repo_result.get('error')}"
                else:
                    gitea_error = f"Gitea user creation failed: {user_result.get('error')}"
        except Exception as e:
            gitea_error = f"Gitea setup failed: {str(e)}"

        if gitea_error:
            logger.error(
                "gitea_repo_required_but_failed",
                project_id=str(new_project.id),
                project_name=project_name,
                error=gitea_error,
            )
            return {
                "success": False,
                "error": f"Failed to create Git repository: {gitea_error}. "
                         "Check that Gitea is running and configured (run: ./setup_dev.sh infra).",
                "project_id": str(new_project.id),
                "project_name": project_name,
            }

        result["message"] = f"Created project '{project_name}' with Gitea repo"

    elif intent == "update_project":
        if not project_id:
            return {
                "success": False,
                "error": "project_id is required for update_project intent",
            }

        try:
            session_repo.update_project(session_id, UUID(project_id))
            final_project_id = UUID(project_id)
            result["project_id"] = project_id
            result["message"] = f"Linked to existing project {project_id}"
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid project_id format: {project_id}",
            }

    else:  # general_chat
        result["message"] = "Intent set to general_chat"

    # Update the pending planner's prompt with intent context
    _update_planner_prompt(execution_repo, session_id, intent, final_project_id)

    db.flush()

    logger.info(
        "intent_set_complete",
        session_id=str(session_id),
        intent=intent,
        project_id=str(final_project_id) if final_project_id else None,
    )

    return result


def _update_planner_prompt(
    execution_repo: "ExecutionRepository",
    session_id: UUID,
    intent: str,
    project_id: UUID | None,
) -> None:
    """Update the pending planner's prompt with intent context.

    Finds the pending planner AgentRun for this session and prepends
    intent context to its planned_prompt.

    Args:
        execution_repo: Execution repository
        session_id: Session UUID
        intent: Intent type
        project_id: Project UUID (or None)
    """
    planner_run = execution_repo.get_pending_by_agent_id(session_id, "planner")

    if not planner_run:
        logger.warning(
            "planner_run_not_found",
            session_id=str(session_id),
        )
        return

    # Prepend intent context to the existing prompt
    intent_context = f"""INTENT: {intent}
PROJECT_ID: {str(project_id) if project_id else 'new'}

"""
    new_prompt = intent_context + (planner_run.planned_prompt or "")
    execution_repo.update_planned_prompt(planner_run.id, new_prompt)

    logger.info(
        "planner_prompt_updated",
        session_id=str(session_id),
        agent_run_id=str(planner_run.id),
        intent=intent,
    )


# =============================================================================
# PLANNING TOOL IMPLEMENTATION
# =============================================================================

async def make_plan(
    steps: list[dict],
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Create an execution plan as pending agent runs.

    Called by planner agent to create the plan. Creates AgentRun records
    with status='pending' that will be executed in sequence.

    Args:
        steps: List of steps, each with agent_id and prompt
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository

    Returns:
        Success message with plan details
    """
    from druppie.domain.common import AgentRunStatus

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

    # Create pending agent runs via repository
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

        execution_repo.create_agent_run(
            session_id=session_id,
            agent_id=step_agent_id,
            status=AgentRunStatus.PENDING,
            planned_prompt=step_prompt,
            sequence_number=i,
        )
        created_runs.append({
            "sequence": i,
            "agent_id": step_agent_id,
            "prompt_preview": step_prompt[:100] + "..." if len(step_prompt) > 100 else step_prompt,
        })

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
    execution_repo: "ExecutionRepository",
) -> dict:
    """Signal that the agent has completed its task.

    This does NOT pause execution - it signals completion immediately.
    Also relays the summary to the next pending agent by prepending it
    to that agent's planned_prompt.

    Args:
        summary: Summary of what was accomplished
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository

    Returns:
        Completion status with summary
    """
    logger.info(
        "agent_done",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        summary=summary[:200] if summary else "",
    )

    # Relay summary to next pending agent
    next_run = execution_repo.get_next_pending(session_id)
    if next_run and next_run.planned_prompt:
        new_prompt = (
            f"PREVIOUS AGENT SUMMARY:\n{summary}\n\n---\n\n"
            + next_run.planned_prompt
        )
        execution_repo.update_planned_prompt(next_run.id, new_prompt)
        execution_repo.flush()
        logger.info(
            "summary_relayed_to_next_agent",
            session_id=str(session_id),
            from_agent_run=str(agent_run_id),
            to_agent_run=str(next_run.id),
            to_agent_id=next_run.agent_id,
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
    execution_repo: "ExecutionRepository",
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
        execution_repo: Execution repository

    Returns:
        Tool result dict
    """
    if tool_name == "done":
        return await done(
            summary=args.get("summary", ""),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
        )
    elif tool_name == "make_plan":
        return await make_plan(
            steps=args.get("steps", []),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
        )
    elif tool_name == "set_intent":
        return await set_intent(
            intent=args.get("intent", "general_chat"),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
            project_id=args.get("project_id"),
            project_name=args.get("project_name"),
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
        "set_intent",
    )


def is_hitl_tool(tool_name: str) -> bool:
    """Check if a tool name is a HITL tool (requires user answer)."""
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
    )
