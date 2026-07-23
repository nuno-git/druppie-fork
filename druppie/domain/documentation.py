"""Documentation domain models."""

from typing import List, Optional

from pydantic import BaseModel


class DocumentationEntry(BaseModel):
    """A documentation entry sourced from a project repository."""
    source_type: str
    source_id: str
    title: str
    content: str


class PlatformDocEntry(BaseModel):
    """A formal documentation entry sourced from the platform's own docs/ tree.

    Covers ADRs, PRDs, Specs (.feature Gherkin), Research notes, and Guides.
    The shape is intentionally uniform so the frontend can render a flat,
    filterable list.
    """
    type: str  # adr|prd|spec|research|guide
    id: Optional[str]
    title: str
    status: Optional[str] = None
    date: Optional[str] = None
    author_or_deciders: Optional[str] = None
    linked_adrs: Optional[List[str]] = None
    linked_prd: Optional[str] = None
    linked_research: Optional[str] = None
    linked_specs: Optional[List[str]] = None
    filename: str
    content: str
