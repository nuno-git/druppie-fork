"""Database models for Druppie Governance Platform."""

import uuid
from datetime import datetime
from typing import Any, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, ARRAY, String
from sqlalchemy.dialects.postgresql import UUID

db = SQLAlchemy()


class Plan(db.Model):
    """Execution plan model."""

    __tablename__ = "plans"

    id = db.Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(String(50), default="pending")  # pending, running, completed, failed
    plan_type = db.Column(String(50), default="agents")  # agents, workflow

    # User info
    created_by = db.Column(String(36))
    created_by_username = db.Column(String(255))

    # Role assignments
    assigned_roles = db.Column(ARRAY(String), default=list)

    # Workflow info
    workflow_id = db.Column(String(100))

    # Context and results
    project_context = db.Column(JSON, default=dict)
    result = db.Column(JSON)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Relationships
    tasks = db.relationship("Task", back_populates="plan", lazy="dynamic")

    def to_dict(self, include_tasks: bool = False, include_approvals: bool = False) -> dict:
        """Convert to dictionary."""
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "plan_type": self.plan_type,
            "created_by": self.created_by,
            "created_by_username": self.created_by_username,
            "assigned_roles": self.assigned_roles or [],
            "workflow_id": self.workflow_id,
            "project_context": self.project_context or {},
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

        if include_tasks:
            data["tasks"] = [
                task.to_dict(include_approvals=include_approvals)
                for task in self.tasks.all()
            ]

        return data


class Task(db.Model):
    """Task model - represents a step that may need approval."""

    __tablename__ = "tasks"

    id = db.Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = db.Column(String(36), db.ForeignKey("plans.id"), nullable=False)
    name = db.Column(String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(String(50), default="pending")  # pending, pending_approval, approved, rejected, running, completed, failed

    # Agent/MCP info
    agent_id = db.Column(String(100))
    mcp_tool = db.Column(String(100))
    mcp_arguments = db.Column(JSON)

    # Approval requirements
    required_role = db.Column(String(100))  # Role required for approval
    approval_type = db.Column(String(50))  # auto, user_approve, role_approve

    # User info
    created_by = db.Column(String(36))

    # Results
    result = db.Column(JSON)
    error = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Relationships
    plan = db.relationship("Plan", back_populates="tasks")
    approvals = db.relationship("Approval", back_populates="task", lazy="dynamic")

    def to_dict(self, include_plan: bool = False, include_approvals: bool = False) -> dict:
        """Convert to dictionary."""
        data = {
            "id": self.id,
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "agent_id": self.agent_id,
            "mcp_tool": self.mcp_tool,
            "mcp_arguments": self.mcp_arguments,
            "required_role": self.required_role,
            "approval_type": self.approval_type,
            "created_by": self.created_by,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

        if include_plan:
            data["plan"] = {"id": self.plan.id, "name": self.plan.name, "status": self.plan.status}

        if include_approvals:
            data["approvals"] = [a.to_dict() for a in self.approvals.all()]

        return data


class Approval(db.Model):
    """Approval record for tasks."""

    __tablename__ = "approvals"

    id = db.Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = db.Column(String(36), db.ForeignKey("tasks.id"), nullable=False)

    # Approver info
    approved_by = db.Column(String(36), nullable=False)
    approved_by_username = db.Column(String(255))
    role = db.Column(String(100))

    # Decision
    decision = db.Column(String(50), nullable=False)  # approved, rejected
    comment = db.Column(db.Text)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    task = db.relationship("Task", back_populates="approvals")

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "approved_by": self.approved_by,
            "approved_by_username": self.approved_by_username,
            "role": self.role,
            "decision": self.decision,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MCPPermission(db.Model):
    """MCP tool permission configuration."""

    __tablename__ = "mcp_permissions"

    id = db.Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_name = db.Column(String(100), unique=True, nullable=False)
    description = db.Column(db.Text)

    # Permission level
    permission_level = db.Column(String(50), default="role_approve")  # auto, user_approve, role_approve
    required_role = db.Column(String(100))

    # Allowed roles (if permission_level is auto)
    allowed_roles = db.Column(ARRAY(String), default=list)

    # Risk level
    risk_level = db.Column(String(50), default="medium")  # low, medium, high, critical

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "description": self.description,
            "permission_level": self.permission_level,
            "required_role": self.required_role,
            "allowed_roles": self.allowed_roles or [],
            "risk_level": self.risk_level,
        }
