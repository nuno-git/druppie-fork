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

import httpx

logger = logging.getLogger("archimate-writer")

# URL of the layout-service microservice. Set via env in docker-compose;
# falls back to localhost for unit tests that spin up the service directly.
LAYOUT_SERVICE_URL = os.getenv("LAYOUT_SERVICE_URL", "http://layout-service:8090")
LAYOUT_SERVICE_TIMEOUT_S = 10.0

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

# Default visual styling.
# Min width is generous enough to fit short ASCII labels; auto-width
# below grows boxes for longer Dutch / compound names so the text stops
# overflowing the rectangle. Height stays fixed at one text-line plus
# the type-letter corner; multi-line labels are wrapped at render time.
DEFAULT_NODE_W = 140
DEFAULT_NODE_H = 55
DEFAULT_GRID_SPACING_X = 160
DEFAULT_GRID_SPACING_Y = 90

# Rough character pixel-width for the 11px Segoe-UI / sans-serif label
# font the renderer uses. Used to auto-size boxes that would otherwise
# clip "Notificatierouteringcomponent" or "Zaaktype-mapping configuratie".
_LABEL_CHAR_PX = 7
_LABEL_HORIZONTAL_PADDING = 24


def _auto_width_for(name: str) -> int:
    """Pick a box width that fits ``name`` at the default label font."""
    if not name:
        return DEFAULT_NODE_W
    estimated = len(name) * _LABEL_CHAR_PX + _LABEL_HORIZONTAL_PADDING
    return max(DEFAULT_NODE_W, estimated)


# Viewpoint detection — maps loose view-name patterns onto the recipe
# names the layout-service knows. The keys are normalised to lower-case
# for matching, the values are the viewpoint identifiers layout-service
# understands. Order matters (most specific first) so "ApplicationCooperation"
# wins over "Application" alone. Falls back to "Layered" — a safe default
# that gives a usable plate for almost any reasonable view.
_VIEWPOINT_PATTERNS: list[tuple[str, str]] = [
    ("application cooperation", "ApplicationCooperation"),
    ("application-cooperation", "ApplicationCooperation"),
    ("information structure", "InformationStructure"),
    ("information-structure", "InformationStructure"),
    ("organization", "Organization"),
    ("organisatie", "Organization"),
    ("layered", "Layered"),
    ("gelaagd", "Layered"),
]


def _detect_viewpoint(view: ET.Element) -> str:
    """Pick a viewpoint identifier from a view's name + documentation.

    Heuristic: match well-known viewpoint phrases (English + Dutch) in
    the view's metadata. Default to Layered when nothing matches — it is
    the most permissive recipe and produces a usable plate for any
    cross-layer view, which is what we get from the architect by default.
    """
    name = _find_text(view, "name") or ""
    doc = _find_text(view, "documentation") or ""
    haystack = f"{name} {doc}".lower()
    for needle, viewpoint in _VIEWPOINT_PATTERNS:
        if needle in haystack:
            return viewpoint
    return "Layered"


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


# --- Text sanitisation ----------------------------------------------------
# Centralised because every text field written to the XML (element / view /
# relationship name + documentation) flows through _text_child. Two reasons
# to clean here rather than at the call sites:
#  - WILMA-sourced documentation contains NBSP, narrow-NBSP, smart-quotes and
#    occasional encoding artefacts; copy_element_from would otherwise leak
#    these into every project file and trigger Gitea's "invisible Unicode"
#    warning.
#  - LLM-authored text is just as likely to contain smart-quotes (model
#    autocorrects ASCII quotes) and zero-width junk (copy-paste from the web).
# Letting both paths share one normaliser keeps the XML stable for diff,
# grep, and Archi-import regardless of where the text originated.

_SMART_QUOTE_MAP = {
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK / apostrophe
    "‚": "'",  # SINGLE LOW-9 QUOTATION MARK
    "‛": "'",  # SINGLE HIGH-REVERSED-9
    "“": '"',  # LEFT DOUBLE QUOTATION MARK
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    "„": '"',  # DOUBLE LOW-9
    "‟": '"',  # DOUBLE HIGH-REVERSED-9
    " ": " ",  # NO-BREAK SPACE
    " ": " ",  # NARROW NO-BREAK SPACE
    " ": " ",  # FIGURE SPACE
    " ": " ",  # THIN SPACE
}

# Codepoints to drop entirely (zero-width, BOM, soft hyphen, joiners, box-drawing).
_STRIP_RANGES = (
    (0x200B, 0x200F),  # zero-width space/joiner/non-joiner + LRM/RLM
    (0x2028, 0x202E),  # line/paragraph separators + bidi overrides (keep 0x202F space)
    (0x2060, 0x206F),  # word joiner + invisible operators
    (0xFEFF, 0xFEFF),  # BOM
    (0x00AD, 0x00AD),  # SOFT HYPHEN
    (0x180E, 0x180E),  # MONGOLIAN VOWEL SEPARATOR
    (0x034F, 0x034F),  # COMBINING GRAPHEME JOINER
    (0x2500, 0x257F),  # Box-drawing block — appears in WILMA as encoding artefacts
)


def _sanitize_text(text: str) -> str:
    """Normalise text destined for the .archimate XML.

    Replaces NBSP variants with regular spaces, smart-quotes with their
    ASCII equivalents, and strips zero-width / control / box-drawing
    junk. Returns a clean string safe to commit to git without tripping
    Gitea's invisible-Unicode warning. Preserves legitimate diacritics
    (é, ö, ä, …) and dashes (–, —).
    """
    if not text:
        return text
    out_chars: list[str] = []
    for ch in text:
        cp = ord(ch)
        if ch in _SMART_QUOTE_MAP:
            out_chars.append(_SMART_QUOTE_MAP[ch])
            continue
        if any(lo <= cp <= hi for lo, hi in _STRIP_RANGES):
            continue
        # Strip control chars except whitespace we actually want
        if cp < 0x20 and ch not in ("\t", "\n", "\r"):
            continue
        out_chars.append(ch)
    return "".join(out_chars)


def _text_child(parent: ET.Element, tag: str, text: str, lang: str = "en") -> ET.Element:
    """Append a namespaced child element with xml:lang and text.

    All text passes through ``_sanitize_text`` so the XML stays free of
    invisible / lookalike characters regardless of whether the caller is
    the LLM, a WILMA import, or a programmatic update.
    """
    el = ET.SubElement(parent, _q(tag))
    el.set(_qxml("lang"), lang)
    el.text = _sanitize_text(text)
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
        if w is None:
            element = self.find_element(element_id)
            element_name = _find_text(element, "name") if element is not None else ""
            w = _auto_width_for(element_name)
        node = ET.SubElement(view, _q("node"))
        node.set("identifier", node_id)
        node.set("elementRef", element_id)
        node.set(_qxsi("type"), "Element")
        node.set("x", str(nx))
        node.set("y", str(ny))
        node.set("w", str(w))
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
        """Return the sentinel (0, 0) for a newly added node.

        Layout happens server-side via the layout-service on save: that
        service knows ArchiMate layers and edge topology and produces a
        coherent plate. The writer just stamps a sentinel so save_model
        knows there are unpositioned nodes worth re-laying out. The old
        naïve "place right of bbox, wrap at x=1400" heuristic produced
        the degenerate single-column layouts that this redesign fixes.
        """
        return (0, 0)

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

    # --- ELK layout via layout-service ---------------------------------

    def _detect_nesting_for_view(
        self, view: ET.Element, node_id_by_element: dict[str, str]
    ) -> dict[str, str]:
        """Build a child-node → parent-node map for the view.

        Composition and Aggregation relationships in ArchiMate semantically
        mean "the target is part of the source". Visually that should
        nest the target inside the source rather than draw a diamond-
        ended edge between them — the nesting *is* the relationship
        (this is Bizzdesign / Wierda guidance and matches what Archi
        users do manually). We only nest when both endpoints are
        actually on this view and the child has no other parent yet
        (composition is a tree, not a graph).
        """
        parent_of: dict[str, str] = {}
        for rel in self.root.findall("am:relationships/am:relationship", NS):
            rel_type = rel.get(_qxsi("type"), "")
            if rel_type not in ("Composition", "Aggregation"):
                continue
            src_el = rel.get("source", "")
            tgt_el = rel.get("target", "")
            src_node = node_id_by_element.get(src_el)
            tgt_node = node_id_by_element.get(tgt_el)
            if not src_node or not tgt_node or src_node == tgt_node:
                continue
            if tgt_node in parent_of:
                continue  # already nested under something — keep first parent
            # Guard against cycles (rare but possible with mutual compositions)
            cursor = src_node
            in_cycle = False
            while cursor in parent_of:
                if parent_of[cursor] == tgt_node:
                    in_cycle = True
                    break
                cursor = parent_of[cursor]
            if not in_cycle:
                parent_of[tgt_node] = src_node
        return parent_of

    def _layout_view_via_service(self, view: ET.Element) -> None:
        """Recompute coordinates for every node on ``view`` via layout-service.

        Existing positions (x > 0 and y > 0) are sent with ``fixed=true`` so
        ELK respects them; freshly-added nodes (x ≤ 0) get fresh
        coordinates. The ArchiMate layer is passed as a partition hint so
        the resulting plate keeps Business above Application above
        Technology. Failures are logged but never abort the save — a stale
        layout is preferable to a lost edit.
        """
        nodes_payload: list[dict[str, Any]] = []
        node_elements: dict[str, ET.Element] = {}
        node_id_by_element: dict[str, str] = {}
        for node in view.findall("am:node", NS):
            node_id = node.get("identifier", "")
            element_ref = node.get("elementRef", "")
            if not node_id or not element_ref:
                continue
            el = self.find_element(element_ref)
            element_type = el.get(_qxsi("type"), "") if el is not None else ""
            layer = ELEMENT_TYPE_LAYER.get(element_type, "Other")
            try:
                x = int(node.get("x", "0"))
                y = int(node.get("y", "0"))
                w = int(node.get("w", str(DEFAULT_NODE_W)))
                h = int(node.get("h", str(DEFAULT_NODE_H)))
            except ValueError:
                x, y, w, h = 0, 0, DEFAULT_NODE_W, DEFAULT_NODE_H
            fixed = x > 0 and y > 0
            nodes_payload.append({
                "id": node_id,
                "w": w if w > 0 else DEFAULT_NODE_W,
                "h": h if h > 0 else DEFAULT_NODE_H,
                "x": x,
                "y": y,
                "fixed": fixed,
                "layer": layer,
            })
            node_elements[node_id] = node
            node_id_by_element[element_ref] = node_id

        edges_payload: list[dict[str, str]] = []
        for conn in view.findall("am:connection", NS):
            conn_id = conn.get("identifier", "")
            src = conn.get("source", "")
            tgt = conn.get("target", "")
            if conn_id and src in node_elements and tgt in node_elements:
                edges_payload.append({"id": conn_id, "source": src, "target": tgt})

        if not nodes_payload:
            return

        # If every node already has positive coordinates, the view is
        # fully laid out from a previous save — skip the round-trip.
        # Pure label updates and relationship-only edits flow through
        # this branch and leave geometry untouched.
        if all(n["fixed"] for n in nodes_payload):
            return

        # Visual nesting: composition/aggregation relationships become
        # parent → child containment instead of edges. Pass the parent
        # map to layout-service so ELK uses a compound graph (children
        # inside the parent's bounding box) rather than flat nodes.
        nesting = self._detect_nesting_for_view(view, node_id_by_element)
        for child_id, parent_id in nesting.items():
            for node in nodes_payload:
                if node["id"] == child_id:
                    node["parent"] = parent_id
                    # Children with sentinel coords always get re-laid-out
                    # by ELK because their position is relative to a parent
                    # that may have moved.
                    node["fixed"] = False
                    break

        viewpoint = _detect_viewpoint(view)
        try:
            response = httpx.post(
                f"{LAYOUT_SERVICE_URL}/layout",
                json={
                    "nodes": nodes_payload,
                    "edges": edges_payload,
                    "viewpoint": viewpoint,
                },
                timeout=LAYOUT_SERVICE_TIMEOUT_S,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # network / json / status — all best-effort
            logger.warning(
                "layout_service_unreachable; keeping current positions: %s", exc
            )
            return

        if not data.get("success"):
            logger.warning("layout_service_failed: %s", data.get("error"))
            return

        for entry in data.get("nodes", []):
            node = node_elements.get(entry.get("id", ""))
            if node is None:
                continue
            node.set("x", str(int(entry.get("x", 0))))
            node.set("y", str(int(entry.get("y", 0))))
            if "w" in entry:
                node.set("w", str(int(entry["w"])))
            if "h" in entry:
                node.set("h", str(int(entry["h"])))

        # Z-order matters for visual nesting: parents must be drawn
        # before their children, otherwise the parent's background
        # rectangle covers the children. Both renderers iterate
        # nodes in document order, so we sort by area (largest first)
        # which naturally puts compound parents before their children.
        nodes_sorted = sorted(
            view.findall("am:node", NS),
            key=lambda n: int(n.get("w", "0")) * int(n.get("h", "0")),
            reverse=True,
        )
        # Re-insert in sorted order; ET preserves child order.
        for n in nodes_sorted:
            view.remove(n)
        # Re-append: nodes before connections so connection markers
        # render on top.
        connections = list(view.findall("am:connection", NS))
        for c in connections:
            view.remove(c)
        for n in nodes_sorted:
            view.append(n)
        for c in connections:
            view.append(c)

    def _layout_all_views(self) -> None:
        """Run ELK on every diagram-view in the model."""
        for view in self.root.findall("am:views/am:diagrams/am:view", NS):
            self._layout_view_via_service(view)

    # --- Save -----------------------------------------------------------

    def save(self) -> Path:
        """Write the in-memory tree to disk as canonical Open Exchange XML.

        Before serialising, calls the layout-service so every view's
        coordinates reflect the latest ELK result. This is what unifies
        the three rendering surfaces (interactive viewer, server-side
        SVG export, Archi-import) — all of them just read positions from
        the XML, so as long as the XML has good positions they all look
        the same.

        Uses ``ET.indent`` to produce stable, diff-friendly formatting.
        Does nothing if not dirty (idempotent saves are no-ops).
        """
        self._layout_all_views()
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
