"""Tool definition domain models.

Unified tool definitions with JSON schema validation for parameters.

Each tool has a JSON schema (from MCP tools/list or builtin definitions) that:
1. Defines parameters with proper JSON types
2. Gets sent directly to the LLM for function calling
3. Validates arguments at runtime via jsonschema
4. Provides parameter descriptions for documentation

Usage:
    tool = registry.get("coding_write_file")

    # Validate arguments (returns validated dict)
    is_valid, error, validated, normalized = tool.validate_arguments({"path": "test.txt", "content": "hello"})

    # Get JSON Schema for LLM
    schema = tool.get_json_schema()

    # Convert to OpenAI format
    openai_tool = tool.to_openai_format()
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ToolType(str, Enum):
    """Tool type - determines execution path."""

    BUILTIN = "builtin"
    MCP = "mcp"


class ToolDefinition(BaseModel):
    """Unified tool definition with JSON schema validation.

    Single source of truth for tool metadata. The json_schema field
    holds the JSON schema dict that defines the tool's parameters.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Identity
    name: str  # "write_file", "done", "hitl_ask_question"
    tool_type: ToolType  # builtin or mcp
    server: str | None = None  # "coding", "docker" (None for builtin)

    # For LLM - description shown to the model
    description: str

    # JSON schema for parameters (from tools/list or builtin definitions)
    json_schema: dict = {}

    # Tool metadata (module_id, version, internal, pre_validate, etc.)
    meta: dict = {}

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
        """Get JSON Schema for the tool's parameters.

        This is what gets sent to the LLM for function calling.

        Args:
            strict: If True, generate OpenAI strict mode compliant schema:
                    - additionalProperties: false on all objects
                    - All properties in required array
                    - Optional fields use type union with null
        """
        if not self.json_schema:
            schema = {"type": "object", "properties": {}}
            if strict:
                schema["additionalProperties"] = False
            return schema

        import copy
        schema = copy.deepcopy(self.json_schema)

        # Inline $defs references before removing $defs
        # This handles nested models like PlanStep in MakePlanParams
        defs = schema.pop("$defs", {})
        if defs:
            schema = self._inline_refs(schema, defs)

        # Clean up schema for LLM consumption
        # Remove fields that confuse some LLMs or cause duplication
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
        """Recursively inline $ref references and clean up artifacts.

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

        Also strips unknown arguments that aren't in the tool's schema.
        Some LLMs copy fields from tool responses into subsequent calls
        (e.g., copying "size" from read_file response into write_file call).

        This is used as a fallback when initial validation fails.
        """
        import json
        import structlog
        _logger = structlog.get_logger()

        # Strip unknown arguments not in the tool's schema
        known_fields = set(self.json_schema.get("properties", {}).keys())
        extra_keys = set(arguments.keys()) - known_fields if known_fields else set()
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

    def validate_arguments(self, arguments: dict | None) -> tuple[bool, str | None, dict | None, dict | None]:
        """Validate arguments against JSON schema.

        First attempts validation with original arguments. If that fails,
        retries with normalized arguments (handling common LLM mistakes like
        "null" strings). This preserves the original values when they're correct.

        Args:
            arguments: Raw arguments dict from LLM

        Returns:
            Tuple of (is_valid, error_message, validated_args, normalized_args)
            - If valid with original: (True, None, args, None)
            - If valid with normalized: (True, None, normalized_dict, normalized_dict)
            - If invalid: (False, error_message, None, None)
        """
        import jsonschema

        if arguments is None:
            arguments = {}

        if not self.json_schema:
            # No schema to validate against - accept everything
            return True, None, arguments, None

        # First try with original arguments
        try:
            jsonschema.validate(instance=arguments, schema=self.json_schema)
            return True, None, arguments, None
        except jsonschema.ValidationError:
            pass  # Try normalization fallback

        # Retry with normalized arguments (handles "null" strings, etc.)
        normalized = self._normalize_llm_arguments(arguments)
        try:
            jsonschema.validate(instance=normalized, schema=self.json_schema)
            return True, None, normalized, normalized
        except jsonschema.ValidationError as e:
            return False, str(e.message), None, None

    def get_param_descriptions(self) -> dict[str, str]:
        """Get parameter descriptions from the JSON schema.

        Returns:
            Dict mapping parameter name to description
        """
        if not self.json_schema:
            return {}

        properties = self.json_schema.get("properties", {})
        descriptions = {}
        for name, prop_schema in properties.items():
            if isinstance(prop_schema, dict):
                descriptions[name] = prop_schema.get("description", "")
            else:
                descriptions[name] = ""
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
