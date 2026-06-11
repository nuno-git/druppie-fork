"""Server-side SVG export for ArchiMate views.

Produces an SVG file per view next to the saved .archimate model so the
plate is also visible directly in Gitea (which renders SVG files inline
in its file preview). The agent commits both files in the same git
commit, keeping the diagram + source in lock-step.

Design notes:
- Pure stdlib (no external deps) to keep the MCP image small.
- Renders existing geometry only — server-side does not run elkjs.
  Views without coordinates are skipped because all agent-generated
  views have positions assigned by writer.add_to_view's free-region
  heuristic.
- Visual conventions match the frontend renderer (layer colors,
  arrow markers per relationship type) so the Gitea preview looks
  the same as what the TD viewer shows.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from .writer import ARCHIMATE_NS, ELEMENT_TYPE_LAYER

NS = {"am": ARCHIMATE_NS}
XSI = "http://www.w3.org/2001/XMLSchema-instance"

LAYER_COLORS = {
    "Business": "#FFFFB5",
    "Application": "#B5FFFF",
    "Technology": "#C9E7B7",
    "Motivation": "#CCCCFF",
    "Strategy": "#F5DEAA",
    "Implementation": "#FFE0E0",
    "Physical": "#C9E7B7",
    "Other": "#F0F0F0",
    "Unknown": "#FFFFFF",
}

# NORA / IEC-62443 trust-level colours (Rijnland tekenafspraken). A security
# zone / security Constraint is coloured by its trust level instead of the
# standard layer colour. Kept in sync with the frontend renderer.
TRUST_COLORS = {
    "niet-vertrouwd": "#F4B6B6",
    "semi-vertrouwd": "#A6D785",
    "vertrouwd": "#F6D365",
    "zeer-vertrouwd": "#6FB04A",
}

# Single-letter layer badge — Wierda / Open Group convention.
# Replaces the previous 4-char truncated type-name ("Acto" / "Inte" /
# "Comp") which was unreadable.
LAYER_LETTER = {
    "Business": "B",
    "Application": "A",
    "Technology": "T",
    "Motivation": "M",
    "Strategy": "S",
    "Implementation": "I",
    "Physical": "P",
}

# --- ArchiMate shape + icon vocabulary -------------------------------------
# Until now every element rendered as an identical rounded rectangle, so a
# reviewer could not tell an actor from a process from a component — and the
# Rijnland "ownership decides the shape" rule (active structure vs behaviour
# vs SaaS-service) was invisible. We now vary the *box shape* by ArchiMate
# element category and stamp a small standard ArchiMate type-icon in the
# top-right corner. The JS renderer (archimateParser.js) mirrors this scheme
# 1:1 so the Gitea preview and the in-app viewer look identical.

_SERVICE_TYPES = {"BusinessService", "ApplicationService", "TechnologyService"}
_BEHAVIOR_TYPES = {
    "BusinessProcess", "BusinessFunction", "BusinessInteraction", "BusinessEvent",
    "ApplicationFunction", "ApplicationInteraction", "ApplicationProcess",
    "ApplicationEvent", "TechnologyFunction", "TechnologyProcess",
    "TechnologyInteraction", "TechnologyEvent",
}
_MOTIVATION_TYPES = {
    "Stakeholder", "Driver", "Assessment", "Goal", "Outcome", "Principle",
    "Requirement", "Constraint", "Meaning", "Value",
}
_GROUPING_TYPES = {"Grouping", "Location"}


def _node_radius(el_type: str, h: int) -> tuple[float, bool]:
    """Return (corner-radius, dashed?) for an element type.

    Service types render as a stadium (fully rounded ends) — the visual cue
    for a behaviour/SaaS element in the Rijnland tekenafspraken. Other
    behaviour and motivation types get softly rounded corners; grouping and
    location get a dashed border; active-structure and passive types stay
    square.
    """
    if el_type in _SERVICE_TYPES:
        return max(4, h / 2), False
    if el_type in _BEHAVIOR_TYPES:
        return 10, False
    if el_type in _MOTIVATION_TYPES:
        return 9, False
    if el_type in _GROUPING_TYPES:
        return 4, True
    return 2, False


def _icon_kind(t: str) -> str:
    """Map an ArchiMate type to a type-icon kind, or '' (→ layer-letter)."""
    if t in ("ApplicationCollaboration", "BusinessCollaboration", "TechnologyCollaboration"):
        return "collab"
    if t == "ApplicationComponent":
        return "component"
    if t == "BusinessActor":
        return "actor"
    if t in ("BusinessRole", "Stakeholder"):
        return "role"
    if t in _SERVICE_TYPES:
        return "service"
    if t.endswith("Interface"):
        return "interface"
    if t.endswith("Process"):
        return "process"
    if t.endswith("Function"):
        return "function"
    if t.endswith("Event"):
        return "event"
    if t in ("DataObject", "BusinessObject"):
        return "object"
    if t == "Artifact":
        return "artifact"
    if t == "Node":
        return "node"
    if t == "Device":
        return "device"
    if t == "SystemSoftware":
        return "syssoft"
    if t == "Driver":
        return "driver"
    if t in ("Goal", "Outcome"):
        return "goal"
    if t == "Principle":
        return "principle"
    if t == "Requirement":
        return "requirement"
    if t == "Constraint":
        return "constraint"
    if t == "Plateau":
        return "plateau"
    return ""


def _type_icon_svg(el_type: str, ix: float, iy: float) -> str:
    """Return a ~15px ArchiMate type icon anchored at (ix, iy), or ''."""
    kind = _icon_kind(el_type)
    if not kind:
        return ""
    s = 'fill="none" stroke="#555" stroke-width="1.1"'
    sf = 'fill="#fff" stroke="#555" stroke-width="1.1"'
    if kind == "component":
        return (
            f'<rect x="{ix+3}" y="{iy}" width="11" height="14" {sf}/>'
            f'<rect x="{ix}" y="{iy+2}" width="5" height="3.5" {sf}/>'
            f'<rect x="{ix}" y="{iy+8}" width="5" height="3.5" {sf}/>'
        )
    if kind == "collab":
        return (
            f'<circle cx="{ix+5}" cy="{iy+7}" r="4.5" {s}/>'
            f'<circle cx="{ix+10}" cy="{iy+7}" r="4.5" {s}/>'
        )
    if kind == "actor":
        return (
            f'<circle cx="{ix+7}" cy="{iy+2}" r="2.2" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+4}" x2="{ix+7}" y2="{iy+10}" {s}/>'
            f'<line x1="{ix+2}" y1="{iy+6}" x2="{ix+12}" y2="{iy+6}" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+10}" x2="{ix+3}" y2="{iy+14}" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+10}" x2="{ix+11}" y2="{iy+14}" {s}/>'
        )
    if kind == "role":
        return (
            f'<circle cx="{ix+9}" cy="{iy+7}" r="4" {s}/>'
            f'<line x1="{ix+1}" y1="{iy+4}" x2="{ix+1}" y2="{iy+10}" {s}/>'
            f'<line x1="{ix+1}" y1="{iy+7}" x2="{ix+5}" y2="{iy+7}" {s}/>'
        )
    if kind == "service":
        return f'<rect x="{ix}" y="{iy+3}" width="15" height="9" rx="4.5" ry="4.5" {s}/>'
    if kind == "interface":
        return (
            f'<line x1="{ix}" y1="{iy+7}" x2="{ix+7}" y2="{iy+7}" {s}/>'
            f'<circle cx="{ix+10}" cy="{iy+7}" r="3.2" {s}/>'
        )
    if kind == "process":
        return (
            f'<path d="M {ix} {iy+3} L {ix+8} {iy+3} L {ix+8} {iy} '
            f'L {ix+14} {iy+7} L {ix+8} {iy+14} L {ix+8} {iy+11} '
            f'L {ix} {iy+11} Z" {s}/>'
        )
    if kind == "function":
        return (
            f'<path d="M {ix+7} {iy} L {ix+14} {iy+5} L {ix+11} {iy+14} '
            f'L {ix+3} {iy+14} L {ix} {iy+5} Z" {s}/>'
        )
    if kind == "event":
        return (
            f'<path d="M {ix} {iy+2} L {ix+10} {iy+2} L {ix+14} {iy+7} '
            f'L {ix+10} {iy+12} L {ix} {iy+12} L {ix+3} {iy+7} Z" {s}/>'
        )
    if kind == "object":
        return (
            f'<rect x="{ix}" y="{iy+1}" width="14" height="12" {s}/>'
            f'<line x1="{ix}" y1="{iy+5}" x2="{ix+14}" y2="{iy+5}" {s}/>'
        )
    if kind == "artifact":
        return (
            f'<path d="M {ix+1} {iy} L {ix+9} {iy} L {ix+13} {iy+4} '
            f'L {ix+13} {iy+14} L {ix+1} {iy+14} Z" {s}/>'
            f'<path d="M {ix+9} {iy} L {ix+9} {iy+4} L {ix+13} {iy+4}" {s}/>'
        )
    if kind == "node":
        return (
            f'<rect x="{ix}" y="{iy+4}" width="10" height="10" {s}/>'
            f'<path d="M {ix} {iy+4} L {ix+4} {iy} L {ix+14} {iy} L {ix+10} {iy+4}" {s}/>'
            f'<path d="M {ix+10} {iy+14} L {ix+14} {iy+10} L {ix+14} {iy}" {s}/>'
        )
    if kind == "device":
        return (
            f'<rect x="{ix+1}" y="{iy+1}" width="12" height="8" rx="1.5" {s}/>'
            f'<path d="M {ix-1} {iy+13} L {ix+15} {iy+13} L {ix+12} {iy+9} L {ix+2} {iy+9} Z" {s}/>'
        )
    if kind == "syssoft":
        return (
            f'<ellipse cx="{ix+7}" cy="{iy+4}" rx="6.5" ry="3" {s}/>'
            f'<path d="M {ix+0.5} {iy+4} L {ix+0.5} {iy+10}" {s}/>'
            f'<path d="M {ix+13.5} {iy+4} L {ix+13.5} {iy+10}" {s}/>'
            f'<path d="M {ix+0.5} {iy+10} A 6.5 3 0 0 0 {ix+13.5} {iy+10}" {s}/>'
        )
    if kind == "driver":
        return (
            f'<circle cx="{ix+7}" cy="{iy+7}" r="6" {s}/>'
            f'<circle cx="{ix+7}" cy="{iy+7}" r="1.6" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+1}" x2="{ix+7}" y2="{iy+13}" {s}/>'
            f'<line x1="{ix+1}" y1="{iy+7}" x2="{ix+13}" y2="{iy+7}" {s}/>'
        )
    if kind == "goal":
        return (
            f'<circle cx="{ix+7}" cy="{iy+7}" r="6" {s}/>'
            f'<circle cx="{ix+7}" cy="{iy+7}" r="2.5" {s}/>'
        )
    if kind == "principle":
        return (
            f'<circle cx="{ix+7}" cy="{iy+7}" r="6" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+3}" x2="{ix+7}" y2="{iy+11}" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+3}" x2="{ix+4.5}" y2="{iy+6}" {s}/>'
            f'<line x1="{ix+7}" y1="{iy+3}" x2="{ix+9.5}" y2="{iy+6}" {s}/>'
        )
    if kind == "requirement":
        return f'<path d="M {ix+3} {iy+1} L {ix+14} {iy+1} L {ix+11} {iy+13} L {ix} {iy+13} Z" {s}/>'
    if kind == "constraint":
        return (
            f'<path d="M {ix+3} {iy+1} L {ix+14} {iy+1} L {ix+11} {iy+13} L {ix} {iy+13} Z" {s}/>'
            f'<line x1="{ix+2}" y1="{iy+7}" x2="{ix+12}" y2="{iy+7}" {s}/>'
        )
    if kind == "plateau":
        return (
            f'<rect x="{ix}" y="{iy+1}" width="14" height="3" {sf}/>'
            f'<rect x="{ix}" y="{iy+6}" width="14" height="3" {sf}/>'
            f'<rect x="{ix}" y="{iy+11}" width="14" height="3" {sf}/>'
        )
    return ""


def _border_point(cx: float, cy: float, w: int, h: int, tx: float, ty: float) -> tuple[float, float]:
    """Point where the line from box-centre (cx,cy) toward (tx,ty) exits the box."""
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw = w / 2.0
    hh = h / 2.0
    sx = hw / abs(dx) if dx else float("inf")
    sy = hh / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


CONNECTION_STYLE = {
    "Composition":    {"line": "solid",  "start": "diamond-filled", "end": None},
    "Aggregation":    {"line": "solid",  "start": "diamond-open",   "end": None},
    "Assignment":     {"line": "solid",  "start": "circle-filled",  "end": "circle-filled"},
    "Realization":    {"line": "dashed", "start": None,             "end": "triangle-open"},
    "Serving":        {"line": "solid",  "start": None,             "end": "arrow-open"},
    "Access":         {"line": "dashed", "start": None,             "end": "arrow-filled"},
    "Triggering":     {"line": "solid",  "start": None,             "end": "arrow-filled"},
    "Flow":           {"line": "dashed", "start": None,             "end": "arrow-filled"},
    "Specialization": {"line": "solid",  "start": None,             "end": "triangle-open"},
    "Influence":      {"line": "dashed", "start": None,             "end": "arrow-open"},
    "Association":    {"line": "solid",  "start": None,             "end": None},
}

PAD = 20


def _safe_filename(name: str) -> str:
    """Convert a view name to a filesystem-safe filename."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    return s or "view"


def _escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&apos;")
    )


def _text_child(parent: ET.Element, tag: str) -> str:
    child = parent.find(f"am:{tag}", NS)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _attr(el: ET.Element, name: str) -> str:
    return el.get(name) or ""


def _build_propdef_names(root: ET.Element) -> dict[str, str]:
    """Map propertyDefinition identifier -> name (for stereotype/trust read-back)."""
    out: dict[str, str] = {}
    for pd in root.findall("am:propertyDefinitions/am:propertyDefinition", NS):
        ident = pd.get("identifier") or ""
        name_el = pd.find("am:name", NS)
        if ident and name_el is not None:
            out[ident] = name_el.text or ""
    return out


def _read_property(el: ET.Element, prop_name: str, propdef_names: dict[str, str]) -> str:
    """Return the value of a named property marker on an element, or ''."""
    props = el.find("am:properties", NS)
    if props is None:
        return ""
    for prop in props.findall("am:property", NS):
        if propdef_names.get(prop.get("propertyDefinitionRef") or "") == prop_name:
            val = prop.find("am:value", NS)
            if val is not None:
                return (val.text or "").strip()
    return ""


def _trust_level_of(info: dict[str, str]) -> str:
    """Detect a NORA trust level from an element's trust-level property or name."""
    hay = f"{info.get('trust', '')} {info.get('name', '')}".lower()
    for level in TRUST_COLORS:
        if level in hay:
            return level
    return ""


def _xsi_type(el: ET.Element) -> str:
    return el.get(f"{{{XSI}}}type", "") or "Unknown"


def _marker_defs(prefix: str) -> str:
    return (
        f'<defs>'
        f'<marker id="{prefix}-arrow-filled" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="8" markerHeight="8" orient="auto">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="#222"/></marker>'
        f'<marker id="{prefix}-arrow-open" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="8" markerHeight="8" orient="auto">'
        f'<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="#222" stroke-width="1.2"/></marker>'
        f'<marker id="{prefix}-triangle-open" viewBox="0 0 12 12" refX="11" refY="6" '
        f'markerWidth="10" markerHeight="10" orient="auto">'
        f'<path d="M 0 0 L 12 6 L 0 12 z" fill="#fff" stroke="#222" stroke-width="1.2"/></marker>'
        f'<marker id="{prefix}-diamond-filled" viewBox="0 0 12 12" refX="1" refY="6" '
        f'markerWidth="10" markerHeight="10" orient="auto">'
        f'<path d="M 0 6 L 6 0 L 12 6 L 6 12 z" fill="#222"/></marker>'
        f'<marker id="{prefix}-diamond-open" viewBox="0 0 12 12" refX="1" refY="6" '
        f'markerWidth="10" markerHeight="10" orient="auto">'
        f'<path d="M 0 6 L 6 0 L 12 6 L 6 12 z" fill="#fff" stroke="#222" stroke-width="1.2"/></marker>'
        f'<marker id="{prefix}-circle-filled" viewBox="0 0 8 8" refX="4" refY="4" '
        f'markerWidth="6" markerHeight="6" orient="auto">'
        f'<circle cx="4" cy="4" r="3" fill="#222"/></marker>'
        f'</defs>'
    )


def render_view_svg(root: ET.Element, view: ET.Element) -> str | None:
    """Render a single ArchiMate view to an SVG string.

    Returns ``None`` if the view has no positioned nodes — server-side
    cannot run auto-layout, so unpositioned views are deferred to the
    frontend (where elkjs runs in the browser).
    """
    nodes = view.findall("am:node", NS)
    if not nodes:
        return None

    # Build element + relationship lookup tables
    propdef_names = _build_propdef_names(root)
    elements_by_id: dict[str, dict[str, str]] = {}
    for el in root.findall("am:elements/am:element", NS):
        ident = _attr(el, "identifier")
        if ident:
            elements_by_id[ident] = {
                "name": _text_child(el, "name"),
                "type": _xsi_type(el),
                "layer": ELEMENT_TYPE_LAYER.get(_xsi_type(el), "Unknown"),
                "stereotype": _read_property(el, "stereotype", propdef_names),
                "trust": _read_property(el, "trust-level", propdef_names),
            }

    relationships_by_id: dict[str, dict[str, str]] = {}
    for rel in root.findall("am:relationships/am:relationship", NS):
        ident = _attr(rel, "identifier")
        if ident:
            relationships_by_id[ident] = {
                "type": _xsi_type(rel),
                "name": _text_child(rel, "name"),
            }

    # Collect positioned nodes
    positioned = []
    for n in nodes:
        try:
            x = int(_attr(n, "x") or "0")
            y = int(_attr(n, "y") or "0")
            w = int(_attr(n, "w") or "120")
            h = int(_attr(n, "h") or "55")
        except ValueError:
            continue
        if w <= 0 or h <= 0:
            continue
        positioned.append({
            "id": _attr(n, "identifier"),
            "ref": _attr(n, "elementRef"),
            "x": x, "y": y, "w": w, "h": h,
        })

    if not positioned or not any(p["x"] > 0 or p["y"] > 0 for p in positioned):
        return None

    min_x = min(p["x"] for p in positioned)
    min_y = min(p["y"] for p in positioned)
    max_x = max(p["x"] + p["w"] for p in positioned)
    max_y = max(p["y"] + p["h"] for p in positioned)
    width = max_x - min_x + 2 * PAD
    height = max_y - min_y + 2 * PAD
    offset_x = PAD - min_x
    offset_y = PAD - min_y

    view_id = _attr(view, "identifier") or "view"
    prefix = f"am-{view_id[-8:]}"

    # Layer bands — a full-width horizontal stripe per ArchiMate layer that
    # contains elements. Every band spans the same x-range (the whole canvas)
    # and only varies in y, so they read as clean Motivation → Business →
    # Application → Technology stripes instead of the ragged per-layer
    # bounding boxes we drew before (different widths/offsets that looked
    # "scattered"). A faded uppercase caption sits in the band's top padding.
    band_xml_parts: list[str] = []
    layer_yranges: dict[str, list[int]] = {}
    for p in positioned:
        info = elements_by_id.get(p["ref"], {})
        layer = info.get("layer", "Unknown")
        if layer in ("Unknown", "Other"):
            continue
        y = p["y"] + offset_y
        yr = layer_yranges.get(layer)
        if yr is None:
            layer_yranges[layer] = [y, y + p["h"]]
        else:
            yr[0] = min(yr[0], y)
            yr[1] = max(yr[1], y + p["h"])
    band_left = PAD - 8
    band_w = (width - 2 * PAD) + 16
    _BAND_ORDER = {"Motivation": 0, "Strategy": 1, "Business": 2,
                   "Application": 3, "Technology": 4, "Physical": 5,
                   "Implementation": 6}
    for layer in sorted(layer_yranges, key=lambda L: _BAND_ORDER.get(L, 9)):
        ly, ry = layer_yranges[layer]
        fill = LAYER_COLORS.get(layer, "#FFFFFF")
        band_xml_parts.append(
            f'<rect x="{band_left}" y="{ly - 14}" width="{band_w}" '
            f'height="{ry - ly + 28}" rx="6" ry="6" fill="{fill}" '
            f'fill-opacity="0.18" stroke="none"/>'
            f'<text x="{band_left + 8}" y="{ly - 4}" font-family="Segoe UI,sans-serif" '
            f'font-size="9" font-weight="bold" letter-spacing="1" fill="#888" '
            f'fill-opacity="0.7">{_escape(layer.upper())}</text>'
        )

    # Containers: any node whose bbox fully encloses at least one other
    # node is treated as a visual parent (composition nesting). Its label
    # has to render at the top — centring it would put it on top of the
    # children's labels and make both unreadable.
    container_ids: set[str] = set()
    for a in positioned:
        for b in positioned:
            if a["id"] == b["id"]:
                continue
            if (a["x"] <= b["x"] and a["y"] <= b["y"]
                    and a["x"] + a["w"] >= b["x"] + b["w"]
                    and a["y"] + a["h"] >= b["y"] + b["h"]):
                container_ids.add(a["id"])
                break

    # Nodes — shape varies by ArchiMate category (service=stadium,
    # behaviour=rounded, grouping=dashed, structure=square) and a standard
    # type-icon sits top-right (falling back to the layer letter).
    node_xml_parts: list[str] = []
    node_by_id = {p["id"]: p for p in positioned}
    for p in positioned:
        info = elements_by_id.get(p["ref"], {})
        layer = info.get("layer", "Unknown")
        el_type = info.get("type", "")
        name = info.get("name") or "(unnamed)"
        stereotype = info.get("stereotype", "")
        # NORA exception: a security zone / Constraint is coloured by trust level.
        trust = _trust_level_of(info)
        is_security = stereotype == "Beveiligingsdomein" or el_type == "Constraint"
        fill = TRUST_COLORS[trust] if (trust and is_security) else LAYER_COLORS.get(layer, LAYER_COLORS["Unknown"])
        x = p["x"] + offset_x
        y = p["y"] + offset_y
        rx, dashed = _node_radius(el_type, p["h"])
        node_dash = ' stroke-dasharray="6,4"' if dashed else ""
        # Type icon top-right; fall back to the single-letter layer badge.
        icon = _type_icon_svg(el_type, x + p["w"] - 21, y + 5)
        corner = icon or (
            f'<text x="{x + p["w"] - 8}" y="{y + 14}" font-family="Segoe UI,sans-serif" '
            f'font-size="10" font-weight="bold" fill="#888" text-anchor="end">'
            f'{_escape(LAYER_LETTER.get(layer, ""))}</text>'
        )
        is_container = p["id"] in container_ids
        # Container labels go in a header strip at the top; leaf labels stay centred.
        # Leave room on the right so a long centred label doesn't run under the icon.
        label_x = x + 12 if is_container else x + (p["w"] - 18) // 2
        base_y = y + 16 if is_container else y + p["h"] // 2 + 4
        label_y = base_y + 6 if (stereotype and not is_container) else base_y
        stereo_y = y + 30 if is_container else label_y - 12
        label_anchor = "start" if is_container else "middle"
        stereo_xml = (
            f'<text x="{label_x}" y="{stereo_y}" font-family="Segoe UI,sans-serif" '
            f'font-size="9" font-style="italic" fill="#555" '
            f'text-anchor="{label_anchor}">«{_escape(stereotype)}»</text>'
            if stereotype else ""
        )
        node_xml_parts.append(
            f'<g class="am-node">'
            f'<rect x="{x}" y="{y}" width="{p["w"]}" height="{p["h"]}" '
            f'rx="{rx}" ry="{rx}" fill="{fill}" stroke="#444" stroke-width="1.2"{node_dash}/>'
            f'{corner}'
            f'{stereo_xml}'
            f'<text x="{label_x}" y="{label_y}" '
            f'font-family="Segoe UI,sans-serif" font-size="11" '
            f'font-weight="{"bold" if is_container else "normal"}" fill="#222" '
            f'text-anchor="{label_anchor}">{_escape(name)}</text>'
            f'</g>'
        )

    # Connections — use ELK's orthogonal routing (persisted as <bendpoint>s)
    # when present, otherwise a straight line clipped to the box borders so
    # the arrowhead lands on the edge instead of hiding under the target.
    conn_xml_parts: list[str] = []
    label_xml_parts: list[str] = []
    for c in view.findall("am:connection", NS):
        src = node_by_id.get(_attr(c, "source"))
        tgt = node_by_id.get(_attr(c, "target"))
        rel = relationships_by_id.get(_attr(c, "relationshipRef"))
        if not src or not tgt:
            continue
        rel_type = rel["type"] if rel else "Association"
        # Skip Composition / Aggregation when one node visually contains
        # the other — the nesting *is* the relationship, drawing the
        # diamond marker inside the parent looks redundant and noisy.
        if rel_type in ("Composition", "Aggregation"):
            def _contains(a, b):
                return (
                    a["x"] <= b["x"]
                    and a["y"] <= b["y"]
                    and a["x"] + a["w"] >= b["x"] + b["w"]
                    and a["y"] + a["h"] >= b["y"] + b["h"]
                )
            if _contains(src, tgt) or _contains(tgt, src):
                continue
        style = CONNECTION_STYLE.get(rel_type, CONNECTION_STYLE["Association"])
        dash = ' stroke-dasharray="5,4"' if style["line"] == "dashed" else ""
        start = f' marker-start="url(#{prefix}-{style["start"]})"' if style.get("start") else ""
        end = f' marker-end="url(#{prefix}-{style["end"]})"' if style.get("end") else ""

        pts = [
            (int(b.get("x", "0")) + offset_x, int(b.get("y", "0")) + offset_y)
            for b in c.findall("am:bendpoint", NS)
        ]
        if len(pts) >= 2:
            points_attr = " ".join(f"{px},{py}" for px, py in pts)
            conn_xml_parts.append(
                f'<polyline points="{points_attr}" fill="none" stroke="#222" '
                f'stroke-width="1.2"{dash}{start}{end}/>'
            )
            mid = pts[len(pts) // 2]
            lx, ly = mid
        else:
            scx = src["x"] + src["w"] / 2 + offset_x
            scy = src["y"] + src["h"] / 2 + offset_y
            tcx = tgt["x"] + tgt["w"] / 2 + offset_x
            tcy = tgt["y"] + tgt["h"] / 2 + offset_y
            sx, sy = _border_point(scx, scy, src["w"], src["h"], tcx, tcy)
            tx, ty = _border_point(tcx, tcy, tgt["w"], tgt["h"], scx, scy)
            conn_xml_parts.append(
                f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                f'stroke="#222" stroke-width="1.2"{dash}{start}{end}/>'
            )
            lx, ly = (sx + tx) / 2, (sy + ty) / 2

        rel_name = rel.get("name", "") if rel else ""
        if rel_name:
            tw = len(rel_name) * 5.4 + 6
            label_xml_parts.append(
                f'<rect x="{lx - tw / 2:.1f}" y="{ly - 7:.1f}" width="{tw:.1f}" height="13" '
                f'rx="2" fill="#fff" fill-opacity="0.72" stroke="none"/>'
                f'<text x="{lx:.1f}" y="{ly + 3:.1f}" font-family="Segoe UI,sans-serif" '
                f'font-size="9" fill="#444" text-anchor="middle">{_escape(rel_name)}</text>'
            )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'{_marker_defs(prefix)}'
        f'{"".join(band_xml_parts)}'
        f'{"".join(conn_xml_parts)}'
        f'{"".join(node_xml_parts)}'
        f'{"".join(label_xml_parts)}'
        f'</svg>'
    )


def export_all_views(model_root: ET.Element, target_dir: Path) -> list[Path]:
    """Render every positioned view in ``model_root`` to an SVG under ``target_dir``.

    Returns the list of written paths. Unpositioned views are skipped.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for view in model_root.findall("am:views/am:diagrams/am:view", NS):
        svg = render_view_svg(model_root, view)
        if svg is None:
            continue
        name = _text_child(view, "name") or _attr(view, "identifier") or "view"
        path = target_dir / f"{_safe_filename(name)}.svg"
        path.write_text(svg, encoding="utf-8")
        written.append(path)
    return written
