"""ArchiMate Write Module — buffered, per-session XML editor.

Maintains an in-memory ElementTree per (session_id, model_path) pair.
Mutations modify the in-memory tree. ``save_model`` writes the tree
back to disk as canonical Open Exchange XML.

Design choices (locked in planning):
- ArchiMate Open Exchange Format 3.0 (matches WILMA namespace)
- ElementTree (stdlib) — no external dependency
- Buffered: mutations stage in memory; save_model commits to disk
- ID-based incremental layout: existing identifiers preserve x/y;
  new elements receive auto-layout coordinates in a free region.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger("archimate-writer")

ARCHIMATE_NS = "http://www.opengroup.org/xsd/archimate/3.0/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SCHEMA_LOCATION = (
    "http://www.opengroup.org/xsd/archimate/3.0/ "
    "http://www.opengroup.org/xsd/archimate/3.1/archimate3_Diagram.xsd"
)

ET.register_namespace("", ARCHIMATE_NS)
ET.register_namespace("xsi", XSI_NS)

NS = {"am": ARCHIMATE_NS}


VALID_LAYERS_V1 = {"Business", "Application", "Technology", "Motivation"}

# Element types supported in v1 (per planning decision Q6).
# Each maps to the layer it belongs to.
ELEMENT_TYPE_LAYER = {
    # Business
    "BusinessActor": "Business",
    "BusinessRole": "Business",
    "BusinessCollaboration": "Business",
    "BusinessInterface": "Business",
    "BusinessProcess": "Business",
    "BusinessFunction": "Business",
    "BusinessInteraction": "Business",
    "BusinessEvent": "Business",
    "BusinessService": "Business",
    "BusinessObject": "Business",
    "Contract": "Business",
    "Representation": "Business",
    "Product": "Business",
    # Application
    "ApplicationComponent": "Application",
    "ApplicationCollaboration": "Application",
    "ApplicationInterface": "Application",
    "ApplicationFunction": "Application",
    "ApplicationInteraction": "Application",
    "ApplicationProcess": "Application",
    "ApplicationEvent": "Application",
    "ApplicationService": "Application",
    "DataObject": "Application",
    # Technology
    "Node": "Technology",
    "Device": "Technology",
    "SystemSoftware": "Technology",
    "TechnologyCollaboration": "Technology",
    "TechnologyInterface": "Technology",
    "Path": "Technology",
    "CommunicationNetwork": "Technology",
    "TechnologyFunction": "Technology",
    "TechnologyProcess": "Technology",
    "TechnologyInteraction": "Technology",
    "TechnologyEvent": "Technology",
    "TechnologyService": "Technology",
    "Artifact": "Technology",
    # Motivation
    "Stakeholder": "Motivation",
    "Driver": "Motivation",
    "Assessment": "Motivation",
    "Goal": "Motivation",
    "Outcome": "Motivation",
    "Principle": "Motivation",
    "Requirement": "Motivation",
    "Constraint": "Motivation",
    "Meaning": "Motivation",
    "Value": "Motivation",
    # Cross-layer
    "Grouping": "Other",
    "Location": "Other",
    "Junction": "Other",
}

VALID_RELATIONSHIP_TYPES = {
    "Composition",
    "Aggregation",
    "Assignment",
    "Realization",
    "Serving",
    "Access",
    "Triggering",
    "Flow",
    "Influence",
    "Specialization",
    "Association",
}

# Default visual styling (matches Archi defaults for clean rendering)
DEFAULT_NODE_W = 120
DEFAULT_NODE_H = 55
DEFAULT_GRID_SPACING_X = 160
DEFAULT_GRID_SPACING_Y = 90


def _q(tag: str) -> str:
    """Return a namespaced tag name for ElementTree."""
    return f"{{{ARCHIMATE_NS}}}{tag}"


def _qxsi(attr: str) -> str:
    return f"{{{XSI_NS}}}{attr}"


def _qxml(attr: str) -> str:
    return f"{{{XML_NS}}}{attr}"


def _make_id() -> str:
    """Generate an Archi-compatible identifier."""
    return f"id-{uuid.uuid4().hex}"


def _text_child(parent: ET.Element, tag: str, text: str, lang: str = "en") -> ET.Element:
    """Append a namespaced child element with xml:lang and text."""
    el = ET.SubElement(parent, _q(tag))
    el.set(_qxml("lang"), lang)
    el.text = text
    return el


def _find_text(parent: ET.Element, tag: str) -> str:
    child = parent.find(f"am:{tag}", NS)
    if child is not None and child.text:
        return child.text.strip()
    return ""


class ArchiMateWriteError(Exception):
    """Raised on invalid write operations (unknown ID, bad type, etc.)."""


class ArchiMateDocument:
    """In-memory ArchiMate Open Exchange XML document with mutation API.

    Loaded from disk (or created fresh). All mutations modify the in-memory
    ElementTree. Call ``save()`` to persist to disk.
    """

    def __init__(self, path: Path, tree: ET.ElementTree, *, fresh: bool = False):
        self.path = path
        self.tree = tree
        self.root = tree.getroot()
        self.fresh = fresh
        self.dirty = fresh
        self._ensure_section("elements")
        self._ensure_section("relationships")
        self._ensure_views_section()

    # --- Construction ----------------------------------------------------

    @classmethod
    def load_or_create(cls, path: Path, *, model_name: str = "Project Architecture") -> "ArchiMateDocument":
        if path.exists():
            tree = ET.parse(path)
            return cls(path, tree, fresh=False)
        return cls._create_empty(path, model_name=model_name)

    @classmethod
    def _create_empty(cls, path: Path, *, model_name: str) -> "ArchiMateDocument":
        root = ET.Element(_q("model"))
        root.set("identifier", _make_id())
        root.set(_qxsi("schemaLocation"), SCHEMA_LOCATION)
        _text_child(root, "name", model_name)
        ET.SubElement(root, _q("elements"))
        ET.SubElement(root, _q("relationships"))
        views = ET.SubElement(root, _q("views"))
        ET.SubElement(views, _q("diagrams"))
        tree = ET.ElementTree(root)
        return cls(path, tree, fresh=True)

    # --- Section helpers -------------------------------------------------

    def _ensure_section(self, tag: str) -> ET.Element:
        section = self.root.find(f"am:{tag}", NS)
        if section is None:
            section = ET.SubElement(self.root, _q(tag))
            self.dirty = True
        return section

    def _ensure_views_section(self) -> ET.Element:
        views = self.root.find("am:views", NS)
        if views is None:
            views = ET.SubElement(self.root, _q("views"))
            self.dirty = True
        diagrams = views.find("am:diagrams", NS)
        if diagrams is None:
            diagrams = ET.SubElement(views, _q("diagrams"))
            self.dirty = True
        return diagrams

    # --- Lookups ---------------------------------------------------------

    def find_element(self, identifier: str) -> ET.Element | None:
        for el in self.root.findall("am:elements/am:element", NS):
            if el.get("identifier") == identifier:
                return el
        return None

    def find_relationship(self, identifier: str) -> ET.Element | None:
        for rel in self.root.findall("am:relationships/am:relationship", NS):
            if rel.get("identifier") == identifier:
                return rel
        return None

    def find_view(self, identifier: str) -> ET.Element | None:
        for v in self.root.findall("am:views/am:diagrams/am:view", NS):
            if v.get("identifier") == identifier:
                return v
        return None

    # --- Element mutations ----------------------------------------------

    def create_element(
        self,
        *,
        element_type: str,
        name: str,
        documentation: str = "",
        identifier: str | None = None,
    ) -> str:
        if element_type not in ELEMENT_TYPE_LAYER:
            raise ArchiMateWriteError(
                f"Unsupported element type '{element_type}'. "
                f"Supported types (v1): {sorted(ELEMENT_TYPE_LAYER)}"
            )
        layer = ELEMENT_TYPE_LAYER[element_type]
        if layer not in VALID_LAYERS_V1 and layer != "Other":
            raise ArchiMateWriteError(
                f"Layer '{layer}' not supported in v1 (Business/Application/Technology/Motivation only)"
            )
        ident = identifier or _make_id()
        if self.find_element(ident) is not None:
            raise ArchiMateWriteError(f"Element identifier '{ident}' already exists")

        section = self._ensure_section("elements")
        el = ET.SubElement(section, _q("element"))
        el.set("identifier", ident)
        el.set(_qxsi("type"), element_type)
        _text_child(el, "name", name)
        if documentation:
            _text_child(el, "documentation", documentation)
        self.dirty = True
        return ident

    def update_element(
        self,
        identifier: str,
        *,
        name: str | None = None,
        documentation: str | None = None,
    ) -> None:
        el = self.find_element(identifier)
        if el is None:
            raise ArchiMateWriteError(f"Element '{identifier}' not found")
        if name is not None:
            self._replace_text_child(el, "name", name)
        if documentation is not None:
            self._replace_text_child(el, "documentation", documentation)
        self.dirty = True

    def delete_element(self, identifier: str) -> dict[str, list[str]]:
        """Delete element + cascade: remove dependent relationships and view nodes."""
        el = self.find_element(identifier)
        if el is None:
            raise ArchiMateWriteError(f"Element '{identifier}' not found")

        deleted_rels: list[str] = []
        rels_section = self._ensure_section("relationships")
        for rel in list(rels_section.findall("am:relationship", NS)):
            if rel.get("source") == identifier or rel.get("target") == identifier:
                deleted_rels.append(rel.get("identifier", ""))
                rels_section.remove(rel)

        removed_view_nodes: list[str] = []
        for view in self.root.findall("am:views/am:diagrams/am:view", NS):
            for node in list(view.findall("am:node", NS)):
                if node.get("elementRef") == identifier:
                    view.remove(node)
                    removed_view_nodes.append(view.get("identifier", ""))
            for conn in list(view.findall("am:connection", NS)):
                if conn.get("relationshipRef") in deleted_rels:
                    view.remove(conn)

        self._ensure_section("elements").remove(el)
        self.dirty = True
        return {"deleted_relationships": deleted_rels, "affected_views": removed_view_nodes}

    # --- Relationship mutations -----------------------------------------

    def create_relationship(
        self,
        *,
        relationship_type: str,
        source_id: str,
        target_id: str,
        name: str = "",
        access_type: str | None = None,
        identifier: str | None = None,
    ) -> str:
        if relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise ArchiMateWriteError(
                f"Unsupported relationship type '{relationship_type}'. "
                f"Valid types: {sorted(VALID_RELATIONSHIP_TYPES)}"
            )
        if self.find_element(source_id) is None:
            raise ArchiMateWriteError(f"Source element '{source_id}' not found")
        if self.find_element(target_id) is None:
            raise ArchiMateWriteError(f"Target element '{target_id}' not found")

        ident = identifier or _make_id()
        if self.find_relationship(ident) is not None:
            raise ArchiMateWriteError(f"Relationship identifier '{ident}' already exists")

        section = self._ensure_section("relationships")
        rel = ET.SubElement(section, _q("relationship"))
        rel.set("identifier", ident)
        rel.set("source", source_id)
        rel.set("target", target_id)
        rel.set(_qxsi("type"), relationship_type)
        if access_type and relationship_type == "Access":
            rel.set("accessType", access_type)
        if name:
            _text_child(rel, "name", name)
        self.dirty = True
        return ident

    def update_relationship(
        self,
        identifier: str,
        *,
        name: str | None = None,
        access_type: str | None = None,
    ) -> None:
        rel = self.find_relationship(identifier)
        if rel is None:
            raise ArchiMateWriteError(f"Relationship '{identifier}' not found")
        if name is not None:
            self._replace_text_child(rel, "name", name)
        if access_type is not None:
            if access_type:
                rel.set("accessType", access_type)
            elif "accessType" in rel.attrib:
                del rel.attrib["accessType"]
        self.dirty = True

    def delete_relationship(self, identifier: str) -> None:
        rel = self.find_relationship(identifier)
        if rel is None:
            raise ArchiMateWriteError(f"Relationship '{identifier}' not found")
        self._ensure_section("relationships").remove(rel)
        for view in self.root.findall("am:views/am:diagrams/am:view", NS):
            for conn in list(view.findall("am:connection", NS)):
                if conn.get("relationshipRef") == identifier:
                    view.remove(conn)
        self.dirty = True

    # --- View mutations -------------------------------------------------

    def create_view(self, *, name: str, documentation: str = "", identifier: str | None = None) -> str:
        ident = identifier or _make_id()
        if self.find_view(ident) is not None:
            raise ArchiMateWriteError(f"View identifier '{ident}' already exists")
        diagrams = self._ensure_views_section()
        view = ET.SubElement(diagrams, _q("view"))
        view.set("identifier", ident)
        view.set(_qxsi("type"), "Diagram")
        _text_child(view, "name", name)
        if documentation:
            _text_child(view, "documentation", documentation)
        self.dirty = True
        return ident

    def delete_view(self, identifier: str) -> None:
        view = self.find_view(identifier)
        if view is None:
            raise ArchiMateWriteError(f"View '{identifier}' not found")
        diagrams = self._ensure_views_section()
        diagrams.remove(view)
        self.dirty = True

    def add_to_view(
        self,
        view_id: str,
        element_id: str,
        *,
        x: int | None = None,
        y: int | None = None,
        w: int | None = None,
        h: int | None = None,
    ) -> str:
        view = self.find_view(view_id)
        if view is None:
            raise ArchiMateWriteError(f"View '{view_id}' not found")
        if self.find_element(element_id) is None:
            raise ArchiMateWriteError(f"Element '{element_id}' not found")

        for node in view.findall("am:node", NS):
            if node.get("elementRef") == element_id:
                raise ArchiMateWriteError(
                    f"Element '{element_id}' already on view '{view_id}'"
                )

        node_id = _make_id()
        nx, ny = self._next_free_position(view) if (x is None or y is None) else (x, y)
        node = ET.SubElement(view, _q("node"))
        node.set("identifier", node_id)
        node.set("elementRef", element_id)
        node.set(_qxsi("type"), "Element")
        node.set("x", str(nx))
        node.set("y", str(ny))
        node.set("w", str(w if w is not None else DEFAULT_NODE_W))
        node.set("h", str(h if h is not None else DEFAULT_NODE_H))
        self.dirty = True
        return node_id

    def add_connection_to_view(
        self,
        view_id: str,
        relationship_id: str,
    ) -> str:
        view = self.find_view(view_id)
        if view is None:
            raise ArchiMateWriteError(f"View '{view_id}' not found")
        rel = self.find_relationship(relationship_id)
        if rel is None:
            raise ArchiMateWriteError(f"Relationship '{relationship_id}' not found")

        source_id = rel.get("source", "")
        target_id = rel.get("target", "")
        source_node = self._find_view_node_for_element(view, source_id)
        target_node = self._find_view_node_for_element(view, target_id)
        if source_node is None or target_node is None:
            raise ArchiMateWriteError(
                "Both source and target elements must be present on the view "
                "before adding a connection. Call add_to_view for each first."
            )

        conn_id = _make_id()
        conn = ET.SubElement(view, _q("connection"))
        conn.set("identifier", conn_id)
        conn.set("relationshipRef", relationship_id)
        conn.set(_qxsi("type"), "Relationship")
        conn.set("source", source_node.get("identifier", ""))
        conn.set("target", target_node.get("identifier", ""))
        self.dirty = True
        return conn_id

    def remove_from_view(self, view_id: str, element_id: str) -> None:
        view = self.find_view(view_id)
        if view is None:
            raise ArchiMateWriteError(f"View '{view_id}' not found")
        removed = False
        for node in list(view.findall("am:node", NS)):
            if node.get("elementRef") == element_id:
                view.remove(node)
                removed = True
        if not removed:
            raise ArchiMateWriteError(f"Element '{element_id}' not on view '{view_id}'")
        # Clean dangling connections referencing this element's removed nodes
        for conn in list(view.findall("am:connection", NS)):
            src_id = conn.get("source")
            tgt_id = conn.get("target")
            if not any(
                n.get("identifier") in (src_id, tgt_id)
                for n in view.findall("am:node", NS)
            ):
                view.remove(conn)
        self.dirty = True

    # --- Layout helpers --------------------------------------------------

    def _find_view_node_for_element(
        self, view: ET.Element, element_id: str
    ) -> ET.Element | None:
        for node in view.findall("am:node", NS):
            if node.get("elementRef") == element_id:
                return node
        return None

    def _next_free_position(self, view: ET.Element) -> tuple[int, int]:
        """Pick a default coordinate for a newly added node.

        Strategy: place the new node to the right of the existing bbox,
        on a horizontal strip below the bbox bottom — keeps existing
        positions untouched while making the new addition obvious.
        """
        nodes = view.findall("am:node", NS)
        if not nodes:
            return (40, 40)
        max_x = 0
        max_y = 0
        for n in nodes:
            try:
                nx = int(n.get("x", "0"))
                ny = int(n.get("y", "0"))
                nw = int(n.get("w", str(DEFAULT_NODE_W)))
                nh = int(n.get("h", str(DEFAULT_NODE_H)))
            except ValueError:
                continue
            if nx + nw > max_x:
                max_x = nx + nw
            if ny + nh > max_y:
                max_y = ny + nh
        new_x = max_x + DEFAULT_GRID_SPACING_X
        new_y = max_y - DEFAULT_NODE_H
        if new_x > 1400:
            new_x = 40
            new_y = max_y + DEFAULT_GRID_SPACING_Y
        return (max(40, new_x), max(40, new_y))

    # --- WILMA references ------------------------------------------------

    def copy_element_from(
        self,
        source_doc: "ArchiMateDocument",
        wilma_element_id: str,
        *,
        mark_property_name: str = "wilma-source",
    ) -> str:
        """Copy a WILMA element into this document, preserving its identifier.

        Adds a property marker so the renderer/agent know it originated in
        WILMA and must not be mutated locally.
        """
        if self.find_element(wilma_element_id) is not None:
            return wilma_element_id  # already imported

        src = source_doc.find_element(wilma_element_id)
        if src is None:
            raise ArchiMateWriteError(
                f"WILMA element '{wilma_element_id}' not found in source model"
            )

        element_type = src.get(_qxsi("type"), "")
        name = _find_text(src, "name")
        doc = _find_text(src, "documentation")
        ident = self.create_element(
            element_type=element_type,
            name=name,
            documentation=doc,
            identifier=wilma_element_id,
        )
        # Tag the element with a property so we know not to mutate it.
        # (Property defs are simplified in v1 — we use an inline property
        # set referencing a fixed marker name.)
        new_el = self.find_element(ident)
        if new_el is not None:
            self._add_property_marker(new_el, mark_property_name, "true")
        self.dirty = True
        return ident

    def _add_property_marker(
        self, element: ET.Element, name: str, value: str
    ) -> None:
        """Attach a marker property using a propertyDefinition with the given name."""
        prop_defs = self._ensure_property_definition(name)
        props = element.find("am:properties", NS)
        if props is None:
            props = ET.SubElement(element, _q("properties"))
        prop = ET.SubElement(props, _q("property"))
        prop.set("propertyDefinitionRef", prop_defs)
        val = ET.SubElement(prop, _q("value"))
        val.set(_qxml("lang"), "en")
        val.text = value

    def _ensure_property_definition(self, name: str) -> str:
        """Return the propertyDefinition identifier for ``name``, creating it if absent."""
        pd_section = self.root.find("am:propertyDefinitions", NS)
        if pd_section is None:
            pd_section = ET.Element(_q("propertyDefinitions"))
            # propertyDefinitions must come before elements per schema order
            elements_section = self.root.find("am:elements", NS)
            if elements_section is not None:
                self.root.insert(list(self.root).index(elements_section), pd_section)
            else:
                self.root.append(pd_section)
        for pd in pd_section.findall("am:propertyDefinition", NS):
            name_el = pd.find("am:name", NS)
            if name_el is not None and name_el.text == name:
                return pd.get("identifier", "")
        ident = f"propid-{uuid.uuid4().hex[:8]}"
        pd = ET.SubElement(pd_section, _q("propertyDefinition"))
        pd.set("identifier", ident)
        pd.set("type", "string")
        name_el = ET.SubElement(pd, _q("name"))
        name_el.text = name
        return ident

    # --- Save -----------------------------------------------------------

    def _replace_text_child(self, parent: ET.Element, tag: str, text: str) -> None:
        existing = parent.find(f"am:{tag}", NS)
        if existing is not None:
            existing.text = text
            return
        _text_child(parent, tag, text)

    def save(self) -> Path:
        """Write the in-memory tree to disk as canonical Open Exchange XML.

        Uses ``ET.indent`` to produce stable, diff-friendly formatting.
        Does nothing if not dirty (idempotent saves are no-ops).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(self.tree, space="  ", level=0)
        # ET writes the namespace via the prior register_namespace call,
        # but xml:lang attributes need to keep their xml:NS prefix.
        self.tree.write(
            self.path,
            encoding="UTF-8",
            xml_declaration=True,
            short_empty_elements=False,
        )
        self.dirty = False
        return self.path


class WriteSessionRegistry:
    """In-memory registry of open ArchiMate documents per (session_id, model_path).

    A single session can have multiple model paths open simultaneously,
    though in practice each session edits one project file. Each session
    also has read-only access to the shared WILMA reference document for
    cross-copies.
    """

    def __init__(self, workspace_root: Path, models_dir: Path):
        self.workspace_root = Path(workspace_root)
        self.models_dir = Path(models_dir)
        self._docs: dict[tuple[str, str], ArchiMateDocument] = {}
        self._wilma: ArchiMateDocument | None = None

    # --- Workspace path resolution --------------------------------------

    def _resolve_workspace_path(self, session_id: str, model_path: str) -> Path:
        """Resolve a session-relative model path to an absolute filesystem path.

        Matches the coding-MCP convention of placing session work under
        ``/workspaces/<user>/<project>/<session_id>``. The archimate MCP
        does not own workspace lifecycle, so it discovers an existing
        workspace directory rather than creating one.
        """
        if not session_id:
            raise ArchiMateWriteError("session_id is required")
        if not model_path:
            raise ArchiMateWriteError("model_path is required")

        # The coding MCP names workspaces using session_id as the leaf
        # directory. We scan for any leaf path ending in ``/<session_id>``
        # under the workspace root.
        matches = list(self.workspace_root.glob(f"*/*/{session_id}"))
        if not matches:
            # Fallback: assume session_id is a flat directory at the root
            # (useful for tests and standalone runs)
            flat = self.workspace_root / session_id
            if flat.exists():
                matches = [flat]
        if not matches:
            raise ArchiMateWriteError(
                f"No workspace found for session_id '{session_id}'. "
                f"Expected a directory under {self.workspace_root}."
            )
        if len(matches) > 1:
            logger.warning(
                "Multiple workspaces match session_id '%s'; using first: %s",
                session_id,
                matches[0],
            )

        rel = Path(model_path)
        if rel.is_absolute():
            raise ArchiMateWriteError("model_path must be workspace-relative")
        full = (matches[0] / rel).resolve()
        # Containment check: prevent path traversal
        try:
            full.relative_to(matches[0].resolve())
        except ValueError as e:
            raise ArchiMateWriteError(
                f"model_path '{model_path}' escapes workspace root"
            ) from e
        return full

    # --- Document access -------------------------------------------------

    def get(
        self,
        session_id: str,
        model_path: str,
        *,
        create_if_missing: bool = True,
        model_name: str = "Project Architecture",
    ) -> ArchiMateDocument:
        key = (session_id, model_path)
        if key in self._docs:
            return self._docs[key]
        path = self._resolve_workspace_path(session_id, model_path)
        if not create_if_missing and not path.exists():
            raise ArchiMateWriteError(f"Model file '{model_path}' does not exist")
        doc = ArchiMateDocument.load_or_create(path, model_name=model_name)
        self._docs[key] = doc
        return doc

    def discard(self, session_id: str, model_path: str) -> None:
        self._docs.pop((session_id, model_path), None)

    def discard_session(self, session_id: str) -> None:
        for key in list(self._docs):
            if key[0] == session_id:
                self._docs.pop(key, None)

    # --- WILMA access ----------------------------------------------------

    def wilma(self) -> ArchiMateDocument:
        if self._wilma is not None:
            return self._wilma
        wilma_files = sorted(self.models_dir.glob("WILMA-exchange.xml"))
        if not wilma_files:
            wilma_files = sorted(self.models_dir.glob("*.xml"))
        if not wilma_files:
            raise ArchiMateWriteError(
                f"No reference model found in {self.models_dir}"
            )
        tree = ET.parse(wilma_files[0])
        self._wilma = ArchiMateDocument(wilma_files[0], tree, fresh=False)
        return self._wilma


# Singleton registry instance (created on first import)
_REGISTRY: WriteSessionRegistry | None = None


def get_registry() -> WriteSessionRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
        models_dir = Path(os.getenv("MODELS_DIR", "/models"))
        _REGISTRY = WriteSessionRegistry(workspace_root, models_dir)
    return _REGISTRY


def view_summary(doc: ArchiMateDocument, view: ET.Element) -> dict[str, Any]:
    """Lightweight view summary suitable for tool responses."""
    nodes = view.findall("am:node", NS)
    conns = view.findall("am:connection", NS)
    return {
        "view_id": view.get("identifier", ""),
        "name": _find_text(view, "name"),
        "element_count": len(nodes),
        "connection_count": len(conns),
    }
