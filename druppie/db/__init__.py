"""Database module for Druppie platform.

Database design principles:
- Simple 1:1 mapping between tables and domain models
- Repositories handle all database access
- MCPs handle their own state (workspaces, containers)

Use repositories (druppie/repositories/) for all database access.
"""

from .database import get_db, init_db, SessionLocal, engine

from .models import (
    # Base
    Base,
    # Users
    User,
    UserRole,
    UserToken,
    # Projects
    Project,
    # Sessions
    Session,
    # Agent Runs
    AgentRun,
    # Messages
    Message,
    # Tool Calls
    ToolCall,
    # Approvals
    Approval,
    # Questions
    Question,
    # LLM Tracking
    LlmCall,
)

__all__ = [
    # Database
    "get_db",
    "init_db",
    "SessionLocal",
    "engine",
    # Base
    "Base",
    # Models
    "User",
    "UserRole",
    "UserToken",
    "Project",
    "Session",
    "AgentRun",
    "Message",
    "ToolCall",
    "Approval",
    "Question",
    "LlmCall",
]
