"""Schema validation tests for the Foundry MCP.

Runs against `validate_yaml_content` — the single entry point used by
both the `validate_agent_yaml` MCP tool and the first stage of
`deploy_agent`. These tests are pure Pydantic/YAML, no Azure SDK needed.
"""

from __future__ import annotations

from v1.schema import validate_yaml_content


MINIMUM_VALID = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful agent. Always be concise.
"""


def _err_codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


def _err_fields(result: dict) -> set[str]:
    return {e["field"] for e in result["errors"]}


def test_minimum_valid_yaml():
    r = validate_yaml_content(MINIMUM_VALID)
    assert r["valid"] is True
    assert r["errors"] == []
    assert r["normalized"]["name"] == "my-agent"
    assert r["normalized"]["model"] == "gpt-4o-mini"


def test_empty_document():
    r = validate_yaml_content("")
    assert r["valid"] is False
    assert "empty_document" in _err_codes(r)


def test_malformed_yaml():
    r = validate_yaml_content("name: [unclosed")
    assert r["valid"] is False
    assert "yaml_parse_error" in _err_codes(r)


def test_top_level_not_mapping():
    r = validate_yaml_content("- just\n- a\n- list")
    assert r["valid"] is False
    assert "bad_top_level" in _err_codes(r)


def test_unknown_top_level_key_rejected():
    r = validate_yaml_content(MINIMUM_VALID + "\nnot_a_field: oops\n")
    assert r["valid"] is False
    # Pydantic's extra=forbid surfaces as an "extra_forbidden" code
    assert any("not_a_field" in f for f in _err_fields(r))


def test_missing_name():
    r = validate_yaml_content(
        "model: gpt-4o-mini\ninstructions: You are helpful and useful.\n"
    )
    assert r["valid"] is False
    assert any(f == "name" for f in _err_fields(r))


def test_missing_model():
    r = validate_yaml_content("name: my-agent\ninstructions: Be helpful.\n")
    assert r["valid"] is False
    assert any(f == "model" for f in _err_fields(r))


def test_missing_instructions():
    r = validate_yaml_content("name: my-agent\nmodel: gpt-4o-mini\n")
    assert r["valid"] is False
    assert any(f == "instructions" for f in _err_fields(r))


def test_blank_instructions_rejected():
    r = validate_yaml_content(
        "name: my-agent\nmodel: gpt-4o-mini\ninstructions: '   '\n"
    )
    assert r["valid"] is False
    assert any(f == "instructions" for f in _err_fields(r))


def test_invalid_name_regex():
    r = validate_yaml_content(
        "name: 'has spaces!'\nmodel: gpt-4o-mini\ninstructions: Be helpful.\n"
    )
    assert r["valid"] is False
    assert any(f == "name" for f in _err_fields(r))


def test_bing_grounding_requires_connection_id():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: Be helpful.
tools:
  - type: bing_grounding
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "missing_connection_id" in _err_codes(r)


def test_bing_grounding_with_connection_id_passes():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: bing_grounding
    connection_id: /subscriptions/x/connections/bing
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True, r["errors"]


def test_code_interpreter_needs_no_connection_id():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: code_interpreter
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True, r["errors"]


def test_file_search_without_tool_resources_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: file_search
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "missing_vector_store_ids" in _err_codes(r)


def test_file_search_with_empty_vector_store_ids_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: file_search
tool_resources:
  file_search:
    vector_store_ids: []
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "missing_vector_store_ids" in _err_codes(r)


def test_file_search_with_non_string_ids_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: file_search
tool_resources:
  file_search:
    vector_store_ids:
      - 123
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "missing_vector_store_ids" in _err_codes(r)


def test_sharepoint_grounding_requires_connection_id():
    yaml_txt = """
name: sp-agent
model: gpt-4o-mini
instructions: You are a helpful SharePoint-grounded agent.
tools:
  - type: sharepoint_grounding
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "missing_connection_id" in _err_codes(r)


def test_sharepoint_grounding_with_connection_id_passes():
    yaml_txt = """
name: sp-agent
model: gpt-4o-mini
instructions: You are a helpful SharePoint-grounded agent.
tools:
  - type: sharepoint_grounding
    connection_id: /subscriptions/x/connections/sharepoint-drive
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True, r["errors"]


def test_file_search_with_vector_store_ids_passes():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: file_search
tool_resources:
  file_search:
    vector_store_ids:
      - vs_abc123
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True, r["errors"]


def test_connection_id_on_zero_config_tool_warns():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: code_interpreter
    connection_id: /bogus
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True
    assert any(w["field"].startswith("tools.0") for w in r["warnings"])


def test_duplicate_tool_types_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: You are a helpful Foundry agent.
tools:
  - type: code_interpreter
  - type: code_interpreter
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "duplicate_tool" in _err_codes(r)


def test_unknown_tool_type_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: Be helpful.
tools:
  - type: nonexistent_tool
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert any(f.startswith("tools.0") for f in _err_fields(r))


def test_temperature_out_of_range():
    r = validate_yaml_content(MINIMUM_VALID + "\ntemperature: 3.5\n")
    assert r["valid"] is False
    assert any(f == "temperature" for f in _err_fields(r))


def test_top_p_out_of_range():
    r = validate_yaml_content(MINIMUM_VALID + "\ntop_p: 1.5\n")
    assert r["valid"] is False
    assert any(f == "top_p" for f in _err_fields(r))


def test_invalid_response_format():
    r = validate_yaml_content(MINIMUM_VALID + "\nresponse_format: xml\n")
    assert r["valid"] is False
    assert any(f == "response_format" for f in _err_fields(r))


def test_metadata_too_many_entries():
    entries = "\n".join(f"  k{i}: v{i}" for i in range(17))
    yaml_txt = MINIMUM_VALID + "\nmetadata:\n" + entries + "\n"
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "metadata_too_many" in _err_codes(r)


def test_metadata_value_too_long():
    long_val = "x" * 513
    yaml_txt = MINIMUM_VALID + f"\nmetadata:\n  key: '{long_val}'\n"
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert "metadata_value_too_long" in _err_codes(r)


def test_extra_key_inside_tool_rejected():
    yaml_txt = """
name: my-agent
model: gpt-4o-mini
instructions: Be helpful.
tools:
  - type: code_interpreter
    unknown_field: boom
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is False
    assert any("unknown_field" in f for f in _err_fields(r))


def test_full_valid_with_all_tool_types():
    yaml_txt = """
name: full-agent
description: Kitchen sink
model: gpt-4o-mini
instructions: |
  You are a comprehensive agent. You help users by using all of the
  tools at your disposal appropriately. Be helpful and concise.
tools:
  - type: code_interpreter
  - type: file_search
  - type: bing_grounding
    connection_id: /subscriptions/x/connections/bing
  - type: bing_custom_search
    connection_id: /subscriptions/x/connections/bing-custom
  - type: azure_ai_search
    connection_id: /subscriptions/x/connections/search
  - type: microsoft_fabric
    connection_id: /subscriptions/x/connections/fabric
  - type: browser_automation
  - type: deep_research
tool_resources:
  file_search:
    vector_store_ids:
      - vs_abc123
metadata:
  druppie_project_id: proj-123
  druppie_version: "1"
temperature: 0.2
top_p: 0.9
response_format: auto
"""
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True, r["errors"]
    assert len(r["normalized"]["tools"]) == 8


def test_short_instructions_warns_but_valid():
    yaml_txt = "name: a\nmodel: gpt-4o-mini\ninstructions: short prompt\n"
    r = validate_yaml_content(yaml_txt)
    assert r["valid"] is True
    assert any(w["field"] == "instructions" for w in r["warnings"])
