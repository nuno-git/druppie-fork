"""Verify the ArchiMate write-tool approval-gating contract.

The architect builds up the ArchiMate plate freely through the
archimate MCP write tools — none of them are individually
approval-gated. The single architect-approval point is the
``coding:submit_design_for_review`` call on ``docs/technical-design.md`` (gated
via the architect agent's ``approval_overrides``). At that moment the
reviewer sees the markdown + the embedded plate as one artifact and
approves the TD as a whole. Approving each MCP call separately is
meaningless because the reviewer cannot visualise individual
mutations.

This test pins both halves of that contract:
  1. ALL archimate write tools are ungated in mcp_config.yaml.
  2. ALL read tools stay ungated.
  3. session_id is injected for every write tool + assess_layout.
  4. The architect agent overrides coding:submit_design_for_review to
     requires_approval=true with required_role=architect.

Run with:
    python druppie/mcp-servers/module-archimate/tests/test_approval_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = REPO_ROOT / "druppie" / "core" / "mcp_config.yaml"
ARCHITECT_YAML = REPO_ROOT / "druppie" / "agents" / "definitions" / "architect.yaml"

# Tools that mutate the project model — must all be UNGATED (the TD
# review handles approval of the resulting plate).
WRITE_TOOLS = {
    "create_element",
    "update_element",
    "delete_element",
    "create_relationship",
    "update_relationship",
    "delete_relationship",
    "add_to_view",
    "add_connection_to_view",
    "remove_from_view",
    "get_or_create_wilma_reference",
    "save_model",
    "request_full_relayout",
}

# Tools that are read-only on either WILMA or the project model.
READ_TOOLS = {
    "list_models",
    "get_statistics",
    "list_elements",
    "get_element",
    "list_views",
    "get_view",
    "search_model",
    "get_impact",
    "assess_layout",
}


def main() -> int:
    print("ArchiMate approval-gate config validation")
    print("=" * 50)

    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)

    archimate_cfg = config.get("mcps", {}).get("archimate")
    if not archimate_cfg:
        print("FAIL — no 'archimate' MCP entry in mcp_config.yaml")
        return 1

    tools = {t["name"]: t for t in archimate_cfg.get("tools", [])}
    failures: list[str] = []

    # Write tools must NOT be individually approval-gated.
    for name in sorted(WRITE_TOOLS):
        tool = tools.get(name)
        if not tool:
            failures.append(f"missing write tool: {name}")
            continue
        if tool.get("requires_approval"):
            failures.append(
                f"{name} is approval-gated; archimate write tools must be ungated "
                f"(approval lives on coding:submit_design_for_review for the TD instead)"
            )

    # Read tools must also stay ungated.
    for name in sorted(READ_TOOLS):
        tool = tools.get(name)
        if not tool:
            failures.append(f"missing read tool: {name}")
            continue
        if tool.get("requires_approval"):
            failures.append(f"{name} is a read tool but is approval-gated")

    # session_id must be injected for every write tool (resolves workspace).
    inject = archimate_cfg.get("inject", {})
    session_inject = inject.get("session_id", {})
    inject_tools = set(session_inject.get("tools", []))
    missing_inject = WRITE_TOOLS - inject_tools
    if "assess_layout" not in inject_tools:
        missing_inject.add("assess_layout")
    if missing_inject:
        failures.append(
            "session_id injection missing for: " + ", ".join(sorted(missing_inject))
        )

    # The architect agent must gate coding:submit_design_for_review.
    with ARCHITECT_YAML.open() as f:
        architect = yaml.safe_load(f)
    override = architect.get("approval_overrides", {}).get("coding:submit_design_for_review", {})
    if not override.get("requires_approval"):
        failures.append("architect.yaml: coding:submit_design_for_review override must set requires_approval=true")
    if override.get("required_role") != "architect":
        failures.append(
            "architect.yaml: coding:submit_design_for_review required_role must be 'architect', "
            f"got {override.get('required_role')!r}"
        )

    if failures:
        print("FAIL — config gaps:")
        for f in failures:
            print(f"    - {f}")
        return 1

    print(f"OK — {len(WRITE_TOOLS)} archimate write tools are ungated")
    print(f"OK — {len(READ_TOOLS)} archimate read tools are ungated")
    print(f"OK — session_id injected for all write tools + assess_layout")
    print(f"OK — architect agent gates coding:submit_design_for_review (the TD-review point)")
    print("=" * 50)
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
