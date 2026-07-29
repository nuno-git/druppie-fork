"""Document formatter domain models.

Provides typed validation for document parameters that were previously
passed as an untyped dict[str, Any] in the legacy generate_pdf() API.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DocumentHouseStyle(str, Enum):
    """Corporate identity template a project's documents are rendered in.

    Each style maps to exactly one Typst template module that exports a
    single show-rule function. The signatures of all template functions are
    identical, so the only thing that varies per style is the import line and
    the function name.
    """

    RIJNLAND = "rijnland"
    HHSK = "hhsk"

    @property
    def template_path(self) -> str:
        """Absolute (Typst --root relative) path used in the #import line."""
        return f"/druppie/templates/documents/{self.value}.typ"

    @property
    def template_function(self) -> str:
        """Name of the show-rule function the template module exports."""
        return f"{self.value}_doc"

    @property
    def import_line(self) -> str:
        """The exact Typst import line an agent must write for this style."""
        return f'#import "{self.template_path}": {self.template_function}'


DEFAULT_HOUSE_STYLE = DocumentHouseStyle.RIJNLAND


class DocumentMetadata(BaseModel):
    """Typed document configuration for a house-style Typst template.

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
