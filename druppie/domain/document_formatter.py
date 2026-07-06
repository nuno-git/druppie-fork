"""Document formatter domain models.

Provides typed validation for document parameters that were previously
passed as an untyped dict[str, Any] in the legacy generate_pdf() API.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Typed document configuration for the Rijnland Typst template.

    Formerly passed as an untyped metadata dict to generate_pdf().
    Now used to validate the parameters an agent writes into a .typ file
    before calling the document formatter.
    """

    title: str = Field(default="Untitled Document", min_length=1)
    document_type: Literal[
        "memo",
        "functional_design",
        "technical_design",
        "technical_research",
        "core_documentation",
    ] = Field(default="memo")
    status: Literal["DRAFT", "FINAL"] = Field(default="DRAFT")
    project_name: str = Field(default="")
    include_toc: bool = Field(default=False)
    include_watermark: bool = Field(default=True)
    section_breaks: bool = Field(default=True)
    author: str = Field(default="")

    @property
    def display_status(self) -> str:
        """Return a human-readable status label."""
        return "Niet-definitief" if self.status == "DRAFT" else "Definitief"
