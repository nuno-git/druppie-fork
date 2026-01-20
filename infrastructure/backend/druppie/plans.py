"""Plan service for managing execution plans."""

import uuid
from datetime import datetime
from typing import Any, Optional

from .models import db, Plan, Task, Approval
from .mcp_permissions import MCPPermissionManager
from .llm_service import LLMService
from .project import project_service
from .builder import builder_service


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

    def execute(self, plan: Plan, executed_by: str) -> dict[str, Any]:
        """Execute a plan (if all approvals are met)."""
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

                # Execute the task (placeholder - integrate with actual MCP execution)
                result = self._execute_task(task)

                task.status = "completed"
                task.result = result
                task.completed_at = datetime.utcnow()
                db.session.commit()

                results.append(
                    {"task_id": task.id, "status": "completed", "result": result}
                )

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                db.session.commit()

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

    def _execute_task(self, task: Task) -> dict[str, Any]:
        """Execute a single task."""
        # Check if this is an app generation task
        if task.mcp_tool == "generate_app" and task.mcp_arguments:
            app_info = task.mcp_arguments.get("app_info", {})
            auto_build = task.mcp_arguments.get("auto_build", False)
            auto_run = task.mcp_arguments.get("auto_run", False)
            username = task.mcp_arguments.get("username")
            email = task.mcp_arguments.get("email")

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
            result = builder_service.build_project(project_id)
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
            result = builder_service.run_project(project_id)

            # Update plan with app URL
            if result.get("success"):
                plan = Plan.query.get(task.plan_id)
                if plan:
                    plan.result = plan.result or {}
                    plan.result["app_url"] = result.get("url")
                    db.session.commit()

            return {
                "executed": True,
                "success": result.get("success", False),
                "url": result.get("url"),
                "port": result.get("port"),
                "error": result.get("error"),
            }

        # Default response for other task types
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
    ) -> dict[str, Any]:
        """Process a chat message through the governance pipeline.

        Args:
            plan: The plan to process
            message: The user's message
            user: User dict with sub (id), realm_access, etc.
            current_project_id: Optional current project context
        """
        user_roles = user.get("realm_access", {}).get("roles", [])
        user_id = user.get("sub")

        # Update plan with message
        plan.description = message

        # Analyze intent with user's existing projects for context
        intent = self._analyze_intent(
            message,
            user_id=user_id,
            current_project_id=current_project_id,
        )

        # If it's a simple chat, respond directly
        if intent.get("type") == "chat":
            plan.status = "completed"
            plan.result = {"response": intent.get("response")}
            db.session.commit()

            return {"response": intent.get("response"), "pending_approvals": []}

        # Create tasks based on intent
        tasks_to_create = intent.get("tasks", [])

        # Extract user info for passing to task execution
        username = user.get("preferred_username")
        email = user.get("email")

        for task_info in tasks_to_create:
            # Add user info to mcp_arguments for project creation
            mcp_args = task_info.get("mcp_arguments", {})
            if task_info.get("mcp_tool") == "generate_app":
                mcp_args["username"] = username
                mcp_args["email"] = email

            self.add_task(
                plan=plan,
                name=task_info.get("name", "Task"),
                description=task_info.get("description", ""),
                agent_id=task_info.get("agent_id"),
                mcp_tool=task_info.get("mcp_tool"),
                mcp_arguments=mcp_args,
                created_by=user.get("sub"),
            )

        # Check for pending approvals
        pending = self.get_pending_approvals(plan)

        if pending:
            plan.status = "pending_approval"
            response = f"Plan created with {len(tasks_to_create)} tasks. {len(pending)} task(s) require approval."
        else:
            # Auto-execute if no approvals needed
            result = self.execute(plan, user.get("sub"))
            response = f"Plan executed. Status: {result['status']}"

        db.session.commit()

        return {"response": response, "pending_approvals": pending}

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
