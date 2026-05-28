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
    elements_by_id: dict[str, dict[str, str]] = {}
    for el in root.findall("am:elements/am:element", NS):
        ident = _attr(el, "identifier")
        if ident:
            elements_by_id[ident] = {
                "name": _text_child(el, "name"),
                "type": _xsi_type(el),
                "layer": ELEMENT_TYPE_LAYER.get(_xsi_type(el), "Unknown"),
            }

    relationships_by_id: dict[str, dict[str, str]] = {}
    for rel in root.findall("am:relationships/am:relationship", NS):
        ident = _attr(rel, "identifier")
        if ident:
            relationships_by_id[ident] = {"type": _xsi_type(rel)}

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

    # Nodes
    node_xml_parts: list[str] = []
    node_by_id = {p["id"]: p for p in positioned}
    for p in positioned:
        info = elements_by_id.get(p["ref"], {})
        layer = info.get("layer", "Unknown")
        fill = LAYER_COLORS.get(layer, LAYER_COLORS["Unknown"])
        name = info.get("name") or "(unnamed)"
        layer_letter = LAYER_LETTER.get(layer, "")
        x = p["x"] + offset_x
        y = p["y"] + offset_y
        node_xml_parts.append(
            f'<g class="am-node">'
            f'<rect x="{x}" y="{y}" width="{p["w"]}" height="{p["h"]}" '
            f'rx="3" ry="3" fill="{fill}" stroke="#444" stroke-width="1.2"/>'
            f'<text x="{x + p["w"] - 8}" y="{y + 14}" font-family="Segoe UI,sans-serif" '
            f'font-size="10" font-weight="bold" fill="#888" text-anchor="end">{_escape(layer_letter)}</text>'
            f'<text x="{x + p["w"] // 2}" y="{y + p["h"] // 2 + 4}" '
            f'font-family="Segoe UI,sans-serif" font-size="11" fill="#222" '
            f'text-anchor="middle">{_escape(name)}</text>'
            f'</g>'
        )

    # Connections — straight center-to-center; server-side doesn't route.
    conn_xml_parts: list[str] = []
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
        sx = src["x"] + src["w"] // 2 + offset_x
        sy = src["y"] + src["h"] // 2 + offset_y
        tx = tgt["x"] + tgt["w"] // 2 + offset_x
        ty = tgt["y"] + tgt["h"] // 2 + offset_y
        dash = ' stroke-dasharray="5,4"' if style["line"] == "dashed" else ""
        start = f' marker-start="url(#{prefix}-{style["start"]})"' if style.get("start") else ""
        end = f' marker-end="url(#{prefix}-{style["end"]})"' if style.get("end") else ""
        conn_xml_parts.append(
            f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="#222" '
            f'stroke-width="1.2"{dash}{start}{end}/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'{_marker_defs(prefix)}'
        f'{"".join(conn_xml_parts)}'
        f'{"".join(node_xml_parts)}'
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
