"""Druppie Platform - AI-powered governance with MCP tool permissions.

This is the main package for the Druppie platform rewrite.
All agents act ONLY through MCPs.

Architecture:
- core/: Models, state management, main loop
- llm/: LLM providers (Z.AI, mock)
- mcps/: MCP servers (coding, git, docker, hitl)
- api/: FastAPI application and routes
- db/: Database models and CRUD
- agents/: Agent YAML definitions
- workflows/: Workflow YAML definitions
"""

__version__ = "2.0.0"
