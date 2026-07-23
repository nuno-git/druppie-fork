"""Tests for scripts/generate_cas.py (CAS renderer)."""

import generate_cas


def _write_adr(adrs_dir, fid, status, title):
    (adrs_dir / f"{fid}-slug.md").write_text(
        f"---\nid: {fid}\ntitle: {title}\nstatus: {status}\n"
        "date: 2026-07-14\ndeciders:\n  - x\nsupersedes: null\n"
        "superseded_by: null\nlinked_prd: null\nlinked_research: null\n---\n\nbody\n",
        encoding="utf-8",
    )


def test_render_cas_deterministic(tmp_path):
    adrs = tmp_path / "docs" / "adrs"
    adrs.mkdir(parents=True)
    _write_adr(adrs, "002", "accepted", "Second")
    _write_adr(adrs, "001", "accepted", "First")

    first = generate_cas.render_cas(tmp_path)
    second = generate_cas.render_cas(tmp_path)
    assert first == second


def test_render_cas_only_accepted_sorted(tmp_path):
    adrs = tmp_path / "docs" / "adrs"
    adrs.mkdir(parents=True)
    _write_adr(adrs, "003", "accepted", "Gamma")
    _write_adr(adrs, "001", "accepted", "Alpha")
    _write_adr(adrs, "002", "proposed", "Beta (not accepted)")

    out = generate_cas.render_cas(tmp_path)
    assert "Alpha" in out
    assert "Gamma" in out
    # Non-accepted ADR must be excluded.
    assert "Beta" not in out
    # Sorted by id: 001 (Alpha) appears before 003 (Gamma).
    assert out.index("Alpha") < out.index("Gamma")


def test_render_cas_empty(tmp_path):
    adrs = tmp_path / "docs" / "adrs"
    adrs.mkdir(parents=True)
    _write_adr(adrs, "001", "proposed", "Not yet accepted")

    out = generate_cas.render_cas(tmp_path)
    assert "No accepted ADRs yet" in out


def test_render_cas_no_dir(tmp_path):
    # Missing adrs dir -> renders the empty placeholder, no crash.
    out = generate_cas.render_cas(tmp_path)
    assert "No accepted ADRs yet" in out
