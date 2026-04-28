"""Foundry v1 — MCP tool definitions.

Exposes three tools to agents:
  - validate_agent_yaml: offline, strict Pydantic validation of a YAML
    blob (no network, no LLM).
  - list_foundry_tools: live query of the configured Azure AI Foundry
    project — enumerates tool connections and deployed models so the
    caller can confirm a requested tool is actually deployable.
  - deploy_agent: validate → cross-check → create_agent. Guarded by
    approval in mcp_config.yaml.

All tools return structured `{ok: bool, ...}` dicts and never raise to
the LLM — failure modes surface as readable reasons the agent can
relay back to the user.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastmcp import FastMCP

from .foundry_client import FoundryClient
from .schema import (
    ALLOWED_TOOL_TYPES,
    CONNECTION_REQUIRED,
    validate_yaml_content,
)

logger = logging.getLogger("foundry-mcp")

MODULE_ID = "foundry"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Foundry v1",
    version=MODULE_VERSION,
    instructions=(
        "Deploy Azure AI Foundry agents from a YAML definition. "
        "Always call validate_agent_yaml first, then list_foundry_tools "
        "to confirm availability, then deploy_agent."
    ),
)


def _client() -> FoundryClient:
    """New client per call — they're cheap and this avoids stale state
    across env var reloads in dev."""
    return FoundryClient(endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT"))


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def validate_agent_yaml(yaml_content: str) -> dict:
    """Strict, non-LLM schema validation of a Foundry agent YAML.

    Checks: YAML parseable, top-level mapping, all required fields,
    field types/ranges, name regex, instruction length cap, metadata
    limits, unknown keys rejected, duplicate tool types rejected, and
    connection_id required for bing_grounding/bing_custom_search/
    azure_ai_search/microsoft_fabric.

    Args:
        yaml_content: The full YAML document as a string.

    Returns:
        {
            "ok": bool,                # alias of "valid" for consistent shape
            "valid": bool,
            "errors": [{field, message, code}, ...],
            "warnings": [{field, message}, ...],
            "normalized": dict | None,  # parsed+coerced data when valid
        }
    """
    result = validate_yaml_content(yaml_content)
    return {
        "ok": result["valid"],
        "valid": result["valid"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "normalized": result["normalized"],
    }


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def list_foundry_tools() -> dict:
    """Live-query the configured Foundry project for available tools.

    Zero-config tools (code_interpreter, file_search) are always
    reported as available. Connection-backed tools are reported with
    the actual connections found in the project — empty list means the
    tool cannot currently be deployed. Deployed models are included so
    the caller can confirm the `model` field in their YAML exists.

    Returns:
        {
            "ok": bool,
            "endpoint": str | None,
            "checked_at": iso8601 str,
            "always_available": ["code_interpreter", "file_search"],
            "connection_backed": [
                {type, available: bool, connections: [{id, name, type}]}, ...
            ],
            "deployed_models": [{name, model}, ...],
            "reason": str,  # present when ok is false
        }
    """
    client = _client()
    checked_at = datetime.now(timezone.utc).isoformat()

    conn_result = client.list_connections()
    if not conn_result.get("ok"):
        return {
            "ok": False,
            "endpoint": client.endpoint,
            "checked_at": checked_at,
            "reason": conn_result.get("reason", "unknown"),
            "code": conn_result.get("code", "error"),
            "always_available": sorted(ALLOWED_TOOL_TYPES - CONNECTION_REQUIRED),
            "connection_backed": [],
            "deployed_models": [],
        }

    by_type = conn_result.get("by_tool_type", {})
    connection_backed = []
    for tool_type in sorted(CONNECTION_REQUIRED):
        conns = by_type.get(tool_type, [])
        connection_backed.append(
            {
                "type": tool_type,
                "available": bool(conns),
                "connections": [
                    {"id": c["id"], "name": c["name"], "type": c["type"]}
                    for c in conns
                ],
            }
        )

    models_result = client.list_deployed_models()
    deployed_models = models_result.get("models", []) if models_result.get("ok") else []

    out = {
        "ok": True,
        "endpoint": client.endpoint,
        "checked_at": checked_at,
        "always_available": sorted(ALLOWED_TOOL_TYPES - CONNECTION_REQUIRED),
        "connection_backed": connection_backed,
        "deployed_models": deployed_models,
    }
    if not models_result.get("ok"):
        out["deployed_models_warning"] = models_result.get(
            "reason", "could not enumerate deployed models"
        )
    return out


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def deploy_agent(yaml_content: str, dry_run: bool = False) -> dict:
    """Validate, cross-check availability, then deploy to Foundry.

    Pipeline:
      1. validate_agent_yaml — abort on schema errors.
      2. list_foundry_tools — every requested tool must be deployable;
         every requested connection_id must match a real connection;
         the requested model must match a deployed model (when the SDK
         exposes them; otherwise skipped with a warning).
      3. If dry_run: return the validated plan without deploying.
      4. create_agent via the Azure SDK.

    Args:
        yaml_content: The YAML document to deploy.
        dry_run: When true, perform validation + availability checks
            and return the planned deployment without calling Azure.

    Returns:
        {
            "ok": bool,
            "stage": "validate" | "availability" | "deploy",
            "errors": [...],       # when ok is false
            "warnings": [...],
            "deployment": {foundry_agent_id, name, model, deployed_at},
                                   # when ok is true and not dry_run
            "plan": {...},         # when dry_run
        }
    """
    # Stage 1 — schema
    v = validate_yaml_content(yaml_content)
    if not v["valid"]:
        return {
            "ok": False,
            "stage": "validate",
            "errors": v["errors"],
            "warnings": v["warnings"],
        }
    normalized = v["normalized"]
    warnings = list(v["warnings"])

    # Stage 2 — availability
    client = _client()
    conn_result = client.list_connections()
    if not conn_result.get("ok"):
        return {
            "ok": False,
            "stage": "availability",
            "errors": [
                {
                    "field": "<foundry>",
                    "message": conn_result.get("reason", "connection check failed"),
                    "code": conn_result.get("code", "azure_error"),
                }
            ],
            "warnings": warnings,
        }
    by_type = conn_result.get("by_tool_type", {})

    avail_errors: list[dict] = []
    for idx, tool in enumerate(normalized.get("tools", [])):
        ttype = tool["type"]
        cid = tool.get("connection_id")
        if ttype in CONNECTION_REQUIRED:
            candidates = by_type.get(ttype, [])
            if not candidates:
                avail_errors.append(
                    {
                        "field": f"tools.{idx}",
                        "message": (
                            f"tool '{ttype}' is not available in project — "
                            "no matching connection configured"
                        ),
                        "code": "tool_unavailable",
                    }
                )
                continue
            if cid and not any(c["id"] == cid or c["name"] == cid for c in candidates):
                avail_errors.append(
                    {
                        "field": f"tools.{idx}.connection_id",
                        "message": (
                            f"connection_id '{cid}' does not match any "
                            f"'{ttype}' connection in the project"
                        ),
                        "code": "connection_not_found",
                    }
                )

    # Cross-check the model against deployed models (soft when SDK can't list)
    models_result = client.list_deployed_models()
    if models_result.get("ok"):
        known = {m["name"] for m in models_result.get("models", []) if m.get("name")}
        if known and normalized["model"] not in known:
            avail_errors.append(
                {
                    "field": "model",
                    "message": (
                        f"model '{normalized['model']}' is not a deployed "
                        f"model in this project (known: {sorted(known)})"
                    ),
                    "code": "model_not_deployed",
                }
            )
    else:
        warnings.append(
            {
                "field": "model",
                "message": (
                    "could not enumerate deployed models — skipping model "
                    f"availability check ({models_result.get('reason', 'unknown')})"
                ),
            }
        )

    if avail_errors:
        return {
            "ok": False,
            "stage": "availability",
            "errors": avail_errors,
            "warnings": warnings,
        }

    # Dry-run stops here
    if dry_run:
        return {
            "ok": True,
            "stage": "availability",
            "dry_run": True,
            "warnings": warnings,
            "plan": {
                "name": normalized["name"],
                "model": normalized["model"],
                "tools": [t["type"] for t in normalized.get("tools", [])],
            },
        }

    # Stage 3 — deploy
    deploy_result = client.create_agent(normalized)
    if not deploy_result.get("ok"):
        return {
            "ok": False,
            "stage": "deploy",
            "errors": [
                {
                    "field": "<foundry>",
                    "message": deploy_result.get("reason", "deploy failed"),
                    "code": deploy_result.get("code", "deploy_failed"),
                }
            ],
            "warnings": warnings,
        }

    if deploy_result.get("skipped_tools"):
        warnings.append(
            {
                "field": "tools",
                "message": (
                    f"these tool types were skipped (not supported by current SDK): "
                    f"{deploy_result['skipped_tools']}"
                ),
            }
        )

    return {
        "ok": True,
        "stage": "deploy",
        "warnings": warnings,
        "deployment": {
            "foundry_agent_id": deploy_result.get("foundry_agent_id"),
            "name": deploy_result.get("name"),
            "version": deploy_result.get("version"),
            "model": deploy_result.get("model"),
            "deployed_at": deploy_result.get("deployed_at"),
        },
    }
