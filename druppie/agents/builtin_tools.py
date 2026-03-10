"""Built-in tools for agents.

These tools are built into the agent runtime and do not require a separate MCP server.
Each agent declares which builtin tools it needs in its YAML via `builtin_tools`.

Default (all agents): done, hitl_ask_question, hitl_ask_multiple_choice_question
Router adds: set_intent
Planner adds: make_plan
Agents with skills: invoke_skill (loads skill markdown prompts)

Tool definitions are in BUILTIN_TOOL_DEFS (dict keyed by name).
Use get_builtin_tools(names) to get OpenAI-format definitions for an agent.
"""

import os
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from druppie.repositories import ExecutionRepository

logger = structlog.get_logger()

from druppie.sandbox.model_resolver import get_agent_chain, resolve_sandbox_models


# =============================================================================
# TOOL DEFINITIONS (OpenAI function format, keyed by name)
# =============================================================================

# Default builtin tools every agent gets (unless overridden in YAML)
DEFAULT_BUILTIN_TOOLS = ["done", "hitl_ask_question", "hitl_ask_multiple_choice_question"]

# All builtin tool definitions, keyed by tool name
BUILTIN_TOOL_DEFS: dict[str, dict] = {
    "hitl_ask_question": {
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
    "hitl_ask_multiple_choice_question": {
        "type": "function",
        "function": {
            "name": "hitl_ask_multiple_choice_question",
            "description": "Ask the user a multiple choice question. Use this when you want the user to select from predefined options. An 'Other' option with free-text input is always shown automatically — do NOT include 'Other' in your choices.",
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
                        "description": "List of choices for the user to select from. Do NOT include an 'Other' option — one is added automatically.",
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
    "done": {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal task completion with a DETAILED summary. The summary is the ONLY way to pass information to the next agent in the pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "DETAILED summary including: (1) your own 'Agent [role]:' line with key outputs (URLs, branch names, container names, file paths). Previous agent summaries are auto-prepended by the system. NEVER write just 'Task completed'.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    "create_message": {
        "type": "function",
        "function": {
            "name": "create_message",
            "description": "Create a visible message in the chat timeline for the user. Use this to provide a human-friendly summary of what was accomplished.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The message content to display to the user",
                    },
                },
                "required": ["content"],
            },
        },
    },
    "set_intent": {
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
    "make_plan": {
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
    "invoke_skill": {
        "type": "function",
        "function": {
            "name": "invoke_skill",
            "description": "Invoke a skill to get its instructions injected into the conversation. Skills provide reusable prompts for common tasks like code review, git workflow, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The name of the skill to invoke (e.g., 'code-review', 'git-workflow')",
                    },
                },
                "required": ["skill_name"],
            },
        },
    },
    "execute_coding_task": {
        "type": "function",
        "function": {
            "name": "execute_coding_task",
            "description": (
                "Execute a coding task in an isolated sandbox. "
                "IMPORTANT: Each call spawns a FRESH container that clones the project repo from git. "
                "The sandbox is DESTROYED after the task completes. "
                "Any work NOT committed and pushed within the sandbox is LOST. "
                "There is NO persistent workspace between calls — each call starts from the latest git state. "
                "The sandbox agent will automatically commit and push its work. "
                "To build on previous work, simply call again — the new sandbox clones the repo with all previous pushes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "The complete task prompt for the sandbox coding agent. "
                            "This is the ONLY instruction it receives, so be self-contained: "
                            "describe what to implement, reference files to read for context "
                            "(e.g. SPEC.md, test files), and include any patterns to follow."
                        ),
                    },
                    "agent": {
                        "type": "string",
                        "description": "Which sandbox agent to use",
                    },
                },
                "required": ["task"],
            },
        },
    },
    "test_report": {
        "type": "function",
        "function": {
            "name": "test_report",
            "description": "Report structured test iteration results. Call this after each test run to log progress. The data is automatically stored as a ToolCall record for tracking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "iteration": {
                        "type": "integer",
                        "description": "Current iteration number (1-based)",
                    },
                    "tests_passed": {
                        "type": "boolean",
                        "description": "Whether all tests passed in this iteration",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Human-readable summary of this iteration's results",
                    },
                    "test_command": {
                        "type": "string",
                        "description": "The test command that was executed",
                    },
                    "failed_count": {
                        "type": "integer",
                        "description": "Number of failed tests",
                    },
                    "passed_count": {
                        "type": "integer",
                        "description": "Number of passed tests",
                    },
                    "error_classification": {
                        "type": "string",
                        "description": "Classification of the error: assertion_failure, missing_function, import_error, type_error, syntax_error, configuration_error, environment_error, test_error",
                    },
                },
                "required": ["iteration", "tests_passed", "summary"],
            },
        },
    },
}


def get_builtin_tools(tool_names: list[str]) -> list[dict]:
    """Get builtin tool definitions for a list of tool names.

    Args:
        tool_names: List of builtin tool names (e.g. ["done", "make_plan"])

    Returns:
        List of OpenAI function tool definitions
    """
    tools = []
    for name in tool_names:
        if name in BUILTIN_TOOL_DEFS:
            tools.append(BUILTIN_TOOL_DEFS[name])
        else:
            logger.warning("unknown_builtin_tool", tool_name=name)
    return tools



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
                    # Use actual Gitea username (may differ if original was reserved)
                    gitea_username = user_result.get("username", gitea_username)

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

MAX_PLANNER_ITERATIONS = 30


async def make_plan(
    steps: list[dict],
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Create an execution plan as pending agent runs.

    Called by planner agent to create the plan. Creates AgentRun records
    with status='pending' that will be executed in sequence.

    Safety: If the planner has already run MAX_PLANNER_ITERATIONS times,
    any "planner" step in the plan is replaced with a forced finalization
    (developer merge + deployer final + summarizer) to prevent infinite loops.

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

    # Safety net: count how many times the planner has already completed
    completed_runs = execution_repo.get_completed_runs(session_id)
    planner_count = sum(1 for r in completed_runs if r.agent_id == "planner")

    # If we've hit the max, strip any planner steps and force finalization
    has_planner_step = any(s.get("agent_id") == "planner" for s in steps)
    if has_planner_step and planner_count >= MAX_PLANNER_ITERATIONS:
        logger.warning(
            "max_planner_iterations_reached",
            session_id=str(session_id),
            planner_count=planner_count,
            max_iterations=MAX_PLANNER_ITERATIONS,
        )
        # Remove planner steps and ensure summarizer is at the end
        steps = [s for s in steps if s.get("agent_id") != "planner"]
        has_summarizer = any(s.get("agent_id") == "summarizer" for s in steps)
        if not has_summarizer:
            steps.append({
                "agent_id": "summarizer",
                "prompt": "Summarize what was accomplished for the user. Note: the iteration limit was reached, so this is a forced finalization.",
            })

    # Cancel any stale pending runs from a previous plan
    cancelled_count = execution_repo.cancel_pending_runs(session_id)
    if cancelled_count > 0:
        logger.info(
            "cancelled_stale_pending_runs",
            session_id=str(session_id),
            cancelled_count=cancelled_count,
        )

    # Determine sequence start: next available session-level sequence number
    start_seq = execution_repo.get_next_sequence_number(session_id)

    # Create pending agent runs via repository
    planned_steps = []
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

        seq = start_seq + i
        execution_repo.create_agent_run(
            session_id=session_id,
            agent_id=step_agent_id,
            status=AgentRunStatus.PENDING,
            planned_prompt=step_prompt,
            sequence_number=seq,
        )
        planned_steps.append({
            "sequence": seq,
            "agent_id": step_agent_id,
            "prompt_preview": step_prompt[:100] + "..." if len(step_prompt) > 100 else step_prompt,
        })

    # Build full plan view: completed runs + new pending runs
    completed_steps = [
        {
            "sequence": r.sequence_number,
            "agent_id": r.agent_id,
            "status": r.status,
        }
        for r in completed_runs
    ]

    logger.info(
        "plan_created",
        session_id=str(session_id),
        step_count=len(planned_steps),
        planner_iteration=planner_count + 1,
        start_seq=start_seq,
    )

    return {
        "success": True,
        "message": f"Created plan with {len(planned_steps)} steps (planner iteration {planner_count + 1})",
        "completed_steps": completed_steps,
        "planned_steps": planned_steps,
    }


# =============================================================================
# MESSAGE TOOL IMPLEMENTATION
# =============================================================================

async def create_message(
    content: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Create a visible message in the chat timeline.

    Called by the summarizer agent to post a user-friendly completion message.

    Args:
        content: Message content to display
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository

    Returns:
        Success status
    """
    # Get next unique sequence number so message never collides with agent_run
    seq = execution_repo.get_next_sequence_number(session_id)

    execution_repo.create_message(
        session_id=session_id,
        role="assistant",
        content=content,
        agent_run_id=agent_run_id,
        agent_id="summarizer",
        sequence_number=seq,
    )
    execution_repo.flush()

    logger.info(
        "create_message",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        content_preview=content[:100] if content else "",
    )

    return {"status": "created", "message": "Message added to timeline"}


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
    Auto-collects previous agent summaries and prepends them to create
    an accumulated summary. Relays the full accumulated summary to the
    next pending agent by prepending it to that agent's planned_prompt.

    Args:
        summary: Summary of what was accomplished (this agent's own summary)
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository

    Returns:
        Completion status with accumulated summary
    """
    logger.info(
        "agent_done",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        summary=summary[:200] if summary else "",
    )

    # Auto-collect previous agent summaries from completed runs
    previous_summaries = []
    completed_runs = execution_repo.get_completed_runs(session_id)
    for run in completed_runs:
        # Skip the current run (it's not completed yet at this point)
        if run.id == agent_run_id:
            continue
        run_summary = execution_repo.get_done_summary_for_run(run.id)
        if run_summary:
            # Extract only the agent's own line(s) to avoid duplication.
            # If the summary already contains accumulated lines from earlier agents,
            # we only want the last line (this agent's own contribution).
            # Look for "Agent <role>:" pattern to find individual lines.
            lines = run_summary.strip().split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped and stripped.startswith("Agent ") and stripped not in previous_summaries:
                    previous_summaries.append(stripped)

    # Build the accumulated summary: previous summaries + current agent's summary
    # If the current summary already contains "Agent " lines from previous agents
    # (because the agent copied them), strip those out to avoid duplication
    current_lines = summary.strip().split("\n")
    own_lines = []
    for line in current_lines:
        stripped = line.strip()
        if stripped and stripped not in previous_summaries:
            own_lines.append(stripped)

    # Combine: previous summaries first, then this agent's own lines
    all_lines = previous_summaries + own_lines
    accumulated_summary = "\n".join(all_lines) if all_lines else summary

    logger.info(
        "agent_done_accumulated",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        previous_count=len(previous_summaries),
        accumulated_preview=accumulated_summary[:200],
    )

    # Relay accumulated summary to next pending agent
    next_run = execution_repo.get_next_pending(session_id)
    if next_run and next_run.planned_prompt:
        new_prompt = (
            f"PREVIOUS AGENT SUMMARY:\n{accumulated_summary}\n\n---\n\n"
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
        "summary": accumulated_summary,
    }


# =============================================================================
# SKILL TOOL IMPLEMENTATION
# =============================================================================

async def invoke_skill(
    skill_name: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Invoke a skill and return its prompt content.

    Skills are markdown files that provide reusable instructions for common tasks.
    The skill content is returned and should be injected into the conversation.
    If the skill has allowed-tools, tool descriptions are also included.

    Args:
        skill_name: The skill name (e.g., 'code-review', 'git-workflow')
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository

    Returns:
        Skill content with optional tool descriptions, or error message
    """
    from druppie.services import SkillService
    from druppie.core.tool_registry import get_tool_registry

    skill_service = SkillService()
    skill = skill_service.get_skill(skill_name)

    if not skill:
        logger.warning(
            "skill_not_found",
            skill_name=skill_name,
            session_id=str(session_id),
            agent_run_id=str(agent_run_id),
        )
        return {
            "success": False,
            "error": f"Skill not found: {skill_name}",
        }

    logger.info(
        "skill_invoked",
        skill_name=skill_name,
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        allowed_tools=skill.allowed_tools,
    )

    result = {
        "success": True,
        "skill_name": skill.name,
        "skill_description": skill.description,
        "instructions": skill.prompt_content,
    }

    # If skill has allowed-tools, include tool descriptions from registry
    if skill.allowed_tools:
        registry = get_tool_registry()
        tool_descriptions = []
        for server, tool_names in skill.allowed_tools.items():
            for tool_name in tool_names:
                tool_def = registry.get_by_server_and_name(server, tool_name)
                if tool_def:
                    tool_descriptions.append(f"- **{server}:{tool_name}**: {tool_def.description}")
        if tool_descriptions:
            result["available_tools"] = "\n".join(tool_descriptions)
            result["allowed_tools"] = skill.allowed_tools

    return result


# =============================================================================
# SANDBOX CODING TASK IMPLEMENTATION
# =============================================================================

async def execute_sandbox_coding_task(
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Create a sandbox session, send the prompt, register ownership, return immediately.

    Does NOT poll for completion. The control plane will send a webhook
    to /api/sandbox-sessions/{sandbox_session_id}/complete when done.

    Returns:
        Dict with status="waiting_sandbox" and sandbox_session_id on success.
        The caller (tool_executor) should set ToolCallStatus.WAITING_SANDBOX.
    """
    import json as _json
    from druppie.sandbox import create_and_start_sandbox, SandboxCreateError

    task = args.get("task", "")
    from druppie.core.config import DEFAULT_SANDBOX_AGENT
    agent = args.get("agent", DEFAULT_SANDBOX_AGENT)

    if not task:
        return {"success": False, "error": "task is required"}

    model_config = resolve_sandbox_models(agent)
    model = model_config.primary_model

    # Get project context from the session via repositories
    from druppie.repositories import SessionRepository, ProjectRepository
    db = execution_repo.db
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        return {"success": False, "error": f"Session {session_id} not found"}

    if not session.user_id:
        return {"success": False, "error": "Cannot create sandbox: session has no user_id"}

    repo_owner = os.getenv("GITEA_ORG", "druppie")
    repo_name = ""
    if session.project_id:
        project_repo = ProjectRepository(db)
        project = project_repo.get_by_id(session.project_id)
        if project:
            repo_owner = project.repo_owner or repo_owner
            repo_name = project.repo_name or ""

    try:
        result = await create_and_start_sandbox(
            task_prompt=task,
            model=model,
            agent_name=agent,
            repo_owner=repo_owner,
            repo_name=repo_name,
            user_id=session.user_id,
            session_id=session_id,
            model_chain=_json.dumps(get_agent_chain(agent)),
            model_chain_index=0,
            title=f"Druppie sandbox: {task[:80]}",
            source="api",
            author_id="druppie-agent",
            db=db,
        )

        logger.info(
            "execute_coding_task: prompt sent, pausing for webhook",
            sandbox_session_id=result["sandbox_session_id"],
            message_id=result["message_id"],
        )

        return {
            "success": True,
            "status": "waiting_sandbox",
            "sandbox_session_id": result["sandbox_session_id"],
            "message_id": result["message_id"],
        }

    except SandboxCreateError as e:
        logger.error("execute_coding_task: failed", error=str(e))
        return {"success": False, "error": str(e)}


# =============================================================================
# TEST REPORT TOOL IMPLEMENTATION
# =============================================================================

async def test_report(
    iteration: int,
    tests_passed: bool,
    summary: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
    changed_files: list[str] | None = None,
    test_command: str | None = None,
    failed_count: int | None = None,
    passed_count: int | None = None,
    error_classification: str | None = None,
    strategy: str | None = None,
) -> dict:
    """Report structured test iteration results.

    Called by test_executor agent to log each test iteration. The data is
    automatically stored as a ToolCall record for tracking and analysis.

    Args:
        iteration: Current iteration number (1-based)
        tests_passed: Whether all tests passed
        summary: Human-readable summary
        session_id: Session UUID
        agent_run_id: Agent run UUID
        execution_repo: Execution repository
        changed_files: Files changed in this iteration
        test_command: Test command executed
        failed_count: Number of failed tests
        passed_count: Number of passed tests
        error_classification: Type of error encountered
        strategy: Fix strategy used

    Returns:
        Acknowledgment with iteration data
    """
    logger.info(
        "test_report",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        iteration=iteration,
        tests_passed=tests_passed,
        failed_count=failed_count,
        passed_count=passed_count,
        error_classification=error_classification,
        strategy=strategy,
        summary=summary[:200] if summary else "",
    )

    return {
        "status": "recorded",
        "iteration": iteration,
        "tests_passed": tests_passed,
        "message": f"Test report for iteration {iteration} recorded. {'PASS' if tests_passed else 'FAIL'}",
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
    elif tool_name == "create_message":
        return await create_message(
            content=args.get("content", ""),
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
    elif tool_name == "invoke_skill":
        return await invoke_skill(
            skill_name=args.get("skill_name", ""),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
        )
    elif tool_name == "execute_coding_task":
        return await execute_sandbox_coding_task(
            args=args,
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
        )
    elif tool_name == "test_report":
        return await test_report(
            iteration=args.get("iteration", 0),
            tests_passed=args.get("tests_passed", False),
            summary=args.get("summary", ""),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
            changed_files=args.get("changed_files"),
            test_command=args.get("test_command"),
            failed_count=args.get("failed_count"),
            passed_count=args.get("passed_count"),
            error_classification=args.get("error_classification"),
            strategy=args.get("strategy"),
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
        "create_message",
        "invoke_skill",
        "execute_coding_task",
        "test_report",
    )


def is_hitl_tool(tool_name: str) -> bool:
    """Check if a tool name is a HITL tool (requires user answer)."""
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
    )
