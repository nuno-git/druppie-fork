"""ArchiMate v1 — Write MCP Tool Definitions.

Tools that mutate per-project ``architecture.archimate`` files in
session workspaces. Read-only WILMA tools live in ``tools.py``.

All tools take an injected ``session_id`` (declared in
``core/mcp_config.yaml``) and a ``model_path`` relative to the session
workspace root (default ``docs/architecture.archimate``). Mutations
buffer in memory; ``save_model`` writes to disk.
"""

import logging
from typing import Any

from .svg_export import export_all_views
from .writer import (
    ELEMENT_TYPE_LAYER,
    VALID_RELATIONSHIP_TYPES,
    ArchiMateWriteError,
    get_registry,
    view_summary,
)

logger = logging.getLogger("archimate-write-tools")

DEFAULT_MODEL_PATH = "docs/architecture.archimate"


def _registry():
    return get_registry()


def _result(payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = {"success": True, **payload}
    out.update(extra)
    return out


def _error(message: str) -> dict[str, Any]:
    return {"success": False, "error": message}


def register_write_tools(mcp, *, module_id: str, module_version: str) -> None:
    """Attach all write tools to the given FastMCP instance."""

    meta = {"module_id": module_id, "version": module_version}

    # --- Elements ---

    @mcp.tool(
        name="create_element",
        description=(
            "Create a new ArchiMate element in the project model. "
            "Returns the element identifier. Buffered: call save_model "
            "to persist. Supported element types in v1: see element_type_layer."
        ),
        meta=meta,
    )
    async def create_element(
        session_id: str,
        element_type: str,
        name: str,
        documentation: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            ident = doc.create_element(
                element_type=element_type,
                name=name,
                documentation=documentation,
            )
            return _result({"element_id": ident, "layer": ELEMENT_TYPE_LAYER[element_type]})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="update_element",
        description=(
            "Update name and/or documentation of an existing element. "
            "Pass an empty string to clear documentation. Approval-gated."
        ),
        meta=meta,
    )
    async def update_element(
        session_id: str,
        element_id: str,
        name: str = "",
        documentation: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            kwargs: dict[str, Any] = {}
            if name:
                kwargs["name"] = name
            if documentation or documentation == "":
                # explicit empty string clears doc; None means "don't touch".
                # Since MCP tool params can't be None, we treat empty as "no-op"
                # only if name was also given without documentation. This mirrors
                # the LLM ergonomic of "only pass what you want to change".
                if documentation:
                    kwargs["documentation"] = documentation
            if not kwargs:
                return _error("Provide at least one of: name, documentation")
            doc.update_element(element_id, **kwargs)
            return _result({"element_id": element_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="delete_element",
        description=(
            "Delete an element and cascade: remove all relationships involving "
            "it and remove it from any views. Approval-gated."
        ),
        meta=meta,
    )
    async def delete_element(
        session_id: str,
        element_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            cascade = doc.delete_element(element_id)
            return _result({"element_id": element_id, **cascade})
        except ArchiMateWriteError as e:
            return _error(str(e))

    # --- Relationships ---

    @mcp.tool(
        name="create_relationship",
        description=(
            "Create a relationship between two existing elements. "
            "Valid relationship types: Composition, Aggregation, Assignment, "
            "Realization, Serving, Access, Triggering, Flow, Influence, "
            "Specialization, Association. For Access relationships, optionally "
            "specify access_type (Read, Write, ReadWrite, Access)."
        ),
        meta=meta,
    )
    async def create_relationship(
        session_id: str,
        relationship_type: str,
        source_id: str,
        target_id: str,
        name: str = "",
        access_type: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            ident = doc.create_relationship(
                relationship_type=relationship_type,
                source_id=source_id,
                target_id=target_id,
                name=name,
                access_type=access_type or None,
            )
            return _result({"relationship_id": ident})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="update_relationship",
        description="Update name or access_type on a relationship. Approval-gated.",
        meta=meta,
    )
    async def update_relationship(
        session_id: str,
        relationship_id: str,
        name: str = "",
        access_type: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            kwargs: dict[str, Any] = {}
            if name:
                kwargs["name"] = name
            if access_type:
                kwargs["access_type"] = access_type
            if not kwargs:
                return _error("Provide at least one of: name, access_type")
            doc.update_relationship(relationship_id, **kwargs)
            return _result({"relationship_id": relationship_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="delete_relationship",
        description=(
            "Delete a relationship and remove its connections from any views. "
            "Approval-gated."
        ),
        meta=meta,
    )
    async def delete_relationship(
        session_id: str,
        relationship_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            doc.delete_relationship(relationship_id)
            return _result({"relationship_id": relationship_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    # --- Views ---

    @mcp.tool(
        name="create_view",
        description=(
            "Create a new empty view (diagram) in the project model. "
            "Use add_to_view and add_connection_to_view to populate it."
        ),
        meta=meta,
    )
    async def create_view(
        session_id: str,
        name: str,
        documentation: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            ident = doc.create_view(name=name, documentation=documentation)
            return _result({"view_id": ident})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="delete_view",
        description="Delete an entire view. Approval-gated.",
        meta=meta,
    )
    async def delete_view(
        session_id: str,
        view_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            doc.delete_view(view_id)
            return _result({"view_id": view_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="add_to_view",
        description=(
            "Place an element on a view. If x/y are omitted, a free position "
            "is chosen to the right/below the existing layout (incremental "
            "layout: existing positions are preserved). Returns the node id."
        ),
        meta=meta,
    )
    async def add_to_view(
        session_id: str,
        view_id: str,
        element_id: str,
        x: int = -1,
        y: int = -1,
        w: int = -1,
        h: int = -1,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            node_id = doc.add_to_view(
                view_id,
                element_id,
                x=x if x >= 0 else None,
                y=y if y >= 0 else None,
                w=w if w > 0 else None,
                h=h if h > 0 else None,
            )
            return _result({"node_id": node_id, "view_id": view_id, "element_id": element_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="add_connection_to_view",
        description=(
            "Add a visual connection on a view for an existing relationship. "
            "Both endpoint elements must already be on the view."
        ),
        meta=meta,
    )
    async def add_connection_to_view(
        session_id: str,
        view_id: str,
        relationship_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            conn_id = doc.add_connection_to_view(view_id, relationship_id)
            return _result({"connection_id": conn_id, "view_id": view_id, "relationship_id": relationship_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="remove_from_view",
        description="Remove an element (and its connections) from a view. Approval-gated.",
        meta=meta,
    )
    async def remove_from_view(
        session_id: str,
        view_id: str,
        element_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            doc.remove_from_view(view_id, element_id)
            return _result({"view_id": view_id, "element_id": element_id})
        except ArchiMateWriteError as e:
            return _error(str(e))

    # --- WILMA references ---

    @mcp.tool(
        name="get_or_create_wilma_reference",
        description=(
            "Import a WILMA reference element into the project model, preserving "
            "its identifier so the reference stays traceable. Idempotent: returns "
            "the existing element_id if already imported. The element is marked "
            "with property 'wilma-source=true' and must not be mutated locally."
        ),
        meta=meta,
    )
    async def get_or_create_wilma_reference(
        session_id: str,
        wilma_element_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            registry = _registry()
            doc = registry.get(session_id, model_path)
            wilma = registry.wilma()
            ident = doc.copy_element_from(wilma, wilma_element_id)
            return _result({"element_id": ident, "wilma_source": True})
        except ArchiMateWriteError as e:
            return _error(str(e))

    # --- Persistence + relayout ---

    @mcp.tool(
        name="save_model",
        description=(
            "Persist all buffered changes to disk. Approval-gated. "
            "Returns the absolute path of the written file. After save, "
            "use coding.run_git to commit + push to Gitea."
        ),
        meta=meta,
    )
    async def save_model(
        session_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            if not doc.dirty:
                return _result({"path": str(doc.path), "written": False, "reason": "no_changes"})
            path = doc.save()
            # Also export an SVG per positioned view to docs/diagrams/
            # so the plates are visible directly in Gitea's file preview
            # (Gitea renders SVG inline, ArchiMate XML it doesn't).
            diagrams_dir = path.parent / "diagrams"
            svg_paths: list[str] = []
            try:
                svg_paths = [str(p) for p in export_all_views(doc.root, diagrams_dir)]
            except Exception as exc:  # noqa: BLE001 — never block save on SVG export
                logger.warning("SVG export failed for %s: %s", path, exc)
            return _result(
                {"path": str(path), "written": True, "svg_exports": svg_paths}
            )
        except ArchiMateWriteError as e:
            return _error(str(e))

    @mcp.tool(
        name="request_full_relayout",
        description=(
            "Request a complete re-layout of a view. Resets all node positions "
            "and lets auto-layout compute fresh coordinates. Approval-gated — "
            "this destroys any manual position tweaks the architect made."
        ),
        meta=meta,
    )
    async def request_full_relayout(
        session_id: str,
        view_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            view = doc.find_view(view_id)
            if view is None:
                return _error(f"View '{view_id}' not found")
            # Clear positions so client-side auto-layout will recompute.
            # We don't compute layout here — the frontend's elkjs pass does
            # that on render. We only clear the x/y so existing positions
            # are no longer "fixed".
            for node in view.findall("am:node", _ns()):
                node.set("x", "0")
                node.set("y", "0")
            doc.dirty = True
            return _result(view_summary(doc, view), relayout_requested=True)
        except ArchiMateWriteError as e:
            return _error(str(e))

    # --- Introspection ---

    @mcp.tool(
        name="assess_layout",
        description=(
            "Report layout health metrics for a view: element count, "
            "connection count, density. Helps the agent decide whether to "
            "recommend request_full_relayout to the architect."
        ),
        meta=meta,
    )
    async def assess_layout(
        session_id: str,
        view_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            view = doc.find_view(view_id)
            if view is None:
                return _error(f"View '{view_id}' not found")
            summary = view_summary(doc, view)
            element_count = summary["element_count"]
            density = (
                summary["connection_count"] / element_count
                if element_count
                else 0.0
            )
            summary["density"] = round(density, 2)
            summary["recommendation"] = (
                "consider_relayout"
                if element_count > 30 or density > 1.5
                else "ok"
            )
            return _result(summary)
        except ArchiMateWriteError as e:
            return _error(str(e))


def _ns() -> dict[str, str]:
    """Return the ArchiMate namespace mapping for ElementTree queries."""
    return {"am": "http://www.opengroup.org/xsd/archimate/3.0/"}
