"""Verify that every ArchiMate write-tool is approval-gated on the architect role.

Covers AC5 from the Archimate-end-to-end user story:
    "Approval-gates: delete_element, update_element en save_model
     weigeren zonder goedkeuring volgens mcp_config.yaml."

Test is intentionally static — it parses the YAML config and inspects
the declared gates, which is exactly what the runtime approval system
uses to decide whether to pause for HITL. No transport round-trip
needed.

Run with:
    python druppie/mcp-servers/module-archimate/tests/test_approval_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = REPO_ROOT / "druppie" / "core" / "mcp_config.yaml"

# Tools that mutate the project model — must all be approval-gated.
WRITE_TOOLS = {
    "create_element",
    "update_element",
    "delete_element",
    "create_relationship",
    "update_relationship",
    "delete_relationship",
    "create_view",
    "delete_view",
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

    # All write tools must be approval-gated on the architect role
    for name in sorted(WRITE_TOOLS):
        tool = tools.get(name)
        if not tool:
            failures.append(f"missing write tool: {name}")
            continue
        if not tool.get("requires_approval"):
            failures.append(f"{name} is a write tool but requires_approval is not true")
        if tool.get("required_role") != "architect":
            failures.append(
                f"{name} is gated but required_role is "
                f"{tool.get('required_role')!r} (expected 'architect')"
            )

    # All read tools must be ungated (would otherwise trip the agent's
    # information-gathering loop unnecessarily)
    for name in sorted(READ_TOOLS):
        tool = tools.get(name)
        if not tool:
            failures.append(f"missing read tool: {name}")
            continue
        if tool.get("requires_approval"):
            failures.append(f"{name} is a read tool but is approval-gated")

    # All write tools must be in the session_id injection list so the MCP
    # can resolve the per-project workspace
    inject = archimate_cfg.get("inject", {})
    session_inject = inject.get("session_id", {})
    inject_tools = set(session_inject.get("tools", []))
    missing_inject = WRITE_TOOLS - inject_tools
    # assess_layout also needs session_id (reads the project model)
    if "assess_layout" not in inject_tools:
        missing_inject.add("assess_layout")
    if missing_inject:
        failures.append(
            "session_id injection missing for: " + ", ".join(sorted(missing_inject))
        )

    if failures:
        print("FAIL — config gaps:")
        for f in failures:
            print(f"    - {f}")
        return 1

    print(f"OK — {len(WRITE_TOOLS)} write tools gated on architect, "
          f"{len(READ_TOOLS)} read tools ungated")
    print(f"OK — session_id injected for all write tools + assess_layout")
    print("=" * 50)
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
