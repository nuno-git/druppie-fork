"""Plan service for managing execution plans."""

import uuid
from datetime import datetime
from typing import Any, Optional, Callable

from .models import db, Plan, Task, Approval
from .mcp_permissions import MCPPermissionManager
from .llm_service import LLMService
from .project import project_service
from .builder import builder_service


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
    """Service for managing plans and tasks."""

    def __init__(self):
        self.mcp_manager = MCPPermissionManager()
        self.llm_service = LLMService()

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

        if mcp_tool:
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
            status="pending" if approval_type == "auto" else "pending_approval",
            agent_id=agent_id,
            mcp_tool=mcp_tool,
            mcp_arguments=mcp_arguments,
            approval_type=approval_type,
            required_role=required_role,
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
        pending_tasks = Task.query.filter(
            Task.plan_id == plan.id, Task.status == "pending_approval"
        ).all()

        approvals = []
        for task in pending_tasks:
            approvals.append(
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "mcp_tool": task.mcp_tool,
                    "required_role": task.required_role,
                    "approval_type": task.approval_type,
                }
            )

        return approvals

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

            result = self.llm_service.generate_app(
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
    ) -> dict[str, Any]:
        """Process a chat message through the governance pipeline.

        Args:
            plan: The plan to process
            message: The user's message
            user: User dict with sub (id), realm_access, etc.
            current_project_id: Optional current project context
            emit_event: Optional callback to emit workflow events in real-time
        """
        user_roles = user.get("realm_access", {}).get("roles", [])
        user_id = user.get("sub")
        workflow_events = []

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
        )

        # Report what router detected
        action = intent.get("action", intent.get("type", "unknown"))
        app_info = intent.get("app_info", {})

        if intent.get("type") == "chat":
            add_event(
                "intent_detected",
                "Intent: General Chat",
                "This is a conversational request, responding directly.",
                "success",
                {"action": "general_chat"}
            )
            plan.status = "completed"
            plan.result = {"response": intent.get("response")}
            db.session.commit()

            add_event(
                "workflow_completed",
                "Complete",
                "Response ready.",
                "success"
            )

            return {
                "response": intent.get("response"),
                "pending_approvals": [],
                "workflow_events": workflow_events,
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

        db.session.commit()

        return {
            "response": response,
            "pending_approvals": pending,
            "workflow_events": workflow_events,
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

    def _analyze_intent(
        self,
        message: str,
        user_id: str | None = None,
        current_project_id: str | None = None,
    ) -> dict[str, Any]:
        """Analyze user message to determine intent.

        Args:
            message: The user's message
            user_id: Optional user ID to fetch their existing projects
            current_project_id: Optional current project ID for context

        Returns:
            Intent dict with type and tasks/response
        """
        message_lower = message.lower()

        # Get user's existing projects for context
        existing_projects = None
        current_project = None

        if user_id:
            existing_projects = self._get_user_projects_for_context(user_id)

            # Get current project context if specified
            if current_project_id:
                project = project_service.get_project_for_plan(current_project_id)
                if project:
                    current_project = {
                        "id": project.id,
                        "name": project.name,
                        "repo_url": project.repo_url,
                        "description": project.description,
                    }

        # Check if this is an app creation/modification request
        if any(kw in message_lower for kw in ["create", "build", "make", "update", "fix", "add", "modify", "change"]):
            # Use LLM service to analyze what app to build with project context
            app_info = self.llm_service.analyze_request(
                message,
                existing_projects=existing_projects,
                current_project=current_project,
            )

            action = app_info.get("action", "create_project")

            # Handle general chat responses from router
            if action == "general_chat":
                return {
                    "type": "chat",
                    "response": app_info.get("answer") or f"I understand: {message}. How can I help?",
                }

            # Determine the task based on action
            if action == "update_project":
                target_id = app_info.get("target_project_id")
                return {
                    "type": "action",
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
            else:
                # create_project
                return {
                    "type": "action",
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

        # Check for deployment requests
        elif any(kw in message_lower for kw in ["deploy", "push", "release"]):
            return {
                "type": "action",
                "tasks": [
                    {
                        "name": "Deploy code",
                        "description": f"Deploy based on: {message}",
                        "mcp_tool": "docker.deploy",
                        "mcp_arguments": {"message": message},
                    }
                ],
            }

        else:
            return {
                "type": "chat",
                "response": f"I understand you want to: {message}. What would you like me to do?",
            }
