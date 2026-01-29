"""Tool Executor - single entry point for ALL tool execution.

This module executes both builtin tools and MCP tools. It handles:
- Checking approval requirements (via MCPConfig)
- Creating Approval records when needed (via ApprovalRepository)
- Creating Question records for HITL tools (via QuestionRepository)
- Executing tools (via builtin_tools.py or MCPHttp)
- Updating ToolCall records with results (via ExecutionRepository)

The ToolCall record is the source of truth. Question and Approval
records link back to it via tool_call_id.

Flow:
    ToolExecutor.execute(tool_call_id)
        │
        ├─► MCP tool needs approval? → Create Approval, status=waiting_approval
        ├─► Builtin HITL tool? → Create Question, status=waiting_answer
        ├─► Builtin other? → Execute, status=completed
        └─► MCP tool? → Call MCPHttp, status=completed/failed

All database operations go through repositories (no raw db session usage).
"""

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.core.mcp_config import MCPConfig
from druppie.execution.mcp_http import MCPHttp, MCPHttpError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

logger = structlog.get_logger()


class ToolCallStatus:
    """Tool call status constants."""
    PENDING = "pending"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_ANSWER = "waiting_answer"
    COMPLETED = "completed"
    FAILED = "failed"


# Builtin tool names (no MCP server needed)
BUILTIN_TOOLS = {
    "done",
    "make_plan",
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
}

# HITL tools require user answer (create Question record)
HITL_TOOLS = {
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
}


class ToolExecutor:
    """Executes all tools (builtin and MCP).

    All database operations go through repositories.

    Usage:
        executor = ToolExecutor(db, mcp_http, mcp_config)
        status = await executor.execute(tool_call_id)
    """

    def __init__(
        self,
        db: "DBSession",
        mcp_http: MCPHttp,
        mcp_config: MCPConfig,
    ):
        """Initialize with db session and MCP components.

        Args:
            db: Database session (passed to repositories)
            mcp_http: HTTP client for MCP servers
            mcp_config: MCP configuration (approval rules, server URLs)
        """
        self.db = db
        self.mcp_http = mcp_http
        self.mcp_config = mcp_config

        # Lazy load repositories
        self._execution_repo = None
        self._approval_repo = None
        self._question_repo = None

    @property
    def execution_repo(self):
        """ExecutionRepository for ToolCall operations."""
        if self._execution_repo is None:
            from druppie.repositories import ExecutionRepository
            self._execution_repo = ExecutionRepository(self.db)
        return self._execution_repo

    @property
    def approval_repo(self):
        """ApprovalRepository for Approval operations."""
        if self._approval_repo is None:
            from druppie.repositories import ApprovalRepository
            self._approval_repo = ApprovalRepository(self.db)
        return self._approval_repo

    @property
    def question_repo(self):
        """QuestionRepository for Question operations."""
        if self._question_repo is None:
            from druppie.repositories import QuestionRepository
            self._question_repo = QuestionRepository(self.db)
        return self._question_repo

    def _get_agent_definition(self, agent_run_id: UUID | None):
        """Load agent definition for approval overrides.

        Gets the agent_id from the agent_run, then loads the definition.
        Returns None if agent_run not found (falls back to global defaults).
        """
        if not agent_run_id:
            return None

        try:
            # Get agent_run to find agent_id
            agent_run = self.execution_repo.get_by_id(agent_run_id)
            if not agent_run or not agent_run.agent_id:
                return None

            # Load agent definition
            from druppie.agents.runtime import Agent
            return Agent._load_definition(agent_run.agent_id)

        except Exception as e:
            logger.warning(
                "failed_to_load_agent_definition",
                agent_run_id=str(agent_run_id),
                error=str(e),
            )
            return None

    def _get_project_repo_info(self, session_id: UUID) -> tuple[str | None, str | None]:
        """Get the repo_name and repo_owner from the session's project.

        Looks up session → project → (repo_name, repo_owner) for auto-injection into docker:build.
        Returns (None, None) if session has no project or project has no repo.
        """
        try:
            from druppie.db.models import Session, Project

            # Get session to find project_id
            session = self.db.query(Session).filter(Session.id == session_id).first()
            if not session or not session.project_id:
                logger.debug("Session has no project", session_id=str(session_id))
                return None, None

            # Get project to find repo_name and repo_owner
            project = self.db.query(Project).filter(Project.id == session.project_id).first()
            if not project or not project.repo_name:
                logger.debug("Project has no repo_name", project_id=str(session.project_id))
                return None, None

            return project.repo_name, project.repo_owner

        except Exception as e:
            logger.warning(
                "failed_to_get_project_repo_info",
                session_id=str(session_id),
                error=str(e),
            )
            return None, None

    def _get_session_context(self, session_id: UUID) -> dict:
        """Get user_id and project_id from session for label injection.

        Looks up session → (user_id, project_id) for auto-injection into docker:run labels.
        Returns empty dict if session not found.
        """
        try:
            from druppie.db.models import Session

            session = self.db.query(Session).filter(Session.id == session_id).first()
            if not session:
                logger.debug("Session not found", session_id=str(session_id))
                return {}

            context = {}
            if session.user_id:
                context["user_id"] = str(session.user_id)
            if session.project_id:
                context["project_id"] = str(session.project_id)

            return context

        except Exception as e:
            logger.warning(
                "failed_to_get_session_context",
                session_id=str(session_id),
                error=str(e),
            )
            return {}

    async def execute(self, tool_call_id: UUID) -> str:
        """Execute a tool call.

        This is the main entry point. It:
        1. Loads the ToolCall from DB via ExecutionRepository
        2. Checks if approval is needed (for MCP tools) via MCPConfig
        3. Executes the tool (builtin or MCP)
        4. Updates the ToolCall record via ExecutionRepository

        Args:
            tool_call_id: ID of the ToolCall to execute

        Returns:
            Final status: completed, failed, waiting_approval, or waiting_answer
        """
        # Step 1: Load tool call from database
        tool_call = self.execution_repo.get_tool_call(tool_call_id)
        if not tool_call:
            logger.error("tool_call_not_found", tool_call_id=str(tool_call_id))
            return ToolCallStatus.FAILED

        logger.info(
            "tool_executor_execute",
            tool_call_id=str(tool_call_id),
            tool_name=tool_call.tool_name,
            mcp_server=tool_call.mcp_server,
        )

        # Step 2: Determine tool type
        # Builtin tools have mcp_server="builtin" (set by runtime.py)
        is_builtin = tool_call.mcp_server == "builtin" or tool_call.tool_name in BUILTIN_TOOLS
        is_hitl = tool_call.tool_name in HITL_TOOLS

        # Step 3: Check approval for MCP tools (not builtin)
        if not is_builtin and tool_call.mcp_server:
            # Load agent definition for approval overrides
            agent_definition = self._get_agent_definition(tool_call.agent_run_id)

            needs_approval, required_role = self.mcp_config.needs_approval(
                tool_call.mcp_server,
                tool_call.tool_name,
                agent_definition=agent_definition,
            )
            if needs_approval:
                # Create Approval record and pause execution
                return await self._create_approval_and_wait(tool_call, required_role)

        # Step 4: Execute based on tool type
        if is_hitl:
            # HITL tools create Question record and pause for user answer
            return await self._execute_hitl_tool(tool_call)
        elif is_builtin:
            # Non-HITL builtin tools (done, make_plan) execute immediately
            return await self._execute_builtin_tool(tool_call)
        else:
            # MCP tools execute via HTTP
            return await self._execute_mcp_tool(tool_call)

    async def execute_after_approval(self, approval_id: UUID) -> str:
        """Execute a tool after it has been approved.

        Called when user approves a tool execution in the UI.

        Args:
            approval_id: ID of the approved Approval record

        Returns:
            Final status: completed or failed
        """
        # Get approval record
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            logger.error("approval_not_found", approval_id=str(approval_id))
            return ToolCallStatus.FAILED

        # Verify approval status
        if approval.status != "approved":
            logger.error("approval_not_approved", status=approval.status)
            return ToolCallStatus.FAILED

        # Get associated tool call
        tool_call = self.execution_repo.get_tool_call(approval.tool_call_id)
        if not tool_call:
            logger.error("tool_call_not_found", tool_call_id=str(approval.tool_call_id))
            return ToolCallStatus.FAILED

        logger.info(
            "execute_after_approval",
            approval_id=str(approval_id),
            tool_call_id=str(tool_call.id),
        )

        # Execute the MCP tool (skip approval check since already approved)
        return await self._execute_mcp_tool(tool_call)

    async def complete_after_answer(self, question_id: UUID, answer: str) -> str:
        """Complete a HITL tool after the user answers.

        Called when user submits an answer to a question in the UI.

        Args:
            question_id: ID of the answered Question record
            answer: User's answer

        Returns:
            Final status: completed
        """
        # Get question record
        question = self.question_repo.get_by_id(question_id)
        if not question:
            logger.error("question_not_found", question_id=str(question_id))
            return ToolCallStatus.FAILED

        # Update question with answer
        self.question_repo.update_answer(question_id, answer)

        # Get associated tool call
        tool_call_id = question.tool_call_id
        if not tool_call_id:
            logger.error("question_missing_tool_call_id", question_id=str(question_id))
            return ToolCallStatus.FAILED

        # Build result that will be passed back to agent
        result = {
            "status": "answered",
            "answer": answer,
            "question": question.question,
            "question_type": question.question_type,
        }

        # Update tool call with result
        self.execution_repo.update_tool_call(
            tool_call_id,
            status=ToolCallStatus.COMPLETED,
            result=result,
        )
        self.db.commit()

        logger.info(
            "hitl_tool_completed",
            question_id=str(question_id),
            tool_call_id=str(tool_call_id),
        )

        return ToolCallStatus.COMPLETED

    async def _create_approval_and_wait(self, tool_call, required_role: str | None) -> str:
        """Create an Approval record and set tool call to waiting.

        This is called when an MCP tool requires approval before execution.
        Creates an Approval record via ApprovalRepository.

        Args:
            tool_call: The ToolCall model
            required_role: Role required to approve (e.g., "developer")

        Returns:
            ToolCallStatus.WAITING_APPROVAL
        """
        # Create approval record via repository
        approval = self.approval_repo.create(
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            mcp_server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments or {},
            required_role=required_role or "developer",
        )

        # Update tool call status to waiting
        self.execution_repo.update_tool_call(
            tool_call.id,
            status=ToolCallStatus.WAITING_APPROVAL,
        )
        self.db.commit()

        logger.info(
            "approval_created",
            approval_id=str(approval.id),
            tool_call_id=str(tool_call.id),
            required_role=required_role,
        )

        return ToolCallStatus.WAITING_APPROVAL

    async def _execute_hitl_tool(self, tool_call) -> str:
        """Execute a HITL tool by creating a Question record.

        HITL (Human-in-the-Loop) tools pause execution to ask the user a question.
        Creates a Question record via QuestionRepository.

        Args:
            tool_call: The ToolCall model

        Returns:
            ToolCallStatus.WAITING_ANSWER
        """
        args = tool_call.arguments or {}

        # Determine question type from tool name
        if tool_call.tool_name == "hitl_ask_multiple_choice_question":
            question_type = "choice"
            choices = [{"text": c} for c in args.get("choices", [])]
        else:
            question_type = "text"
            choices = None

        # Create question record via repository
        question = self.question_repo.create(
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            question=args.get("question", ""),
            question_type=question_type,
            choices=choices,
        )

        # Update tool call status to waiting
        self.execution_repo.update_tool_call(
            tool_call.id,
            status=ToolCallStatus.WAITING_ANSWER,
        )
        self.db.commit()

        logger.info(
            "question_created",
            question_id=str(question.id),
            tool_call_id=str(tool_call.id),
            question_type=question_type,
        )

        return ToolCallStatus.WAITING_ANSWER

    async def _execute_builtin_tool(self, tool_call) -> str:
        """Execute a non-HITL builtin tool.

        Builtin tools (done, make_plan) are executed via builtin_tools.execute_builtin().

        Args:
            tool_call: The ToolCall model

        Returns:
            ToolCallStatus.COMPLETED or ToolCallStatus.FAILED
        """
        from druppie.agents.builtin_tools import execute_builtin

        args = tool_call.arguments or {}

        try:
            # Mark as executing
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.EXECUTING,
            )

            # Execute the builtin tool
            result = await execute_builtin(
                tool_name=tool_call.tool_name,
                args=args,
                session_id=tool_call.session_id,
                agent_run_id=tool_call.agent_run_id,
                db=self.db,
            )

            # Mark as completed with result
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.COMPLETED,
                result=result,
            )
            self.db.commit()

            logger.info(
                "builtin_tool_completed",
                tool_call_id=str(tool_call.id),
                tool_name=tool_call.tool_name,
                result_status=result.get("status"),
            )

            return ToolCallStatus.COMPLETED

        except Exception as e:
            logger.error(
                "builtin_tool_error",
                tool_call_id=str(tool_call.id),
                tool_name=tool_call.tool_name,
                error=str(e),
            )
            # Mark as failed with error
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=str(e),
            )
            self.db.commit()
            return ToolCallStatus.FAILED

    async def _execute_mcp_tool(self, tool_call) -> str:
        """Execute an MCP tool via HTTP.

        MCP tools are executed via MCPHttp which calls the MCP server.

        Args:
            tool_call: The ToolCall model

        Returns:
            ToolCallStatus.COMPLETED or ToolCallStatus.FAILED
        """
        args = tool_call.arguments or {}

        # Auto-inject session_id for MCP tools that support it
        # This enables standalone operation without requiring the LLM to pass session_id
        if "session_id" not in args and tool_call.session_id:
            args = {**args, "session_id": str(tool_call.session_id)}
            logger.debug(
                "Auto-injected session_id into MCP tool args",
                tool_name=tool_call.tool_name,
                session_id=str(tool_call.session_id),
            )

        # Auto-inject repo_name and repo_owner for docker:build calls
        # This enables git-based builds without requiring LLM to know the repo details
        if (
            tool_call.mcp_server == "docker"
            and tool_call.tool_name == "build"
            and "repo_name" not in args
            and "git_url" not in args
            and tool_call.session_id
        ):
            repo_name, repo_owner = self._get_project_repo_info(tool_call.session_id)
            if repo_name:
                args = {**args, "repo_name": repo_name}
                if repo_owner:
                    args = {**args, "repo_owner": repo_owner}
                logger.info(
                    "Auto-injected repo info into docker:build args",
                    tool_name=tool_call.tool_name,
                    repo_name=repo_name,
                    repo_owner=repo_owner,
                )

        # Auto-inject repo_name and repo_owner for coding MCP write operations
        # This enables pushing to the correct user repo
        if (
            tool_call.mcp_server == "coding"
            and tool_call.tool_name in ("write_file", "batch_write_files")
            and "repo_name" not in args
            and tool_call.session_id
        ):
            repo_name, repo_owner = self._get_project_repo_info(tool_call.session_id)
            if repo_name:
                args = {**args, "repo_name": repo_name}
                if repo_owner:
                    args = {**args, "repo_owner": repo_owner}
                logger.debug(
                    "Auto-injected repo info into coding write args",
                    tool_name=tool_call.tool_name,
                    repo_name=repo_name,
                    repo_owner=repo_owner,
                )

        # Auto-inject user_id and project_id for docker:run calls
        # This enables ownership tracking via container labels
        if (
            tool_call.mcp_server == "docker"
            and tool_call.tool_name == "run"
            and tool_call.session_id
        ):
            context = self._get_session_context(tool_call.session_id)
            if "user_id" not in args and context.get("user_id"):
                args = {**args, "user_id": context["user_id"]}
            if "project_id" not in args and context.get("project_id"):
                args = {**args, "project_id": context["project_id"]}
            if context:
                logger.info(
                    "Auto-injected ownership labels into docker:run args",
                    tool_name=tool_call.tool_name,
                    user_id=context.get("user_id"),
                    project_id=context.get("project_id"),
                )

        try:
            # Mark as executing
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.EXECUTING,
            )

            # Execute via HTTP
            result = await self.mcp_http.call(
                tool_call.mcp_server,
                tool_call.tool_name,
                args,
            )

            # Check if result indicates failure
            is_success = result.get("success", True)

            # Update tool call with result
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.COMPLETED if is_success else ToolCallStatus.FAILED,
                result=result if is_success else None,
                error=result.get("error") if not is_success else None,
            )
            self.db.commit()

            logger.info(
                "mcp_tool_completed",
                tool_call_id=str(tool_call.id),
                mcp_server=tool_call.mcp_server,
                tool_name=tool_call.tool_name,
                success=is_success,
            )

            return ToolCallStatus.COMPLETED if is_success else ToolCallStatus.FAILED

        except MCPHttpError as e:
            logger.error(
                "mcp_tool_error",
                tool_call_id=str(tool_call.id),
                mcp_server=tool_call.mcp_server,
                tool_name=tool_call.tool_name,
                error=str(e),
                retryable=e.retryable,
            )
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=str(e),
            )
            self.db.commit()
            return ToolCallStatus.FAILED

        except Exception as e:
            logger.error(
                "mcp_tool_unexpected_error",
                tool_call_id=str(tool_call.id),
                error=str(e),
            )
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=str(e),
            )
            self.db.commit()
            return ToolCallStatus.FAILED
