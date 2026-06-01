"""Documentation domain models."""

from pydantic import BaseModel


class DocumentationEntry(BaseModel):
    """A documentation entry sourced from a project repository."""
    source_type: str
    source_id: str
    title: str
    content: str
