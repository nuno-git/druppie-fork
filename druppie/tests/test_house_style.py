"""Tests for the per-project document house style.

Covers the DocumentHouseStyle enum, its mapping onto Typst templates, the
Project model column, and the documenter prompt that tells the agent which
template to import.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from druppie.agents.prompt_builder import PromptBuilder
from druppie.db.models import Project
from druppie.domain import DEFAULT_HOUSE_STYLE, DocumentHouseStyle

TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "documents"
DOCUMENTER_YAML = Path(__file__).parent.parent / "agents" / "definitions" / "documenter.yaml"


class TestDocumentHouseStyleEnum:
    """The enum is the single source of truth for style -> template mapping."""

    def test_expected_styles_exist(self):
        assert {style.value for style in DocumentHouseStyle} == {"rijnland", "hhsk"}

    def test_default_is_rijnland(self):
        """Default must stay rijnland so existing projects render unchanged."""
        assert DEFAULT_HOUSE_STYLE is DocumentHouseStyle.RIJNLAND

    @pytest.mark.parametrize("style", list(DocumentHouseStyle))
    def test_template_file_exists(self, style):
        """Every style points at a template that is actually on disk."""
        assert (TEMPLATE_DIR / f"{style.value}.typ").is_file()

    @pytest.mark.parametrize("style", list(DocumentHouseStyle))
    def test_template_exports_its_function(self, style):
        """The template really defines the function the enum names."""
        source = (TEMPLATE_DIR / f"{style.value}.typ").read_text(encoding="utf-8")
        assert f"#let {style.template_function}(" in source

    @pytest.mark.parametrize("style", list(DocumentHouseStyle))
    def test_import_line_is_consistent(self, style):
        assert style.import_line == f'#import "{style.template_path}": {style.template_function}'

    def test_is_a_string_enum(self):
        """Value must serialise as a plain string for JSON/DB round-trips."""
        assert DocumentHouseStyle.HHSK == "hhsk"


class TestProjectHouseStyleColumn:
    """The style is a constrained column, not free text and not JSON."""

    def test_column_is_not_nullable(self):
        assert Project.__table__.c.house_style.nullable is False

    def test_column_constrains_values(self):
        """Column enumerates exactly the supported styles."""
        column_type = Project.__table__.c.house_style.type
        assert set(column_type.enums) == {"rijnland", "hhsk"}

    def test_default_applied_to_new_instance(self):
        """A project created without a style falls back to rijnland."""
        default = Project.__table__.c.house_style.default
        assert default.arg is DEFAULT_HOUSE_STYLE

    def test_to_dict_exposes_style(self):
        project = Project(name="p", house_style=DocumentHouseStyle.HHSK)
        assert project.to_dict()["house_style"] == "hhsk"


class TestHouseStyleReachesTheAgent:
    """The agent is told the style explicitly rather than guessing it."""

    def test_context_key_is_rendered_into_the_prompt(self):
        """build_user_prompt surfaces document_house_style in the CONTEXT block.

        This is the existing generic context mechanism; the orchestrator puts
        the project's style into the same dict as project_name and repo_name.
        """
        builder = PromptBuilder("documenter", definition=None)
        prompt = builder.build_user_prompt(
            "Export the FO as PDF",
            {"project_name": "Demo", "document_house_style": "hhsk"},
        )
        assert "- document_house_style: hhsk" in prompt

    def test_documenter_prompt_documents_every_style(self):
        """Prompt must map each style to its import line and show rule.

        Drift guard: adding a style to the enum without teaching the
        documenter how to import it fails here.
        """
        source = DOCUMENTER_YAML.read_text(encoding="utf-8")

        for style in DocumentHouseStyle:
            assert style.import_line in source, f"missing import line for {style.value}"
            assert (
                f"{style.template_function}.with(" in source
            ), f"missing show rule for {style.value}"

    def test_documenter_prompt_names_the_context_key(self):
        """The prompt must point the agent at the context key by name."""
        source = DOCUMENTER_YAML.read_text(encoding="utf-8")
        assert "document_house_style" in source

    def test_documenter_definition_is_valid_yaml(self):
        """The edited agent definition still parses and keeps its prompt."""
        definition = yaml.safe_load(DOCUMENTER_YAML.read_text(encoding="utf-8"))
        assert isinstance(definition, dict)
        assert definition.get("system_prompt")
