"""SQLAlchemy database models for Druppie platform.

Models are organized into separate files for clean code.
All models use the shared Base from base.py.
"""

from .base import Base, utcnow, new_uuid

# User models
from .user import User, UserRole, UserToken

# Project model
from .project import Project

# Session model
from .session import Session

# Agent execution models
from .agent_run import AgentRun, Message
from .tool_call import ToolCall
from .llm_call import LlmCall

# Approval model
from .approval import Approval

# HITL question model
from .question import HitlQuestion

# Workspace model
from .workspace import Workspace

# Build and deployment models
from .build import Build, Deployment

# Event model
from .event import SessionEvent

__all__ = [
    # Base
    "Base",
    "utcnow",
    "new_uuid",
    # User
    "User",
    "UserRole",
    "UserToken",
    # Project
    "Project",
    # Session
    "Session",
    # Agent execution
    "AgentRun",
    "Message",
    "ToolCall",
    "LlmCall",
    # Approval
    "Approval",
    # HITL
    "HitlQuestion",
    # Workspace
    "Workspace",
    # Build/Deployment
    "Build",
    "Deployment",
    # Event
    "SessionEvent",
]
