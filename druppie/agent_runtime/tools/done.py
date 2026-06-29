"""done() builtin tool — dynamic schema generation and validation.

The done() tool is a RUNTIME builtin, NOT a ToolProvider tool.
It is always included for every agent. Every agent MUST call done() to complete.
"""

from __future__ import annotations

from typing import Any

from druppie.agent_runtime.definition import AgentDefinition, build_done_schema


class DoneTool:
    """Generates and validates the done() tool for an agent."""

    def build_schema(self, definition: AgentDefinition) -> dict:
        """Generate the done() tool JSON Schema from an agent definition.

        Delegates to definition.build_done_schema().
        """
        return build_done_schema(definition)

    def validate(
        self,
        call_args: dict[str, Any],
        definition: AgentDefinition,
        tool_call_history: dict[str, int],
    ) -> tuple[bool, str | None]:
        """Validate a done() call against the agent's rules.

        Validation order:
        1. Schema validation (summary presence, required variables, types, enums)
        2. required_summary_status check (summary must contain at least one keyword)
        3. completion_preconditions check (conditional tool call requirements)

        Args:
            call_args: The arguments passed to done()
            definition: The agent definition with validation rules
            tool_call_history: {tool_name: call_count} tracking all tool calls

        Returns:
            (is_valid, error_message) — error_message is None when valid
        """
        error = self._validate_schema(call_args, definition)
        if error:
            return False, error

        summary = call_args.get("summary", "")

        error = self._validate_summary_status(summary, definition)
        if error:
            return False, error

        error = self._validate_preconditions(summary, definition, tool_call_history)
        if error:
            return False, error

        return True, None

    def build_result(self, summary: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Format a successful done result."""
        return {
            "summary": summary,
            "variables": variables or {},
        }

    def _validate_schema(self, call_args: dict[str, Any], definition: AgentDefinition) -> str | None:
        if not call_args.get("summary"):
            return "Missing required field: summary"

        if not definition.done_variables:
            return None

        for var_name, var_schema in definition.done_variables.items():
            is_required = var_schema.get("required", False)
            value = call_args.get(var_name)

            if is_required and value is None:
                return f"Missing required field: {var_name}"

            if value is not None:
                expected_type = var_schema.get("type")
                if expected_type and not self._check_type(value, expected_type):
                    return f"Wrong type for {var_name}: expected {expected_type}"

                enum_values = var_schema.get("enum")
                if enum_values and value not in enum_values:
                    return f"Invalid value for {var_name}: must be one of {enum_values}"

        return None

    def _validate_summary_status(self, summary: str, definition: AgentDefinition) -> str | None:
        if not definition.required_summary_status:
            return None

        one_of = definition.required_summary_status.get("one_of", [])
        error_message = definition.required_summary_status.get("error_message", "")

        if one_of and not any(keyword in summary for keyword in one_of):
            return error_message or f"Summary must contain one of: {', '.join(one_of)}"

        return None

    def _validate_preconditions(
        self,
        summary: str,
        definition: AgentDefinition,
        tool_call_history: dict[str, int],
    ) -> str | None:
        for precondition in definition.completion_preconditions:
            summary_contains = precondition.get("summary_contains")
            unless_contains = precondition.get("unless_summary_contains")
            required_tools = precondition.get("required_tools", [])
            error_message = precondition.get("error_message", "")

            if summary_contains and summary_contains not in summary:
                continue

            if unless_contains and unless_contains in summary:
                continue

            for tool_req in required_tools:
                tool_name = tool_req["tool_name"]
                min_calls = tool_req.get("min_calls", 1)
                actual_calls = self._count_tool_calls(tool_name, tool_call_history)

                if actual_calls < min_calls:
                    return error_message or f"Must call {tool_name} at least {min_calls} time(s)"

        return None

    @staticmethod
    def _count_tool_calls(tool_name: str, tool_call_history: dict[str, int]) -> int:
        total = tool_call_history.get(tool_name, 0)
        if total > 0:
            return total
        for key, count in tool_call_history.items():
            if key.endswith(f"_{tool_name}"):
                total += count
        return total

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
        }
        python_type = type_map.get(expected_type)
        if python_type is None:
            return True
        return isinstance(value, python_type)
