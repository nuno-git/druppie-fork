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

import base64
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.core.translation import TranslationNotAvailableError

if TYPE_CHECKING:
    from druppie.repositories import ExecutionRepository

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS (OpenAI function format, keyed by name)
# =============================================================================

# Default builtin tools every agent gets (unless overridden in YAML)
DEFAULT_BUILTIN_TOOLS = ["done", "hitl_ask_question", "hitl_ask_multiple_choice_question", "read_attachment"]

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
                    "attachment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional attachment IDs to display with this question (e.g. PDF files the user can download before answering)",
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
                    "attachment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional attachment IDs to display with this question (e.g. PDF files the user can download before answering)",
                    },
                },
                "required": ["question", "choices"],
            },
        },
    },
    "ask_expert_question": {
        "type": "function",
        "function": {
            "name": "ask_expert_question",
            "description": (
                "Ask a free-form question to an expert (a user with a specific Keycloak role) "
                "instead of the session owner. Use this when you need domain expertise the "
                "current user does not have. The workflow pauses until any user holding the "
                "given role answers. The session owner CANNOT answer expert questions unless "
                "they themselves hold the role. Available expert_role values are restricted "
                "by the agent's allowed_expert_roles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expert_role": {
                        "type": "string",
                        "description": "Keycloak role of the expert pool to ask (must be in this agent's allowed_expert_roles).",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to ask the expert.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked.",
                    },
                    "attachment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional attachment IDs to display with this question (e.g. PDF files the user can download before answering)",
                    },
                },
                "required": ["expert_role", "question"],
            },
        },
    },
    "ask_expert_multiple_choice_question": {
        "type": "function",
        "function": {
            "name": "ask_expert_multiple_choice_question",
            "description": (
                "Ask an expert (a user with a specific Keycloak role) a multiple choice question. "
                "Same routing rules as ask_expert_question. An 'Other' option is added "
                "automatically — do NOT include it in your choices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expert_role": {
                        "type": "string",
                        "description": "Keycloak role of the expert pool to ask (must be in this agent's allowed_expert_roles).",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to ask the expert.",
                    },
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of choices for the expert to select from. Do NOT include an 'Other' option — one is added automatically.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context explaining why this question is being asked.",
                    },
                    "attachment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional attachment IDs to display with this question (e.g. PDF files the user can download before answering)",
                    },
                },
                "required": ["expert_role", "question", "choices"],
            },
        },
    },
    "done": {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal task completion with a DETAILED summary. The summary is the ONLY way to pass information to the next agent in the pipeline. Optionally specify next_agent to route directly to a specific agent, bypassing the Planner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "DETAILED summary including: (1) your own 'Agent [role]:' line with key outputs (URLs, branch names, container names, file paths). Previous agent summaries are auto-prepended by the system. NEVER write just 'Task completed'.",
                    },
                    "next_agent": {
                        "type": "string",
                        "description": "Optional: ID of the agent to run next, bypassing the Planner. Use only when the next step is deterministic. If omitted, the Planner decides as usual.",
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
            "description": "Create a visible message in the chat timeline for the user. Use this to provide a human-friendly summary of what was accomplished. Optionally attach file IDs so the user can download them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The message content to display to the user",
                    },
                    "attachment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of attachment IDs to include with the message so the user can download them",
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
                        "description": "The ID of the project to work with. Required for update_project. Optional for general_chat when the user asks about a specific project by name. ONLY include this if the user mentions a specific project - otherwise OMIT this parameter entirely.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "For create_project: the name for the new project. ONLY include this when intent is 'create_project' - otherwise OMIT this parameter entirely.",
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
    "make_pdf_document": {
        "type": "function",
        "function": {
            "name": "make_pdf_document",
            "description": (
                "Compile a native Typst source file (.typ) into a professionally formatted PDF "
                "using the corporate identity template the .typ file imports. "
                "The agent must first write the .typ file to the workspace, "
                "then call this tool with the workspace-relative path. "
                "The resulting PDF is attached to the chat and a download link is returned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "typ_path": {
                        "type": "string",
                        "description": "Workspace-relative path to the .typ source file (e.g. 'docs/functional-design.typ')",
                    },
                    "output_pdf_name": {
                        "type": "string",
                        "description": "Optional name for the output PDF file. Defaults to '{document_type}-{project_name}.pdf'",
                    },
                },
                "required": ["typ_path"],
            },
        },
    },
    "verify_typst": {
        "type": "function",
        "function": {
            "name": "verify_typst",
            "description": (
                "Run a syntax-only check on a Typst source file before committing it. "
                "Does not produce a PDF. Use this to catch syntax errors in .typ files "
                "before pushing to Gitea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "typ_path": {
                        "type": "string",
                        "description": "Workspace-relative path to the .typ file to validate (e.g. 'docs/document.typ')",
                    },
                },
                "required": ["typ_path"],
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
                    "repo_target": {
                        "type": "string",
                        "enum": ["project", "druppie_core"],
                        "description": (
                            "Which repo the sandbox works on. "
                            "'project' (default) = session's Gitea project repo. "
                            "'druppie_core' = Druppie's own GitHub repo (dual-repo: core + project context)."
                        ),
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
    "read_attachment": {
        "type": "function",
        "function": {
            "name": "read_attachment",
            "description": "Read the content of a file uploaded by the user. Use this when you need to see the contents of an attached file listed in the session context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "The UUID of the attachment to read",
                    },
                },
                "required": ["attachment_id"],
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

    if project_id and isinstance(project_id, str):
        normalized = project_id.lower().strip()
        if normalized in ("null", "none") or normalized == "":
            project_id = None

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

                        project_repo.update_repo(
                            project_id=new_project.id,
                            repo_name=repo_name,
                            repo_owner=repo_owner,
                        )

                        result["repo_name"] = repo_name
                        result["repo_owner"] = repo_owner

                        logger.info(
                            "gitea_repo_created",
                            project_id=str(new_project.id),
                            repo_name=repo_name,
                            repo_owner=repo_owner,
                        )

                        # Push project template into the new repo
                        from pathlib import Path

                        template_dir = Path(__file__).resolve().parent.parent / "templates" / "project"
                        if template_dir.is_dir():
                            template_result = await gitea.push_template(
                                repo=repo_name,
                                template_dir=str(template_dir),
                                owner=repo_owner,
                            )
                            if template_result.get("success"):
                                logger.info(
                                    "project_template_pushed",
                                    repo_name=repo_name,
                                    files=template_result.get("files_pushed"),
                                )
                            else:
                                logger.warning(
                                    "project_template_push_failed",
                                    repo_name=repo_name,
                                    errors=template_result.get("errors"),
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
        if project_id:
            try:
                session_repo.update_project(session_id, UUID(project_id))
                final_project_id = UUID(project_id)
                result["project_id"] = project_id
                result["message"] = f"Intent set to general_chat with project context: {project_id}"
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid project_id format: {project_id}",
                }
        else:
            result["message"] = "Intent set to general_chat"

    _update_planner_prompt(
        execution_repo,
        session_id,
        intent,
        final_project_id,
        project_name if intent == "create_project" else None,
    )

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
    project_name: str | None = None,
) -> None:
    """Update the pending planner's prompt with intent context.

    Finds the pending planner AgentRun for this session and prepends
    intent context to its planned_prompt.

    Args:
        execution_repo: Execution repository
        session_id: Session UUID
        intent: Intent type
        project_id: Project UUID (or None)
        project_name: Project name (optional, for create_project)
    """
    from druppie.repositories import ProjectRepository

    planner_run = execution_repo.get_pending_by_agent_id(session_id, "planner")

    if not planner_run:
        logger.warning(
            "planner_run_not_found",
            session_id=str(session_id),
        )
        return

    owner = None
    if project_id:
        try:
            project_repo = ProjectRepository(execution_repo.db)
            project = project_repo.get_by_id(project_id)
            if project:
                if not project_name:
                    project_name = project.name
                owner = project.repo_owner
            else:
                logger.warning(
                    "_update_planner_prompt_project_not_found",
                    project_id=str(project_id),
                    session_id=str(session_id),
                )
        except Exception as e:
            logger.error(
                "_update_planner_prompt_project_lookup_failed",
                project_id=str(project_id),
                session_id=str(session_id),
                error=str(e),
            )

    # Prepend intent context to the existing prompt
    if project_id:
        intent_context = f"INTENT: {intent}\nPROJECT_ID: {str(project_id)}\nPROJECT_NAME: {project_name or 'unknown'}\nOWNER: {owner or 'unknown'}\n\n"
    else:
        intent_context = f"INTENT: {intent}\nPROJECT_ID: new\nPROJECT_NAME: {project_name or 'unknown'}\nOWNER: unknown\n\n"
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
    attachment_ids: list[str] | None = None,
) -> dict:
    """Create a visible message in the chat timeline.

    Called by the summarizer agent to post a user-friendly completion message.
    Translates English agent output to the user's language before storing.

    Args:
        content: Message content to display
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository
        attachment_ids: Optional list of attachment IDs to link to the message

    Returns:
        Success status with message_id and optional attachment_count
    """
    display_content = content
    try:
        from druppie.repositories import SessionRepository
        from druppie.core.translation import get_translation_service
        session_repo = SessionRepository(execution_repo.db)
        session = session_repo.get_by_id(session_id)
        if session and session.language and session.language != "en":
            translator = get_translation_service()
            display_content = await translator.translate_from_english(
                content, session.language
            )
            if display_content != content:
                logger.info(
                    "create_message_translated",
                    session_id=str(session_id),
                    target_language=session.language,
                )
    except TranslationNotAvailableError:
        logger.warning("translation_skipped_no_api_key", session_id=str(session_id))
    except Exception as e:
        logger.warning("create_message_translation_failed", error=str(e))

    # Get next unique sequence number so message never collides with agent_run
    seq = execution_repo.get_next_sequence_number(session_id)

    caller_agent_id = "summarizer"
    try:
        caller_run = execution_repo.get_by_id(agent_run_id)
        if caller_run and caller_run.agent_id:
            caller_agent_id = caller_run.agent_id
    except Exception:
        logger.debug("caller_agent_id_lookup_failed", agent_run_id=str(agent_run_id))

    message_id = execution_repo.create_message(
        session_id=session_id,
        role="assistant",
        content=display_content,
        content_english=content if display_content != content else None,
        agent_run_id=agent_run_id,
        agent_id=caller_agent_id,
        sequence_number=seq,
    )
    execution_repo.flush()

    linked_count = 0
    if attachment_ids:
        raw_ids = [
            aid for aid in attachment_ids
            if aid and isinstance(aid, str) and aid.lower() not in ("null", "none", "")
        ]
        if raw_ids:
            logger.info(
                "create_message_attachments_received",
                session_id=str(session_id),
                raw_count=len(attachment_ids),
                valid_count=len(raw_ids),
            )
            try:
                from druppie.repositories import AttachmentRepository
                att_repo = AttachmentRepository(execution_repo.db)
                att_ids = [UUID(aid) for aid in raw_ids]
                att_repo.link_to_message(
                    attachment_ids=att_ids,
                    message_id=message_id,
                    session_id=session_id,
                )
                linked_count = len(att_ids)
                execution_repo.flush()
            except Exception as e:
                logger.error(
                    "create_message_attachment_link_failed",
                    session_id=str(session_id),
                    message_id=str(message_id),
                    error=str(e),
                    exc_info=True,
                )
        else:
            logger.warning(
                "create_message_no_valid_attachment_ids",
                session_id=str(session_id),
                message_id=str(message_id),
                received=attachment_ids,
            )

    logger.info(
        "create_message",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        content_preview=display_content[:100] if display_content else "",
        linked_attachments=linked_count,
    )

    result: dict = {"status": "created", "message": "Message added to timeline"}
    if linked_count:
        result["attachment_count"] = linked_count
        result["message_id"] = str(message_id)
    return result


# =============================================================================
# COMPLETION TOOL IMPLEMENTATION
# =============================================================================


def _check_completion_preconditions(
    summary: str,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> str | None:
    """Check if done() preconditions are met for this agent run.

    Returns error message string if a precondition is violated, None if all OK.
    """
    from druppie.agents.definition_loader import AgentDefinitionLoader

    agent_run = execution_repo.get_by_id(agent_run_id)
    if not agent_run or not agent_run.agent_id:
        return None

    try:
        loader = AgentDefinitionLoader()
        definition = loader.load(agent_run.agent_id)
    except Exception:
        # Fail closed: if we can't load the definition, block completion.
        # A guardrail that can be bypassed by an error isn't a guardrail.
        logger.error(
            "completion_precondition_definition_load_failed",
            agent_run_id=str(agent_run_id),
            agent_id=agent_run.agent_id,
        )
        return (
            f"Internal error: could not load agent definition for '{agent_run.agent_id}'. "
            "Cannot verify completion preconditions. Please retry or contact support."
        )

    # Check required summary status keywords
    if definition.required_summary_status:
        req = definition.required_summary_status
        if not any(keyword in summary for keyword in req.one_of):
            return req.error_message

    if not definition.completion_preconditions:
        return None

    for precondition in definition.completion_preconditions:
        if (
            precondition.summary_contains is not None
            and precondition.summary_contains not in summary
        ):
            continue

        if (
            precondition.unless_summary_contains is not None
            and precondition.unless_summary_contains in summary
        ):
            continue

        # Rule matches — check required tools
        tool_calls = execution_repo.get_tool_calls_for_run(agent_run_id)

        for required in precondition.required_tools:
            completed_count = sum(
                1
                for tc in tool_calls
                if tc.tool_name == required.tool_name and tc.status == "completed"
            )
            if completed_count < required.min_calls:
                return precondition.error_message

    return None


async def done(
    summary: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
    next_agent: str | None = None,
) -> dict:
    """Signal that the agent has completed its task.

    This does NOT pause execution - it signals completion immediately.
    Stores the agent's summary for later retrieval. The orchestrator
    handles building the accumulated summary when starting planner runs.

    When next_agent is specified, creates a direct pending run for that agent
    (plus a follow-up planner run), bypassing the normal Planner routing.

    Args:
        summary: Summary of what was accomplished (this agent's own summary)
        session_id: Session UUID
        agent_run_id: Agent run UUID for tracking
        execution_repo: Execution repository
        next_agent: Optional agent ID to route to directly

    Returns:
        Completion status with the agent's own summary
    """
    # Check completion preconditions before proceeding
    precondition_error = _check_completion_preconditions(
        summary=summary,
        agent_run_id=agent_run_id,
        execution_repo=execution_repo,
    )
    if precondition_error:
        logger.warning(
            "completion_precondition_failed",
            agent_run_id=str(agent_run_id),
            summary=summary[:200] if summary else "",
            error=precondition_error,
        )
        return {"success": False, "error": precondition_error}

    logger.info(
        "agent_done",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        summary=summary[:200] if summary else "",
    )

    # Direct routing: if next_agent is specified, validate it against the
    # calling agent's allowed_next_agents list and insert it as the next
    # pending run. Does NOT cancel existing pending runs — just inserts
    # before them. The planner still runs after (already planned).
    if next_agent:
        from druppie.agents.definition_loader import AgentDefinitionLoader
        from druppie.domain.common import AgentRunStatus

        # Get the calling agent's definition to check allowed_next_agents
        current_agent_run = execution_repo.get_by_id(agent_run_id)
        current_agent_id = current_agent_run.agent_id if current_agent_run else None

        loader = AgentDefinitionLoader()
        allowed = False
        try:
            if current_agent_id:
                caller_def = loader.load(current_agent_id)
                if next_agent in caller_def.allowed_next_agents:
                    # Also verify the target agent exists
                    loader.load(next_agent)
                    allowed = True
                else:
                    logger.warning(
                        "next_agent_not_allowed",
                        caller=current_agent_id,
                        next_agent=next_agent,
                        allowed=caller_def.allowed_next_agents,
                        session_id=str(session_id),
                    )
        except Exception as e:
            logger.warning(
                "next_agent_validation_failed",
                next_agent=next_agent,
                error=str(e),
                session_id=str(session_id),
            )

        if allowed:
            # Insert the target agent as the next pending run,
            # BEFORE any existing pending runs (like the planner).
            # We use the lowest pending sequence_number - 1 so
            # get_next_pending() picks this run first.
            existing_next = execution_repo.get_next_pending(session_id)
            if existing_next:
                start_seq = existing_next.sequence_number - 1
            else:
                start_seq = execution_repo.get_next_sequence_number(session_id)

            execution_repo.create_agent_run(
                session_id=session_id,
                agent_id=next_agent,
                status=AgentRunStatus.PENDING,
                planned_prompt="",
                sequence_number=start_seq,
            )
            execution_repo.flush()

            logger.info(
                "next_agent_direct_route",
                session_id=str(session_id),
                from_agent=current_agent_id,
                next_agent=next_agent,
            )
        else:
            next_agent = None  # Ignored — planner will decide as usual

    result = {
        "status": "completed",
        "summary": summary,
    }
    if next_agent:
        result["next_agent"] = next_agent
    return result


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
    from druppie.opencode import create_and_start_sandbox, SandboxCreateError

    task = args.get("task", "")
    from druppie.core.config import DEFAULT_SANDBOX_AGENT
    raw_agent = args.get("agent")
    raw_repo_target = args.get("repo_target")

    if not task:
        return {"success": False, "error": "task is required"}

    # Load caller's sandbox_constraints (if any) so defaults can prefer an
    # allowed value rather than falling through to "project" / DEFAULT_SANDBOX_AGENT
    # and hitting the validation below.
    from druppie.agents.runtime import Agent as AgentLoader
    definition = None
    constraints = None
    try:
        agent_run = execution_repo.get_by_id(agent_run_id)
        if agent_run and agent_run.agent_id:
            definition = AgentLoader._load_definition(agent_run.agent_id)
            if definition and definition.sandbox_constraints:
                constraints = definition.sandbox_constraints
    except Exception:
        logger.debug("sandbox_constraints_load_failed", agent_run_id=str(agent_run_id))

    if raw_agent is not None:
        agent = raw_agent
    elif constraints and constraints.allowed_agents and DEFAULT_SANDBOX_AGENT not in constraints.allowed_agents:
        agent = constraints.allowed_agents[0]
    else:
        agent = DEFAULT_SANDBOX_AGENT

    if raw_repo_target is not None:
        repo_target = raw_repo_target
    elif constraints and constraints.allowed_repo_targets and "project" not in constraints.allowed_repo_targets:
        repo_target = constraints.allowed_repo_targets[0]
    else:
        repo_target = "project"

    # Enforce per-agent sandbox constraints (e.g. architect can only use explore/druppie_core)
    if constraints:
        if constraints.allowed_agents is not None and agent not in constraints.allowed_agents:
            return {
                "success": False,
                "error": (
                    f"Agent '{definition.id}' is only allowed to use sandbox agents: "
                    f"{constraints.allowed_agents}. Got: '{agent}'"
                ),
            }
        if constraints.allowed_repo_targets is not None and repo_target not in constraints.allowed_repo_targets:
            return {
                "success": False,
                "error": (
                    f"Agent '{definition.id}' is only allowed to use repo targets: "
                    f"{constraints.allowed_repo_targets}. Got: '{repo_target}'"
                ),
            }

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

    # Validate repo_target value
    if repo_target not in VALID_REPO_TARGETS:
        return {"success": False, "error": f"Invalid repo_target '{repo_target}'. Must be one of: {VALID_REPO_TARGETS}."}

    from druppie.opencode.repo_context import resolve_repo_context
    try:
        repo_ctx = resolve_repo_context(repo_target, session_id, db)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    repo_owner = repo_ctx.repo_owner
    repo_name = repo_ctx.repo_name
    git_provider = repo_ctx.git_provider
    context_repo_owner = repo_ctx.context_repo_owner
    context_repo_name = repo_ctx.context_repo_name
    context_git_provider = repo_ctx.context_git_provider

    # Append mandatory push instruction to the task prompt.
    # The sandbox agent (OpenCode) must push after committing — the deployer
    # pulls from the remote and unpushed commits are invisible.
    task += (
        "\n\n## MANDATORY: Git push after commit"
        "\nAfter committing your changes, you MUST push to the remote."
        "\n"
        "\nFirst, configure git credentials (the git proxy handles auth server-side,"
        "\nso these are just placeholders to prevent interactive prompts):"
        "\n```bash"
        "\ngit config --global credential.helper '!f() { echo username=x; echo password=x; }; f'"
        "\n```"
        "\n"
        "\nThen push:"
        "\n```bash"
        "\ngit push origin HEAD"
        "\n```"
        "\nVerify the push succeeded by running: git log --oneline origin/HEAD..HEAD"
        "\n(should show nothing). Do NOT complete the task until push succeeds."
    )

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
            git_provider=git_provider,
            context_repo_owner=context_repo_owner,
            context_repo_name=context_repo_name,
            context_git_provider=context_git_provider,
            repo_target=repo_target,
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


async def read_attachment(
    attachment_id: str,
    session_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Read the content of an uploaded attachment."""
    from druppie.db.models import MessageAttachment

    try:
        att_uuid = UUID(attachment_id)
    except (ValueError, AttributeError):
        return {"success": False, "error": f"Invalid attachment ID: {attachment_id}"}

    attachment = (
        execution_repo.db.query(MessageAttachment)
        .filter(
            MessageAttachment.id == att_uuid,
            MessageAttachment.session_id == session_id,
        )
        .first()
    )
    if not attachment:
        return {"success": False, "error": f"Attachment not found: {attachment_id}"}

    if attachment.extracted_text:
        return {
            "success": True,
            "filename": attachment.original_filename,
            "content_type": attachment.content_type,
            "content": attachment.extracted_text,
        }

    return {
        "success": False,
        "filename": attachment.original_filename,
        "error": "No extracted text available for this file",
    }


async def _resolve_typ_file(
    typ_path: str,
    session,
    executor,
) -> tuple[Path | None, str | None]:
    """Resolve a .typ file for builtin tools.

    Checks the local workspace first, runs git pull next, and finally
    falls back to a direct Gitea API read — the canonical source of truth.

    When falling back to Gitea, also fetches image dependencies
    (SVG/PNG/JPG files referenced via #image() in the Typst source or
    exported from ArchiMate models in docs/diagrams/) so that PDF
    compilation can include them.

    Returns (typ_file, error_message).  typ_file is None when resolution fails.
    """
    import subprocess

    from druppie.core.gitea import get_gitea_client
    from druppie.core.workspace import workspace_path_for_session
    from druppie.repositories import ProjectRepository

    workspace_path = workspace_path_for_session(session)
    typ_file = workspace_path / typ_path

    if not typ_file.exists() and (workspace_path / ".git").exists():
        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            logger.warning("_resolve_typ_file_git_pull_failed", session_id=str(session.id), workspace=str(workspace_path))
            pass

    if not typ_file.exists():
        project_repo = ProjectRepository(executor.db)
        project = project_repo.get_by_id(session.project_id)
        if project and project.repo_name and project.repo_owner:
            gitea = get_gitea_client()
            branches = ["main", f"session-{str(session.id)[:8]}"]
            file_content = None
            successful_branch = None
            for branch in branches:
                try:
                    file_result = await gitea.get_file(
                        repo=project.repo_name,
                        path=typ_path,
                        branch=branch,
                        owner=project.repo_owner,
                    )
                    if file_result.get("success") and file_result.get("content"):
                        file_content = file_result["content"]
                        successful_branch = branch
                        break
                except Exception as exc:
                    logger.warning(
                        "_resolve_typ_file_gitea_branch_lookup_failed",
                        session_id=str(session.id),
                        branch=branch,
                        typ_path=typ_path,
                        error=str(exc),
                    )
                    continue

            if file_content is not None:
                fallback_tmp = Path("/app") / "tmp" / "gitea-fallback"
                fallback_tmp.mkdir(parents=True, exist_ok=True)
                temp_dir = fallback_tmp / str(session.id)
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_typ = temp_dir / Path(typ_path).name
                temp_typ.parent.mkdir(parents=True, exist_ok=True)
                temp_typ.write_text(file_content, encoding="utf-8")

                image_refs: set[str] = set()

                for match in re.finditer(r'[#\s]*image\s*\(', file_content):
                    start = match.end()
                    rest = file_content[start:start + 500]
                    quoted = re.search(r'''["']([^"']+)["']''', rest)
                    if quoted:
                        img_path = quoted.group(1).strip()
                        if img_path.startswith(("http://", "https://", "/")):
                            continue
                        image_refs.add(img_path)

                if successful_branch:
                    try:
                        listed = await gitea.list_files(
                            repo=project.repo_name,
                            path="docs/diagrams",
                            branch=successful_branch,
                            owner=project.repo_owner,
                        )
                        if listed.get("success") and listed.get("files"):
                            for f in listed["files"]:
                                if f.get("path", "").endswith(".svg"):
                                    image_refs.add(f["path"])
                    except Exception as exc:
                        logger.warning(
                            "_resolve_typ_file_diagram_list_failed",
                            session_id=str(session.id),
                            branch=successful_branch,
                            error=str(exc),
                        )

                typ_parent = Path(typ_path).parent
                for img_ref in image_refs:
                    if img_ref.startswith("docs/"):
                        gitea_img_path = img_ref
                    else:
                        gitea_img_path = str(typ_parent / img_ref) if typ_parent != Path(".") else img_ref

                    try:
                        img_res = await gitea.get_file(
                            repo=project.repo_name,
                            path=gitea_img_path,
                            branch=successful_branch,
                            owner=project.repo_owner,
                        )
                        if img_res.get("success") and img_res.get("data", {}).get("content"):
                            raw_b64 = img_res["data"]["content"]
                            try:
                                img_bytes = base64.b64decode(raw_b64)
                                local_img = temp_dir / img_ref
                                local_img.parent.mkdir(parents=True, exist_ok=True)
                                local_img.write_bytes(img_bytes)
                            except (ValueError, OSError) as exc:
                                logger.warning(
                                    "_resolve_typ_file_image_decode_failed",
                                    session_id=str(session.id),
                                    img_ref=img_ref,
                                    error=str(exc),
                                )
                                continue
                    except Exception as exc:
                        logger.warning(
                            "_resolve_typ_file_image_download_failed",
                            session_id=str(session.id),
                            img_ref=img_ref,
                            error=str(exc),
                        )
                        continue

                return temp_typ, None
            else:
                return None, f"Typst source file not found in Gitea or workspace: {typ_path}"
        else:
            return None, f"Typst source file not found: {typ_path}"

    if not typ_file.exists():
        return None, f"Typst source file not found: {typ_path}"

    return typ_file, None


async def make_pdf_document(
    typ_path: str,
    output_pdf_name: str | None,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Compile a native Typst source file into a PDF via render cache.

    Caches renders keyed by the source file's Git blob SHA so identical
    revisions are served instantly without recompiling.
    """
    from druppie.repositories import SessionRepository
    from druppie.services.pdf_render_service import PdfRenderService

    db = execution_repo.db
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        return {"success": False, "error": f"Session {session_id} not found"}

    if not session.project_id:
        return {"success": False, "error": "Session has no project"}

    from druppie.repositories import ProjectRepository
    project_repo = ProjectRepository(execution_repo.db)
    project = project_repo.get_by_id(session.project_id)
    if not project or not project.repo_name or not project.repo_owner:
        return {"success": False, "error": "Project has no Gitea repository configured"}

    branches = ["main", f"session-{str(session.id)[:8]}"]
    service = PdfRenderService(db=db)
    pdf_bytes, storage_path, error = await service.get_or_create_pdf(
        project_id=session.project_id,
        repo_name=project.repo_name,
        repo_owner=project.repo_owner,
        typ_path=typ_path,
        branches=branches,
        output_pdf_name=output_pdf_name,
    )
    if error:
        return {"success": False, "error": error}

    pdf_name = output_pdf_name or f"{Path(typ_path).stem}.pdf"
    pdf_name = pdf_name.replace(" ", "_").replace("/", "_")

    attachment_id = None
    attachment_error = None
    try:
        from druppie.repositories import AttachmentRepository

        att_repo = AttachmentRepository(db)
        attachment = att_repo.create(
            original_filename=pdf_name,
            content_type="application/pdf",
            file_size=len(pdf_bytes),
            storage_path=storage_path,
            session_id=session_id,
            owner_user_id=session.user_id,
        )
        db.flush()
        attachment_id = str(attachment.id)
    except Exception as e:
        attachment_error = str(e)
        logger.error(
            "pdf_attachment_storage_failed",
            session_id=str(session_id),
            pdf_name=pdf_name,
            error=attachment_error,
            exc_info=True,
        )

    if not attachment_id:
        return {
            "success": False,
            "error": f"PDF was generated but could not be made downloadable: {attachment_error or 'unknown attachment storage error'}. PDF path: {pdf_name}",
            "pdf_path": pdf_name,
            "pdf_size": len(pdf_bytes),
        }

    return {
        "success": True,
        "pdf_path": pdf_name,
        "pdf_size": len(pdf_bytes),
        "message": f"PDF generated: {pdf_name} ({len(pdf_bytes)} bytes)",
        "attachment_id": attachment_id,
    }


async def verify_typst(
    typ_path: str,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
) -> dict:
    """Run a syntax-only check on a .typ file. Does not produce a PDF."""
    from druppie.repositories import SessionRepository

    db = execution_repo.db
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        return {"success": False, "error": f"Session {session_id} not found"}

    typ_file, error = await _resolve_typ_file(typ_path, session, execution_repo)
    if error:
        return {"success": False, "error": error}

    from druppie.services.document_formatter_service import DocumentFormatterService

    service = DocumentFormatterService()
    is_valid, error_msg = service.verify_typ(typ_file)

    if is_valid:
        return {"success": True, "message": f"{typ_path} is syntactically valid."}
    else:
        return {"success": False, "error": f"Syntax check failed for {typ_path}:\n{error_msg}"}


# =============================================================================
# TOOL EXECUTION (called by ToolExecutor)
# =============================================================================

async def execute_builtin(
    tool_name: str,
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
    tool_call_id: UUID | None = None,
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
            next_agent=args.get("next_agent"),
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
            attachment_ids=args.get("attachment_ids"),
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
    elif tool_name == "make_pdf_document":
        return await make_pdf_document(
            typ_path=args.get("typ_path", ""),
            output_pdf_name=args.get("output_pdf_name"),
            session_id=session_id,
            agent_run_id=agent_run_id,
            execution_repo=execution_repo,
        )
    elif tool_name == "verify_typst":
        return await verify_typst(
            typ_path=args.get("typ_path", ""),
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
    elif tool_name == "read_attachment":
        return await read_attachment(
            attachment_id=args.get("attachment_id", ""),
            session_id=session_id,
            execution_repo=execution_repo,
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
        "ask_expert_question",
        "ask_expert_multiple_choice_question",
        "done",
        "make_plan",
        "set_intent",
        "create_message",
        "invoke_skill",
        "make_pdf_document",
        "verify_typst",
        "execute_coding_task",
        "test_report",
        "read_attachment",
    )


def is_hitl_tool(tool_name: str) -> bool:
    """Check if a tool name pauses the agent for a human answer.

    Includes both classic HITL tools (session owner answers) and ask_expert
    tools (a user holding a given role answers). Both share the Question
    record and pause/resume plumbing.
    """
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
        "ask_expert_question",
        "ask_expert_multiple_choice_question",
    )


def is_ask_expert_tool(tool_name: str) -> bool:
    """Check if a tool name is one of the ask_expert variants."""
    return tool_name in (
        "ask_expert_question",
        "ask_expert_multiple_choice_question",
    )
