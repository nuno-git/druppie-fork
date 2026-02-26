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

    def get_json_schema(self, strict: bool = True) -> dict:
        """Generate JSON Schema from the params model.

        This is what gets sent to the LLM for function calling.
        Pydantic generates this automatically from the model definition.

        Args:
            strict: If True, generate OpenAI strict mode compliant schema:
                    - additionalProperties: false on all objects
                    - All properties in required array
                    - Optional fields use type union with null
        """
        if self.params_model is EmptyParams:
            schema = {"type": "object", "properties": {}}
            if strict:
                schema["additionalProperties"] = False
            return schema

        schema = self.params_model.model_json_schema()

        # Inline $defs references before removing $defs
        # This handles nested models like PlanStep in MakePlanParams
        defs = schema.pop("$defs", {})
        if defs:
            schema = self._inline_refs(schema, defs)

        # Clean up schema for LLM consumption
        # Remove Pydantic-specific fields that confuse some LLMs or cause duplication
        schema.pop("title", None)
        schema.pop("description", None)  # Remove - already in function.description

        # Recursively clean nested title fields
        schema = self._clean_schema(schema)

        # Ensure we have the basic structure
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}

        # Apply strict mode requirements
        if strict:
            schema = self._apply_strict_mode(schema)

        return schema

    def _apply_strict_mode(self, schema: dict) -> dict:
        """Apply OpenAI strict mode requirements to schema.

        Strict mode requires:
        - additionalProperties: false on all objects
        - All properties listed in required array
        - Optional fields must have null in type union and default: null

        This is applied recursively to nested objects.
        """
        if not isinstance(schema, dict):
            return schema

        # Add additionalProperties: false to object types
        if schema.get("type") == "object" or "properties" in schema:
            schema["additionalProperties"] = False

            # Ensure all properties are in required array
            if "properties" in schema:
                all_props = list(schema["properties"].keys())
                existing_required = set(schema.get("required", []))

                # For properties not in required, add null to their type
                for prop_name, prop_schema in schema["properties"].items():
                    if prop_name not in existing_required:
                        # Make optional by adding null to type union
                        self._make_nullable(prop_schema)

                # All properties must be in required for strict mode
                schema["required"] = all_props

                # Recursively apply to nested objects
                for prop_schema in schema["properties"].values():
                    if isinstance(prop_schema, dict):
                        self._apply_strict_mode(prop_schema)

        # Handle array items
        if "items" in schema and isinstance(schema["items"], dict):
            self._apply_strict_mode(schema["items"])

        return schema

    def _make_nullable(self, prop_schema: dict) -> None:
        """Make a property nullable by adding null to its type.

        For strict mode, optional fields need:
        - Type as array: ["string", "null"] or {"anyOf": [..., {"type": "null"}]}
        - default: null
        """
        if not isinstance(prop_schema, dict):
            return

        # Already nullable
        if prop_schema.get("type") == "null":
            return

        # Handle anyOf/oneOf patterns
        if "anyOf" in prop_schema or "oneOf" in prop_schema:
            key = "anyOf" if "anyOf" in prop_schema else "oneOf"
            types = prop_schema[key]
            # Check if null is already in the union
            has_null = any(
                t.get("type") == "null" if isinstance(t, dict) else False
                for t in types
            )
            if not has_null:
                types.append({"type": "null"})
            prop_schema.setdefault("default", None)
            return

        # Handle simple type
        if "type" in prop_schema:
            current_type = prop_schema["type"]
            if isinstance(current_type, list):
                if "null" not in current_type:
                    current_type.append("null")
            else:
                # Convert to anyOf pattern for clarity
                prop_schema["anyOf"] = [
                    {"type": current_type},
                    {"type": "null"},
                ]
                del prop_schema["type"]
            prop_schema.setdefault("default", None)

    def _inline_refs(self, obj: dict | list, defs: dict) -> dict | list:
        """Recursively inline $ref references and clean up Pydantic artifacts.

        Args:
            obj: The schema object to process
            defs: The $defs dictionary containing definitions

        Returns:
            Schema with $refs replaced and cleaned up
        """
        if isinstance(obj, dict):
            if "$ref" in obj:
                # Extract definition name from "#/$defs/PlanStep" format
                ref_path = obj["$ref"]
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs:
                        # Return the inlined definition (recursively process it too)
                        inlined = defs[def_name].copy()
                        inlined.pop("title", None)  # Clean up nested titles
                        return self._inline_refs(inlined, defs)
                return obj
            else:
                # Recursively process and clean up title fields in properties
                result = {}
                for k, v in obj.items():
                    processed = self._inline_refs(v, defs)
                    result[k] = processed
                return result
        elif isinstance(obj, list):
            return [self._inline_refs(item, defs) for item in obj]
        else:
            return obj

    def _clean_schema(self, schema: dict) -> dict:
        """Remove Pydantic-specific fields from schema recursively.

        Removes 'title' fields from all nested properties.
        """
        if not isinstance(schema, dict):
            return schema

        # Remove title from current level
        schema.pop("title", None)

        # Process properties
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                if isinstance(prop_schema, dict):
                    prop_schema.pop("title", None)
                    # Recurse into nested objects
                    if "properties" in prop_schema:
                        self._clean_schema(prop_schema)
                    # Handle array items
                    if "items" in prop_schema and isinstance(prop_schema["items"], dict):
                        self._clean_schema(prop_schema["items"])

        # Handle array items at current level
        if "items" in schema and isinstance(schema["items"], dict):
            self._clean_schema(schema["items"])

        return schema

    def to_openai_format(self, strict: bool = True) -> dict:
        """Convert to OpenAI function calling format.

        This is the format expected by OpenAI/Anthropic for tool definitions.
        Includes approval requirements in the description so the LLM knows
        which tools will pause for human approval.

        Args:
            strict: If True, use OpenAI strict mode for structured outputs.
                    This enables JSON Schema validation on the LLM side.
        """
        description = self.description
        if self.requires_approval:
            role = self.required_role or "developer"
            description = f"{description} [REQUIRES APPROVAL by {role}]"

        result = {
            "type": "function",
            "function": {
                "name": self.full_name,
                "description": description,
                "parameters": self.get_json_schema(strict=strict),
            },
        }

        # Add strict mode flag for OpenAI structured outputs
        if strict:
            result["function"]["strict"] = True

        return result

    def _normalize_llm_arguments(self, arguments: dict) -> dict:
        """Normalize common LLM mistakes in argument values.

        Some LLMs send string representations instead of proper JSON types:
        - "null" string instead of null
        - "{}" string instead of empty object {}
        - "[]" string instead of empty array []
        - "true"/"false" strings instead of booleans
        - Extra/unknown keyword arguments (e.g., "size" copied from read_file response)

        This is used as a fallback when initial validation fails.
        """
        import json
        import structlog
        _logger = structlog.get_logger()

        # Strip unknown arguments not in the tool's schema
        known_fields = set(self.params_model.model_fields.keys())
        extra_keys = set(arguments.keys()) - known_fields
        if extra_keys:
            _logger.warning(
                "stripping_unknown_tool_arguments",
                tool=self.full_name,
                extra_keys=sorted(extra_keys),
            )

        normalized = {}
        for key, value in arguments.items():
            if key in extra_keys:
                continue  # Strip unknown arguments
            if isinstance(value, str):
                # Handle string "null" -> None
                if value.lower() == "null":
                    normalized[key] = None
                # Handle string booleans -> bool
                elif value.lower() == "true":
                    normalized[key] = True
                elif value.lower() == "false":
                    normalized[key] = False
                # Handle string JSON objects/arrays -> parsed
                elif value.startswith(("{", "[")):
                    try:
                        parsed = json.loads(value)
                        normalized[key] = parsed
                    except json.JSONDecodeError:
                        normalized[key] = value  # Keep original if not valid JSON
                else:
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized

    def validate_arguments(self, arguments: dict | None) -> tuple[bool, str | None, BaseModel | None, dict | None]:
        """Validate arguments and return typed params model.

        First attempts validation with original arguments. If that fails,
        retries with normalized arguments (handling common LLM mistakes like
        "null" strings). This preserves the original values when they're correct.

        Args:
            arguments: Raw arguments dict from LLM

        Returns:
            Tuple of (is_valid, error_message, validated_params, normalized_args)
            - If valid with original: (True, None, ParamsModel, None)
            - If valid with normalized: (True, None, ParamsModel, normalized_dict)
            - If invalid: (False, error_message, None, None)
        """
        if arguments is None:
            arguments = {}

        # First try with original arguments
        try:
            validated = self.params_model.model_validate(arguments)
            return True, None, validated, None  # No normalization needed
        except ValidationError as first_error:
            pass  # Try normalization fallback

        # Retry with normalized arguments (handles "null" strings, etc.)
        normalized = self._normalize_llm_arguments(arguments)
        try:
            validated = self.params_model.model_validate(normalized)
            return True, None, validated, normalized  # Return normalized dict
        except ValidationError as e:
            # Format error message nicely (use original error for clarity)
            errors = []
            for error in first_error.errors():
                loc = ".".join(str(x) for x in error["loc"])
                msg = error["msg"]
                errors.append(f"{loc}: {msg}")
            return False, "; ".join(errors), None, None

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
