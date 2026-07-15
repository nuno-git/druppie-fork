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
from druppie.core.translation import TranslationError, TranslationNotAvailableError
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
    WAITING_ENTRA_AUTH = "waiting_entra_auth"
    WAITING_SANDBOX = "waiting_sandbox"
    COMPLETED = "completed"
    FAILED = "failed"


class EntraTokenMissing(Exception):
    """Tool requires user.entra_token but it resolved to None."""
    def __init__(self, user_id: str | None):
        super().__init__(f"user.entra_token is None for user_id={user_id}")
        self.user_id = user_id


# Builtin tool names (no MCP server needed)
BUILTIN_TOOLS = {
    "done",
    "make_plan",
    "set_intent",
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
    "create_message",
    "invoke_skill",
    "execute_coding_task",
    "test_report",
    "read_attachment",
}

# HITL tools require user answer (create Question record)
HITL_TOOLS = {
    "hitl_ask_question",
    "hitl_ask_multiple_choice_question",
}

# Tools that can take significantly longer than the default 60s timeout.
# These get a generous but bounded timeout (20 min) instead of waiting
# indefinitely, to prevent infinite hangs if the MCP server crashes or
# the network drops.
LONG_RUNNING_TOOLS = {
    "run_tests",
    "install_test_dependencies",
    "compose_up",
}
LONG_RUNNING_TIMEOUT = 1200.0  # 20 minutes

# Servers where the first call can be slow (e.g. Synapse serverless cold start)
SLOW_START_SERVERS = {"dataaccess"}
SLOW_START_TIMEOUT = 120.0  # 2 minutes — covers SQL Login Timeout=90s + overhead


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
        context: "ToolContext | None" = None,
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
            context: Optional pre-built ToolContext (e.g. with Entra token already set)

        Returns:
            Updated args dict with injected values
        """
        from druppie.execution.tool_context import SENSITIVE_PATHS, ToolContext

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

        # Use provided context or create a new one
        if context is None:
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
                is_sensitive = rule.from_path in SENSITIVE_PATHS
                log_value = "<redacted>" if is_sensitive else value

                if rule.hidden and rule.param in injected_args:
                    logger.warning(
                        "overriding_llm_value_for_hidden_param",
                        server=server,
                        tool=tool_name,
                        param=rule.param,
                        llm_value="<redacted>" if is_sensitive else injected_args[rule.param],
                        injected_value=log_value,
                    )
                injected_args[rule.param] = value
                logger.info(
                    "injected_param",
                    server=server,
                    tool=tool_name,
                    param=rule.param,
                    from_path=rule.from_path,
                    value=log_value,
                )
            else:
                # Value resolved to None.
                # If the rule is optional, inject None and let the downstream
                # tool/adapter decide whether it actually needs this value.
                # This is critical for user.entra_token: key-based data sources
                # (e.g., Azure Data Lake) don't need it, while OBO sources
                # (e.g., waterschap) do — but the injection layer can't tell
                # which source the tool will query.
                if rule.optional:
                    # Don't inject the param — let the MCP tool use its
                    # default value (e.g. user_token="" which the tool
                    # converts to None via `or None`).  This avoids
                    # sending JSON null for a str-typed parameter.
                    # Also strip any LLM-guessed value for hidden params.
                    if rule.hidden and rule.param in injected_args:
                        del injected_args[rule.param]
                    logger.info(
                        "skipping_optional_param_value_is_none",
                        server=server,
                        tool=tool_name,
                        param=rule.param,
                        from_path=rule.from_path,
                    )
                elif rule.from_path == "user.entra_token":
                    # Non-optional entra_token missing → signal the caller to pause
                    user_id = str(context.session.user_id) if context.session else None
                    raise EntraTokenMissing(user_id=user_id)
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
            # Rollback in case the exception left the transaction poisoned
            try:
                self.db.rollback()
            except Exception:
                pass
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
            # Log but don't fail - let the tool execution handle it.
            # Rollback in case the exception left the transaction poisoned
            # (e.g. failed flush during normalization).
            try:
                self.db.rollback()
            except Exception:
                pass
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

        # Step 2.6: Generic pre-validation via meta.pre_validate
        # If the tool definition has a meta.pre_validate field, call the named
        # validation tool BEFORE the approval gate so agents can fix errors
        # without wasting a human reviewer's time.
        from druppie.core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        if tool_call.mcp_server and tool_call.mcp_server != "builtin":
            full_name = f"{tool_call.mcp_server}_{tool_call.tool_name}"
        else:
            full_name = tool_call.tool_name
        tool_def = registry.get(full_name) if full_name else None
        if tool_def and tool_def.meta.get("pre_validate"):
            validate_tool_name = tool_def.meta["pre_validate"]
            # Look up the validation tool's schema to pass only the args it expects
            validate_tool_def = registry.get_by_server_and_name(tool_def.server, validate_tool_name)
            validate_args = tool_call.arguments or {}
            if validate_tool_def and validate_tool_def.json_schema:
                expected_params = set(validate_tool_def.json_schema.get("properties", {}).keys())
                if expected_params:
                    validate_args = {k: v for k, v in validate_args.items() if k in expected_params}
            try:
                validate_result = await self.mcp_http.call(
                    tool_def.server, validate_tool_name, validate_args
                )
                if not validate_result.get("valid", True):
                    errors = validate_result.get("errors", [])
                    error_lines = []
                    for e in errors:
                        if isinstance(e, dict):
                            error_lines.append(f"Line {e.get('line', '?')} [{e.get('rule', '?')}]: {e.get('message', '')}")
                        else:
                            error_lines.append(str(e))
                    content_error = (
                        "PRE-VALIDATION FAILED — tool was NOT executed. "
                        "Fix these errors and try again:\n\n"
                        + "\n".join(error_lines)
                    )
                    logger.warning(
                        "pre_validation_failed",
                        tool_call_id=str(tool_call_id),
                        tool_name=tool_call.tool_name,
                    )
                    self.execution_repo.update_tool_call(
                        tool_call.id,
                        status=ToolCallStatus.FAILED,
                        error=content_error,
                    )
                    self.db.commit()
                    return ToolCallStatus.FAILED
            except Exception as e:
                # Pre-validation infrastructure failure — block execution rather than
                # silently skipping validation (which would defeat the purpose)
                error_msg = (
                    f"PRE-VALIDATION ERROR — could not run {validate_tool_name}: {e}. "
                    f"Tool was NOT executed. Retry or contact an administrator."
                )
                logger.error(
                    "pre_validation_exception",
                    tool_name=tool_call.tool_name,
                    validate_tool=validate_tool_name,
                    error=str(e),
                )
                self.execution_repo.update_tool_call(
                    tool_call.id,
                    status=ToolCallStatus.FAILED,
                    error=error_msg,
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
                    self.db.commit()
                    return ToolCallStatus.FAILED

            needs_approval, required_role = self.mcp_config.needs_approval(
                tool_call.mcp_server,
                tool_call.tool_name,
                agent_definition=agent_definition,
            )
            if needs_approval:
                # Translate design content before showing the approval card
                await self._translate_design_content(tool_call)
                return await self._create_approval_and_wait(tool_call, required_role)

        # Step 3.5: Check approval for builtin tools (via agent approval_overrides)
        if is_builtin and not is_hitl:
            agent_definition = self._get_agent_definition(tool_call.agent_run_id)
            if agent_definition is not None:
                override = agent_definition.get_approval_override("builtin", tool_call.tool_name)
                if override is not None and override.requires_approval:
                    logger.info(
                        "builtin_tool_needs_approval",
                        tool_name=tool_call.tool_name,
                        agent_id=agent_definition.id,
                        required_role=override.required_role,
                    )
                    return await self._create_approval_and_wait(tool_call, override.required_role)

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

        # Idempotency guard: prevent double-execution on duplicate approval submissions
        if tool_call.status == ToolCallStatus.COMPLETED:
            logger.info(
                "execute_after_approval_already_completed",
                approval_id=str(approval_id),
                tool_call_id=str(tool_call.id),
            )
            return ToolCallStatus.COMPLETED

        logger.info(
            "execute_after_approval",
            approval_id=str(approval_id),
            tool_call_id=str(tool_call.id),
        )

        # Execute the tool (skip approval check since already approved)
        if tool_call.mcp_server == "builtin" or tool_call.tool_name in BUILTIN_TOOLS:
            return await self._execute_builtin_tool(tool_call)
        return await self._execute_mcp_tool(tool_call)

    async def complete_after_answer(
        self, question_id: UUID, answer_english: str, user_answer: str | None = None, selected_choices: list[int] | None = None
    ) -> str:
        """Complete a HITL tool after the user answers.

        Called when user submits an answer to a question in the UI.

        Args:
            question_id: ID of the answered Question record
            answer_english: User's answer translated to English (for the agent)
            user_answer: Original answer in user's language (what the user typed).
                         If None, uses answer_english for both.
            selected_choices: Indices of selected multiple-choice options

        Returns:
            Final status: completed
        """
        # Get question record
        question = self.question_repo.get_by_id(question_id)
        if not question:
            logger.error("question_not_found", question_id=str(question_id))
            return ToolCallStatus.FAILED

        # Update question with the user's original answer (their language)
        self.question_repo.update_answer(question_id, user_answer or answer_english, selected_choices)

        # Get associated tool call
        tool_call_id = question.tool_call_id
        if not tool_call_id:
            logger.error("question_missing_tool_call_id", question_id=str(question_id))
            return ToolCallStatus.FAILED

        # Build result — contains both English (for agent) and user's original (for frontend).
        # message_history.py strips user_answer when reconstructing for agents.
        choices = None
        if question.choices:
            try:
                choices = [c["text"] if isinstance(c, dict) else c for c in question.choices]
            except (TypeError, KeyError):
                choices = question.choices

        result = {
            "status": "answered",
            "answer_english": answer_english,
            "user_answer": user_answer or answer_english,
            "question": question.question_english or question.question,
            "question_type": question.question_type,
        }
        if selected_choices is not None and choices:
            result["selected_choices"] = [choices[i] for i in selected_choices if i < len(choices)]

        # Include uploaded file contents so the agent sees them immediately
        # (weaker models won't call read_attachment on their own)
        from druppie.db.models import MessageAttachment
        question_attachments = (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.question_id == question_id)
            .all()
        )
        if question_attachments:
            file_contents = []
            for att in question_attachments:
                if att.extracted_text:
                    file_contents.append(
                        f"--- {att.original_filename} ---\n{att.extracted_text}"
                    )
            if file_contents:
                result["uploaded_file_contents"] = "\n\n".join(file_contents)

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

    # Dutch file path mapping for design documents
    DESIGN_TRANSLATION_PATHS = {
        "docs/functional-design.md": "docs/functioneel-ontwerp.md",
        "docs/technical-design.md": "docs/technisch-ontwerp.md",
        "docs/technical-research.md": "docs/technisch-onderzoek.md",
    }

    async def _translate_design_content(self, tool_call) -> None:
        """Translate design content to the session language before the approval gate.

        For make_design calls in non-English sessions, translates the English content
        and adds translated_content/translated_path to tool_call.arguments.
        The approval card shows the translated version; the MCP tool writes both files.

        On translation failure, switches the session to English and notifies the user.
        """
        if tool_call.tool_name != "make_design":
            return

        from druppie.repositories import SessionRepository
        session_repo = SessionRepository(self.db)
        session = session_repo.get_by_id(tool_call.session_id)

        if not session or not session.language or session.language == "en":
            return

        args = tool_call.arguments or {}
        content = args.get("content")
        path = args.get("path")
        if not content or not path:
            return

        translated_path = self.DESIGN_TRANSLATION_PATHS.get(path)
        if not translated_path:
            return

        try:
            from druppie.core.translation import get_translation_service
            translator = get_translation_service()
            translated_content = await self._translate_long_content(
                translator, content, session.language
            )
            if translated_content and translated_content != content:
                enriched_args = dict(args)
                enriched_args["translated_content"] = translated_content
                enriched_args["translated_path"] = translated_path
                tool_call.arguments = enriched_args
                self.execution_repo.update_tool_call_arguments(
                    tool_call.id, enriched_args
                )
                self.db.flush()
                logger.info(
                    "design_content_translated",
                    tool_call_id=str(tool_call.id),
                    path=path,
                    translated_path=translated_path,
                )
        except TranslationNotAvailableError:
            self._notify_translation_unavailable(
                tool_call.session_id, session_repo,
                reason="De vertalingsservice is niet geconfigureerd (DEEPINFRA_API_KEY ontbreekt).",
            )
        except Exception as e:
            logger.warning(
                "design_translation_failed",
                tool_call_id=str(tool_call.id),
                path=path,
                error=str(e),
            )
            self._notify_translation_unavailable(
                tool_call.session_id, session_repo,
                reason=f"Er is een fout opgetreden bij het vertalen: {str(e)[:150]}",
            )

    def _notify_translation_unavailable(
        self, session_id, session_repo, *, reason: str
    ) -> None:
        """Switch session to English and inject a user-facing message."""
        session_repo.update_language(session_id, "en")

        message = (
            f"⚠️ **Vertaling niet beschikbaar** — {reason}\n\n"
            "De sessie gaat verder in het Engels. Alle documenten worden in het Engels opgesteld.\n\n"
            "---\n\n"
            f"⚠️ **Translation unavailable** — The translation service encountered an error. "
            "This session will continue in English."
        )

        seq = self.execution_repo.get_next_sequence_number(session_id)
        self.execution_repo.create_message(
            session_id=session_id,
            role="system",
            content=message,
            sequence_number=seq,
        )
        self.db.flush()
        logger.info("translation_fallback_to_english", session_id=str(session_id))

    async def _translate_long_content(
        self, translator, content: str, target_language: str
    ) -> str:
        """Translate long markdown by splitting on heading boundaries."""
        import asyncio
        import re

        if len(content) < 3000:
            return await translator.translate_from_english(content, target_language)

        sections = re.split(r"(^#{1,3}\s+.+$)", content, flags=re.MULTILINE)

        chunks = []
        current = ""
        for part in sections:
            if re.match(r"^#{1,3}\s+", part):
                if current:
                    chunks.append(current)
                current = part
            else:
                current += part
        if current:
            chunks.append(current)

        untranslated_count = 0

        async def _translate_chunk(chunk):
            nonlocal untranslated_count
            if not chunk.strip():
                return chunk

            heading_prefix = ""
            heading_match = re.match(r"^(#{1,3}\s+)", chunk)
            if heading_match:
                heading_prefix = heading_match.group(1)

            try:
                result = await translator.translate_from_english(chunk, target_language)
                if heading_prefix and not re.match(r"^#{1,3}\s+", result):
                    result = heading_prefix + result
                return result
            except TranslationError as e:
                untranslated_count += 1
                logger.warning(
                    "translation_chunk_failed",
                    error=str(e)[:200],
                    chunk_length=len(chunk),
                )
                return f"\n\n> **[NIET VERTAALD / NOT TRANSLATED]**\n\n{chunk}"

        translated = await asyncio.gather(*[_translate_chunk(c) for c in chunks])
        result = "".join(translated)

        if untranslated_count:
            logger.warning(
                "translation_partially_failed",
                untranslated_chunks=untranslated_count,
                total_chunks=len(chunks),
            )

        return result

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

    async def _handle_entra_token_missing(self, tool_call, user_id: str | None) -> str:
        """Handle a tool that needs user.entra_token but it's not available.

        Checks if the user has a linked Entra identity:
        - If not linked: fails with a user-friendly message
        - If linked: pauses with waiting_entra_auth for the HITL token flow
        """
        from druppie.core.entra_token import check_entra_linked, is_entra_configured

        if not is_entra_configured():
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=(
                    "This tool requires Azure access, but Entra ID is not configured. "
                    "Contact your administrator to set up Entra ID integration."
                ),
            )
            self.db.commit()
            return ToolCallStatus.FAILED

        if not user_id:
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error="Cannot determine session owner for Entra ID authentication.",
            )
            self.db.commit()
            return ToolCallStatus.FAILED

        is_linked = await check_entra_linked(user_id)

        if not is_linked:
            logger.info(
                "entra_token_missing_not_linked_proceeding",
                tool_call_id=str(tool_call.id),
                user_id=user_id,
            )
            return None

        # User has a linked identity — pause and wait for frontend to provide token
        self.execution_repo.update_tool_call(
            tool_call.id,
            status=ToolCallStatus.WAITING_ENTRA_AUTH,
        )
        self.db.commit()

        logger.info(
            "entra_token_missing_waiting_auth",
            tool_call_id=str(tool_call.id),
            user_id=user_id,
        )
        return ToolCallStatus.WAITING_ENTRA_AUTH

    async def _execute_hitl_tool(self, tool_call) -> str:
        """Execute a HITL tool by creating a Question record.

        HITL (Human-in-the-Loop) tools pause execution to ask the user a question.
        Translates English agent output to the user's language before storing.
        Creates a Question record via QuestionRepository.

        Args:
            tool_call: The ToolCall model

        Returns:
            ToolCallStatus.WAITING_ANSWER
        """
        args = tool_call.arguments or {}

        question_text = args.get("question", "")

        # Determine question type from tool name
        if tool_call.tool_name == "hitl_ask_multiple_choice_question":
            question_type = "choice"
            raw_choices = args.get("choices", [])
        else:
            question_type = "text"
            raw_choices = []

        # Save English originals before translation
        english_question = question_text
        english_choices = list(raw_choices) if raw_choices else None
        is_translated = False

        # Translate question and choices to the user's language
        session_repo = None
        session = None
        try:
            from druppie.repositories import SessionRepository
            from druppie.core.translation import get_translation_service
            session_repo = SessionRepository(self.db)
            session = session_repo.get_by_id(tool_call.session_id)
            if session and session.language and session.language != "en":
                translator = get_translation_service()
                question_text = await translator.translate_from_english(
                    question_text, session.language
                )
                if raw_choices:
                    translated_choices = []
                    for c in raw_choices:
                        translated_choices.append(
                            await translator.translate_label(c, session.language)
                        )
                    raw_choices = translated_choices
                context_text = args.get("context", "")
                if context_text:
                    translated_context = await translator.translate_from_english(
                        context_text, session.language
                    )
                    updated_args = dict(args)
                    updated_args["context"] = translated_context
                    self.execution_repo.update_tool_call_arguments(tool_call.id, updated_args)
                is_translated = True
                logger.info(
                    "hitl_question_translated",
                    tool_call_id=str(tool_call.id),
                    target_language=session.language,
                )
        except TranslationNotAvailableError:
            if session_repo:
                self._notify_translation_unavailable(
                    tool_call.session_id, session_repo,
                    reason="De vertalingsservice is niet geconfigureerd (DEEPINFRA_API_KEY ontbreekt).",
                )
        except Exception as e:
            logger.warning("hitl_question_translation_failed", error=str(e))
            if session and session_repo and session.language and session.language != "en":
                self._notify_translation_unavailable(
                    tool_call.session_id, session_repo,
                    reason=f"Er is een fout opgetreden bij het vertalen: {str(e)[:150]}",
                )

        choices = [{"text": c} for c in raw_choices] if raw_choices else None

        # Create question record via repository
        question = self.question_repo.create(
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            question=question_text,
            question_type=question_type,
            choices=choices,
            question_english=english_question if is_translated else None,
            choices_english=[{"text": c} for c in english_choices] if english_choices and is_translated else None,
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

            # Handle sandbox delegation — tool is waiting for external callback
            if isinstance(result, dict) and result.get("status") == "waiting_sandbox":
                from datetime import datetime, timezone
                self.execution_repo.update_tool_call(
                    tool_call.id,
                    status=ToolCallStatus.WAITING_SANDBOX,
                    result=result,  # Store sandbox_session_id for resume
                    sandbox_waiting_at=datetime.now(timezone.utc),  # For accurate watchdog timeout
                )
                # Link the SandboxSession record to this tool call for direct lookup
                # (avoids full table scan + JSON parsing in the webhook handler)
                sandbox_session_id = result.get("sandbox_session_id")
                if sandbox_session_id:
                    from druppie.repositories import SandboxSessionRepository
                    sandbox_repo = SandboxSessionRepository(self.db)
                    sandbox_repo.update_tool_call_id(sandbox_session_id, tool_call.id)
                self.db.commit()
                logger.info(
                    "builtin_tool_waiting_sandbox",
                    tool_call_id=str(tool_call.id),
                    sandbox_session_id=sandbox_session_id,
                )
                return ToolCallStatus.WAITING_SANDBOX

            # Check if the builtin tool reported failure via success field
            is_success = result.get("success", True) if isinstance(result, dict) else True
            status = ToolCallStatus.COMPLETED if is_success else ToolCallStatus.FAILED

            self.execution_repo.update_tool_call(
                tool_call.id,
                status=status,
                result=result if is_success else None,
                error=result.get("error") if not is_success else None,
            )
            self.db.commit()

            logger.info(
                "builtin_tool_completed",
                tool_call_id=str(tool_call.id),
                tool_name=tool_call.tool_name,
                result_status=result.get("status"),
                success=is_success,
            )

            return status

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
        # Copy to avoid mutating the ORM model's JSON dict in-place
        args = dict(tool_call.arguments or {})

        # Extract platform-injected translation fields before sending to MCP
        translated_content = args.pop("translated_content", None)
        translated_path = args.pop("translated_path", None)

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
        try:
            args = self._apply_injection_rules(
                server=tool_call.mcp_server,
                tool_name=tool_call.tool_name,
                args=args,
                session_id=tool_call.session_id,
            )
        except EntraTokenMissing as e:
            entra_result = await self._handle_entra_token_missing(tool_call, e.user_id)
            if entra_result is not None:
                return entra_result
            # User has no Entra identity — proceed without token so
            # non-OBO sources (datalake with key/public auth) still work.
            # OBO sources will fail at the adapter level with a clear error.
            args.pop("user_token", None)

        logger.info(
            "mcp_tool_post_injection",
            tool_call_id=str(tool_call.id),
            mcp_server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            final_args=list(args.keys()),
        )

        try:
            # Mark as executing and commit so the session is clean
            # before the HTTP call (avoids auto-flush issues later)
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.EXECUTING,
            )
            self.db.commit()

            # Long-running tools (run_tests, install_test_dependencies) get a
            # generous 20-min client timeout. Server-side subprocess timeouts
            # (300s/180s) should fire first, but this prevents infinite hangs
            # if the MCP server crashes or the network drops.
            if tool_call.tool_name in LONG_RUNNING_TOOLS:
                timeout = LONG_RUNNING_TIMEOUT
            elif tool_call.mcp_server in SLOW_START_SERVERS:
                timeout = SLOW_START_TIMEOUT
            else:
                timeout = 60.0

            result = await self.mcp_http.call(
                tool_call.mcp_server,
                tool_call.tool_name,
                args,
                timeout_seconds=timeout,
            )

            # Check if result indicates failure
            is_success = result.get("success", True)

            # Write translated design file after English original succeeds
            if is_success and translated_content and translated_path:
                try:
                    await self.mcp_http.call(
                        tool_call.mcp_server,
                        "write_file",
                        {**args, "path": translated_path, "content": translated_content},
                        timeout_seconds=60.0,
                    )
                    logger.info(
                        "translated_design_written",
                        tool_call_id=str(tool_call.id),
                        translated_path=translated_path,
                    )
                except Exception as e:
                    logger.warning(
                        "translated_design_write_failed",
                        tool_call_id=str(tool_call.id),
                        translated_path=translated_path,
                        error=str(e),
                    )

            # Update tool call with result. Preserve the full result body on
            # failure too so test assertions and downstream callers can inspect
            # the structured error payload, not just the error message string.
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.COMPLETED if is_success else ToolCallStatus.FAILED,
                result=result,
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
