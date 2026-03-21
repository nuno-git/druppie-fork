"""Deterministic UUID generation for YAML fixtures."""

import uuid

# Fixed namespace for all fixture-generated UUIDs.
FIXTURE_NAMESPACE = uuid.UUID("d1a7e5f0-cafe-4b1d-b0a1-f1a70ee5eed5")


def fixture_uuid(session_id: str, *parts: str | int) -> uuid.UUID:
    """Generate a deterministic UUID from a session ID and optional sub-parts.

    Examples:
        fixture_uuid("todo-app")                      # session UUID
        fixture_uuid("todo-app", "project")            # project UUID
        fixture_uuid("todo-app", "run", 0)             # agent run 0
        fixture_uuid("todo-app", "run", 0, "llm")     # llm call for run 0
        fixture_uuid("todo-app", "run", 0, "tc", 1)   # tool call 1 in run 0
        fixture_uuid("todo-app", "msg", 0)             # message 0
    """
    name = session_id + ":" + ":".join(str(p) for p in parts) if parts else session_id
    return uuid.uuid5(FIXTURE_NAMESPACE, name)
