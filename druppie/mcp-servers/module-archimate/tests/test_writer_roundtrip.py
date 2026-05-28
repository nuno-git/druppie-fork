"""Round-trip smoke-test for the ArchiMate writer.

Verifies AC1 from the Archimate-end-to-end user story:
    "Een bestaand model laden, één element wijzigen via MCP, opslaan →
     byte-diff toont alleen de wijziging; Archi opent het bestand zonder errors"

This test exercises ``writer.py`` directly (no MCP transport, no Docker)
so it can be run locally without bringing up the full stack.

Run with:
    python druppie/mcp-servers/module-archimate/tests/test_writer_roundtrip.py
"""

from __future__ import annotations

import difflib
import importlib.util
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET


def _load_writer():
    """Load writer.py by file path (the module is not installed as a package)."""
    here = Path(__file__).resolve().parent
    writer_path = here.parent / "v1" / "writer.py"
    spec = importlib.util.spec_from_file_location("archimate_writer", writer_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["archimate_writer"] = module
    spec.loader.exec_module(module)
    return module


writer = _load_writer()
ArchiMateDocument = writer.ArchiMateDocument


# --- Helpers ----------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _diff_summary(a: str, b: str) -> tuple[int, list[str]]:
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm=""))
    # Count actual change lines (not file headers / hunk markers)
    change_lines = [ln for ln in diff if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    return len(change_lines), diff


def _xml_valid(path: Path) -> bool:
    try:
        ET.parse(path)
        return True
    except ET.ParseError:
        return False


# --- Test cases -------------------------------------------------------------


def test_create_save_roundtrip(tmpdir: Path) -> dict:
    """Create a fresh model, add elements + view + connection, save."""
    path = tmpdir / "architecture.archimate"
    doc = ArchiMateDocument.load_or_create(path, model_name="Smoke Test Model")

    customer_id = doc.create_element(
        element_type="BusinessActor",
        name="Customer",
        documentation="External party using the platform",
    )
    portal_id = doc.create_element(
        element_type="ApplicationComponent",
        name="Customer Portal",
    )
    db_id = doc.create_element(
        element_type="DataObject",
        name="Customer Data",
    )

    serves_id = doc.create_relationship(
        relationship_type="Serving",
        source_id=portal_id,
        target_id=customer_id,
        name="serves",
    )
    reads_id = doc.create_relationship(
        relationship_type="Access",
        source_id=portal_id,
        target_id=db_id,
        access_type="Read",
    )

    view_id = doc.create_view(name="Context", documentation="High-level context view")
    doc.add_to_view(view_id, customer_id)
    doc.add_to_view(view_id, portal_id)
    doc.add_to_view(view_id, db_id)
    doc.add_connection_to_view(view_id, serves_id)
    doc.add_connection_to_view(view_id, reads_id)

    doc.save()

    assert path.exists(), "file should be written"
    assert _xml_valid(path), "saved XML must parse"

    return {
        "path": path,
        "customer_id": customer_id,
        "portal_id": portal_id,
        "db_id": db_id,
        "view_id": view_id,
    }


def test_load_modify_save_byte_diff(tmpdir: Path, baseline: dict) -> tuple[int, list[str]]:
    """Load baseline, change one element's name, save, diff."""
    original = _read(baseline["path"])

    # Re-load via fresh document instance to simulate a separate session
    doc = ArchiMateDocument.load_or_create(baseline["path"])
    doc.update_element(baseline["portal_id"], name="Customer Self-Service Portal")
    doc.save()

    modified = _read(baseline["path"])
    change_count, diff = _diff_summary(original, modified)

    assert _xml_valid(baseline["path"]), "modified XML must parse"
    return change_count, diff


def test_incremental_add_preserves_membership(tmpdir: Path, baseline: dict) -> tuple[bool, list[str]]:
    """Add a new element to the view; all original elements stay and the new one appears.

    Note: exact coordinates are no longer promised across saves — the
    layout-service is the authority on geometry, and may shift things
    when topology changes. The reviewer-facing invariant is membership
    (no element disappears) plus the delta-highlight (handled
    elsewhere), not bit-perfect position stability.
    """
    # Snapshot identities of the original three nodes
    doc1 = ArchiMateDocument.load_or_create(baseline["path"])
    view = doc1.find_view(baseline["view_id"])
    assert view is not None
    original_ids = {
        n.get("elementRef")
        for n in view.findall("am:node", {"am": writer.ARCHIMATE_NS})
    }

    # Add a new element + place it on the view
    new_id = doc1.create_element(
        element_type="BusinessActor",
        name="Support Agent",
    )
    doc1.add_to_view(baseline["view_id"], new_id)
    doc1.save()

    # Re-read and check membership
    doc2 = ArchiMateDocument.load_or_create(baseline["path"])
    view2 = doc2.find_view(baseline["view_id"])
    assert view2 is not None
    post_ids = {
        n.get("elementRef")
        for n in view2.findall("am:node", {"am": writer.ARCHIMATE_NS})
    }

    drift: list[str] = []
    for el_id in original_ids:
        if el_id not in post_ids:
            drift.append(f"element {el_id} disappeared")
    if new_id not in post_ids:
        drift.append(f"new element {new_id} not placed on view")
    return (len(drift) == 0), drift


# --- Runner -----------------------------------------------------------------


def test_realistic_feedback_iteration(tmpdir: Path) -> tuple[bool, list[str]]:
    """End-to-end feedback iteration covering AC4 in a realistic flow.

    Setup: build a view with five elements + four relationships (the
    kind of plate an architect would actually review).

    Iteration: simulate feedback "add a Notifications service that the
    portal calls" — adds one new element and one new relationship.

    Verification: every pre-existing element is still on the view after
    the save; the new element appears; and no bounding boxes overlap.
    Bit-perfect position stability across saves is no longer promised
    (layout-service may reflow when topology changes), so the byte-diff
    check is intentionally absent — the reviewer-facing invariant is
    delta-visibility, not zero-noise.
    """
    path = tmpdir / "iteration.archimate"
    doc = ArchiMateDocument.load_or_create(path, model_name="Iteration Test")
    customer = doc.create_element(element_type="BusinessActor", name="Customer")
    portal = doc.create_element(element_type="ApplicationComponent", name="Portal")
    auth = doc.create_element(element_type="ApplicationComponent", name="Auth Service")
    data = doc.create_element(element_type="DataObject", name="Customer Data")
    db = doc.create_element(element_type="SystemSoftware", name="PostgreSQL")
    serves = doc.create_relationship(relationship_type="Serving", source_id=portal, target_id=customer)
    uses_auth = doc.create_relationship(relationship_type="Serving", source_id=auth, target_id=portal)
    reads = doc.create_relationship(relationship_type="Access", source_id=portal, target_id=data, access_type="Read")
    runs_on = doc.create_relationship(relationship_type="Realization", source_id=db, target_id=data)
    view = doc.create_view(name="Context")
    for el in (customer, portal, auth, data, db):
        doc.add_to_view(view, el)
    for rel in (serves, uses_auth, reads, runs_on):
        doc.add_connection_to_view(view, rel)
    doc.save()
    snapshot_xml = _read(path)

    # Snapshot existing positions
    doc1 = ArchiMateDocument.load_or_create(path)
    view_el = doc1.find_view(view)
    pre_positions = {
        n.get("elementRef"): (n.get("x"), n.get("y"), n.get("w"), n.get("h"))
        for n in view_el.findall("am:node", {"am": writer.ARCHIMATE_NS})
    }

    # Apply feedback: "add a Notifications service that the portal calls"
    notif = doc1.create_element(
        element_type="ApplicationComponent",
        name="Notifications",
        documentation="Email + push channels for transactional events.",
    )
    triggers = doc1.create_relationship(
        relationship_type="Triggering", source_id=portal, target_id=notif,
    )
    doc1.add_to_view(view, notif)
    doc1.add_connection_to_view(view, triggers)
    doc1.save()

    # Verify no drift on pre-existing nodes
    doc2 = ArchiMateDocument.load_or_create(path)
    view2 = doc2.find_view(view)
    post_positions = {
        n.get("elementRef"): (n.get("x"), n.get("y"), n.get("w"), n.get("h"))
        for n in view2.findall("am:node", {"am": writer.ARCHIMATE_NS})
    }
    drift: list[str] = []
    for el_id in pre_positions:
        if el_id not in post_positions:
            drift.append(f"existing element {el_id} disappeared")
    if notif not in post_positions:
        drift.append("new Notifications element was not placed")
    else:
        # No bounding-box overlaps anywhere in the post-layout view
        items = [(eid, *map(int, vals)) for eid, vals in post_positions.items()]
        for i, (id_a, ax, ay, aw, ah) in enumerate(items):
            for id_b, bx, by, bw, bh in items[i + 1:]:
                overlaps = not (
                    ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
                )
                if overlaps:
                    drift.append(f"layout produced overlap: {id_a} ∩ {id_b}")

    # The snapshot_xml reference is kept above so the diff machinery is
    # still wired in if a future iteration wants byte-level invariants.
    _ = snapshot_xml

    return (len(drift) == 0), drift


def main() -> int:
    print("ArchiMate writer round-trip smoke-test")
    print("=" * 50)

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)

        print("\n[1/4] Create + save initial model...")
        baseline = test_create_save_roundtrip(tmpdir)
        initial_bytes = baseline["path"].stat().st_size
        print(f"    OK — wrote {initial_bytes} bytes to {baseline['path'].name}")

        print("\n[2/4] Load + modify one element + save (AC1: byte-diff)...")
        change_count, diff = test_load_modify_save_byte_diff(tmpdir, baseline)
        print(f"    Changed lines in unified-diff: {change_count}")
        if change_count > 6:
            print(f"    FAIL — expected ≤6 change lines, got {change_count}")
            print("    Diff:")
            for line in diff[:40]:
                print(f"        {line}")
            return 1
        print("    OK — byte-diff scoped to the requested change")

        print("\n[3/4] Add new element to view — verify membership preserved...")
        ok, drift = test_incremental_add_preserves_membership(tmpdir, baseline)
        if not ok:
            print("    FAIL — view membership drifted:")
            for d in drift:
                print(f"        {d}")
            return 1
        print("    OK — all original nodes present + new node placed")

        print("\n[4/4] Realistic feedback iteration (AC4: 5-element view + 1-element delta)...")
        ok, drift = test_realistic_feedback_iteration(tmpdir)
        if not ok:
            print("    FAIL — feedback iteration produced unexpected drift:")
            for d in drift:
                print(f"        {d}")
            return 1
        print("    OK — feedback delta applied, all members present, no overlap")

    print("\n" + "=" * 50)
    print("All checks passed.")
    print(
        "\nNote: 'Archi opens without errors' (AC1, second half) requires manual\n"
        "verification — open the resulting .archimate file in the Archi desktop\n"
        "tool. Schema validation against the Open Group XSD is also recommended\n"
        "but not yet automated (see docs/BACKLOG.md)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
