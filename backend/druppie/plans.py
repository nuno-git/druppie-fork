"""Plan service for managing execution plans.

Uses the ChatOrchestrator for intent analysis and plan creation.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Optional, Callable

import structlog

from .models import db, Plan, Task, Approval, Question
from .mcp_permissions import MCPPermissionManager
from .mcp_registry import mcp_registry as approval_mcp_registry
from .llm_service import LLMService
from .code_service import CodeService
from .project import project_service
from .builder import builder_service

# Import the new orchestrator (handles routing + planning)
from druppie.orchestrator import chat_orchestrator
from druppie.core.models import IntentAction

# Import workflow execution components
from druppie.core.models import Plan as PydanticPlan, PlanType, PlanStatus
from druppie.agents import AgentRuntime
from druppie.workflows import WorkflowEngine, WorkflowRegistry
from druppie.mcp import MCPClient, MCPRegistry
from druppie.registry import AgentRegistry
# LLMService handles provider selection (Z.AI or Ollama)
from druppie.plan_execution_engine import PlanExecutionEngine

logger = structlog.get_logger()


class WorkflowEvent:
    """Represents a workflow event for user visibility."""

    def __init__(
        self,
        event_type: str,
        title: str,
        description: str,
        status: str = "info",
        data: dict | None = None,
    ):
        self.event_type = event_type
        self.title = title
        self.description = description
        self.status = status  # info, success, warning, error, working
        self.data = data or {}
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class PlanService:
    """Service for managing plans and tasks.

    Uses the ChatOrchestrator for:
    - Intent analysis (router agent)
    - Plan creation (planner agent)

    Uses PlanExecutionEngine for workflow execution.
    """

    def __init__(self):
        self.mcp_manager = MCPPermissionManager()
        self.llm_service = LLMService()
        self.code_service = CodeService()

        # Track LLM calls for debugging
        self._llm_calls: list[dict] = []

        # Workflow execution components (lazy initialized)
        self._workflow_initialized = False
        self._llm = None
        self._agent_registry = None
        self._workflow_registry = None
        self._mcp_registry = None
        self._mcp_client = None
        self._plan_execution_engine = None

    def _ensure_workflow_initialized(self, emit_event: Callable | None = None) -> PlanExecutionEngine:
        """Initialize workflow components lazily."""
        if not self._workflow_initialized:
            registry_path = os.getenv("REGISTRY_PATH", "/app/registry")

            # Initialize LLM via LLMService (auto-selects provider)
            self._llm = self.llm_service.get_llm()

            # Load registries
            self._agent_registry = AgentRegistry(registry_path)
            self._agent_registry.load()

            self._workflow_registry = WorkflowRegistry(registry_path)
            self._workflow_registry.load()

            self._mcp_registry = MCPRegistry(registry_path)
            self._mcp_registry.load()

            # Initialize MCP client
            self._mcp_client = MCPClient(self._mcp_registry)

            self._workflow_initialized = True

            logger.info(
                "workflow_components_initialized",
                agents=len(self._agent_registry.list_agents()),
                workflows=len(self._workflow_registry.list_workflows()),
            )

        # Create agent runtime with emit_event for this execution
        agent_runtime = AgentRuntime(
            mcp_client=self._mcp_client,
            mcp_registry=self._mcp_registry,
            agent_registry=self._agent_registry,
            llm=self._llm,
            emit_event=emit_event,
        )

        # Create workflow engine
        workflow_engine = WorkflowEngine(
            agent_runtime=agent_runtime,
            mcp_client=self._mcp_client,
        )

        # Create plan execution engine
        return PlanExecutionEngine(
            agent_runtime=agent_runtime,
            workflow_engine=workflow_engine,
            workflow_registry=self._workflow_registry,
        )

    def _record_llm_call(
        self,
        name: str,
        model: str,
        prompt: str,
        response: str,
        usage: dict | None = None,
        duration_ms: int | None = None,
        plan_output: dict | None = None,
    ) -> None:
        """Record an LLM call for debugging.

        Args:
            name: Name of the agent/component making the call
            model: Model name used
            prompt: Input prompt
            response: Response text
            usage: Token usage dict
            duration_ms: Call duration in milliseconds
            plan_output: Structured plan output for planning_agent calls
        """
        import time
        call_record = {
            "name": name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": model,
            "request": {"messages": [{"role": "user", "content": prompt[:500] + "..." if len(prompt) > 500 else prompt}]},
            "response": response[:2000] + "..." if len(response) > 2000 else response,
            "usage": usage or {},
            "duration_ms": duration_ms,
            "status": "success",
        }

        # Include structured plan output for debugging visibility
        if plan_output:
            call_record["plan_output"] = plan_output

        self._llm_calls.append(call_record)

    def get_llm_calls(self) -> list[dict]:
        """Get all recorded LLM calls."""
        # Combine calls from both old and new architecture
        old_calls = self.llm_service.get_llm_calls()
        return self._llm_calls + old_calls

    def clear_llm_calls(self) -> None:
        """Clear all recorded LLM calls."""
        self._llm_calls = []
        self.llm_service.clear_llm_calls()

    async def execute_workflow(
        self,
        db_plan: Plan,
        workflow_id: str,
        project_context: dict[str, Any],
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow for a plan.

        Args:
            db_plan: SQLAlchemy Plan from database
            workflow_id: ID of the workflow to execute
            project_context: Context variables for template substitution
            emit_event: Callback for emitting workflow events

        Returns:
            Result dict with success status and any output data
        """
        def add_event(title: str, description: str, status: str = "info", data: dict = None):
            if emit_event:
                event = WorkflowEvent("workflow_step", title, description, status, data)
                emit_event(event.to_dict())

        try:
            add_event("Initializing Workflow", f"Starting {workflow_id}...", "working")

            # Get plan execution engine
            plan_execution_engine = self._ensure_workflow_initialized(emit_event)

            # Create Pydantic Plan for workflow execution
            pydantic_plan = PydanticPlan(
                id=db_plan.id,
                name=db_plan.name,
                description=db_plan.description or "",
                plan_type=PlanType.WORKFLOW,
                status=PlanStatus.PENDING,
                workflow_id=workflow_id,
                project_context=project_context,
            )

            add_event("Executing Workflow", f"Running workflow: {workflow_id}", "working")

            # Execute the plan through PlanExecutionEngine
            result_plan = await plan_execution_engine.execute(pydantic_plan)

            # Update database plan with results
            db_plan.status = result_plan.status.value
            if result_plan.workflow_run:
                db_plan.result = db_plan.result or {}
                db_plan.result["workflow_run"] = {
                    "id": result_plan.workflow_run.id,
                    "status": result_plan.workflow_run.status,
                    "context": result_plan.workflow_run.context,
                }
                # Extract useful URLs from context
                context = result_plan.workflow_run.context
                if context.get("step_deploy_production", {}).get("url"):
                    db_plan.result["app_url"] = context["step_deploy_production"]["url"]
                if context.get("step_deploy_preview", {}).get("url"):
                    db_plan.result["preview_url"] = context["step_deploy_preview"]["url"]
            db.session.commit()

            success = result_plan.status == PlanStatus.COMPLETED
            if success:
                add_event(
                    "Workflow Complete",
                    f"Workflow {workflow_id} completed successfully",
                    "success",
                    {"status": "completed"}
                )
            else:
                add_event(
                    "Workflow Failed",
                    f"Workflow {workflow_id} failed",
                    "error",
                    {"status": "failed"}
                )

            return {
                "success": success,
                "status": result_plan.status.value,
                "workflow_run": result_plan.workflow_run.model_dump() if result_plan.workflow_run else None,
                "result": db_plan.result,
            }

        except Exception as e:
            logger.error("workflow_execution_failed", error=str(e), workflow_id=workflow_id)
            add_event("Workflow Error", str(e), "error")
            db_plan.status = "failed"
            db.session.commit()
            return {
                "success": False,
                "error": str(e),
            }

    def _format_plan_for_display(
        self,
        plan: Any,
        intent: Any,
        app_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Format a Plan object for UI display.

        Args:
            plan: The Plan object from orchestrator (can be None)
            intent: The Intent object
            app_info: The app_info dict for fallback

        Returns:
            dict with plan_summary, plan_details, execution_steps, considerations
        """
        # If we have a plan from the orchestrator, use it
        if plan is not None:
            # Build detailed plan output for debugging
            plan_output = {
                "name": plan.name,
                "description": plan.description,
                "plan_type": plan.plan_type.value,
                "workflow_id": plan.workflow_id,
                "tasks": [
                    {
                        "id": task.id,
                        "agent_id": task.agent_id,
                        "description": task.description,
                        "depends_on": task.depends_on,
                    }
                    for task in plan.tasks
                ] if plan.tasks else [],
            }

            # Convert to the expected format for display
            execution_steps = []
            if plan.tasks:
                for i, task in enumerate(plan.tasks):
                    execution_steps.append({
                        "step": i + 1,
                        "name": f"Task: {task.agent_id}",
                        "description": task.description,
                        "tool": "agent_task",
                        "details": f"Agent: {task.agent_id}",
                    })

            return {
                "plan_summary": plan.name or f"Create {app_info.get('app_type', 'application')}",
                "plan_details": {
                    "objective": plan.description or (intent.prompt if intent else ""),
                    "approach": f"Using {plan.plan_type.value} execution",
                    "technologies": app_info.get("technologies", []),
                    "estimated_files": [],
                    "architecture": "Agent-based autonomous execution",
                },
                "execution_steps": execution_steps or [{
                    "step": 1,
                    "name": "Generate Application",
                    "description": f"Create {app_info.get('app_type', 'application')} with all necessary files",
                    "tool": "generate_app",
                    "details": "Using LLM to generate complete, working code",
                }],
                "considerations": [],
                "plan_output": plan_output,  # Include for debugging
            }

        # Fallback to a default plan if no Plan object
        return {
            "plan_summary": f"Create {app_info.get('app_type', 'application')}",
            "plan_details": {
                "objective": app_info.get("description", "Build the requested application"),
                "approach": "Generate complete application files",
                "technologies": app_info.get("technologies", []),
                "estimated_files": [],
                "architecture": "Standard application structure",
            },
            "execution_steps": [
                {
                    "step": 1,
                    "name": "Generate Application",
                    "description": f"Create {app_info.get('app_type', 'application')} with all necessary files",
                    "tool": "generate_app",
                    "details": "Using LLM to generate complete, working code",
                }
            ],
            "considerations": [],
        }

    def create_plan(
        self,
        name: str,
        description: str,
        created_by: str,
        user_roles: list[str],
        plan_type: str = "agents",
        workflow_id: Optional[str] = None,
        project_context: Optional[dict] = None,
    ) -> Plan:
        """Create a new plan."""
        plan = Plan(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            status="pending",
            plan_type=plan_type,
            created_by=created_by,
            assigned_roles=user_roles,
            workflow_id=workflow_id,
            project_context=project_context or {},
        )

        db.session.add(plan)
        db.session.commit()

        return plan

    def add_task(
        self,
        plan: Plan,
        name: str,
        description: str,
        agent_id: Optional[str] = None,
        mcp_tool: Optional[str] = None,
        mcp_arguments: Optional[dict] = None,
        created_by: Optional[str] = None,
    ) -> Task:
        """Add a task to a plan."""
        # Determine approval requirements
        approval_type = "auto"
        required_role = None
        required_roles = None
        required_approvals = 1

        if mcp_tool:
            # First check the new MCP registry for approval settings (deploy tools, etc.)
            tool = approval_mcp_registry.get_tool(mcp_tool)
            if tool and tool.approval_type.value != "none":
                approval_type = tool.approval_type.value
                if tool.approval_roles:
                    required_role = tool.approval_roles[0]
                    if approval_type == "multi":
                        required_roles = tool.approval_roles
                        required_approvals = 2
            else:
                # Fall back to permission manager for other tools
                permission = self.mcp_manager.check_permission(
                    mcp_tool, plan.assigned_roles, created_by or plan.created_by
                )

                if permission["requires_approval"]:
                    approval_type = permission["approval_type"]
                    required_role = permission["required_role"]

        task = Task(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            name=name,
            description=description,
            status="pending" if approval_type in ("auto", "none") else "pending_approval",
            agent_id=agent_id,
            mcp_tool=mcp_tool,
            mcp_arguments=mcp_arguments,
            approval_type=approval_type,
            required_role=required_role,
            required_roles=required_roles,
            required_approvals=required_approvals,
            created_by=created_by or plan.created_by,
        )

        db.session.add(task)
        db.session.commit()

        return task

    def can_execute(self, plan: Plan, user_roles: list[str]) -> bool:
        """Check if all required approvals are met."""
        # Get pending approval tasks
        pending_tasks = Task.query.filter(
            Task.plan_id == plan.id, Task.status == "pending_approval"
        ).all()

        # If no pending approvals, can execute
        if not pending_tasks:
            return True

        # Check if user can approve all pending tasks
        for task in pending_tasks:
            if task.required_role not in user_roles and "admin" not in user_roles:
                return False

        return True

    def get_pending_approvals(self, plan: Plan) -> list[dict]:
        """Get list of pending approval requirements."""
        from druppie.models import Approval

        pending_tasks = Task.query.filter(
            Task.plan_id == plan.id, Task.status == "pending_approval"
        ).all()

        approvals = []
        for task in pending_tasks:
            # Get current approval count for MULTI approval tasks
            current_approvals = 0
            approved_by_roles = []
            if task.approval_type == "multi":
                existing_approvals = Approval.query.filter_by(
                    task_id=task.id, decision="approved"
                ).all()
                current_approvals = len(existing_approvals)
                approved_by_roles = [a.approver_role for a in existing_approvals if a.approver_role]

            approvals.append(
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "mcp_tool": task.mcp_tool,
                    "required_role": task.required_role,
                    "approval_type": task.approval_type,
                    "required_roles": task.required_roles,
                    "required_approvals": task.required_approvals or 1,
                    "current_approvals": current_approvals,
                    "approved_by_roles": approved_by_roles,
                }
            )

        return approvals

    def create_question(
        self,
        plan: Plan,
        question_text: str,
        context: str | None = None,
        required_for: str | None = None,
        options: list[str] | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
    ) -> Question:
        """Create a question that requires user response.

        Args:
            plan: The plan this question is associated with
            question_text: The question to ask the user
            context: Additional context about why this question is needed
            required_for: What this information is needed for
            options: Optional list of suggested answers
            agent_id: Which agent is asking this question
            task_id: Optional task ID this question is associated with

        Returns:
            The created Question object
        """
        question = Question(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            task_id=task_id,
            question=question_text,
            context=context,
            required_for=required_for,
            options=options or [],
            agent_id=agent_id,
            status="pending",
        )

        db.session.add(question)
        db.session.commit()

        return question

    def answer_question(
        self,
        question_id: str,
        answer: str,
        answered_by: str,
        answered_by_username: str | None = None,
    ) -> Question:
        """Answer a pending question.

        Args:
            question_id: The question ID to answer
            answer: The user's answer
            answered_by: User ID of who answered
            answered_by_username: Username of who answered

        Returns:
            The updated Question object
        """
        question = Question.query.get(question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")

        if question.status != "pending":
            raise ValueError(f"Question {question_id} is not pending (status: {question.status})")

        question.answer = answer
        question.answered_by = answered_by
        question.answered_by_username = answered_by_username
        question.answered_at = datetime.utcnow()
        question.status = "answered"

        db.session.commit()

        return question

    def get_pending_questions(self, plan_id: str | None = None, user_id: str | None = None) -> list[Question]:
        """Get pending questions, optionally filtered by plan or user.

        Args:
            plan_id: Optional plan ID to filter by
            user_id: Optional user ID to filter by (questions from their plans)

        Returns:
            List of pending Question objects
        """
        query = Question.query.filter(Question.status == "pending")

        if plan_id:
            query = query.filter(Question.plan_id == plan_id)

        if user_id:
            # Get questions from plans created by this user
            query = query.join(Plan).filter(Plan.created_by == user_id)

        return query.order_by(Question.created_at.desc()).all()

    def execute(
        self,
        plan: Plan,
        executed_by: str,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Execute a plan (if all approvals are met)."""

        def add_event(event_type: str, title: str, description: str, status: str = "info", data: dict = None):
            if emit_event:
                event = WorkflowEvent(event_type, title, description, status, data)
                emit_event(event.to_dict())

        # Update status
        plan.status = "running"
        db.session.commit()

        results = []
        failed = False

        # Execute each task
        tasks = Task.query.filter(
            Task.plan_id == plan.id, Task.status.in_(["pending", "approved"])
        ).order_by(Task.created_at).all()

        for task in tasks:
            try:
                task.status = "running"
                db.session.commit()

                # Emit task started event
                add_event(
                    "task_executing",
                    f"Executing: {task.name}",
                    f"Running {task.mcp_tool or 'task'}...",
                    "working",
                    {"task_id": task.id, "mcp_tool": task.mcp_tool}
                )

                # Execute the task with event emission
                result = self._execute_task(task, emit_event=emit_event)

                task.status = "completed"
                task.result = result
                task.completed_at = datetime.utcnow()
                db.session.commit()

                add_event(
                    "task_completed",
                    f"Completed: {task.name}",
                    "Task finished successfully",
                    "success",
                    {"task_id": task.id, "result": result}
                )

                results.append(
                    {"task_id": task.id, "status": "completed", "result": result}
                )

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                db.session.commit()

                add_event(
                    "task_failed",
                    f"Failed: {task.name}",
                    str(e),
                    "error",
                    {"task_id": task.id, "error": str(e)}
                )

                results.append({"task_id": task.id, "status": "failed", "error": str(e)})
                failed = True
                break

        # Update plan status - preserve repo_url/app_url from task execution
        plan.status = "failed" if failed else "completed"
        plan.completed_at = datetime.utcnow()

        # Preserve URLs that were set during task execution
        existing_result = plan.result or {}
        plan.result = {
            "tasks": results,
            "repo_url": existing_result.get("repo_url"),
            "app_url": existing_result.get("app_url"),
        }
        db.session.commit()

        return {"status": plan.status, "results": results}

    def _execute_task(
        self,
        task: Task,
        emit_event: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        """Execute a single task."""

        def add_event(event_type: str, title: str, description: str, status: str = "info", data: dict = None):
            if emit_event:
                event = WorkflowEvent(event_type, title, description, status, data)
                emit_event(event.to_dict())

        # Check if this is an app generation task
        if task.mcp_tool == "generate_app" and task.mcp_arguments:
            app_info = task.mcp_arguments.get("app_info", {})
            auto_build = task.mcp_arguments.get("auto_build", False)
            auto_run = task.mcp_arguments.get("auto_run", False)
            username = task.mcp_arguments.get("username")
            email = task.mcp_arguments.get("email")

            add_event(
                "mcp_tool",
                "MCP Tool: generate_app",
                f"Generating {app_info.get('app_type', 'application')} code...",
                "working",
                {"tool": "generate_app", "app_type": app_info.get("app_type")}
            )

            add_event(
                "llm_generating",
                "AI Code Generation",
                "LLM is writing your application code...",
                "working",
                {"model": "GLM-4.7"}
            )

            result = self.code_service.generate_app(
                plan_id=task.plan_id,
                app_info=app_info,
                auto_commit=True,  # Always commit to Git
                auto_build=auto_build,
                auto_run=auto_run,
                created_by=task.created_by,
                username=username,
                email=email,
            )

            files_created = result.get("files_created", [])
            if files_created:
                add_event(
                    "files_created",
                    f"Created {len(files_created)} Files",
                    ", ".join(files_created[:5]) + ("..." if len(files_created) > 5 else ""),
                    "success",
                    {"files": files_created}
                )

            if result.get("repo_url"):
                add_event(
                    "git_pushed",
                    "Pushed to Git Repository",
                    f"Code pushed to {result['repo_url']}",
                    "success",
                    {"repo_url": result["repo_url"]}
                )

            # Update plan with repo and app URLs
            plan = Plan.query.get(task.plan_id)
            if plan and result.get("success"):
                plan.result = plan.result or {}
                if result.get("repo_url"):
                    plan.result["repo_url"] = result["repo_url"]
                if result.get("app_url"):
                    plan.result["app_url"] = result["app_url"]
                db.session.commit()

            return {
                "executed": True,
                "success": result.get("success", False),
                "workspace": result.get("workspace"),
                "files_created": result.get("files_created", []),
                "app_info": result.get("app_info"),
                "repo_url": result.get("repo_url"),
                "app_url": result.get("app_url"),
            }

        # Handle build task
        if task.mcp_tool == "docker.build" and task.mcp_arguments:
            project_id = task.mcp_arguments.get("project_id", task.plan_id)

            add_event(
                "mcp_tool",
                "MCP Tool: docker.build",
                "Building Docker image for your project...",
                "working",
                {"tool": "docker.build", "project_id": project_id}
            )

            result = builder_service.build_project(project_id)

            if result.get("success"):
                add_event(
                    "build_complete",
                    "Docker Build Complete",
                    f"Image built successfully for {result.get('app_type', 'app')}",
                    "success",
                    {"app_type": result.get("app_type"), "port": result.get("port")}
                )

            return {
                "executed": True,
                "success": result.get("success", False),
                "app_type": result.get("app_type"),
                "port": result.get("port"),
                "error": result.get("error"),
            }

        # Handle run task
        if task.mcp_tool == "docker.run" and task.mcp_arguments:
            project_id = task.mcp_arguments.get("project_id", task.plan_id)

            add_event(
                "mcp_tool",
                "MCP Tool: docker.run",
                "Starting your application container...",
                "working",
                {"tool": "docker.run", "project_id": project_id}
            )

            result = builder_service.run_project(project_id)

            # Update plan with app URL
            if result.get("success"):
                plan = Plan.query.get(task.plan_id)
                if plan:
                    plan.result = plan.result or {}
                    plan.result["app_url"] = result.get("url")
                    db.session.commit()

                add_event(
                    "app_running",
                    "Application Running!",
                    f"Your app is live at {result.get('url')}",
                    "success",
                    {"url": result.get("url"), "port": result.get("port")}
                )

            return {
                "executed": True,
                "success": result.get("success", False),
                "url": result.get("url"),
                "port": result.get("port"),
                "error": result.get("error"),
            }

        # Handle update_app task (UPDATE_PROJECT flow) - Uses update_workflow
        if task.mcp_tool == "update_app" and task.mcp_arguments:
            app_info = task.mcp_arguments.get("app_info", {})
            target_project_id = task.mcp_arguments.get("target_project_id")
            update_description = task.mcp_arguments.get("message", "Update project")

            add_event(
                "mcp_tool",
                "MCP Tool: update_app",
                f"Updating project with changes: {update_description[:100]}...",
                "working",
                {"tool": "update_app", "project_id": target_project_id}
            )

            # Get the target project
            project = project_service.get_project_for_plan(target_project_id)
            if not project:
                return {
                    "executed": True,
                    "success": False,
                    "error": f"Project not found: {target_project_id}",
                }

            add_event(
                "project_found",
                f"Found Project: {project.name}",
                f"Repository: {project.repo_url}",
                "success",
                {"project_id": project.id, "repo_url": project.repo_url}
            )

            # Build workflow context for update_workflow
            import time
            timestamp = int(time.time())

            workflow_context = {
                "project_name": project.name,
                "project_id": project.id,
                "update_description": update_description,
                "timestamp": timestamp,
                "app_type": app_info.get("app_type", "application"),
                "technologies": app_info.get("technologies", []),
                "features": app_info.get("features", []),
            }

            add_event(
                "update_workflow_starting",
                "Starting Update Workflow",
                f"Using update_workflow to implement changes...",
                "working",
                {"workflow_id": "update_workflow", "branch": f"feature/update-{timestamp}"}
            )

            # Get the plan and execute the update_workflow
            plan = Plan.query.get(task.plan_id)
            if not plan:
                return {
                    "executed": True,
                    "success": False,
                    "error": f"Plan not found: {task.plan_id}",
                }

            # Execute the update_workflow asynchronously
            result = asyncio.run(
                self.execute_workflow(
                    db_plan=plan,
                    workflow_id="update_workflow",
                    project_context=workflow_context,
                    emit_event=emit_event,
                )
            )

            if result.get("success"):
                add_event(
                    "update_complete",
                    "Update Workflow Complete",
                    "Changes implemented and preview deployed",
                    "success",
                    {
                        "preview_url": result.get("result", {}).get("preview_url"),
                        "status": result.get("status"),
                    }
                )

            return {
                "executed": True,
                "success": result.get("success", False),
                "project_id": project.id,
                "project_name": project.name,
                "preview_url": result.get("result", {}).get("preview_url"),
                "workflow_run": result.get("workflow_run"),
                "error": result.get("error"),
            }

        # Handle ask_question MCP tool
        if task.mcp_tool == "interaction.ask_question" and task.mcp_arguments:
            question_text = task.mcp_arguments.get("question", "")
            context = task.mcp_arguments.get("context")
            options = task.mcp_arguments.get("options", [])
            required_for = task.mcp_arguments.get("required_for")

            add_event(
                "mcp_tool",
                "MCP Tool: ask_question",
                f"Agent is asking: {question_text[:100]}{'...' if len(question_text) > 100 else ''}",
                "warning",
                {"tool": "interaction.ask_question", "question": question_text}
            )

            # Create the question
            plan = Plan.query.get(task.plan_id)
            question = self.create_question(
                plan=plan,
                question_text=question_text,
                context=context,
                required_for=required_for,
                options=options,
                agent_id=task.agent_id,
                task_id=task.id,
            )

            add_event(
                "question_pending",
                "Waiting for Your Response",
                question_text,
                "warning",
                {
                    "question_id": question.id,
                    "question": question_text,
                    "context": context,
                    "options": options,
                    "required_for": required_for,
                }
            )

            # Set task to waiting state
            task.status = "waiting_response"
            db.session.commit()

            return {
                "executed": True,
                "waiting_for_response": True,
                "question_id": question.id,
                "question": question_text,
                "context": context,
                "options": options,
            }

        # Handle deploy.staging and deploy.production MCP tools
        if task.mcp_tool in ("deploy.staging", "deploy.production") and task.mcp_arguments:
            project_id = task.mcp_arguments.get("project_id")
            version = task.mcp_arguments.get("version", "latest")
            environment = task.mcp_arguments.get("environment", "staging")

            add_event(
                "mcp_tool",
                f"MCP Tool: {task.mcp_tool}",
                f"Deploying {project_id} to {environment}...",
                "working",
                {"tool": task.mcp_tool, "project_id": project_id, "environment": environment}
            )

            # For now, simulate deployment success
            # In production, this would call actual deployment infrastructure
            add_event(
                "deployment_complete",
                f"Deployed to {environment.title()}",
                f"Project {project_id} (version {version}) deployed successfully to {environment}",
                "success",
                {
                    "project_id": project_id,
                    "version": version,
                    "environment": environment,
                    "url": f"https://{project_id}.{environment}.example.com",
                }
            )

            return {
                "executed": True,
                "mcp_tool": task.mcp_tool,
                "success": True,
                "environment": environment,
                "project_id": project_id,
                "version": version,
                "deployment_url": f"https://{project_id}.{environment}.example.com",
            }

        # Default response for other task types
        add_event(
            "mcp_tool",
            f"MCP Tool: {task.mcp_tool}",
            "Executing tool...",
            "working",
            {"tool": task.mcp_tool}
        )

        return {
            "executed": True,
            "mcp_tool": task.mcp_tool,
            "mcp_arguments": task.mcp_arguments,
        }

    def process_chat(
        self,
        plan: Plan,
        message: str,
        user: dict,
        current_project_id: str | None = None,
        emit_event: Callable[[dict], None] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Process a chat message through the governance pipeline.

        Args:
            plan: The plan to process
            message: The user's message
            user: User dict with sub (id), realm_access, etc.
            current_project_id: Optional current project context
            emit_event: Optional callback to emit workflow events in real-time
            conversation_history: Previous conversation messages for context
        """
        user_roles = user.get("realm_access", {}).get("roles", [])
        user_id = user.get("sub")
        workflow_events = []

        # Clear LLM call history for fresh tracking
        self.llm_service.clear_llm_calls()

        def add_event(event_type: str, title: str, description: str, status: str = "info", data: dict = None):
            event = WorkflowEvent(event_type, title, description, status, data)
            workflow_events.append(event.to_dict())
            if emit_event:
                emit_event(event.to_dict())

        # Start workflow
        add_event(
            "workflow_started",
            "Processing your request",
            f"Analyzing: {message[:100]}{'...' if len(message) > 100 else ''}",
            "working"
        )

        # Update plan with message
        plan.description = message

        # Analyze intent with user's existing projects for context
        add_event(
            "router_analyzing",
            "Router Agent",
            "Analyzing your intent and determining the best action...",
            "working"
        )

        intent = self._analyze_intent(
            message,
            user_id=user_id,
            current_project_id=current_project_id,
            conversation_history=conversation_history,
        )

        # Report what router detected
        action = intent.get("action", intent.get("type", "unknown"))
        app_info = intent.get("app_info", {})

        if intent.get("type") == "chat":
            response_text = intent.get("response") or "Hello! How can I help you today?"

            add_event(
                "intent_detected",
                "Intent: General Chat",
                "This is a conversational request, responding directly.",
                "success",
                {"action": "general_chat"}
            )

            add_event(
                "workflow_completed",
                "Complete",
                "Response ready.",
                "success"
            )

            # Get LLM calls before storing (from both old and new architecture)
            llm_calls = self.get_llm_calls()

            # Store everything in plan.result for persistence
            # Must assign a new dict for SQLAlchemy to detect the change
            plan.status = "completed"
            existing_result = dict(plan.result) if plan.result else {}
            existing_result.update({
                "response": response_text,
                "workflow_events": workflow_events,
                "llm_calls": llm_calls,
            })
            plan.result = existing_result
            db.session.commit()

            return {
                "response": response_text,
                "pending_approvals": [],
                "pending_questions": [],
                "workflow_events": workflow_events,
                "llm_calls": llm_calls,
            }

        # It's an action - report what we detected
        tasks_to_create = intent.get("tasks", [])
        if tasks_to_create:
            task_info = tasks_to_create[0]
            mcp_tool = task_info.get("mcp_tool", "unknown")
            app_info = task_info.get("mcp_arguments", {}).get("app_info", {})

            intent_title = "Intent: Create Project" if mcp_tool == "generate_app" else f"Intent: {mcp_tool}"
            intent_desc = f"Creating a {app_info.get('app_type', 'application')} called '{app_info.get('name', 'my-app')}'"

            add_event(
                "intent_detected",
                intent_title,
                intent_desc,
                "success",
                {
                    "action": mcp_tool,
                    "app_type": app_info.get("app_type"),
                    "app_name": app_info.get("name"),
                    "features": app_info.get("features", []),
                }
            )

            # Format the plan from orchestrator for display
            # (planner agent already ran in _analyze_intent via orchestrator)
            orchestrator_plan = intent.get("plan")
            execution_plan = self._format_plan_for_display(
                plan=orchestrator_plan,
                intent=intent.get("intent"),
                app_info=app_info,
            )

            # Show the plan to the user
            plan_details = execution_plan.get("plan_details", {})
            steps = execution_plan.get("execution_steps", [])
            steps_desc = ", ".join([s.get("name", f"Step {i+1}") for i, s in enumerate(steps[:3])])
            if len(steps) > 3:
                steps_desc += f", +{len(steps) - 3} more"

            add_event(
                "plan_ready",
                "Execution Plan Ready",
                execution_plan.get("plan_summary", "Plan created"),
                "success",
                {
                    "plan_summary": execution_plan.get("plan_summary"),
                    "objective": plan_details.get("objective"),
                    "approach": plan_details.get("approach"),
                    "technologies": plan_details.get("technologies", []),
                    "estimated_files": plan_details.get("estimated_files", []),
                    "steps": steps,
                    "considerations": execution_plan.get("considerations", []),
                }
            )

        # Create plan
        add_event(
            "plan_creating",
            "Creating Execution Plan",
            f"Setting up {len(tasks_to_create)} task(s) for execution...",
            "working"
        )

        # Extract user info for passing to task execution
        username = user.get("preferred_username")
        email = user.get("email")

        for task_info in tasks_to_create:
            # Add user info to mcp_arguments for project creation
            mcp_args = task_info.get("mcp_arguments", {})
            if task_info.get("mcp_tool") == "generate_app":
                mcp_args["username"] = username
                mcp_args["email"] = email

            task = self.add_task(
                plan=plan,
                name=task_info.get("name", "Task"),
                description=task_info.get("description", ""),
                agent_id=task_info.get("agent_id"),
                mcp_tool=task_info.get("mcp_tool"),
                mcp_arguments=mcp_args,
                created_by=user.get("sub"),
            )

            add_event(
                "task_created",
                f"Task: {task.name}",
                task.description[:100] if task.description else "Task ready for execution",
                "info",
                {"task_id": task.id, "mcp_tool": task.mcp_tool, "agent_id": task.agent_id}
            )

        # Check for pending approvals
        pending = self.get_pending_approvals(plan)

        if pending:
            plan.status = "pending_approval"
            for p in pending:
                add_event(
                    "approval_required",
                    f"Approval Required: {p['task_name']}",
                    f"Requires approval from: {p['required_role']}",
                    "warning",
                    p
                )
            response = f"Plan created with {len(tasks_to_create)} tasks. {len(pending)} task(s) require approval."
        else:
            # Auto-execute if no approvals needed
            add_event(
                "executing",
                "Executing Plan",
                "All approvals met, executing tasks...",
                "working"
            )

            result = self.execute(plan, user.get("sub"), emit_event=emit_event)

            if result["status"] == "completed":
                # Get results for response
                task_results = result.get("results", [])
                repo_url = None
                app_url = None
                files_created = []

                for tr in task_results:
                    task_result = tr.get("result", {})
                    if task_result.get("repo_url"):
                        repo_url = task_result["repo_url"]
                    if task_result.get("app_url"):
                        app_url = task_result["app_url"]
                    if task_result.get("files_created"):
                        files_created = task_result["files_created"]

                add_event(
                    "workflow_completed",
                    "Project Created Successfully!",
                    f"Created {len(files_created)} files" + (f" • Repository: {repo_url}" if repo_url else ""),
                    "success",
                    {"repo_url": repo_url, "app_url": app_url, "files_count": len(files_created)}
                )

                response = f"✅ Project created successfully!"
                if repo_url:
                    response += f"\n\n📦 **Repository:** {repo_url}"
                if files_created:
                    response += f"\n\n📁 **Files created:** {len(files_created)}"
                    if len(files_created) <= 10:
                        response += "\n" + "\n".join(f"  • {f}" for f in files_created)
            else:
                add_event(
                    "workflow_failed",
                    "Execution Failed",
                    f"Plan execution failed: {result.get('status')}",
                    "error"
                )
                response = f"❌ Plan execution failed. Status: {result['status']}"

        # Check for any pending questions
        pending_questions = self.get_pending_questions(plan_id=plan.id)
        questions_list = [q.to_dict() for q in pending_questions]

        # Get LLM calls before storing (from both old and new architecture)
        llm_calls = self.get_llm_calls()

        # Store workflow_events and llm_calls in plan.result for persistence
        # Must assign a new dict for SQLAlchemy to detect the change
        existing_result = dict(plan.result) if plan.result else {}
        existing_result.update({
            "response": response,
            "workflow_events": workflow_events,
            "llm_calls": llm_calls,
        })
        plan.result = existing_result
        db.session.commit()

        return {
            "response": response,
            "pending_approvals": pending,
            "pending_questions": questions_list,
            "workflow_events": workflow_events,
            "llm_calls": llm_calls,
        }

    def _get_user_projects_for_context(
        self, user_id: str | None
    ) -> list[dict[str, Any]]:
        """Get list of user's existing projects formatted for LLM context.

        Args:
            user_id: The user ID to filter projects by

        Returns:
            List of project dicts with id, name, repo_url, description
        """
        projects = project_service.list_projects(user_id=user_id)
        return [
            {
                "id": p.id,
                "name": p.name,
                "repo_url": p.repo_url,
                "description": p.description,
            }
            for p in projects
        ]

    def _analyze_intent_with_orchestrator(
        self,
        message: str,
        user_projects: list[dict] | None = None,
        plan_id: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> tuple[Any, dict[str, Any], Any]:
        """Analyze user message using the ChatOrchestrator.

        The orchestrator runs both router and planner agents.

        Args:
            message: The user's message
            user_projects: List of user's existing projects for context
            plan_id: Optional plan ID for context
            conversation_history: Previous conversation messages for context

        Returns:
            Tuple of (Intent, app_info dict, Plan or None)
        """
        import time
        import structlog
        logger = structlog.get_logger()

        start_time = time.time()

        # Run orchestrator in sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        chat_orchestrator.process_message(
                            message=message,
                            user_projects=user_projects,
                            plan_id=plan_id,
                            conversation_history=conversation_history,
                        )
                    ).result()
            else:
                result = loop.run_until_complete(
                    chat_orchestrator.process_message(
                        message=message,
                        user_projects=user_projects,
                        plan_id=plan_id,
                        conversation_history=conversation_history,
                    )
                )
        except RuntimeError:
            result = asyncio.run(
                chat_orchestrator.process_message(
                    message=message,
                    user_projects=user_projects,
                    plan_id=plan_id,
                    conversation_history=conversation_history,
                )
            )

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "orchestrator_result",
            success=result.get("success"),
            type=result.get("type"),
            duration_ms=duration_ms,
        )

        # Handle errors
        if not result.get("success"):
            logger.error("orchestrator_failed", error=result.get("error"))
            # Return a fallback intent
            from druppie.core.models import Intent
            fallback_intent = Intent(
                initial_prompt=message,
                prompt=message,
                action=IntentAction.GENERAL_CHAT,
                answer=result.get("error") or "I couldn't process your request. Please try again.",
            )
            return fallback_intent, {"action": "general_chat", "answer": fallback_intent.answer}, None

        # Handle chat responses (no plan needed)
        if result.get("type") == "chat":
            # Collect LLM calls from orchestrator
            orchestrator_llm_calls = result.get("llm_calls", [])
            if orchestrator_llm_calls:
                for call in orchestrator_llm_calls:
                    self._llm_calls.append(call)

            intent = result.get("intent")
            if not intent:
                from druppie.core.models import Intent
                intent = Intent(
                    initial_prompt=message,
                    prompt=message,
                    action=IntentAction.GENERAL_CHAT,
                    answer=result.get("response"),
                )
            return intent, {"action": "general_chat", "answer": result.get("response")}, None

        # Handle question responses
        if result.get("type") == "question":
            # Collect LLM calls from orchestrator
            orchestrator_llm_calls = result.get("llm_calls", [])
            if orchestrator_llm_calls:
                for call in orchestrator_llm_calls:
                    self._llm_calls.append(call)

            intent = result.get("intent")
            app_info = {
                "action": "ask_question",
                "question": {
                    "text": result.get("question"),
                    "context": "Router needs more information",
                    "options": [],
                    "required_for": "Determining the appropriate action",
                },
            }
            return intent, app_info, None

        # Handle action responses (has intent and plan)
        intent = result.get("intent")
        plan = result.get("plan")

        # Convert Intent to app_info dict for compatibility
        app_info = {
            "action": intent.action.value,
            "app_type": intent.project_context.get("app_type", "generic"),
            "name": intent.project_context.get("project_name", "my-app"),
            "description": intent.prompt,
            "features": intent.project_context.get("features", []),
            "technologies": intent.project_context.get("technologies", []),
            "target_project_id": intent.project_context.get("target_project_id") or intent.deploy_context.get("target_project_id"),
            "answer": intent.answer,
            "deploy_context": intent.deploy_context,  # Include deploy context for deployment actions
        }

        # Collect LLM calls from orchestrator (these are the detailed agent calls)
        orchestrator_llm_calls = result.get("llm_calls", [])
        if orchestrator_llm_calls:
            # Add orchestrator LLM calls to our tracking
            for call in orchestrator_llm_calls:
                self._llm_calls.append(call)

        # Also record a summary call if we have token usage
        total_usage = result.get("total_usage")
        if total_usage:
            self._record_llm_call(
                name="orchestrator_summary",
                model=os.getenv("ZAI_MODEL", "GLM-4.7"),
                prompt=message,
                response=f"Action: {intent.action.value}, Plan: {plan.name if plan else 'None'}",
                usage={
                    "prompt_tokens": total_usage.prompt_tokens,
                    "completion_tokens": total_usage.completion_tokens,
                    "total_tokens": total_usage.total_tokens,
                },
                duration_ms=duration_ms,
            )

        return intent, app_info, plan

    def _analyze_intent(
        self,
        message: str,
        user_id: str | None = None,
        current_project_id: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Analyze user message to determine intent using the ChatOrchestrator.

        ALL messages go through the orchestrator which runs router + planner agents.

        Args:
            message: The user's message
            user_id: Optional user ID to fetch their existing projects
            current_project_id: Optional current project ID for context
            conversation_history: Previous conversation messages for context

        Returns:
            Intent dict with type and tasks/response
        """
        # Get user's existing projects for context
        existing_projects = None

        if user_id:
            existing_projects = self._get_user_projects_for_context(user_id)

        # Use the orchestrator for intent analysis (runs router + planner)
        intent, app_info, plan = self._analyze_intent_with_orchestrator(
            message=message,
            user_projects=existing_projects,
            conversation_history=conversation_history,
        )

        # Store the plan for later use
        self._cached_plan = plan

        action = app_info.get("action", "general_chat")

        # Handle general chat responses
        if action == "general_chat":
            return {
                "type": "chat",
                "response": app_info.get("answer") or intent.answer or f"I understand your message: {message}. How can I help you today?",
                "intent": intent,
            }

        # Handle ask_question action - router needs clarification
        if action == "ask_question":
            question_info = app_info.get("question", {})
            return {
                "type": "action",
                "intent": intent,
                "tasks": [
                    {
                        "name": "Clarification Needed",
                        "description": question_info.get("text", "Need more information to proceed"),
                        "agent_id": "router",
                        "mcp_tool": "interaction.ask_question",
                        "mcp_arguments": {
                            "question": question_info.get("text", "Can you provide more details about what you'd like to build?"),
                            "context": question_info.get("context", "I need more information to understand your request"),
                            "options": question_info.get("options", []),
                            "required_for": question_info.get("required_for", "Determining the right approach"),
                        },
                    }
                ],
            }

        # Handle update_project action
        if action == "update_project":
            target_id = app_info.get("target_project_id")
            return {
                "type": "action",
                "intent": intent,
                "app_info": app_info,
                "plan": plan,
                "tasks": [
                    {
                        "name": f"Update {app_info['name']}",
                        "description": f"Updating {app_info['app_type']} application: {app_info['description']}",
                        "agent_id": "developer",
                        "mcp_tool": "update_app",
                        "mcp_arguments": {
                            "app_info": app_info,
                            "message": message,
                            "target_project_id": target_id,
                        },
                    }
                ],
            }

        # Handle deploy_project action
        if action == "deploy_project":
            deploy_context = intent.deploy_context if intent else {}
            target_id = deploy_context.get("target_project_id") or app_info.get("target_project_id")
            environment = deploy_context.get("environment", "staging")
            version = deploy_context.get("version", "latest")

            # Determine MCP tool based on environment
            mcp_tool = f"deploy.{environment}"
            approval_desc = (
                f"Approval required from 2 of: developer, infra-engineer, product-owner"
                if environment == "production"
                else f"Approval required from developer or infra-engineer"
            )

            return {
                "type": "action",
                "intent": intent,
                "app_info": app_info,
                "plan": plan,
                "tasks": [
                    {
                        "name": f"Deploy to {environment.title()}",
                        "description": f"Deploying project {target_id or 'unknown'} to {environment}. {approval_desc}",
                        "agent_id": "devops",
                        "mcp_tool": mcp_tool,
                        "mcp_arguments": {
                            "project_id": target_id,
                            "version": version,
                            "environment": environment,
                        },
                    }
                ],
            }

        # Handle create_project action (default for action requests)
        return {
            "type": "action",
            "intent": intent,
            "app_info": app_info,
            "plan": plan,
            "tasks": [
                {
                    "name": f"Generate {app_info['name']}",
                    "description": f"Creating {app_info['app_type']} application: {app_info['description']}",
                    "agent_id": "developer",
                    "mcp_tool": "generate_app",
                    "mcp_arguments": {"app_info": app_info, "message": message},
                }
            ],
        }

