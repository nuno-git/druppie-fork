"""Tests for scripts/check_mandatory_docs.py (Check A gate)."""

import check_mandatory_docs as cmd


# ---------------------------------------------------------------------------
# is_exempt
# ---------------------------------------------------------------------------


def test_exempt_via_label():
    assert cmd.is_exempt("other,docs-exempt,more", "") is True
    # newline-separated labels also work.
    assert cmd.is_exempt("other\ndocs-exempt", "") is True


def test_label_substring_does_not_count():
    # Must be an *exact* label, not a substring.
    assert cmd.is_exempt("docs-exempted", "") is False
    assert cmd.is_exempt("not-docs-exempt", "") is False


def test_exempt_via_checked_checkbox():
    body = "Some intro\n- [x] This PR is docs-exempt because reasons\nrest"
    assert cmd.is_exempt("", body) is True
    # Upper-case X also counts.
    assert cmd.is_exempt("", "- [X] docs-exempt") is True


def test_unchecked_checkbox_does_not_count():
    body = "- [ ] docs-exempt (not ticked)"
    assert cmd.is_exempt("", body) is False


def test_exempt_via_directive_with_reason():
    body = "Title\n\ndocs-exempt: pure refactor, no behaviour change\n"
    assert cmd.is_exempt("", body) is True


def test_bare_directive_without_reason_does_not_count():
    # "docs-exempt:" with nothing after it (or only whitespace) is NOT enough.
    assert cmd.is_exempt("", "docs-exempt:") is False
    assert cmd.is_exempt("", "docs-exempt:   ") is False


def test_directive_case_insensitive():
    assert cmd.is_exempt("", "DOCS-EXEMPT: because") is True


def test_not_exempt_when_nothing_matches():
    assert cmd.is_exempt("bug,enhancement", "A normal PR body\nwith no exempt markers") is False


def test_is_exempt_handles_none():
    assert cmd.is_exempt(None, None) is False


# ---------------------------------------------------------------------------
# mandatory_gate
# ---------------------------------------------------------------------------


def test_code_without_docs_fails():
    ok, reason = cmd.mandatory_gate(["druppie/api/routes.py"])
    assert ok is False
    assert "documentation" in reason


def test_code_with_docs_passes():
    ok, reason = cmd.mandatory_gate(
        ["druppie/api/routes.py", "docs/adrs/001-thing.md"]
    )
    assert ok is True
    assert reason == "OK"


def test_only_non_code_passes():
    # A README change is neither code nor a templated doc -> gate passes.
    ok, reason = cmd.mandatory_gate(["README.md"])
    assert ok is True
    assert reason == "OK"


def test_frontend_src_code_without_docs_fails():
    ok, reason = cmd.mandatory_gate(["frontend/src/pages/Home.tsx"])
    assert ok is False


def test_frontend_non_src_does_not_trigger_gate():
    # frontend/ outside src/ is not "code" for the gate.
    ok, reason = cmd.mandatory_gate(["frontend/package.json"])
    assert ok is True


def test_spec_feature_counts_as_docs():
    ok, reason = cmd.mandatory_gate(
        ["druppie/services/x.py", "testing/specs/features/foo.feature"]
    )
    assert ok is True


def test_empty_changeset_passes():
    ok, reason = cmd.mandatory_gate([])
    assert ok is True


# ---------------------------------------------------------------------------
# main() — env + STDIN wiring
# ---------------------------------------------------------------------------


def test_main_exempt_skips(monkeypatch, capsys):
    monkeypatch.setenv("LABELS", "docs-exempt")
    monkeypatch.setenv("PR_BODY", "")
    monkeypatch.setattr("sys.stdin", _FakeStdin("druppie/x.py\n"))
    assert cmd.main() == 0
    out = capsys.readouterr().out
    assert "skipped" in out


def test_main_blocks_code_without_docs(monkeypatch, capsys):
    monkeypatch.setenv("LABELS", "")
    monkeypatch.setenv("PR_BODY", "no exempt here")
    monkeypatch.setattr("sys.stdin", _FakeStdin("druppie/x.py\n"))
    assert cmd.main() == 1
    out = capsys.readouterr().out
    assert "::error::" in out
    assert "code changed without documentation" in out
    assert "docs/guides/documentation-framework.md" in out
    # The 3 exempt mechanisms are named literally.
    assert "docs-exempt" in out
    assert "- [x] docs-exempt" in out
    assert "docs-exempt: <reason>" in out


def test_main_passes_with_docs(monkeypatch, capsys):
    monkeypatch.setenv("LABELS", "")
    monkeypatch.setenv("PR_BODY", "")
    monkeypatch.setattr(
        "sys.stdin", _FakeStdin("druppie/x.py\ndocs/prds/002-feature.md\n")
    )
    assert cmd.main() == 0
    assert "Mandatory-docs gate OK." in capsys.readouterr().out


class _FakeStdin:
    """Minimal stdin stand-in: iterable of lines like a real file object."""

    def __init__(self, text):
        self._lines = text.splitlines(keepends=True)

    def __iter__(self):
        return iter(self._lines)
