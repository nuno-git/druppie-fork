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
    "set_intent",
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
    "create_message",
    "invoke_skill",
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

    def _apply_injection_rules(
        self,
        server: str,
        tool_name: str,
        args: dict,
        session_id: UUID | None,
    ) -> dict:
        """Apply declarative injection rules from mcp_config.yaml.

        Resolves context paths and injects values into tool arguments.

        For hidden params: always override LLM-provided values with the DB value.
        This prevents the LLM from guessing wrong values for params it shouldn't see.

        For non-hidden params: only inject if not already provided by LLM.

        Args:
            server: MCP server name
            tool_name: Tool name
            args: Original tool arguments
            session_id: Session ID for context resolution

        Returns:
            Updated args dict with injected values
        """
        from druppie.execution.tool_context import ToolContext

        # Get injection rules for this server/tool
        rules = self.mcp_config.get_injection_rules(server, tool_name)
        if not rules:
            logger.info(
                "no_injection_rules",
                server=server,
                tool=tool_name,
            )
            return args

        logger.info(
            "applying_injection_rules",
            server=server,
            tool=tool_name,
            num_rules=len(rules),
            rule_params=[r.param for r in rules],
            session_id=str(session_id) if session_id else None,
            original_args=list(args.keys()),
        )

        # Create context for resolving paths
        context = ToolContext(self.db, session_id)

        # Apply each rule
        injected_args = dict(args)
        for rule in rules:
            # For hidden params: always override (LLM shouldn't provide these)
            # For non-hidden params: skip if LLM already provided a value
            if not rule.hidden and rule.param in injected_args:
                continue

            # Resolve the value from context
            value = context.resolve(rule.from_path)
            if value is not None:
                if rule.hidden and rule.param in injected_args:
                    logger.warning(
                        "overriding_llm_value_for_hidden_param",
                        server=server,
                        tool=tool_name,
                        param=rule.param,
                        llm_value=injected_args[rule.param],
                        injected_value=value,
                    )
                injected_args[rule.param] = value
                logger.info(
                    "injected_param",
                    server=server,
                    tool=tool_name,
                    param=rule.param,
                    from_path=rule.from_path,
                    value=value,
                )
            else:
                logger.warning(
                    "injection_value_is_none",
                    server=server,
                    tool=tool_name,
                    param=rule.param,
                    from_path=rule.from_path,
                )

        logger.info(
            "injection_complete",
            server=server,
            tool=tool_name,
            final_args=list(injected_args.keys()),
        )

        return injected_args

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

    def _validate_tool_arguments(self, tool_call) -> str | None:
        """Validate tool arguments against the tool's schema.

        Uses the unified ToolRegistry to get the tool definition and validate
        the LLM-provided arguments. This catches type errors, missing required
        fields, and invalid values before execution.

        If validation fails with original args but succeeds with normalized args
        (e.g., "null" string -> None), updates tool_call.arguments in-place
        with the normalized values.

        Args:
            tool_call: The ToolCall model with tool_name, mcp_server, arguments

        Returns:
            Error message string if validation fails, None if valid
        """
        try:
            from druppie.core.tool_registry import get_tool_registry

            registry = get_tool_registry()

            # Build full tool name (e.g., "coding_read_file" or "done")
            if tool_call.mcp_server and tool_call.mcp_server != "builtin":
                full_name = f"{tool_call.mcp_server}_{tool_call.tool_name}"
            else:
                full_name = tool_call.tool_name

            # Get tool definition
            tool_def = registry.get(full_name)
            if not tool_def:
                # Tool not in registry - skip validation (MCP server will validate)
                logger.debug(
                    "tool_not_in_registry_skipping_validation",
                    tool_name=full_name,
                )
                return None

            # Validate arguments - this tries original first, then normalized if needed
            is_valid, error_msg, validated_params, normalized_args = tool_def.validate_arguments(tool_call.arguments)
            if not is_valid:
                return (
                    f"Invalid arguments for tool '{full_name}': {error_msg}. "
                    f"Please check the tool schema and provide valid arguments."
                )

            # If normalization was needed (e.g., "null" string -> None), update arguments
            # and persist an audit trail of what changed
            if normalized_args is not None:
                import json

                original_args = tool_call.arguments or {}
                norm_records = []
                for key in normalized_args:
                    orig = original_args.get(key)
                    normed = normalized_args[key]
                    if orig != normed:
                        norm_records.append({
                            "field_name": key,
                            "original_value": json.dumps(orig) if orig is not None else None,
                            "normalized_value": json.dumps(normed) if normed is not None else None,
                        })

                if norm_records:
                    self.execution_repo.create_tool_call_normalizations(
                        tool_call.id, norm_records,
                    )

                logger.debug(
                    "tool_args_normalized",
                    tool_name=full_name,
                    normalized_fields=[r["field_name"] for r in norm_records],
                )
                tool_call.arguments = normalized_args

            return None

        except Exception as e:
            # Log but don't fail - let the tool execution handle it
            logger.warning(
                "tool_validation_exception",
                tool_name=tool_call.tool_name,
                error=str(e),
            )
            return None

    def _is_tool_allowed_via_skill(
        self,
        mcp_server: str,
        tool_name: str,
        agent_run_id: UUID,
    ) -> bool:
        """Check if a tool is allowed via a previously invoked skill.

        Queries the tool_calls table for invoke_skill calls in this agent_run,
        loads those skills, and checks if the requested mcp:tool is in any
        of their allowed_tools.

        Args:
            mcp_server: MCP server name (e.g., "coding", "docker")
            tool_name: Tool name (e.g., "read_file", "build")
            agent_run_id: Agent run ID to check

        Returns:
            True if tool is allowed via a skill, False otherwise
        """
        from druppie.services import SkillService

        # Query all invoke_skill calls in this agent run
        invoked_skills = self.execution_repo.get_invoked_skills(agent_run_id)
        if not invoked_skills:
            return False

        skill_service = SkillService()

        for skill_name in invoked_skills:
            skill = skill_service.get_skill(skill_name)
            if not skill or not skill.allowed_tools:
                continue

            # Check if mcp_server:tool_name is in this skill's allowed_tools
            if mcp_server in skill.allowed_tools:
                if tool_name in skill.allowed_tools[mcp_server]:
                    logger.info(
                        "tool_allowed_via_skill",
                        mcp_server=mcp_server,
                        tool_name=tool_name,
                        skill=skill_name,
                        agent_run_id=str(agent_run_id),
                    )
                    return True

        return False

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

        # Step 2.5: Validate arguments against tool schema
        validation_error = self._validate_tool_arguments(tool_call)
        if validation_error:
            logger.warning(
                "tool_argument_validation_failed",
                tool_call_id=str(tool_call_id),
                tool_name=tool_call.tool_name,
                mcp_server=tool_call.mcp_server,
                error=validation_error,
            )
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=validation_error,
            )
            self.db.commit()
            return ToolCallStatus.FAILED

        # Step 3: Check tool access and approval for MCP tools (not builtin)
        if not is_builtin and tool_call.mcp_server:
            # Load agent definition for approval overrides and access control
            agent_definition = self._get_agent_definition(tool_call.agent_run_id)

            # Validate agent is allowed to use this tool
            # Priority: 1) Direct access via agent.yaml, 2) Access via invoked skill
            if agent_definition is not None:
                allowed_tools = agent_definition.get_allowed_tools(tool_call.mcp_server)
                tool_allowed = (
                    allowed_tools is None  # No restriction (all tools allowed)
                    or tool_call.tool_name in allowed_tools  # Explicitly allowed
                )

                # If not directly allowed, check skill-based access
                if not tool_allowed and tool_call.agent_run_id:
                    tool_allowed = self._is_tool_allowed_via_skill(
                        tool_call.mcp_server,
                        tool_call.tool_name,
                        tool_call.agent_run_id,
                    )

                if not tool_allowed:
                    error_msg = (
                        f"Agent '{agent_definition.id}' is not allowed to use "
                        f"'{tool_call.mcp_server}:{tool_call.tool_name}'. "
                        f"Not in agent.yaml mcps and no invoked skill grants access."
                    )
                    logger.warning("tool_access_denied", error=error_msg)
                    self.execution_repo.update_tool_call(
                        tool_call.id,
                        status=ToolCallStatus.FAILED,
                        error=error_msg,
                    )
                    return ToolCallStatus.FAILED

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

        # Handle rejection: write reason to tool_call so the agent sees it
        if approval.status != "approved":
            tool_call = self.execution_repo.get_tool_call(approval.tool_call_id)
            if tool_call:
                rejection_reason = getattr(approval, "rejection_reason", None) or "No reason provided"
                self.execution_repo.update_tool_call(
                    tool_call.id,
                    status=ToolCallStatus.FAILED,
                    error=f"Tool call was rejected by a human reviewer. Reason: {rejection_reason}",
                )
                self.db.commit()
            logger.info(
                "approval_rejected",
                approval_id=str(approval_id),
                status=approval.status,
                rejection_reason=getattr(approval, "rejection_reason", None),
            )
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
                execution_repo=self.execution_repo,
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
        Uses declarative injection rules from mcp_config.yaml to inject
        context values (session_id, repo_name, etc.) into tool arguments.

        Args:
            tool_call: The ToolCall model

        Returns:
            ToolCallStatus.COMPLETED or ToolCallStatus.FAILED
        """
        args = tool_call.arguments or {}

        logger.info(
            "mcp_tool_pre_injection",
            tool_call_id=str(tool_call.id),
            mcp_server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            session_id=str(tool_call.session_id) if tool_call.session_id else None,
            original_args=list(args.keys()),
        )

        # Apply declarative injection rules from mcp_config.yaml
        # This replaces all the hardcoded injection logic
        args = self._apply_injection_rules(
            server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            args=args,
            session_id=tool_call.session_id,
        )

        logger.info(
            "mcp_tool_post_injection",
            tool_call_id=str(tool_call.id),
            mcp_server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            final_args=list(args.keys()),
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
