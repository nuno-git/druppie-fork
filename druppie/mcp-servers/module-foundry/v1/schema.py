"""Pydantic schema for Azure AI Foundry agent YAML.

Hard, non-LLM validation of the YAML produced by the architect. Models
mirror the fields accepted by Azure AI Foundry's `create_agent` /
`PromptAgentDefinition` API. Unknown keys are rejected at every level
(`extra="forbid"`).

Cross-field invariants that Pydantic can't express directly (duplicate
tool types, required connection_id for connection-backed tools,
metadata count/size limits, name regex) are enforced in
`validate_yaml_content` which wraps model instantiation and returns
structured `{valid, errors, warnings, normalized}` results.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


# Tool types Foundry currently supports. Kept as a module-level set so
# validate_yaml_content can surface a helpful error listing the allowed
# values without duplicating the literal.
ALLOWED_TOOL_TYPES: set[str] = {
    "code_interpreter",
    "file_search",
    "bing_grounding",
    "bing_custom_search",
    "azure_ai_search",
    "microsoft_fabric",
    "sharepoint_grounding",
    "browser_automation",
    "deep_research",
}

# Tool types that require a project-level connection. Foundry will
# reject deployment if connection_id is absent for these.
CONNECTION_REQUIRED: set[str] = {
    "bing_grounding",
    "bing_custom_search",
    "azure_ai_search",
    "microsoft_fabric",
    "sharepoint_grounding",
}

# Foundry agent name constraints
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")

# Foundry metadata limits
METADATA_MAX_ENTRIES = 16
METADATA_KEY_MAX = 64
METADATA_VALUE_MAX = 512

# Instruction length ceiling (Foundry hard limit)
INSTRUCTIONS_MAX = 256_000


class FoundryToolRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    connection_id: str | None = None

    @field_validator("type")
    @classmethod
    def _type_in_allowed(cls, v: str) -> str:
        if v not in ALLOWED_TOOL_TYPES:
            raise ValueError(
                f"unknown tool type '{v}'. Allowed: "
                + ", ".join(sorted(ALLOWED_TOOL_TYPES))
            )
        return v


class FoundryAgentYAML(BaseModel):
    """Shape of the YAML the architect produces for a Foundry agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    model: str
    instructions: str
    tools: list[FoundryToolRef] = Field(default_factory=list)
    tool_resources: dict[str, Any] | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    temperature: float | None = None
    top_p: float | None = None
    response_format: Literal["auto", "json_object"] | None = None

    @field_validator("name")
    @classmethod
    def _name_format(cls, v: str) -> str:
        if not NAME_PATTERN.match(v):
            raise ValueError(
                "name must match ^[A-Za-z0-9_-]{1,256}$ "
                "(alphanumeric, underscore, hyphen; 1-256 chars)"
            )
        return v

    @field_validator("description")
    @classmethod
    def _description_length(cls, v: str) -> str:
        if len(v) > 512:
            raise ValueError("description must be <= 512 characters")
        return v

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must be a non-empty deployment name")
        return v

    @field_validator("instructions")
    @classmethod
    def _instructions_bounds(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("instructions must be a non-empty system prompt")
        if len(v) > INSTRUCTIONS_MAX:
            raise ValueError(
                f"instructions exceed Foundry limit of {INSTRUCTIONS_MAX} characters"
            )
        return v

    @field_validator("temperature")
    @classmethod
    def _temperature_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v

    @field_validator("top_p")
    @classmethod
    def _top_p_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("top_p must be between 0.0 and 1.0")
        return v


def _format_validation_errors(exc: ValidationError) -> list[dict]:
    """Map Pydantic ValidationError entries to our structured error shape."""
    errors = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        errors.append(
            {
                "field": loc or "<root>",
                "message": err.get("msg", "invalid"),
                "code": err.get("type", "validation_error"),
            }
        )
    return errors


def _check_cross_field(model: FoundryAgentYAML) -> tuple[list[dict], list[dict]]:
    """Checks that don't fit naturally inside individual field validators."""
    errors: list[dict] = []
    warnings: list[dict] = []

    # Duplicate tool types
    seen: set[str] = set()
    for idx, tool in enumerate(model.tools):
        if tool.type in seen:
            errors.append(
                {
                    "field": f"tools.{idx}.type",
                    "message": f"duplicate tool type '{tool.type}' — each tool may appear at most once",
                    "code": "duplicate_tool",
                }
            )
        seen.add(tool.type)

        # Connection requirement
        if tool.type in CONNECTION_REQUIRED and not tool.connection_id:
            errors.append(
                {
                    "field": f"tools.{idx}.connection_id",
                    "message": (
                        f"tool '{tool.type}' requires connection_id referencing a "
                        "connection configured in the Foundry project"
                    ),
                    "code": "missing_connection_id",
                }
            )

        # Warn when connection_id is set for a tool that doesn't use one
        if tool.type not in CONNECTION_REQUIRED and tool.connection_id:
            warnings.append(
                {
                    "field": f"tools.{idx}.connection_id",
                    "message": (
                        f"tool '{tool.type}' does not take a connection_id — "
                        "field will be ignored by Foundry"
                    ),
                }
            )

    # file_search requires a non-empty tool_resources.file_search.vector_store_ids.
    # Foundry's create_agent rejects file_search without it — catching here
    # surfaces the failure at validation instead of during deploy.
    if any(t.type == "file_search" for t in model.tools):
        tr = model.tool_resources or {}
        fs = tr.get("file_search") if isinstance(tr, dict) else None
        ids = fs.get("vector_store_ids") if isinstance(fs, dict) else None
        if not isinstance(ids, list) or not ids or not all(
            isinstance(i, str) and i.strip() for i in ids
        ):
            errors.append(
                {
                    "field": "tool_resources.file_search.vector_store_ids",
                    "message": (
                        "tool 'file_search' requires tool_resources.file_search."
                        "vector_store_ids to be a non-empty list of vector store "
                        "IDs — Foundry rejects deployment otherwise"
                    ),
                    "code": "missing_vector_store_ids",
                }
            )

    # Metadata limits
    if len(model.metadata) > METADATA_MAX_ENTRIES:
        errors.append(
            {
                "field": "metadata",
                "message": f"metadata has {len(model.metadata)} entries, max {METADATA_MAX_ENTRIES}",
                "code": "metadata_too_many",
            }
        )
    for key, value in model.metadata.items():
        if len(key) > METADATA_KEY_MAX:
            errors.append(
                {
                    "field": f"metadata.{key}",
                    "message": f"metadata key too long ({len(key)} > {METADATA_KEY_MAX})",
                    "code": "metadata_key_too_long",
                }
            )
        if len(value) > METADATA_VALUE_MAX:
            errors.append(
                {
                    "field": f"metadata.{key}",
                    "message": f"metadata value too long ({len(value)} > {METADATA_VALUE_MAX})",
                    "code": "metadata_value_too_long",
                }
            )

    # Advisory warnings
    if not model.description.strip():
        warnings.append(
            {
                "field": "description",
                "message": "description is empty — adding one improves discoverability",
            }
        )
    if len(model.instructions) < 200:
        warnings.append(
            {
                "field": "instructions",
                "message": (
                    "instructions are short (<200 chars). Foundry agents rely "
                    "entirely on instructions — consider expanding."
                ),
            }
        )

    return errors, warnings


def validate_yaml_content(yaml_content: str) -> dict:
    """Parse and validate a YAML string against the Foundry agent schema.

    Never raises. Returns a structured dict:
        {
            "valid": bool,
            "errors": [{"field", "message", "code"}, ...],
            "warnings": [{"field", "message"}, ...],
            "normalized": dict | None,  # model.model_dump() when valid
        }
    """
    # Parse
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        return {
            "valid": False,
            "errors": [
                {
                    "field": "<root>",
                    "message": f"YAML parse error: {exc}",
                    "code": "yaml_parse_error",
                }
            ],
            "warnings": [],
            "normalized": None,
        }

    if data is None:
        return {
            "valid": False,
            "errors": [
                {
                    "field": "<root>",
                    "message": "YAML document is empty",
                    "code": "empty_document",
                }
            ],
            "warnings": [],
            "normalized": None,
        }

    if not isinstance(data, dict):
        return {
            "valid": False,
            "errors": [
                {
                    "field": "<root>",
                    "message": f"top-level YAML must be a mapping, got {type(data).__name__}",
                    "code": "bad_top_level",
                }
            ],
            "warnings": [],
            "normalized": None,
        }

    # Schema validate
    try:
        model = FoundryAgentYAML(**data)
    except ValidationError as exc:
        return {
            "valid": False,
            "errors": _format_validation_errors(exc),
            "warnings": [],
            "normalized": None,
        }

    # Cross-field checks
    errors, warnings = _check_cross_field(model)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "normalized": model.model_dump(mode="json") if not errors else None,
    }
