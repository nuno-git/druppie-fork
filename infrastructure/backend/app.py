"""
Druppie Governance Platform - Flask Backend

Features:
- Keycloak JWT authentication
- Role-based access control (RBAC)
- MCP permission system with approvals
- Task approval workflows
- Real-time updates via WebSocket
"""

import os
import json
import uuid
from datetime import datetime
from functools import wraps
from typing import Any

import jwt
import requests
import structlog
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room

from druppie.auth import KeycloakAuth, auth_required, role_required
from druppie.models import db, Plan, Task, MCPPermission, Approval
from druppie.mcp_permissions import MCPPermissionManager
from druppie.plans import PlanService
from druppie.config import Config
from druppie.project import project_service
from druppie.builder import builder_service
from druppie.mcp_registry import mcp_registry

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# CORS configuration
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
CORS(app, origins=cors_origins, supports_credentials=True)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins=cors_origins, async_mode="gevent")

# Initialize database
db.init_app(app)

# Create database tables on app startup
with app.app_context():
    db.create_all()

# Initialize services
keycloak_auth = KeycloakAuth(app)
mcp_manager = MCPPermissionManager()
plan_service = PlanService()


# =============================================================================
# WEBSOCKET EVENTS
# =============================================================================


@socketio.on("connect")
def handle_connect():
    """Handle WebSocket connection."""
    client_id = request.sid
    logger.info("WebSocket client connected", client_id=client_id)
    emit("connected", {"status": "connected", "client_id": client_id})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket disconnection."""
    client_id = request.sid
    logger.info("WebSocket client disconnected", client_id=client_id)


@socketio.on("join_plan")
def handle_join_plan(data):
    """Join a plan room for real-time updates."""
    plan_id = data.get("plan_id")
    if plan_id:
        join_room(f"plan:{plan_id}")
        emit("joined_plan", {"plan_id": plan_id})


@socketio.on("join_approvals")
def handle_join_approvals(data):
    """Join approvals room for a user's role."""
    user_id = data.get("user_id")
    roles = data.get("roles", [])

    for role in roles:
        join_room(f"approvals:{role}")

    emit("joined_approvals", {"roles": roles})


# =============================================================================
# HEALTH & STATUS
# =============================================================================


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "healthy",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@app.route("/api/status", methods=["GET"])
def status():
    """System status endpoint."""
    return jsonify(
        {
            "keycloak": keycloak_auth.is_available(),
            "database": True,  # TODO: Add actual check
            "llm": True,  # TODO: Add actual check
        }
    )


# =============================================================================
# AUTHENTICATION
# =============================================================================


@app.route("/api/user", methods=["GET"])
@auth_required
def get_user_info():
    """Get current user information."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    # Get MCP permissions for user's roles
    mcp_permissions = mcp_manager.get_permissions_for_roles(roles)

    return jsonify(
        {
            "id": user.get("sub"),
            "username": user.get("preferred_username"),
            "email": user.get("email"),
            "firstName": user.get("given_name"),
            "lastName": user.get("family_name"),
            "roles": roles,
            "mcpPermissions": mcp_permissions,
        }
    )


# =============================================================================
# PLANS
# =============================================================================


@app.route("/api/plans", methods=["GET"])
@auth_required
def list_plans():
    """List all plans accessible to the user."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin sees all, others see their own or team plans
    if "admin" in roles:
        plans = Plan.query.order_by(Plan.created_at.desc()).limit(100).all()
    else:
        user_id = user.get("sub")
        # For SQLite compatibility, fetch all and filter in Python
        # (PostgreSQL ARRAY overlap not available)
        all_plans = Plan.query.order_by(Plan.created_at.desc()).limit(500).all()
        plans = []
        for plan in all_plans:
            if plan.created_by == user_id:
                plans.append(plan)
            elif plan.assigned_roles:
                if any(r in plan.assigned_roles for r in roles):
                    plans.append(plan)
            if len(plans) >= 100:
                break

    return jsonify([plan.to_dict() for plan in plans])


@app.route("/api/plans/<plan_id>", methods=["GET"])
@auth_required
def get_plan(plan_id):
    """Get plan details."""
    plan = Plan.query.get_or_404(plan_id)
    return jsonify(plan.to_dict(include_tasks=True, include_approvals=True))


@app.route("/api/plans", methods=["POST"])
@auth_required
def create_plan():
    """Create a new plan from user request."""
    user = g.user
    data = request.get_json()

    plan = plan_service.create_plan(
        name=data.get("name", "New Plan"),
        description=data.get("description", ""),
        created_by=user.get("sub"),
        user_roles=user.get("realm_access", {}).get("roles", []),
    )

    # Broadcast to connected clients
    socketio.emit("plan_created", plan.to_dict(), room=f"plan:{plan.id}")

    return jsonify(plan.to_dict()), 201


@app.route("/api/plans/<plan_id>/execute", methods=["POST"])
@auth_required
def execute_plan(plan_id):
    """Execute a plan (if all approvals are met)."""
    user = g.user
    plan = Plan.query.get_or_404(plan_id)

    # Check if user can execute
    roles = user.get("realm_access", {}).get("roles", [])
    if not plan_service.can_execute(plan, roles):
        return jsonify({"error": "Pending approvals required"}), 403

    # Execute plan
    result = plan_service.execute(plan, user.get("sub"))

    # Broadcast update
    socketio.emit("plan_updated", plan.to_dict(), room=f"plan:{plan.id}")

    return jsonify(result)


# =============================================================================
# TASKS
# =============================================================================


@app.route("/api/tasks", methods=["GET"])
@auth_required
def list_tasks():
    """List pending tasks that need approval from the user's role."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    # Get tasks pending approval for user's roles
    tasks = (
        Task.query.filter(
            Task.status == "pending_approval", Task.required_role.in_(roles)
        )
        .order_by(Task.created_at.desc())
        .all()
    )

    return jsonify([task.to_dict() for task in tasks])


@app.route("/api/tasks/<task_id>", methods=["GET"])
@auth_required
def get_task(task_id):
    """Get task details."""
    task = Task.query.get_or_404(task_id)
    return jsonify(task.to_dict(include_plan=True))


@app.route("/api/tasks/<task_id>/approve", methods=["POST"])
@auth_required
def approve_task(task_id):
    """Approve a task."""
    user = g.user
    task = Task.query.get_or_404(task_id)

    # Check if user's role can approve
    roles = user.get("realm_access", {}).get("roles", [])
    if task.required_role not in roles and "admin" not in roles:
        return jsonify({"error": "You don't have permission to approve this task"}), 403

    # Create approval
    approval = Approval(
        id=str(uuid.uuid4()),
        task_id=task_id,
        approved_by=user.get("sub"),
        approved_by_username=user.get("preferred_username"),
        role=task.required_role,
        decision="approved",
        comment=request.get_json().get("comment", ""),
    )

    db.session.add(approval)
    task.status = "approved"
    db.session.commit()

    # Broadcast approval
    socketio.emit("task_approved", task.to_dict(), room=f"approvals:{task.required_role}")
    socketio.emit("plan_updated", task.plan.to_dict(), room=f"plan:{task.plan_id}")

    return jsonify({"status": "approved", "approval": approval.to_dict()})


@app.route("/api/tasks/<task_id>/reject", methods=["POST"])
@auth_required
def reject_task(task_id):
    """Reject a task."""
    user = g.user
    task = Task.query.get_or_404(task_id)

    # Check if user's role can reject
    roles = user.get("realm_access", {}).get("roles", [])
    if task.required_role not in roles and "admin" not in roles:
        return jsonify({"error": "You don't have permission to reject this task"}), 403

    data = request.get_json()
    reason = data.get("reason", "")

    if not reason:
        return jsonify({"error": "Rejection reason is required"}), 400

    # Create rejection
    approval = Approval(
        id=str(uuid.uuid4()),
        task_id=task_id,
        approved_by=user.get("sub"),
        approved_by_username=user.get("preferred_username"),
        role=task.required_role,
        decision="rejected",
        comment=reason,
    )

    db.session.add(approval)
    task.status = "rejected"
    db.session.commit()

    # Broadcast rejection
    socketio.emit("task_rejected", task.to_dict(), room=f"approvals:{task.required_role}")
    socketio.emit("plan_updated", task.plan.to_dict(), room=f"plan:{task.plan_id}")

    return jsonify({"status": "rejected", "approval": approval.to_dict()})


# =============================================================================
# MCP PERMISSIONS
# =============================================================================


@app.route("/api/mcp/permissions", methods=["GET"])
@auth_required
def list_mcp_permissions():
    """List MCP permission configurations."""
    return jsonify(mcp_manager.get_all_permissions())


@app.route("/api/mcp/permissions/<tool_name>", methods=["GET"])
@auth_required
def get_mcp_permission(tool_name):
    """Get permission requirements for a specific MCP tool."""
    permission = mcp_manager.get_permission(tool_name)
    if not permission:
        return jsonify({"error": "Tool not found"}), 404

    return jsonify(permission)


@app.route("/api/mcp/check", methods=["POST"])
@auth_required
def check_mcp_permission():
    """Check if user can execute an MCP tool."""
    user = g.user
    data = request.get_json()

    tool_name = data.get("tool")
    if not tool_name:
        return jsonify({"error": "Tool name required"}), 400

    roles = user.get("realm_access", {}).get("roles", [])
    result = mcp_manager.check_permission(tool_name, roles, user.get("sub"))

    return jsonify(result)


@app.route("/api/mcp/request-approval", methods=["POST"])
@auth_required
def request_mcp_approval():
    """Request approval for an MCP tool execution."""
    user = g.user
    data = request.get_json()

    tool_name = data.get("tool")
    plan_id = data.get("plan_id")
    arguments = data.get("arguments", {})

    if not tool_name:
        return jsonify({"error": "Tool name required"}), 400

    # Create approval request task
    task = Task(
        id=str(uuid.uuid4()),
        plan_id=plan_id,
        name=f"Approve MCP: {tool_name}",
        description=f"Approval required to execute {tool_name}",
        mcp_tool=tool_name,
        mcp_arguments=arguments,
        status="pending_approval",
        required_role=mcp_manager.get_required_role(tool_name),
        created_by=user.get("sub"),
    )

    db.session.add(task)
    db.session.commit()

    # Broadcast approval request
    socketio.emit(
        "approval_requested",
        task.to_dict(),
        room=f"approvals:{task.required_role}",
    )

    return jsonify(task.to_dict()), 201


# =============================================================================
# CHAT (LLM Integration)
# =============================================================================


@app.route("/api/chat", methods=["POST"])
@auth_required
def chat():
    """Process a chat message through the governance system."""
    user = g.user
    data = request.get_json()

    message = data.get("message", "")
    plan_id = data.get("plan_id")

    if not message:
        return jsonify({"error": "Message required"}), 400

    # Get or create plan
    if plan_id:
        plan = Plan.query.get(plan_id)
    else:
        plan = plan_service.create_plan(
            name=f"Chat: {message[:50]}...",
            description=message,
            created_by=user.get("sub"),
            user_roles=user.get("realm_access", {}).get("roles", []),
        )

    # Process through governance pipeline
    result = plan_service.process_chat(plan, message, user)

    # Broadcast update
    socketio.emit("plan_updated", plan.to_dict(), room=f"plan:{plan.id}")

    return jsonify(
        {
            "plan_id": plan.id,
            "response": result.get("response"),
            "status": plan.status,
            "pending_approvals": result.get("pending_approvals", []),
        }
    )


# =============================================================================
# WORKSPACE
# =============================================================================


@app.route("/api/workspace", methods=["GET"])
@auth_required
def list_workspace():
    """List files in the workspace."""
    from pathlib import Path

    workspace = Path(os.getenv("WORKSPACE_PATH", "/app/workspace"))
    plan_id = request.args.get("plan_id")

    if plan_id:
        workspace = workspace / plan_id

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        return jsonify({"files": [], "directories": []})

    files = []
    directories = []

    for item in sorted(workspace.iterdir()):
        if item.is_dir():
            directories.append({"name": item.name, "type": "directory"})
        else:
            files.append(
                {"name": item.name, "type": "file", "size": item.stat().st_size}
            )

    return jsonify({"files": files, "directories": directories})


@app.route("/api/workspace/file", methods=["GET"])
@auth_required
def get_workspace_file():
    """Get content of a workspace file."""
    from pathlib import Path

    workspace = Path(os.getenv("WORKSPACE_PATH", "/app/workspace"))
    file_path = request.args.get("path", "")
    plan_id = request.args.get("plan_id", "")

    # If plan_id provided, prepend it to path
    if plan_id:
        target = workspace / plan_id / file_path
    else:
        target = workspace / file_path

    if not target.exists():
        return jsonify({"error": "File not found"}), 404

    if not str(target.resolve()).startswith(str(workspace.resolve())):
        return jsonify({"error": "Access denied"}), 403

    try:
        content = target.read_text()
        return jsonify({"path": file_path, "content": content})
    except UnicodeDecodeError:
        return jsonify({"path": file_path, "binary": True})


@app.route("/api/workspace/download", methods=["GET"])
@auth_required
def download_workspace_file():
    """Download a workspace file."""
    from pathlib import Path
    from flask import send_file

    workspace = Path(os.getenv("WORKSPACE_PATH", "/app/workspace"))
    file_path = request.args.get("path", "")
    plan_id = request.args.get("plan_id", "")

    # If plan_id provided, prepend it to path
    if plan_id:
        target = workspace / plan_id / file_path
    else:
        target = workspace / file_path

    if not target.exists():
        return jsonify({"error": "File not found"}), 404

    if not str(target.resolve()).startswith(str(workspace.resolve())):
        return jsonify({"error": "Access denied"}), 403

    return send_file(target, as_attachment=True, download_name=target.name)


# =============================================================================
# PROJECTS
# =============================================================================


@app.route("/api/projects", methods=["GET"])
@auth_required
def list_projects():
    """List all projects for the user."""
    user = g.user
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin sees all projects
    if "admin" in roles:
        projects = project_service.list_projects()
    else:
        projects = project_service.list_projects(user_id)

    return jsonify([p.to_dict() for p in projects])


@app.route("/api/projects/<project_id>", methods=["GET"])
@auth_required
def get_project(project_id):
    """Get project details including running app info."""
    project = project_service.get_project_for_plan(project_id)

    if not project:
        return jsonify({"error": "Project not found"}), 404

    project_dict = project.to_dict()

    # Add running app info
    running_app = builder_service.get_running_app(project_id)
    if running_app:
        project_dict["running_app"] = running_app.to_dict()
    else:
        project_dict["running_app"] = None

    # Add build status
    project_dict["build_status"] = builder_service.get_project_status(project_id)

    return jsonify(project_dict)


@app.route("/api/projects/<project_id>/build", methods=["POST"])
@auth_required
def build_project(project_id):
    """Build a project's Docker image."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    # Check permission
    perm = mcp_registry.check_permission("docker.build", roles, user.get("sub"))
    if not perm["allowed"]:
        return jsonify({"error": perm.get("message", "Permission denied")}), 403

    result = builder_service.build_project(project_id)

    if result.get("success"):
        # Broadcast update
        socketio.emit("project_built", {"project_id": project_id, **result})

    return jsonify(result)


@app.route("/api/projects/<project_id>/run", methods=["POST"])
@auth_required
def run_project(project_id):
    """Run a project's Docker container."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    # Check permission
    perm = mcp_registry.check_permission("docker.run", roles, user.get("sub"))
    if not perm["allowed"]:
        return jsonify({"error": perm.get("message", "Permission denied")}), 403

    result = builder_service.run_project(project_id)

    if result.get("success"):
        # Update plan with app URL
        plan = Plan.query.get(project_id)
        if plan:
            plan.result = plan.result or {}
            plan.result["app_url"] = result.get("url")
            db.session.commit()

        # Broadcast update
        socketio.emit("project_running", {"project_id": project_id, **result})

    return jsonify(result)


@app.route("/api/projects/<project_id>/stop", methods=["POST"])
@auth_required
def stop_project(project_id):
    """Stop a project's Docker container."""
    result = builder_service.stop_project(project_id)

    if result.get("success"):
        socketio.emit("project_stopped", {"project_id": project_id})

    return jsonify(result)


# =============================================================================
# RUNNING APPS
# =============================================================================


@app.route("/api/apps/running", methods=["GET"])
@auth_required
def list_running_apps():
    """List all running applications."""
    apps = builder_service.list_running_apps()
    return jsonify([app.to_dict() for app in apps])


@app.route("/api/apps/<project_id>/status", methods=["GET"])
@auth_required
def get_app_status(project_id):
    """Get status of a running application."""
    status = builder_service.get_project_status(project_id)
    return jsonify(status)


# =============================================================================
# MCP REGISTRY (Enhanced)
# =============================================================================


@app.route("/api/mcp/registry", methods=["GET"])
@auth_required
def get_mcp_registry():
    """Get the full MCP registry."""
    return jsonify(mcp_registry.to_dict())


@app.route("/api/mcp/tools", methods=["GET"])
@auth_required
def list_mcp_tools():
    """List MCP tools available to the user."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    tools = mcp_registry.list_tools(roles)
    return jsonify([{
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "approval_type": t.approval_type.value,
        "danger_level": t.danger_level,
        "input_schema": t.input_schema,
    } for t in tools])


@app.route("/api/mcp/tools/<tool_id>", methods=["GET"])
@auth_required
def get_mcp_tool(tool_id):
    """Get details of an MCP tool."""
    tool = mcp_registry.get_tool(tool_id)
    if not tool:
        return jsonify({"error": "Tool not found"}), 404

    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])
    permission = mcp_registry.check_permission(tool_id, roles, user.get("sub"))

    return jsonify({
        "id": tool.id,
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "input_schema": tool.input_schema,
        "approval_type": tool.approval_type.value,
        "approval_roles": tool.approval_roles,
        "danger_level": tool.danger_level,
        "permission": permission,
    })


@app.route("/api/mcp/servers", methods=["GET"])
@auth_required
def list_mcp_servers():
    """List MCP servers available to the user."""
    user = g.user
    roles = user.get("realm_access", {}).get("roles", [])

    servers = mcp_registry.list_servers(roles)
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "tool_count": len(s.tools),
    } for s in servers])


# =============================================================================
# ERROR HANDLERS
# =============================================================================


@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Unauthorized"}), 401


@app.errorhandler(403)
def forbidden(error):
    return jsonify({"error": "Forbidden"}), 403


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error("Internal server error", error=str(error))
    return jsonify({"error": "Internal server error"}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_ENV") == "development",
    )
