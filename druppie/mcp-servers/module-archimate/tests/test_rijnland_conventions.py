"""Tests for the Rijnland / waterschap tekenafspraken layer.

Covers the convention enforcement added on top of the generic ArchiMate
writer + validator:
  1. ``create_element`` persists a ``stereotype`` and rejects it on the
     wrong ArchiMate type (the tekenafspraken pin each concept to one type).
  2. The Implementation layer (Plateau) is creatable for SOLL / project plates.
  3. ``validate_view`` flags a Beveiligingsdomein with no trust level and a
     stereotype carried on the wrong type — but stays silent on a clean,
     non-stereotyped (non-waterschap) plate.

Exercises ``writer.py`` and ``write_tools.py`` directly (no MCP transport,
no Docker), so it runs locally without the full stack.

Run with:
    python druppie/mcp-servers/module-archimate/tests/test_rijnland_conventions.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path


def _load_v1():
    """Load the v1 modules as a synthetic package so relative imports resolve.

    ``write_tools.py`` does ``from .writer import ...`` / ``from .svg_export
    import ...``; loading it standalone needs a package context. We register
    a throwaway ``amv1`` package pointing at the v1 directory and load the
    three modules into it in dependency order.
    """
    v1 = Path(__file__).resolve().parent.parent / "v1"
    pkg = types.ModuleType("amv1")
    pkg.__path__ = [str(v1)]
    sys.modules["amv1"] = pkg
    for name in ("writer", "svg_export", "write_tools"):
        spec = importlib.util.spec_from_file_location(f"amv1.{name}", v1 / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"amv1.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["amv1.writer"], sys.modules["amv1.write_tools"]


writer, write_tools = _load_v1()
ArchiMateDocument = writer.ArchiMateDocument
ArchiMateWriteError = writer.ArchiMateWriteError


def _fresh_doc():
    """An empty ArchiMate document backed by a throwaway temp path."""
    tmp = Path(tempfile.mkdtemp()) / "architecture.archimate"
    return ArchiMateDocument.load_or_create(tmp, model_name="Test model")


def _fail(msg: str):
    print(f"    FAIL — {msg}")
    sys.exit(1)


# --- Tests ------------------------------------------------------------------


def test_stereotype_persists_on_correct_type():
    print("[1/8] stereotype persists on the prescribed type...")
    doc = _fresh_doc()
    eid = doc.create_element(
        element_type="BusinessRole", name="Watersysteembeheer", stereotype="Account"
    )
    el = doc.find_element(eid)
    if el is None:
        _fail("element not found after create")
    stereo = write_tools._read_property(doc, el, "stereotype")
    if stereo != "Account":
        _fail(f"expected stereotype 'Account', got {stereo!r}")
    print("    OK — Account stereotype stored and read back")


def test_stereotype_rejected_on_wrong_type():
    print("[2/8] stereotype rejected on the wrong type...")
    doc = _fresh_doc()
    try:
        # Account must be a BusinessRole, not a BusinessActor.
        doc.create_element(
            element_type="BusinessActor", name="X", stereotype="Account"
        )
    except ArchiMateWriteError:
        print("    OK — wrong type rejected at create-time")
        return
    _fail("expected ArchiMateWriteError for Account on BusinessActor")


def test_ownership_behavior_type_accepted():
    print("[3/8] consumed concept on a behavior type is accepted...")
    doc = _fresh_doc()
    # 'Applicatie als service' (SaaS we consume) -> ApplicationService.
    eid = doc.create_element(
        element_type="ApplicationService",
        name="Zaaksysteem SaaS",
        stereotype="Applicatie als service",
    )
    if doc.find_element(eid) is None:
        _fail("behavior-typed concept was not created")
    print("    OK — ApplicationService accepts 'Applicatie als service'")


def test_plateau_implementation_layer():
    print("[4/8] Plateau (Implementation layer) is creatable...")
    doc = _fresh_doc()
    eid = doc.create_element(element_type="Plateau", name="SOLL 2026-Q1")
    if doc.find_element(eid) is None:
        _fail("Plateau was not created")
    if writer.ELEMENT_TYPE_LAYER.get("Plateau") != "Implementation":
        _fail("Plateau is not mapped to the Implementation layer")
    print("    OK — Plateau creatable, mapped to Implementation")


def test_security_domain_without_trust_is_flagged():
    print("[5/8] validate_view flags a Beveiligingsdomein with no trust level...")
    doc = _fresh_doc()
    gid = doc.create_element(
        element_type="Grouping", name="DMZ Servers", stereotype="Beveiligingsdomein"
    )
    vid = doc.create_view(name="Zones", documentation="")
    doc.add_to_view(vid, gid)
    view = doc.find_view(vid)
    errors = write_tools._validate_view_impl(doc, view)
    codes = {e["code"] for e in errors}
    if "security_domain_missing_trust" not in codes:
        _fail(f"expected security_domain_missing_trust, got {codes}")

    # Same zone, now with a NORA level in the name -> no trust error.
    doc2 = _fresh_doc()
    gid2 = doc2.create_element(
        element_type="Grouping",
        name="DMZ Servers (semi-vertrouwd)",
        stereotype="Beveiligingsdomein",
    )
    vid2 = doc2.create_view(name="Zones", documentation="")
    doc2.add_to_view(vid2, gid2)
    errors2 = write_tools._validate_view_impl(doc2, doc2.find_view(vid2))
    codes2 = {e["code"] for e in errors2}
    if "security_domain_missing_trust" in codes2:
        _fail("trust level in name should clear the error")
    print("    OK — missing trust flagged, present trust clears it")


def test_account_on_plain_role_is_flagged():
    print("[7/8] validate_view warns about «Account» on an ordinary role...")
    doc = _fresh_doc()
    # Misapplied: a handling team stereotyped as Account.
    rid = doc.create_element(
        element_type="BusinessRole", name="Behandelteam", stereotype="Account"
    )
    vid = doc.create_view(name="Org", documentation="")
    doc.add_to_view(vid, rid)
    errors = write_tools._validate_view_impl(doc, doc.find_view(vid))
    if "account_likely_plain_role" not in {e["code"] for e in errors}:
        _fail("expected account_likely_plain_role for 'Behandelteam'")

    # A genuine governance account is not flagged.
    doc2 = _fresh_doc()
    aid = doc2.create_element(
        element_type="BusinessRole", name="Watersysteembeheer", stereotype="Account"
    )
    vid2 = doc2.create_view(name="Org", documentation="")
    doc2.add_to_view(vid2, aid)
    errors2 = write_tools._validate_view_impl(doc2, doc2.find_view(vid2))
    if "account_likely_plain_role" in {e["code"] for e in errors2}:
        _fail("a genuine account name should not be flagged")
    print("    OK — misapplied Account flagged, genuine account clean")


def test_clean_plate_has_no_rijnland_noise():
    print("[8/8] a non-stereotyped plate gets no Rijnland errors...")
    doc = _fresh_doc()
    a = doc.create_element(element_type="ApplicationComponent", name="Portal")
    b = doc.create_element(element_type="DataObject", name="Customer")
    rid = doc.create_relationship(
        relationship_type="Access", source_id=a, target_id=b, access_type="Write"
    )
    vid = doc.create_view(name="App", documentation="")
    doc.add_to_view(vid, a)
    doc.add_to_view(vid, b)
    doc.add_connection_to_view(vid, rid)
    errors = write_tools._validate_view_impl(doc, doc.find_view(vid))
    rijnland_codes = {
        e["code"] for e in errors
        if e["code"] in {"rijnland_stereotype_type", "security_domain_missing_trust"}
    }
    if rijnland_codes:
        _fail(f"non-waterschap plate should be clean, got {rijnland_codes}")
    print("    OK — no Rijnland false positives on a generic plate")


def _view_with_rel(doc, src_type, src_name, tgt_type, tgt_name, rel_type, **rel_kw):
    """Helper: a one-relationship view, returns its validation error codes."""
    a = doc.create_element(element_type=src_type, name=src_name)
    b = doc.create_element(element_type=tgt_type, name=tgt_name)
    rid = doc.create_relationship(
        relationship_type=rel_type, source_id=a, target_id=b, **rel_kw
    )
    vid = doc.create_view(name="V", documentation="")
    doc.add_to_view(vid, a)
    doc.add_to_view(vid, b)
    doc.add_connection_to_view(vid, rid)
    errors = write_tools._validate_view_impl(doc, doc.find_view(vid))
    return {e["code"] for e in errors}


def test_triggering_from_active_structure_is_flagged():
    print("[9/12] validate_view flags an actor triggering a process...")
    codes = _view_with_rel(
        _fresh_doc(), "BusinessActor", "Burger",
        "BusinessProcess", "Melding indienen", "Triggering",
    )
    if "triggering_from_active_structure" not in codes:
        _fail(f"expected triggering_from_active_structure, got {codes}")
    # The same shape as Assignment is clean.
    codes_ok = _view_with_rel(
        _fresh_doc(), "BusinessActor", "Burger",
        "BusinessProcess", "Melding indienen", "Assignment",
    )
    if "triggering_from_active_structure" in codes_ok or "assignment_from_behavior" in codes_ok:
        _fail(f"actor → process Assignment should be clean, got {codes_ok}")
    print("    OK — actor→process Triggering flagged, Assignment clean")


def test_cross_aspect_flow_is_flagged():
    print("[10/12] validate_view flags a process flowing into a component...")
    codes = _view_with_rel(
        _fresh_doc(), "BusinessProcess", "Melding indienen",
        "ApplicationComponent", "Meldportaal", "Flow",
    )
    if "flow_invalid_endpoints" not in codes:
        _fail(f"expected flow_invalid_endpoints, got {codes}")
    # Flow between two services (behaviour↔behaviour) is fine.
    codes_ok = _view_with_rel(
        _fresh_doc(), "ApplicationService", "A",
        "ApplicationService", "B", "Flow",
    )
    if "flow_invalid_endpoints" in codes_ok:
        _fail(f"service→service Flow should be clean, got {codes_ok}")
    print("    OK — cross-aspect Flow flagged, behaviour↔behaviour clean")


def test_serving_direction_is_flagged():
    print("[11/12] validate_view flags Application serving Technology...")
    codes = _view_with_rel(
        _fresh_doc(), "ApplicationComponent", "Meldportaal",
        "SystemSoftware", "PostgreSQL", "Serving",
    )
    if "serving_direction" not in codes:
        _fail(f"expected serving_direction, got {codes}")
    # Technology serving Application is the correct direction.
    codes_ok = _view_with_rel(
        _fresh_doc(), "SystemSoftware", "PostgreSQL",
        "ApplicationComponent", "Meldportaal", "Serving",
    )
    if "serving_direction" in codes_ok:
        _fail(f"Technology→Application Serving should be clean, got {codes_ok}")
    print("    OK — App→Tech Serving flagged, Tech→App clean")


def test_name_type_mismatch_is_flagged():
    print("[12/12] validate_view flags a service named '…component'...")
    doc = _fresh_doc()
    eid = doc.create_element(
        element_type="ApplicationService", name="Notificatieroutering component"
    )
    vid = doc.create_view(name="V", documentation="")
    doc.add_to_view(vid, eid)
    codes = {e["code"] for e in write_tools._validate_view_impl(doc, doc.find_view(vid))}
    if "name_type_mismatch" not in codes:
        _fail(f"expected name_type_mismatch, got {codes}")
    print("    OK — service named like a component is flagged")


if __name__ == "__main__":
    print("=" * 50)
    print("Rijnland tekenafspraken — convention tests")
    print("=" * 50)
    test_stereotype_persists_on_correct_type()
    test_stereotype_rejected_on_wrong_type()
    test_ownership_behavior_type_accepted()
    test_plateau_implementation_layer()
    test_security_domain_without_trust_is_flagged()
    test_account_on_plain_role_is_flagged()
    test_clean_plate_has_no_rijnland_noise()
    test_triggering_from_active_structure_is_flagged()
    test_cross_aspect_flow_is_flagged()
    test_serving_direction_is_flagged()
    test_name_type_mismatch_is_flagged()
    print("=" * 50)
    print("All checks passed.")
