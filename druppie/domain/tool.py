"""Tool definition domain models.

Unified tool definitions using Pydantic models for type-safe parameters.

Instead of storing parameters as JSON Schema (dict), each tool has a
Pydantic model class that:
1. Defines parameters with proper Python types
2. Auto-generates JSON Schema for LLM function calling
3. Validates arguments at runtime with helpful error messages
4. Provides IDE autocomplete and type checking

Usage:
    tool = registry.get("coding_write_file")

    # Validate arguments (returns typed model instance)
    params = tool.validate_arguments({"path": "test.txt", "content": "hello"})
    # params is WriteFileParams with .path and .content attributes

    # Get JSON Schema for LLM
    schema = tool.get_json_schema()

    # Convert to OpenAI format
    openai_tool = tool.to_openai_format()
"""

from enum import Enum
from typing import Type

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolType(str, Enum):
    """Tool type - determines execution path."""

    BUILTIN = "builtin"
    MCP = "mcp"


class EmptyParams(BaseModel):
    """Empty parameters model for tools with no parameters."""

    pass


class ToolDefinition(BaseModel):
    """Unified tool definition with type-safe parameters.

    Single source of truth for tool metadata. The params_model field
    holds a Pydantic model class that defines the tool's parameters.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Identity
    name: str  # "write_file", "done", "hitl_ask_question"
    tool_type: ToolType  # builtin or mcp
    server: str | None = None  # "coding", "docker" (None for builtin)

    # For LLM - description shown to the model
    description: str

    # Type-safe parameters - a Pydantic model class
    params_model: Type[BaseModel] = EmptyParams

    # For approval system
    requires_approval: bool = False
    required_role: str | None = None

    @property
    def full_name(self) -> str:
        """Full tool name for LLM (e.g., 'coding_write_file').

        Builtin tools use just the name, MCP tools prefix with server.
        """
        if self.server and self.tool_type == ToolType.MCP:
            return f"{self.server}_{self.name}"
        return self.name

    def get_json_schema(self) -> dict:
        """Generate JSON Schema from the params model.

        This is what gets sent to the LLM for function calling.
        Pydantic generates this automatically from the model definition.
        """
        if self.params_model is EmptyParams:
            return {"type": "object", "properties": {}}

        schema = self.params_model.model_json_schema()

        # Clean up schema for LLM consumption
        # Remove Pydantic-specific fields that confuse some LLMs
        schema.pop("title", None)
        schema.pop("$defs", None)

        # Ensure we have the basic structure
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}

        return schema

    def to_openai_format(self) -> dict:
        """Convert to OpenAI function calling format.

        This is the format expected by OpenAI/Anthropic for tool definitions.
        """
        return {
            "type": "function",
            "function": {
                "name": self.full_name,
                "description": self.description,
                "parameters": self.get_json_schema(),
            },
        }

    def validate_arguments(self, arguments: dict | None) -> tuple[bool, str | None, BaseModel | None]:
        """Validate arguments and return typed params model.

        Args:
            arguments: Raw arguments dict from LLM

        Returns:
            Tuple of (is_valid, error_message, validated_params)
            - If valid: (True, None, ParamsModel instance)
            - If invalid: (False, error_message, None)
        """
        if arguments is None:
            arguments = {}

        try:
            validated = self.params_model.model_validate(arguments)
            return True, None, validated
        except ValidationError as e:
            # Format error message nicely
            errors = []
            for error in e.errors():
                loc = ".".join(str(x) for x in error["loc"])
                msg = error["msg"]
                errors.append(f"{loc}: {msg}")
            return False, "; ".join(errors), None

    def get_param_descriptions(self) -> dict[str, str]:
        """Get parameter descriptions from the model's field info.

        Returns:
            Dict mapping parameter name to description
        """
        if self.params_model is EmptyParams:
            return {}

        descriptions = {}
        for name, field_info in self.params_model.model_fields.items():
            descriptions[name] = field_info.description or ""
        return descriptions


class ToolDefinitionSummary(BaseModel):
    """Lightweight tool definition for API responses."""

    name: str
    full_name: str
    tool_type: ToolType
    server: str | None
    description: str
    requires_approval: bool

    @classmethod
    def from_definition(cls, defn: ToolDefinition) -> "ToolDefinitionSummary":
        """Create summary from full definition."""
        return cls(
            name=defn.name,
            full_name=defn.full_name,
            tool_type=defn.tool_type,
            server=defn.server,
            description=defn.description,
            requires_approval=defn.requires_approval,
        )
