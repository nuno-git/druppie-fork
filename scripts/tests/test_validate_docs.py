"""Tests for scripts/validate_docs.py (Check B validator)."""

import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import generate_cas
import validate_docs

# Real repo root (scripts/tests -> scripts -> repo).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Fixtures — build a mini-repo in tmp_path with the REAL schemas copied in.
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_repo(tmp_path):
    """A tmp repo with docs/{adrs,prds,research}/ and the real *.schema.json."""
    for folder, schema_rel in validate_docs.DOC_TYPES.items():
        (tmp_path / folder).mkdir(parents=True)
        shutil.copy(REPO_ROOT / schema_rel, tmp_path / schema_rel)
    (tmp_path / "docs/specs").mkdir(parents=True)
    return tmp_path


def _validator_for(root, doc_type):
    import json

    schema = json.loads(
        (root / validate_docs.DOC_TYPES[doc_type]).read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


VALID_ADR = """\
---
id: "{id}"
title: A decision
status: {status}
date: 2026-07-14
deciders:
  - alice
supersedes: null
superseded_by: {superseded_by}
linked_prd: {linked_prd}
linked_research: null
---

# A decision
"""

VALID_PRD = """\
---
id: "{id}"
title: A product
status: draft
author: bob
date: 2026-07-14
linked_adrs: []
linked_research: []
linked_specs: []
linked_workitem: null
supersedes: null
superseded_by: null
---

# A product
"""

VALID_RESEARCH = """\
---
id: "{id}"
title: Some research
status: complete
author: carol
date: 2026-07-14
outcome: null
---

# Some research
"""


# ---------------------------------------------------------------------------
# extract_frontmatter
# ---------------------------------------------------------------------------


def test_extract_frontmatter_happy():
    text = "---\nid: 001\ntitle: x\n---\n\nbody"
    raw = validate_docs.extract_frontmatter(text)
    assert "id: 001" in raw
    assert "body" not in raw


def test_extract_frontmatter_missing():
    assert validate_docs.extract_frontmatter("no frontmatter here\n") is None


def test_extract_frontmatter_unclosed():
    assert validate_docs.extract_frontmatter("---\nid: 001\nno closing fence") is None


def test_extract_frontmatter_with_bom():
    # A leading UTF-8 BOM must not hide the opening `---` fence.
    text = "﻿---\nid: 001\ntitle: x\n---\n\nbody"
    raw = validate_docs.extract_frontmatter(text)
    assert raw is not None
    assert "id: 001" in raw


def test_valid_adr_with_bom_has_no_errors(mini_repo):
    # A valid ADR written with a UTF-8 BOM should still validate cleanly.
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        "﻿"
        + VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert errors == []


# ---------------------------------------------------------------------------
# load_frontmatter — the _StrDateLoader invariant
# ---------------------------------------------------------------------------


def test_load_frontmatter_keeps_unquoted_date_as_str():
    data = validate_docs.load_frontmatter("date: 2026-07-14")
    assert data["date"] == "2026-07-14"
    assert isinstance(data["date"], str)


# ---------------------------------------------------------------------------
# validate_frontmatter_file
# ---------------------------------------------------------------------------


def test_valid_adr_has_no_errors(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert errors == []


def test_valid_prd_has_no_errors(mini_repo):
    p = mini_repo / "docs/prds/001-product.md"
    p.write_text(VALID_PRD.format(id="001"), encoding="utf-8")
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/prds"), mini_repo
    )
    assert errors == []


def test_valid_research_has_no_errors(mini_repo):
    p = mini_repo / "docs/research/001-study.md"
    p.write_text(VALID_RESEARCH.format(id="001"), encoding="utf-8")
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/research"), mini_repo
    )
    assert errors == []


def test_missing_frontmatter_is_error(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text("# no frontmatter\n", encoding="utf-8")
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("frontmatter" in e for e in errors)


def test_bad_status_enum_is_error(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001", status="bogus", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("schema" in e and "status" in e for e in errors)


def test_id_mismatch_is_error(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    # frontmatter id 999 != filename prefix 001.
    p.write_text(
        VALID_ADR.format(
            id="999", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("id mismatch" in e for e in errors)


def test_broken_link_is_error(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001",
            status="accepted",
            superseded_by="null",
            linked_prd="docs/prds/404-missing.md",
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("linked file does not exist" in e for e in errors)


def test_http_link_is_rejected(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001",
            status="accepted",
            superseded_by="null",
            linked_prd="https://example.com/prd",
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("linked file does not exist" in e for e in errors)


def test_comma_separated_linked_research(mini_repo):
    (mini_repo / "docs/research/004-agent-runtime.md").write_text(
        "---\nid: \"004\"\ntitle: Test\nstatus: complete\nauthor: nuno\ndate: 2026-01-01\noutcome: null\n---\n\n# Test\n",
        encoding="utf-8",
    )
    (mini_repo / "docs/research/002-foo.md").write_text(
        "---\nid: \"002\"\ntitle: Foo\nstatus: complete\nauthor: nuno\ndate: 2026-01-01\noutcome: null\n---\n\n# Foo\n",
        encoding="utf-8",
    )
    content = """\
---
id: "001"
title: Test comma-separated linked fields
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: docs/research/004-agent-runtime.md, docs/research/002-foo.md
---

# Test
"""
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(content, encoding="utf-8")
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert not any("linked file does not exist" in e for e in errors)


def test_link_with_anchor_resolves(mini_repo):
    # A link with a "#section" anchor must resolve to the underlying file.
    (mini_repo / "docs/prds/001-product.md").write_text(
        VALID_PRD.format(id="001"), encoding="utf-8"
    )
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001",
            status="accepted",
            superseded_by="null",
            linked_prd="docs/prds/001-product.md#goal",
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert errors == []


def test_link_with_anchor_to_missing_file_still_errors(mini_repo):
    # Anchor-stripping must not mask a genuinely missing target file.
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001",
            status="accepted",
            superseded_by="null",
            linked_prd="docs/prds/404-missing.md#goal",
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("linked file does not exist" in e for e in errors)


def test_superseded_without_superseded_by_is_error(mini_repo):
    p = mini_repo / "docs/adrs/001-decision.md"
    p.write_text(
        VALID_ADR.format(
            id="001", status="superseded", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    errors = validate_docs.validate_frontmatter_file(
        p, _validator_for(mini_repo, "docs/adrs"), mini_repo
    )
    assert any("superseded" in e and "superseded_by" in e for e in errors)


# ---------------------------------------------------------------------------
# check_spec_files
# ---------------------------------------------------------------------------


def test_spec_missing_reference_is_error(mini_repo):
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text(
        "@prd docs/prds/404-missing.md\nFeature: x\n", encoding="utf-8"
    )
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert any("referenced file does not exist" in e for e in errors)


def test_spec_placeholder_is_skipped(mini_repo):
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text("@prd <feature-name>\nFeature: x\n", encoding="utf-8")
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert errors == []


def test_spec_template_is_skipped(mini_repo):
    tmpl = mini_repo / "docs/specs/TEMPLATE.feature"
    tmpl.write_text("@prd docs/prds/404-missing.md\n", encoding="utf-8")
    checked, results = validate_docs.check_spec_files(mini_repo)
    assert results == []


def test_spec_valid_reference_no_error(mini_repo):
    (mini_repo / "docs/prds/001-product.md").write_text(
        VALID_PRD.format(id="001"), encoding="utf-8"
    )
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text("@prd docs/prds/001-product.md\n", encoding="utf-8")
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert errors == []


def test_spec_second_tag_on_same_line_is_checked(mini_repo):
    # Two tags on one line: the first resolves, the second is broken and
    # must still be reported (regression: re.match only saw the first tag).
    (mini_repo / "docs/prds/001-product.md").write_text(
        VALID_PRD.format(id="001"), encoding="utf-8"
    )
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text(
        "@prd docs/prds/001-product.md @adr docs/adrs/404-missing.md\n",
        encoding="utf-8",
    )
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert any(
        "referenced file does not exist" in e and "404-missing.md" in e
        for e in errors
    )


def test_spec_comment_and_prose_tags_are_ignored(mini_repo):
    # @prd/@adr mentions inside comment lines ("# @adr foo.md") or prose
    # ("the @prd / @adr tags below ...") are not tag references and must not
    # be resolved (regression: unanchored finditer flagged them as broken).
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text(
        "# @adr 404-missing.md\n"
        "# the @prd / @adr tags below link this behaviour back to the docs\n"
        "Feature: x\n",
        encoding="utf-8",
    )
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert errors == []


def test_spec_second_tag_placeholder_is_skipped(mini_repo):
    # A placeholder second tag on the same line is skipped, not errored.
    (mini_repo / "docs/prds/001-product.md").write_text(
        VALID_PRD.format(id="001"), encoding="utf-8"
    )
    feat = mini_repo / "docs/specs/thing.feature"
    feat.write_text(
        "@prd docs/prds/001-product.md @adr <adr-name>\n", encoding="utf-8"
    )
    checked, results = validate_docs.check_spec_files(mini_repo)
    rel, errors = results[0]
    assert errors == []


# ---------------------------------------------------------------------------
# check_cas_freshness
# ---------------------------------------------------------------------------


def test_cas_missing_is_error(mini_repo):
    (mini_repo / "docs/adrs/001-decision.md").write_text(
        VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    results = validate_docs.check_cas_freshness(mini_repo)
    rel, errors = results[0]
    assert any("stale or missing" in e for e in errors)


def test_cas_stale_is_error(mini_repo):
    (mini_repo / "docs/adrs/001-decision.md").write_text(
        VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    (mini_repo / "docs/adrs/CAS.md").write_text("stale content\n", encoding="utf-8")
    results = validate_docs.check_cas_freshness(mini_repo)
    rel, errors = results[0]
    assert any("stale or missing" in e for e in errors)


def test_cas_fresh_has_no_error(mini_repo):
    (mini_repo / "docs/adrs/001-decision.md").write_text(
        VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    (mini_repo / "docs/adrs/CAS.md").write_text(
        generate_cas.render_cas(mini_repo), encoding="utf-8"
    )
    results = validate_docs.check_cas_freshness(mini_repo)
    rel, errors = results[0]
    assert errors == []


# ---------------------------------------------------------------------------
# check_stray_docs
# ---------------------------------------------------------------------------


def test_stray_nnn_doc_outside_type_folder_is_error(mini_repo):
    stray = mini_repo / "docs/guides/003-orphan.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(
        "---\nid: '003'\ntitle: orphan\n---\n\nbody\n", encoding="utf-8"
    )
    results = validate_docs.check_stray_docs(mini_repo)
    rels = {rel for rel, errors in results if errors}
    assert "docs/guides/003-orphan.md" in rels


def test_nnn_doc_inside_type_folder_not_stray(mini_repo):
    inside = mini_repo / "docs/adrs/003-decision.md"
    inside.write_text(
        "---\nid: '003'\ntitle: ok\n---\n\nbody\n", encoding="utf-8"
    )
    results = validate_docs.check_stray_docs(mini_repo)
    # This file should not be reported as stray.
    for rel, errors in results:
        if rel == "docs/adrs/003-decision.md":
            assert errors == []


# ---------------------------------------------------------------------------
# main() — end-to-end on a tmp repo
# ---------------------------------------------------------------------------


def _make_clean_repo(mini_repo):
    """Populate mini_repo so validate_docs.main() reports zero errors."""
    (mini_repo / "docs/adrs/001-decision.md").write_text(
        VALID_ADR.format(
            id="001", status="accepted", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    (mini_repo / "docs/adrs/CAS.md").write_text(
        generate_cas.render_cas(mini_repo), encoding="utf-8"
    )


def test_main_clean_repo_returns_0(mini_repo, monkeypatch, capsys):
    _make_clean_repo(mini_repo)
    monkeypatch.setattr("sys.argv", ["validate_docs.py", "--root", str(mini_repo)])
    assert validate_docs.main() == 0
    assert "0 errors" in capsys.readouterr().out


def test_main_one_error_returns_1(mini_repo, monkeypatch, capsys):
    _make_clean_repo(mini_repo)
    # Introduce a single error: an ADR with a bad status enum.
    (mini_repo / "docs/adrs/002-bad.md").write_text(
        VALID_ADR.format(
            id="002", status="bogus", superseded_by="null", linked_prd="null"
        ),
        encoding="utf-8",
    )
    # Keep CAS fresh (bogus status is not "accepted", so CAS is unaffected).
    (mini_repo / "docs/adrs/CAS.md").write_text(
        generate_cas.render_cas(mini_repo), encoding="utf-8"
    )
    monkeypatch.setattr("sys.argv", ["validate_docs.py", "--root", str(mini_repo)])
    assert validate_docs.main() == 1
