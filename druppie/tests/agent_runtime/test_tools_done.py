"""Tests for druppie.agent_runtime.tools.done."""


from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.tools.done import DoneTool


class TestBuildSchema:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {"id": "test", "name": "Test", "description": "Test", "system_prompt": "test"}
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_build_schema_no_done_variables(self):
        tool = DoneTool()
        schema = tool.build_schema(self._defn(done_variables=None))
        assert schema["name"] == "done"
        assert "summary" in schema["inputSchema"]["properties"]
        assert schema["inputSchema"]["required"] == ["summary"]

    def test_build_schema_with_done_variables(self):
        tool = DoneTool()
        defn = self._defn(done_variables={
            "next_agent": {"type": "string", "enum": ["a", "b"], "required": True},
        })
        schema = tool.build_schema(defn)
        assert "next_agent" in schema["inputSchema"]["properties"]
        assert "summary" in schema["inputSchema"]["required"]
        assert "next_agent" in schema["inputSchema"]["required"]

    def test_build_schema_summary_always_required(self):
        tool = DoneTool()
        defn = self._defn(done_variables={"opt": {"type": "string", "required": False}})
        schema = tool.build_schema(defn)
        assert "summary" in schema["inputSchema"]["required"]
        assert "opt" not in schema["inputSchema"]["required"]

    def test_build_schema_enum_restriction(self):
        tool = DoneTool()
        defn = self._defn(done_variables={
            "choice": {"type": "string", "enum": ["x", "y"], "required": True},
        })
        schema = tool.build_schema(defn)
        assert schema["inputSchema"]["properties"]["choice"]["enum"] == ["x", "y"]

    def test_build_schema_type_preservation(self):
        tool = DoneTool()
        defn = self._defn(done_variables={
            "name": {"type": "string", "required": True},
            "count": {"type": "number", "required": True},
            "flag": {"type": "boolean", "required": False},
        })
        schema = tool.build_schema(defn)
        props = schema["inputSchema"]["properties"]
        assert props["name"]["type"] == "string"
        assert props["count"]["type"] == "number"
        assert props["flag"]["type"] == "boolean"


class TestValidateSchema:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {"id": "test", "name": "Test", "description": "Test", "system_prompt": "test"}
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_validate_summary_present(self):
        tool = DoneTool()
        valid, err = tool.validate({"summary": "Done"}, self._defn(), {})
        assert valid is True
        assert err is None

    def test_validate_summary_missing(self):
        tool = DoneTool()
        valid, err = tool.validate({}, self._defn(), {})
        assert valid is False
        assert "summary" in err

    def test_validate_required_variable_present(self):
        tool = DoneTool()
        defn = self._defn(done_variables={"next_agent": {"type": "string", "required": True}})
        valid, err = tool.validate({"summary": "Done", "next_agent": "architect"}, defn, {})
        assert valid is True

    def test_validate_required_variable_missing(self):
        tool = DoneTool()
        defn = self._defn(done_variables={"next_agent": {"type": "string", "required": True}})
        valid, err = tool.validate({"summary": "Done"}, defn, {})
        assert valid is False
        assert "next_agent" in err

    def test_validate_optional_variable_omitted(self):
        tool = DoneTool()
        defn = self._defn(done_variables={"confidence": {"type": "number", "required": False}})
        valid, err = tool.validate({"summary": "Done"}, defn, {})
        assert valid is True

    def test_validate_wrong_type(self):
        tool = DoneTool()
        defn = self._defn(done_variables={"count": {"type": "number", "required": True}})
        valid, err = tool.validate({"summary": "Done", "count": "not_a_number"}, defn, {})
        assert valid is False
        assert "Wrong type" in err

    def test_validate_invalid_enum(self):
        tool = DoneTool()
        defn = self._defn(done_variables={
            "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
        })
        valid, err = tool.validate({"summary": "Done", "next_agent": "invalid"}, defn, {})
        assert valid is False
        assert "Invalid value" in err

    def test_validate_all_types_valid(self):
        tool = DoneTool()
        defn = self._defn(done_variables={
            "name": {"type": "string", "required": True},
            "count": {"type": "number", "required": True},
        })
        valid, err = tool.validate({"summary": "Done", "name": "test", "count": 42}, defn, {})
        assert valid is True

    def test_validate_no_preconditions(self):
        tool = DoneTool()
        defn = self._defn()
        valid, err = tool.validate({"summary": "Done"}, defn, {})
        assert valid is True


class TestValidatePreconditions:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {"id": "test", "name": "Test", "description": "Test", "system_prompt": "test"}
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_precondition_summary_contains_match(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "DESIGN_APPROVED",
            "required_tools": [{"tool_name": "submit_design_for_review", "min_calls": 1}],
            "error_message": "Must call submit_design_for_review",
        }])
        history = {"submit_design_for_review": 1}
        valid, err = tool.validate({"summary": "DESIGN_APPROVED done"}, defn, history)
        assert valid is True

    def test_precondition_summary_contains_no_match(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "DESIGN_APPROVED",
            "required_tools": [{"tool_name": "submit_design_for_review", "min_calls": 1}],
            "error_message": "Must call submit_design_for_review",
        }])
        valid, err = tool.validate({"summary": "Something else"}, defn, {})
        assert valid is True

    def test_precondition_unless_bypass(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "DESIGN_APPROVED",
            "unless_summary_contains": "HARD",
            "required_tools": [{"tool_name": "submit_design_for_review", "min_calls": 1}],
            "error_message": "Must call submit_design_for_review",
        }])
        valid, err = tool.validate({"summary": "DESIGN_APPROVED but HARD exception"}, defn, {})
        assert valid is True

    def test_precondition_tool_not_called(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "COMPLETE",
            "required_tools": [{"tool_name": "write_file", "min_calls": 1}],
            "error_message": "Must call write_file before done",
        }])
        valid, err = tool.validate({"summary": "COMPLETE"}, defn, {})
        assert valid is False
        assert "write_file" in err

    def test_precondition_tool_called_enough(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "COMPLETE",
            "required_tools": [{"tool_name": "write_file", "min_calls": 2}],
            "error_message": "Need 2 write_file calls",
        }])
        valid, err = tool.validate({"summary": "COMPLETE"}, defn, {"write_file": 3})
        assert valid is True

    def test_precondition_multiple_tools(self):
        tool = DoneTool()
        defn = self._defn(completion_preconditions=[{
            "summary_contains": "COMPLETE",
            "required_tools": [
                {"tool_name": "write_file", "min_calls": 1},
                {"tool_name": "push_changes", "min_calls": 1},
            ],
            "error_message": "Must write and push",
        }])
        valid, err = tool.validate({"summary": "COMPLETE"}, defn, {"write_file": 1})
        assert valid is False


class TestValidateSummaryStatus:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {"id": "test", "name": "Test", "description": "Test", "system_prompt": "test"}
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_required_summary_status_match(self):
        tool = DoneTool()
        defn = self._defn(required_summary_status={
            "one_of": ["DESIGN_APPROVED", "DESIGN_REJECTED"],
            "error_message": "Must have status",
        })
        valid, err = tool.validate({"summary": "DESIGN_APPROVED done"}, defn, {})
        assert valid is True

    def test_required_summary_status_no_match(self):
        tool = DoneTool()
        defn = self._defn(required_summary_status={
            "one_of": ["DESIGN_APPROVED", "DESIGN_REJECTED"],
            "error_message": "Must have status",
        })
        valid, err = tool.validate({"summary": "Something else"}, defn, {})
        assert valid is False

    def test_required_summary_status_error_message(self):
        tool = DoneTool()
        defn = self._defn(required_summary_status={
            "one_of": ["STATUS_ONE"],
            "error_message": "Custom error message here",
        })
        valid, err = tool.validate({"summary": "no match"}, defn, {})
        assert valid is False
        assert err == "Custom error message here"


class TestBuildResult:
    def test_build_result_basic(self):
        tool = DoneTool()
        result = tool.build_result("Task done", {"next": "architect"})
        assert result["summary"] == "Task done"
        assert result["variables"] == {"next": "architect"}

    def test_build_result_empty_variables(self):
        tool = DoneTool()
        result = tool.build_result("Done")
        assert result["variables"] == {}


class TestFullDoneFlow:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {"id": "test", "name": "Test", "description": "Test", "system_prompt": "test"}
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_full_done_flow_valid(self):
        tool = DoneTool()
        defn = self._defn(
            done_variables={"next_agent": {"type": "string", "enum": ["a", "b"], "required": True}},
            completion_preconditions=[{
                "summary_contains": "COMPLETE",
                "required_tools": [{"tool_name": "work_tool", "min_calls": 1}],
                "error_message": "Must work",
            }],
        )
        args = {"summary": "COMPLETE", "next_agent": "a"}
        history = {"work_tool": 1}
        valid, err = tool.validate(args, defn, history)
        assert valid is True
        result = tool.build_result(args["summary"], {"next_agent": args["next_agent"]})
        assert result["summary"] == "COMPLETE"

    def test_full_done_flow_invalid_retry(self):
        tool = DoneTool()
        defn = self._defn(
            completion_preconditions=[{
                "summary_contains": "COMPLETE",
                "required_tools": [{"tool_name": "required_tool", "min_calls": 1}],
                "error_message": "Must call required_tool",
            }],
        )
        valid, err = tool.validate({"summary": "COMPLETE"}, defn, {})
        assert valid is False
        assert "required_tool" in err
