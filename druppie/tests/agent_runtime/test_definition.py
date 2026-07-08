"""Tests for druppie.agent_runtime.definition."""


import pytest
import yaml

from druppie.agent_runtime.definition import (
    AgentDefinition,
    build_done_schema,
    load_definition,
    parse_definition,
)


class TestParseDefinition:
    def _minimal_yaml(self, **overrides) -> dict:
        """Create a minimal valid agent definition dict."""
        data = {
            "id": "test_agent",
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent.",
            "mcps": {},
        }
        data.update(overrides)
        return data

    def test_parse_minimal_definition(self):
        data = self._minimal_yaml()
        defn = parse_definition(data)
        assert defn.id == "test_agent"
        assert defn.name == "Test Agent"
        assert defn.description == "A test agent"
        assert defn.system_prompt == "You are a test agent."

    def test_parse_full_definition(self):
        data = self._minimal_yaml(
            role="both",
            subagents=["builder", "tester"],
            done_variables={
                "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
                "confidence": {"type": "number", "required": False},
            },
            completion_preconditions=[{
                "summary_contains": "IMPLEMENTATION_COMPLETE",
                "required_tools": [{"tool_name": "write_file", "min_calls": 1}],
                "error_message": "Must call write_file",
            }],
            approval_overrides={
                "sandbox:push_changes": {"requires_approval": True, "required_role": "architect"},
            },
            skills=["code-review"],
            llm_profile="standard",
            temperature=0.7,
            max_tokens=8000,
            max_iterations=15,
        )
        defn = parse_definition(data)
        assert defn.role == "both"
        assert defn.subagents == ["builder", "tester"]
        assert "next_agent" in defn.done_variables
        assert len(defn.completion_preconditions) == 1
        assert "sandbox:push_changes" in defn.approval_overrides
        assert defn.skills == ["code-review"]
        assert defn.llm_profile == "standard"
        assert defn.temperature == 0.7

    def test_parse_role_primary(self):
        defn = parse_definition(self._minimal_yaml(role="primary"))
        assert defn.role == "primary"

    def test_parse_role_subagent(self):
        defn = parse_definition(self._minimal_yaml(role="subagent"))
        assert defn.role == "subagent"

    def test_parse_role_both(self):
        defn = parse_definition(self._minimal_yaml(role="both"))
        assert defn.role == "both"

    def test_parse_role_default(self):
        defn = parse_definition(self._minimal_yaml())
        assert defn.role == "primary"

    def test_parse_mcps_sandbox_with_tools_and_git(self):
        data = self._minimal_yaml(mcps={
            "sandbox": {"tools": ["read_file", "write_file"], "git": "current_project"},
        })
        defn = parse_definition(data)
        assert "sandbox" in defn.mcps
        assert defn.mcps["sandbox"]["tools"] == ["read_file", "write_file"]
        assert defn.mcps["sandbox"]["git"] == "current_project"
        assert defn.sandbox_git_scope == "current_project"

    def test_parse_mcps_core_tools_list(self):
        data = self._minimal_yaml(mcps={"core-tools": ["hitl_ask_question", "make_plan"]})
        defn = parse_definition(data)
        assert "core-tools" in defn.mcps
        assert defn.mcps["core-tools"]["tools"] == ["hitl_ask_question", "make_plan"]

    def test_parse_mcps_mixed(self):
        data = self._minimal_yaml(mcps={
            "sandbox": {"tools": ["read_file"], "git": "current_project"},
            "core-tools": ["hitl_ask_question"],
            "docker": ["build", "run"],
        })
        defn = parse_definition(data)
        assert "sandbox" in defn.mcps
        assert "core-tools" in defn.mcps
        assert "docker" in defn.mcps

    def test_parse_done_variables(self):
        data = self._minimal_yaml(done_variables={
            "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
        })
        defn = parse_definition(data)
        assert defn.done_variables is not None
        assert "next_agent" in defn.done_variables

    def test_parse_done_variables_empty(self):
        defn = parse_definition(self._minimal_yaml())
        assert defn.done_variables is None

    def test_parse_completion_preconditions(self):
        data = self._minimal_yaml(completion_preconditions=[{
            "summary_contains": "DESIGN_APPROVED",
            "unless_summary_contains": "EXCEPTION",
            "required_tools": [
                {"tool_name": "make_design", "min_calls": 1},
                {"tool_name": "push_changes", "min_calls": 2},
            ],
            "error_message": "Must create design first",
        }])
        defn = parse_definition(data)
        assert len(defn.completion_preconditions) == 1
        pre = defn.completion_preconditions[0]
        assert pre["summary_contains"] == "DESIGN_APPROVED"
        assert pre["unless_summary_contains"] == "EXCEPTION"
        assert len(pre["required_tools"]) == 2
        assert pre["error_message"] == "Must create design first"

    def test_parse_required_summary_status(self):
        data = self._minimal_yaml(required_summary_status={
            "one_of": ["STATUS_ONE", "STATUS_TWO"],
            "error_message": "Must contain a status",
        })
        defn = parse_definition(data)
        assert defn.required_summary_status is not None
        assert defn.required_summary_status["one_of"] == ["STATUS_ONE", "STATUS_TWO"]

    def test_parse_approval_overrides(self):
        data = self._minimal_yaml(approval_overrides={
            "sandbox:push_changes": {"requires_approval": True, "required_role": "architect"},
            "sandbox:make_design": {"requires_approval": False, "pre_validate": "validate_mermaid"},
        })
        defn = parse_definition(data)
        assert "sandbox:push_changes" in defn.approval_overrides
        assert defn.approval_overrides["sandbox:push_changes"]["requires_approval"] is True

    def test_parse_subagents_list(self):
        defn = parse_definition(self._minimal_yaml(subagents=["builder", "tester"]))
        assert defn.subagents == ["builder", "tester"]
        assert defn.has_subagents is True

    def test_parse_subagents_empty(self):
        defn = parse_definition(self._minimal_yaml())
        assert defn.subagents == []
        assert defn.has_subagents is False

    def test_parse_llm_settings(self):
        data = self._minimal_yaml(temperature=0.7, max_tokens=8000, max_iterations=15, llm_profile="fast")
        defn = parse_definition(data)
        assert defn.temperature == 0.7
        assert defn.max_tokens == 8000
        assert defn.max_iterations == 15
        assert defn.llm_profile == "fast"

    def test_parse_skills(self):
        defn = parse_definition(self._minimal_yaml(skills=["code-review", "git-workflow"]))
        assert defn.skills == ["code-review", "git-workflow"]

    def test_parse_system_prompts_list(self):
        defn = parse_definition(self._minimal_yaml(
            system_prompt=None,
            system_prompts=["tool_only_communication", "summary_relay"],
        ))
        assert defn.system_prompt is None
        assert defn.system_prompts == ["tool_only_communication", "summary_relay"]

    def test_parse_invalid_role(self):
        with pytest.raises(ValueError, match="Invalid role"):
            parse_definition(self._minimal_yaml(role="invalid"))

    def test_parse_missing_required_fields(self):
        for missing_field in ("id", "name", "description"):
            data = self._minimal_yaml()
            del data[missing_field]
            with pytest.raises(ValueError, match="Missing required field"):
                parse_definition(data)

    def test_parse_missing_system_prompt_and_prompts(self):
        data = self._minimal_yaml()
        del data["system_prompt"]
        with pytest.raises(ValueError, match="system_prompt"):
            parse_definition(data)

    def test_defaults(self):
        defn = parse_definition(self._minimal_yaml())
        assert defn.temperature == 0.1
        assert defn.max_tokens == 4096
        assert defn.max_iterations == 20
        assert defn.llm_profile == "default"
        assert defn.skills == []
        assert defn.subagents == []
        assert defn.completion_preconditions == []
        assert defn.required_summary_status is None


class TestLoadDefinition:
    def test_load_from_yaml_file(self, tmp_path):
        yaml_content = {
            "id": "loaded_agent",
            "name": "Loaded Agent",
            "description": "Loaded from file",
            "system_prompt": "You are loaded.",
            "mcps": {},
        }
        yaml_file = tmp_path / "loaded_agent.yaml"
        yaml_file.write_text(yaml.dump(yaml_content))

        defn = load_definition(yaml_file)
        assert defn.id == "loaded_agent"

    def test_load_from_yaml_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_definition("/nonexistent/path.yaml")


class TestBuildDoneSchema:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {
            "id": "test",
            "name": "Test",
            "description": "Test",
            "system_prompt": "test",
        }
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_build_done_schema_no_variables(self):
        defn = self._defn(done_variables=None)
        schema = build_done_schema(defn)
        assert schema["name"] == "done"
        assert "summary" in schema["inputSchema"]["properties"]
        assert schema["inputSchema"]["required"] == ["summary"]

    def test_build_done_schema_with_variables(self):
        defn = self._defn(done_variables={
            "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
            "confidence": {"type": "number", "required": False},
        })
        schema = build_done_schema(defn)
        props = schema["inputSchema"]["properties"]
        assert "summary" in props
        assert "next_agent" in props
        assert "confidence" in props
        required = schema["inputSchema"]["required"]
        assert "summary" in required
        assert "next_agent" in required
        assert "confidence" not in required

    def test_build_done_schema_summary_always_required(self):
        defn = self._defn(done_variables={
            "optional_var": {"type": "string", "required": False},
        })
        schema = build_done_schema(defn)
        assert "summary" in schema["inputSchema"]["required"]

    def test_build_done_schema_enum_restriction(self):
        defn = self._defn(done_variables={
            "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
        })
        schema = build_done_schema(defn)
        next_agent_schema = schema["inputSchema"]["properties"]["next_agent"]
        assert next_agent_schema["enum"] == ["architect", "developer"]

    def test_build_done_schema_type_preservation(self):
        defn = self._defn(done_variables={
            "name": {"type": "string", "required": True},
            "count": {"type": "number", "required": True},
            "flag": {"type": "boolean", "required": False},
        })
        schema = build_done_schema(defn)
        props = schema["inputSchema"]["properties"]
        assert props["name"]["type"] == "string"
        assert props["count"]["type"] == "number"
        assert props["flag"]["type"] == "boolean"


class TestAgentDefinitionProperties:
    def _defn(self, **kwargs) -> AgentDefinition:
        defaults = {
            "id": "test",
            "name": "Test",
            "description": "Test",
            "system_prompt": "test",
        }
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_allowed_mcp_tools(self):
        defn = self._defn(mcps={
            "sandbox": {"tools": ["read_file", "write_file"], "git": "current_project"},
            "core-tools": {"tools": ["hitl_ask_question"]},
        })
        tools = defn.allowed_mcp_tools
        assert tools["sandbox"] == ["read_file", "write_file"]
        assert tools["core-tools"] == ["hitl_ask_question"]

    def test_sandbox_git_scope_with_sandbox(self):
        defn = self._defn(mcps={"sandbox": {"tools": ["read_file"], "git": "current_project"}})
        assert defn.sandbox_git_scope == "current_project"

    def test_sandbox_git_scope_without_sandbox(self):
        defn = self._defn(mcps={"core-tools": {"tools": ["make_plan"]}})
        assert defn.sandbox_git_scope is None

    def test_sandbox_git_scope_empty_mcps(self):
        defn = self._defn(mcps={})
        assert defn.sandbox_git_scope is None
