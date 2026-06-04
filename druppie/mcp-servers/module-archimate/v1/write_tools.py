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
    RIJNLAND_CONCEPTS,
    RIJNLAND_TRUST_LEVELS,
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
            "to persist. Supported element types in v1: see element_type_layer.\n\n"
            "For waterschap/Rijnland plates, pass a `stereotype` to pin the "
            "element to a tekenafspraken concept (e.g. stereotype='Account' on "
            "a BusinessRole, 'Applicatie als service' on an ApplicationService, "
            "'Beveiligingsdomein' on a Grouping). The stereotype must match the "
            "ArchiMate type the tekenafspraken prescribe, or creation is "
            "rejected. It renders as a «stereotype» label above the name."
        ),
        meta=meta,
    )
    async def create_element(
        session_id: str,
        element_type: str,
        name: str,
        documentation: str = "",
        stereotype: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path)
            ident = doc.create_element(
                element_type=element_type,
                name=name,
                documentation=documentation,
                stereotype=stereotype,
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

    # --- Composite viewpoint builders ---

    @mcp.tool(
        name="add_layered_view",
        description=(
            "Build a complete Layered viewpoint in one call: creates the "
            "view, the listed elements grouped by ArchiMate layer, and the "
            "given relationships between them. Returns view_id + maps of "
            "element name → id and relationship key → id. Use this when "
            "the plate fits the Layered convention (Business on top, "
            "Application middle, Technology bottom). For non-standard "
            "viewpoints or fine-grained editing, fall back to the primitive "
            "create_* / add_to_view tools.\n\n"
            "Element specs: {name, type, documentation?, stereotype?} — or "
            "{name, wilma_id} to REUSE an existing WILMA reference element "
            "(preserves its identifier; search WILMA first with "
            "archimate_search_model). Relationship specs: {source, target, "
            "type, access_type?} where source / target are element NAMES from "
            "the lists below (no need to track IDs). Composition / Aggregation "
            "relations automatically become visual nesting in the rendered "
            "plate (e.g. systems inside a Beveiligingsdomein Grouping)."
        ),
        meta=meta,
    )
    async def add_layered_view(
        session_id: str,
        name: str,
        business: list[dict] | None = None,
        application: list[dict] | None = None,
        technology: list[dict] | None = None,
        motivation: list[dict] | None = None,
        relationships: list[dict] | None = None,
        documentation: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        return await _build_composite_view(
            session_id=session_id,
            view_name=name,
            view_documentation=documentation,
            groups={
                "Motivation": motivation or [],
                "Business": business or [],
                "Application": application or [],
                "Technology": technology or [],
            },
            relationships=relationships or [],
            model_path=model_path,
        )

    @mcp.tool(
        name="add_cooperation_view",
        description=(
            "Build a complete Application Cooperation viewpoint in one "
            "call: peer application components are laid out side-by-side, "
            "shared services in the middle. Returns view_id + name → id "
            "maps. Use when the plate is about how application components "
            "collaborate via shared services (horizontal flow). For "
            "cross-layer blueprints, use add_layered_view instead.\n\n"
            "Element specs: {name, type, documentation?, stereotype?} — or "
            "{name, wilma_id} to reuse an existing WILMA reference element. "
            "Relationship specs: {source, target, type, access_type?}."
        ),
        meta=meta,
    )
    async def add_cooperation_view(
        session_id: str,
        name: str,
        peers: list[dict] | None = None,
        shared_services: list[dict] | None = None,
        relationships: list[dict] | None = None,
        documentation: str = "",
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        return await _build_composite_view(
            session_id=session_id,
            view_name=f"{name} — Application Cooperation",
            view_documentation=documentation,
            groups={
                "Application": (peers or []) + (shared_services or []),
            },
            relationships=relationships or [],
            model_path=model_path,
        )

    # --- Validation ---

    @mcp.tool(
        name="validate_view",
        description=(
            "Run metamodel + layout checks on a view and return a list of "
            "concrete errors. Call this before done() to catch issues the "
            "architect can fix in one round. Returns success=true with an "
            "empty errors list when the view is clean. Each error has a "
            "code, a message, and an optional element_id / relationship_id "
            "so the agent can target the fix. Conservative by design: "
            "only flags things that are almost certainly wrong (self-loops, "
            "obvious metamodel violations, overlapping boxes that aren't "
            "nesting, labels that don't fit their box). Routine concerns "
            "like 'too many edges' are not errors here."
        ),
        meta=meta,
    )
    async def validate_view(
        session_id: str,
        view_id: str,
        model_path: str = DEFAULT_MODEL_PATH,
    ) -> dict:
        try:
            doc = _registry().get(session_id, model_path, create_if_missing=False)
            view = doc.find_view(view_id)
            if view is None:
                return _error(f"View '{view_id}' not found")
            errors = _validate_view_impl(doc, view)
            return _result({
                "view_id": view_id,
                "error_count": len(errors),
                "errors": errors,
            })
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


# --- Composite-view helper -------------------------------------------------
# Shared implementation for add_layered_view / add_cooperation_view. Builds
# a complete view from a flat description (groups of element specs +
# relationship specs by element name) in one call, so the architect can
# express "make this view" instead of orchestrating ~30 primitive calls.
# Element creation honours the architect's choice of name as the primary
# key — duplicate names within a group are not allowed, but reusing an
# existing element name from elsewhere in the model is fine (lookup-first,
# create-if-missing). Returns a name→id map so subsequent edits don't need
# to grep the XML for identifiers.


async def _build_composite_view(
    *,
    session_id: str,
    view_name: str,
    view_documentation: str,
    groups: dict[str, list[dict]],
    relationships: list[dict],
    model_path: str,
) -> dict[str, Any]:
    """Materialise a viewpoint from a flat element + relationship spec.

    ``groups`` maps an ArchiMate layer label to a list of element specs.
    Each element spec is {name, type, documentation?}. ``relationships``
    is a list of {source, target, type, access_type?} where source and
    target reference element names from the groups.
    """
    try:
        registry = _registry()
        doc = registry.get(session_id, model_path)

        # Step 1: create the view itself.
        view_id = doc.create_view(name=view_name, documentation=view_documentation)

        # Step 2: ensure every element exists, indexing by name.
        element_id_by_name: dict[str, str] = {}
        for layer, specs in groups.items():
            for spec in specs:
                name = (spec.get("name") or "").strip()
                if not name:
                    return _error(f"Element in layer '{layer}' is missing a name")
                if name in element_id_by_name:
                    return _error(f"Element name '{name}' appears twice")
                # WILMA reuse: a spec carrying `wilma_id` imports the existing
                # WILMA reference element (preserving its original identifier)
                # instead of creating a project-specific copy. `name` stays the
                # key used to wire relationships below. This keeps a plate that
                # reuses WILMA a single one-shot call instead of falling back to
                # per-element get_or_create_wilma_reference + add_to_view.
                wilma_id = (spec.get("wilma_id") or "").strip()
                if wilma_id:
                    try:
                        element_id_by_name[name] = doc.copy_element_from(
                            registry.wilma(), wilma_id
                        )
                    except ArchiMateWriteError as e:
                        return _error(
                            f"WILMA import for '{name}' (wilma_id='{wilma_id}') failed: {e}"
                        )
                    continue
                element_type = spec.get("type") or ""
                if not element_type:
                    return _error(f"Element '{name}' is missing 'type' (or a 'wilma_id')")
                if element_type not in ELEMENT_TYPE_LAYER:
                    return _error(
                        f"Element '{name}': unsupported type '{element_type}'. "
                        f"Allowed: {sorted(ELEMENT_TYPE_LAYER)}"
                    )
                actual_layer = ELEMENT_TYPE_LAYER[element_type]
                if actual_layer != layer and layer != "Other":
                    return _error(
                        f"Element '{name}' has type '{element_type}' "
                        f"(layer {actual_layer}) but was placed in group "
                        f"'{layer}'. Move it to the matching group."
                    )
                element_id_by_name[name] = doc.create_element(
                    element_type=element_type,
                    name=name,
                    documentation=spec.get("documentation", ""),
                    stereotype=spec.get("stereotype", ""),
                )

        # Step 3: create relationships by resolving names → ids.
        relationship_ids: list[dict[str, str]] = []
        for rel_spec in relationships:
            src_name = (rel_spec.get("source") or "").strip()
            tgt_name = (rel_spec.get("target") or "").strip()
            rel_type = rel_spec.get("type") or ""
            if rel_type not in VALID_RELATIONSHIP_TYPES:
                return _error(
                    f"Relationship type '{rel_type}' not supported. "
                    f"Allowed: {sorted(VALID_RELATIONSHIP_TYPES)}"
                )
            if src_name not in element_id_by_name:
                return _error(
                    f"Relationship source '{src_name}' not found in element groups"
                )
            if tgt_name not in element_id_by_name:
                return _error(
                    f"Relationship target '{tgt_name}' not found in element groups"
                )
            rel_kwargs = {
                "relationship_type": rel_type,
                "source_id": element_id_by_name[src_name],
                "target_id": element_id_by_name[tgt_name],
            }
            access_type = rel_spec.get("access_type") or rel_spec.get("accessType")
            if rel_type == "Access" and access_type:
                rel_kwargs["access_type"] = access_type
            rel_id = doc.create_relationship(**rel_kwargs)
            relationship_ids.append({
                "source": src_name,
                "target": tgt_name,
                "type": rel_type,
                "relationship_id": rel_id,
            })

        # Step 4: place every element on the view (auto-width per name).
        for element_id in element_id_by_name.values():
            doc.add_to_view(view_id, element_id)

        # Step 5: connect every relationship on the view.
        for rel in relationship_ids:
            doc.add_connection_to_view(view_id, rel["relationship_id"])

        return _result({
            "view_id": view_id,
            "element_ids": element_id_by_name,
            "relationship_ids": relationship_ids,
            "element_count": len(element_id_by_name),
            "relationship_count": len(relationship_ids),
        })
    except ArchiMateWriteError as e:
        return _error(str(e))


# --- View validation -------------------------------------------------------
# Deliberately conservative: only catches things that are almost certainly
# wrong. False positives drive the LLM to "fix" things that aren't broken
# and degrade output quality (see the Snorkel self-critique-paradox
# research note). Each error has a stable code so prompt rules can target
# specific ones without parsing message text.

# Layer ordering for cross-layer rule checks. Higher number = more abstract.
_LAYER_ORDER = {
    "Motivation": 4,
    "Business": 3,
    "Application": 2,
    "Technology": 1,
    "Implementation": 0,
    "Other": 0,
}

# Name tokens that strongly signal an ordinary handling role / team / person
# rather than a Rijnland "Account" (a governance construct). Used to warn on a
# misapplied «Account» stereotype. Kept narrow to avoid false positives — none
# of these belong to a genuine account name.
_ACCOUNT_NOT_HINTS = (
    "team", "coördinator", "coordinator", "medewerker", "behandel",
    "beheerder", "gebruiker", "burger", "klant", "inwoner", "aanvrager",
)

# ArchiMate element categories — coarse buckets driving the relationship
# metamodel checks. Active structure *performs* behaviour; behaviour *is*
# performed; passive structure is *acted on*; motivation expresses intent.
# Anything else (Grouping/Location/Junction/Plateau/WorkPackage/…) is "other"
# and treated permissively so we never fire on composite/aggregation glue.
_ACTIVE_STRUCTURE_TYPES = {
    "BusinessActor", "BusinessRole", "BusinessCollaboration", "BusinessInterface",
    "ApplicationComponent", "ApplicationCollaboration", "ApplicationInterface",
    "Node", "Device", "SystemSoftware", "TechnologyCollaboration",
    "TechnologyInterface", "Path", "CommunicationNetwork",
    "Equipment", "Facility", "DistributionNetwork",
}
_BEHAVIOR_TYPES = {
    "BusinessProcess", "BusinessFunction", "BusinessInteraction", "BusinessEvent",
    "BusinessService", "ApplicationFunction", "ApplicationInteraction",
    "ApplicationProcess", "ApplicationEvent", "ApplicationService",
    "TechnologyFunction", "TechnologyProcess", "TechnologyInteraction",
    "TechnologyEvent", "TechnologyService",
}
_PASSIVE_STRUCTURE_TYPES = {
    "BusinessObject", "Contract", "Representation", "DataObject", "Artifact",
    "Deliverable", "Material",
}
_MOTIVATION_TYPES = {
    "Stakeholder", "Driver", "Assessment", "Goal", "Outcome", "Principle",
    "Requirement", "Constraint", "Meaning", "Value",
}


def _category(t: str) -> str:
    if t in _ACTIVE_STRUCTURE_TYPES:
        return "active"
    if t in _BEHAVIOR_TYPES:
        return "behavior"
    if t in _PASSIVE_STRUCTURE_TYPES:
        return "passive"
    if t in _MOTIVATION_TYPES:
        return "motivation"
    return "other"


def _read_property(doc, el, prop_name: str) -> str:
    """Return the value of a named property marker on an element, or ''.

    Mirrors writer._add_property_marker: the value lives in
    ``properties/property/value`` and is linked to a ``propertyDefinition``
    whose ``name`` is ``prop_name``. Used to read the Rijnland ``stereotype``
    marker back out during validation and rendering.
    """
    ns = _ns()
    pd_id = ""
    for pd in doc.root.findall("am:propertyDefinitions/am:propertyDefinition", ns):
        name_el = pd.find("am:name", ns)
        if name_el is not None and (name_el.text or "") == prop_name:
            pd_id = pd.get("identifier", "")
            break
    if not pd_id:
        return ""
    for prop in el.findall("am:properties/am:property", ns):
        if prop.get("propertyDefinitionRef") == pd_id:
            val = prop.find("am:value", ns)
            if val is not None:
                return (val.text or "").strip()
    return ""


def _validate_view_impl(doc, view) -> list[dict[str, Any]]:
    """Return a list of concrete error dicts for the given view."""
    from xml.etree import ElementTree as ET  # local import to keep top clean

    ns = _ns()
    xsi_type = "{http://www.w3.org/2001/XMLSchema-instance}type"

    errors: list[dict[str, Any]] = []

    # Index nodes on this view by element-ref so we can resolve connections.
    nodes_on_view: dict[str, ET.Element] = {}
    node_geom: dict[str, tuple[int, int, int, int]] = {}
    for node in view.findall("am:node", ns):
        ref = node.get("elementRef") or ""
        if ref:
            nodes_on_view[ref] = node
            try:
                node_geom[ref] = (
                    int(node.get("x", "0")),
                    int(node.get("y", "0")),
                    int(node.get("w", "0")),
                    int(node.get("h", "0")),
                )
            except ValueError:
                pass

    # --- Metamodel checks (only on relationships visible in this view) ---

    visible_rels: list[ET.Element] = []
    for conn in view.findall("am:connection", ns):
        rel_id = conn.get("relationshipRef") or ""
        if not rel_id:
            continue
        rel = doc.find_relationship(rel_id)
        if rel is not None:
            visible_rels.append(rel)

    for rel in visible_rels:
        rel_id = rel.get("identifier", "")
        rel_type = rel.get(xsi_type, "")
        src_id = rel.get("source", "")
        tgt_id = rel.get("target", "")

        # Self-loop — almost always a modelling mistake.
        if src_id and src_id == tgt_id:
            errors.append({
                "code": "self_relationship",
                "message": f"Relationship '{rel_type}' has the same source and target ({src_id}). Remove or repoint one end.",
                "relationship_id": rel_id,
            })
            continue

        src_el = doc.find_element(src_id) if src_id else None
        tgt_el = doc.find_element(tgt_id) if tgt_id else None
        if src_el is None or tgt_el is None:
            continue  # dangling refs are caught at create-time

        src_type = src_el.get(xsi_type, "")
        tgt_type = tgt_el.get(xsi_type, "")
        src_layer = ELEMENT_TYPE_LAYER.get(src_type, "Other")
        tgt_layer = ELEMENT_TYPE_LAYER.get(tgt_type, "Other")

        # Realization direction: the source provides a realization for the
        # target. Typically source is *more concrete* (lower layer) than
        # the target. "Business realizes Application" is the reverse of
        # what the standard documents.
        if rel_type == "Realization":
            if _LAYER_ORDER.get(src_layer, 0) > _LAYER_ORDER.get(tgt_layer, 0):
                errors.append({
                    "code": "realization_direction",
                    "message": (
                        f"Realization is reversed: '{src_type}' ({src_layer}) "
                        f"realizes '{tgt_type}' ({tgt_layer}). Source should be "
                        f"the more concrete element. Swap source and target, "
                        f"or pick a different relationship type."
                    ),
                    "relationship_id": rel_id,
                })

        # Access must have an accessType (Read / Write / ReadWrite / Access)
        if rel_type == "Access":
            access_type = rel.get("accessType") or ""
            if access_type not in {"Read", "Write", "ReadWrite", "Access"}:
                errors.append({
                    "code": "access_missing_type",
                    "message": (
                        f"Access relationship is missing an accessType (got "
                        f"'{access_type or 'none'}'). Set Read / Write / "
                        f"ReadWrite / Access."
                    ),
                    "relationship_id": rel_id,
                })
            # Access targets a passive data element in ArchiMate.
            # ApplicationComponent → ApplicationComponent via Access is the
            # most common mis-use we've seen; the architect probably meant
            # Serving (caller is served by callee) or Used-By.
            if tgt_type not in {"DataObject", "BusinessObject", "Artifact", "Representation", "Contract"}:
                errors.append({
                    "code": "access_target_not_passive",
                    "message": (
                        f"Access targets '{tgt_type}', but Access is for "
                        f"passive data elements (DataObject, BusinessObject, "
                        f"Artifact, Representation, Contract). For active "
                        f"elements use Serving (callee → caller) or Triggering."
                    ),
                    "relationship_id": rel_id,
                })

        # --- ArchiMate relationship metamodel (category-level) ---
        src_cat = _category(src_type)
        tgt_cat = _category(tgt_type)

        # Triggering is a dynamic relationship between behaviour elements. An
        # active-structure source (actor / role / component / node) does not
        # "trigger" a behaviour — it is *assigned to* the behaviour it
        # performs. This is the most common mis-draw (actor → process).
        if rel_type == "Triggering" and src_cat == "active":
            errors.append({
                "code": "triggering_from_active_structure",
                "message": (
                    f"Triggering runs from '{src_type}' (active structure). An "
                    f"active element performing a behaviour is an Assignment, not "
                    f"a Triggering. Use Assignment (active → behaviour), or make "
                    f"the source the behaviour element that does the triggering."
                ),
                "relationship_id": rel_id,
            })

        # Flow moves information/value between two behaviour elements (or two
        # active-structure elements). Mixing an active-structure end with a
        # behaviour end — or touching passive/motivation — is a metamodel
        # error (e.g. a BusinessProcess "flowing" into an ApplicationComponent).
        if rel_type == "Flow":
            cats = {src_cat, tgt_cat}
            if (cats & {"passive", "motivation"}) or cats == {"active", "behavior"}:
                errors.append({
                    "code": "flow_invalid_endpoints",
                    "message": (
                        f"Flow connects '{src_type}' and '{tgt_type}', which mix "
                        f"incompatible kinds. Flow is for two behaviour elements "
                        f"or two active-structure elements. For an app/service "
                        f"supporting a process use Serving; for reading or writing "
                        f"data use Access."
                    ),
                    "relationship_id": rel_id,
                })

        # Assignment goes from active structure to the behaviour it performs
        # (or actor → role, role → interface). A behaviour source is reversed.
        if rel_type == "Assignment" and src_cat == "behavior":
            errors.append({
                "code": "assignment_from_behavior",
                "message": (
                    f"Assignment runs from '{src_type}' (behaviour). Assignment "
                    f"goes from an active-structure element to the behaviour it "
                    f"performs — swap source and target."
                ),
                "relationship_id": rel_id,
            })

        # Serving direction across the Business/Application/Technology stack:
        # the more concrete layer serves the more abstract one (Technology
        # serves Application serves Business). The reverse — e.g. an
        # ApplicationComponent "serving" a database/SystemSoftware — is almost
        # always a mis-drawn dependency.
        if rel_type == "Serving":
            _BAT = {"Business", "Application", "Technology"}
            if (src_layer in _BAT and tgt_layer in _BAT
                    and _LAYER_ORDER.get(src_layer, 0) > _LAYER_ORDER.get(tgt_layer, 0)):
                errors.append({
                    "code": "serving_direction",
                    "message": (
                        f"Serving is reversed: '{src_type}' ({src_layer}) serves "
                        f"'{tgt_type}' ({tgt_layer}). The more concrete layer "
                        f"serves the more abstract one "
                        f"(Technology → Application → Business). Swap source and "
                        f"target."
                    ),
                    "relationship_id": rel_id,
                })

    # --- Element-type sanity checks ---

    # Databases / persistent stores modelled as ApplicationComponent are a
    # frequent class of error: a Postgres / Mongo / etc. is either a
    # SystemSoftware (the engine, Technology layer) or a DataObject (the
    # logical data, Application layer). Naming gives us a strong hint.
    _STORAGE_HINTS = ("database", "datastore", "data store", "postgres",
                      "postgresql", "mysql", "mongodb", "mongo", "redis",
                      "kafka", "elasticsearch", "-db", " db ", "(db)")
    for ref in nodes_on_view:
        el = doc.find_element(ref)
        if el is None:
            continue
        el_type = el.get(xsi_type, "")
        name_el = el.find("am:name", ns)
        name = (name_el.text or "") if name_el is not None else ""
        name_lc = name.lower()
        looks_like_storage = any(hint in name_lc for hint in _STORAGE_HINTS)
        if looks_like_storage and el_type not in {"SystemSoftware", "DataObject", "Artifact", "Node", "Device"}:
            errors.append({
                "code": "storage_as_application_component",
                "message": (
                    f"Element '{name}' looks like a database / persistent "
                    f"store but is typed as '{el_type}'. Use SystemSoftware "
                    f"(Technology layer) for the engine, or DataObject "
                    f"(Application layer) for the logical data."
                ),
                "element_id": ref,
            })

    # Name vs type: a service named "...component" — or a component named
    # "...service" / "...dienst" — signals a typing mistake, usually the
    # ownership/active-vs-behaviour choice made on the wrong axis (the
    # Rijnland §3 rule). High-confidence and cheap.
    for ref in nodes_on_view:
        el = doc.find_element(ref)
        if el is None:
            continue
        el_type = el.get(xsi_type, "")
        name_el = el.find("am:name", ns)
        name = (name_el.text or "") if name_el is not None else ""
        nl = name.lower()
        if el_type.endswith("Service") and "component" in nl:
            errors.append({
                "code": "name_type_mismatch",
                "message": (
                    f"'{name}' is typed '{el_type}' (a service) but is named like "
                    f"a component. A service is named for the behaviour it offers, "
                    f"not '…component'. Re-type as the component, or rename."
                ),
                "element_id": ref,
            })
        elif el_type.endswith("Component") and (
            nl.endswith("service") or nl.endswith("dienst")
        ):
            errors.append({
                "code": "name_type_mismatch",
                "message": (
                    f"'{name}' is typed '{el_type}' (an active component) but is "
                    f"named like a service. If it is consumed as a service / SaaS, "
                    f"re-type as ApplicationService (a behaviour shape)."
                ),
                "element_id": ref,
            })

    # --- Rijnland / waterschap tekenafspraken checks ---
    # Conservative by design: every check below only fires on an element that
    # actually carries a Rijnland `stereotype`. A generic (non-waterschap)
    # plate has no stereotypes and is therefore never flagged here.
    for ref in nodes_on_view:
        el = doc.find_element(ref)
        if el is None:
            continue
        stereotype = _read_property(doc, el, "stereotype")
        if not stereotype:
            continue
        el_type = el.get(xsi_type, "")

        # 1. A known concept must sit on the prescribed ArchiMate type.
        #    create_element enforces this too, but WILMA-imports and
        #    hand-edited XML can bypass create-time — re-check here.
        concept = RIJNLAND_CONCEPTS.get(stereotype)
        if concept is not None and el_type != concept["type"]:
            errors.append({
                "code": "rijnland_stereotype_type",
                "message": (
                    f"Rijnland concept «{stereotype}» must be modelled as "
                    f"'{concept['type']}', but is typed '{el_type}'. "
                    f"Re-create it with the correct type."
                ),
                "element_id": ref,
            })

        # 1b. «Account» is a governance construct (coordinates WILMA functions
        #     + an application group), not a generic role. Warn when it's
        #     applied to an ordinary handling role / team / person.
        if stereotype == "Account":
            name_el = el.find("am:name", ns)
            nm = ((name_el.text or "") if name_el is not None else "").lower()
            if any(hint in nm for hint in _ACCOUNT_NOT_HINTS):
                errors.append({
                    "code": "account_likely_plain_role",
                    "message": (
                        f"'{nm or ref}' is stereotyped «Account», but its name "
                        f"reads like an ordinary role/team/person. An Account "
                        f"is a governance construct (coordinates WILMA functions "
                        f"+ an application group). If this is just a role, drop "
                        f"the «Account» stereotype and use a plain BusinessRole/"
                        f"BusinessActor."
                    ),
                    "element_id": ref,
                })

        # 2. A Beveiligingsdomein (security zone) must carry a NORA/IEC-62443
        #    trust level — the whole point of the concept is its security
        #    property. Accept it either as a trust-level property or as a
        #    recognised token in the element name.
        if stereotype == "Beveiligingsdomein":
            name_el = el.find("am:name", ns)
            name_lc = ((name_el.text or "") if name_el is not None else "").lower()
            trust_prop = _read_property(doc, el, "trust-level").lower()
            has_trust = (
                trust_prop in RIJNLAND_TRUST_LEVELS
                or any(level in name_lc for level in RIJNLAND_TRUST_LEVELS)
                or "level " in name_lc  # IEC-62443 "Level L4" style
            )
            if not has_trust:
                errors.append({
                    "code": "security_domain_missing_trust",
                    "message": (
                        f"Beveiligingsdomein '{name_lc or ref}' has no trust "
                        f"level. Add a NORA level (niet-/semi-/vertrouwd/"
                        f"zeer-vertrouwd) or an IEC-62443 'Level Lx' to the "
                        f"name, or set a 'trust-level' property."
                    ),
                    "element_id": ref,
                })

    # --- Layout checks ---

    # Off-canvas elements.
    for ref, (x, y, _w, _h) in node_geom.items():
        if x < 0 or y < 0:
            errors.append({
                "code": "off_canvas",
                "message": f"Element placed at negative coordinates ({x}, {y}). Re-run layout or move it on-canvas.",
                "element_id": ref,
            })

    # Overlapping boxes — but containment (visual nesting) is fine.
    geom_items = list(node_geom.items())
    for i, (id_a, (ax, ay, aw, ah)) in enumerate(geom_items):
        for id_b, (bx, by, bw, bh) in geom_items[i + 1:]:
            overlaps = not (
                ax + aw <= bx or bx + bw <= ax
                or ay + ah <= by or by + bh <= ay
            )
            if not overlaps:
                continue
            contains_ab = (ax <= bx and ay <= by
                           and ax + aw >= bx + bw and ay + ah >= by + bh)
            contains_ba = (bx <= ax and by <= ay
                           and bx + bw >= ax + aw and by + bh >= ay + ah)
            if contains_ab or contains_ba:
                continue
            errors.append({
                "code": "overlap",
                "message": f"Elements overlap on the view: {id_a} and {id_b}. Trigger a relayout or remove one.",
                "element_id": id_a,
            })

    # Label clipping — estimated label pixel-width vs box width.
    for ref, (_x, _y, w, _h) in node_geom.items():
        el = doc.find_element(ref)
        if el is None:
            continue
        name_el = el.find("am:name", ns)
        name = (name_el.text or "") if name_el is not None else ""
        # Same heuristic as writer._auto_width_for, kept in sync manually.
        needed = len(name) * 7 + 24
        if w > 0 and needed > w + 8:  # 8 px tolerance
            errors.append({
                "code": "label_clipping",
                "message": (
                    f"Label '{name}' likely clips its box (needs ~{needed}px, "
                    f"has {w}px). The auto-width on add_to_view should have "
                    f"caught this — call update_element or readd with explicit w."
                ),
                "element_id": ref,
            })

    return errors
