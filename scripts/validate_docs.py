#!/usr/bin/env python3
"""Documentation validator (PBI 9744).

Validates ONLY the templated doc folders so that legacy/reference docs without
frontmatter never fail. Doc-type -> schema mapping:

    docs/adrs/     -> docs/adrs/adr.schema.json
    docs/prds/     -> docs/prds/prd.schema.json
    docs/research/ -> docs/research/research.schema.json

Exit 1 if any ERROR, else 0.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Doc-type folder -> schema file (relative to repo root).
DOC_TYPES = {
    "docs/adrs": "docs/adrs/adr.schema.json",
    "docs/prds": "docs/prds/prd.schema.json",
    "docs/research": "docs/research/research.schema.json",
}

# Files like 001-something.md (skips TEMPLATE.md, *.schema.json, README).
TEMPLATED_NAME = re.compile(r"^\d{3}-.*\.md$")

# Frontmatter link fields that hold repo-root-relative paths.
LINK_FIELDS = ("linked_prd", "linked_adrs", "linked_research", "linked_specs")

# NNN id inside a doc's frontmatter (for stray-doc detection).
NNN_ID = re.compile(r"^[0-9]{3}$")

# Valid lifecycle statuses for a Spec (.feature) @status tag.
SPEC_STATUSES = ("draft", "active", "superseded")


class _StrDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps unquoted dates/timestamps as plain strings.

    The schemas validate ``date`` fields via a string ``pattern`` (YYYY-MM-DD),
    so an unquoted ``date: 2026-07-14`` must stay a string rather than being
    coerced to a ``datetime.date`` object.
    """


# Drop the implicit resolvers that turn 2026-07-14 / timestamps into date objects.
for _first_char, _resolvers in list(_StrDateLoader.yaml_implicit_resolvers.items()):
    _StrDateLoader.yaml_implicit_resolvers[_first_char] = [
        (tag, regexp)
        for tag, regexp in _resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]


def load_frontmatter(raw):
    """Parse frontmatter YAML, keeping dates as strings."""
    return yaml.load(raw, Loader=_StrDateLoader)


def extract_frontmatter(text):
    """Return the raw YAML frontmatter block, or None if missing.

    Frontmatter is the text between the first ``---`` line and the next
    ``---`` line.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def as_list(value):
    """Normalize a link field: null->[], string->[string], list->list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return [value]


def validate_frontmatter_file(path, schema_validator, root):
    """Validate a single templated doc file. Returns list of error strings."""
    errors = []
    text = path.read_text(encoding="utf-8")

    raw = extract_frontmatter(text)
    if raw is None:
        errors.append("missing YAML frontmatter (no `---` block at top of file)")
        return errors

    try:
        data = load_frontmatter(raw)
    except yaml.YAMLError as exc:
        errors.append(f"invalid YAML frontmatter: {exc}")
        return errors

    if not isinstance(data, dict):
        errors.append("frontmatter did not parse to a mapping")
        return errors

    # 2. Schema validation.
    for err in sorted(schema_validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"schema: {loc}: {err.message}")

    # 3. id == filename prefix.
    prefix = path.name[:3]
    fm_id = data.get("id")
    if fm_id != prefix:
        errors.append(
            f"id mismatch: frontmatter id {fm_id!r} != filename prefix {prefix!r}"
        )

    # 4. Link resolution.
    for field in LINK_FIELDS:
        if field not in data:
            continue
        for value in as_list(data[field]):
            if not isinstance(value, str) or not value:
                continue
            if value.startswith("http"):
                continue
            target = root / value
            if not target.exists():
                errors.append(
                    f"{field}: linked file does not exist: {value}"
                )

    # 5. Superseded consistency.
    if data.get("status") == "superseded" and data.get("superseded_by") is None:
        errors.append(
            "status is 'superseded' but superseded_by is null"
        )

    return errors


def check_templated_docs(root):
    """A) Validate frontmatter of every templated doc. Returns (checked, results)."""
    results = []  # (relpath, errors)
    checked = 0

    for folder, schema_rel in DOC_TYPES.items():
        folder_path = root / folder
        if not folder_path.is_dir():
            continue
        schema_path = root / schema_rel
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)  # no format checker registered

        for path in sorted(folder_path.iterdir()):
            if not path.is_file():
                continue
            if not TEMPLATED_NAME.match(path.name):
                continue
            checked += 1
            rel = path.relative_to(root).as_posix()
            errors = validate_frontmatter_file(path, validator, root)
            results.append((rel, errors))

    return checked, results


def check_spec_files(root):
    """Validate @prd/@adr references and @status/@superseded_by tags in specs.

    Returns (checked, results). The @prd/@adr tags are Gherkin tags (no leading
    ``#``) whose referenced files must exist. The @status/@superseded_by tags are
    comment lines (``# @status ...``) matching the ADR/PRD/Research lifecycle
    pattern; they are validated only when present so specs predating the tags
    still pass. TEMPLATE.feature is skipped.
    """
    results = []  # (relpath, errors)
    checked = 0
    features_dir = root / "docs/specs"
    if not features_dir.is_dir():
        return checked, results

    tag_re = re.compile(r"^\s*@(prd|adr)\s+(\S+)")
    status_re = re.compile(r"^\s*#\s*@status\s+(\S+)")
    superseded_by_re = re.compile(r"^\s*#\s*@superseded_by\s*(.*)$")
    for path in sorted(features_dir.glob("*.feature")):
        if path.name == "TEMPLATE.feature":
            continue
        checked += 1
        errors = []
        rel = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()

        # @prd / @adr Gherkin tags — referenced files must exist.
        for line in lines:
            m = tag_re.match(line)
            if not m:
                continue
            ref = m.group(2)
            if "<" in ref:  # placeholder like <feature-name>
                continue
            if not (root / ref).exists():
                errors.append(f"@{m.group(1)}: referenced file does not exist: {ref}")

        # @status / @superseded_by lifecycle tags (validated only when present).
        status = None
        superseded_by = None
        for line in lines:
            m = status_re.match(line)
            if m and status is None:
                status = m.group(1).strip()
                continue
            m = superseded_by_re.match(line)
            if m and superseded_by is None:
                superseded_by = m.group(1).strip()

        if status is not None:
            if status not in SPEC_STATUSES:
                errors.append(
                    f"@status: invalid value {status!r} "
                    f"(expected one of: {', '.join(SPEC_STATUSES)})"
                )
            elif status == "superseded":
                if not superseded_by:
                    errors.append(
                        "@status is 'superseded' but @superseded_by is empty or absent"
                    )
            elif superseded_by:
                errors.append(
                    f"@status is {status!r} but @superseded_by is set "
                    "(must be empty for draft/active)"
                )

        results.append((rel, errors))

    return checked, results


def check_cas_freshness(root):
    """B) Verify docs/adrs/CAS.md matches freshly generated content.

    Shares its render logic with ``scripts/generate_cas.py`` (single source of
    truth). Compares content, not mtime.
    """
    from generate_cas import render_cas

    cas_path = root / "docs" / "adrs" / "CAS.md"
    rel = cas_path.relative_to(root).as_posix()
    expected = render_cas(root)

    if not cas_path.exists():
        return [(rel, [
            "CAS.md is stale or missing — run `python scripts/generate_cas.py` "
            "and commit the result"
        ])]

    actual = cas_path.read_text(encoding="utf-8")
    if actual != expected:
        return [(rel, [
            "CAS.md is stale or missing — run `python scripts/generate_cas.py` "
            "and commit the result"
        ])]

    return [(rel, [])]


def check_stray_docs(root):
    """C) Flag markdown docs with an NNN id living outside a type folder."""
    results = []
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return results

    type_folders = {(root / f).resolve() for f in DOC_TYPES}

    for path in sorted(docs_dir.rglob("*.md")):
        if not path.is_file():
            continue
        raw = extract_frontmatter(path.read_text(encoding="utf-8"))
        if raw is None:
            continue
        try:
            data = load_frontmatter(raw)
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        fm_id = data.get("id")
        if not (isinstance(fm_id, str) and NNN_ID.match(fm_id)):
            continue
        if path.parent.resolve() in type_folders:
            continue
        rel = path.relative_to(root).as_posix()
        results.append(
            (
                rel,
                [
                    "looks like a templated doc (NNN id) but is outside a type "
                    "folder; move it to the matching folder"
                ],
            )
        )

    return results


def main():
    parser = argparse.ArgumentParser(description="Validate templated documentation.")
    default_root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help="Repo root (default: script's parent.parent).",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    checked, results = check_templated_docs(root)
    spec_checked, spec_results = check_spec_files(root)
    results += spec_results
    results += check_cas_freshness(root)
    results += check_stray_docs(root)

    total_errors = 0
    for rel, errors in results:
        if errors:
            total_errors += len(errors)
            print(f"[FAIL] {rel}")
            for err in errors:
                print(f"    ERROR: {err}")
        else:
            print(f"[OK]   {rel}")

    print()
    print(f"{checked} docs checked, {spec_checked} specs checked, {total_errors} errors")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
