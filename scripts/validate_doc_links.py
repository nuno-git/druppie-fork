#!/usr/bin/env python3
"""Validate cross-references between documentation files.

Checks that:
- ADR linked_prd/linked_research paths exist (if non-null)
- Acceptance spec @prd and @adr tags point to existing files
- CAS.md is up to date (warns if its content_hash doesn't match the current ADR contents)
- Markdown [links](./path) in docs/ point to existing files

Usage:
    python scripts/validate_doc_links.py [files...]
    python scripts/validate_doc_links.py docs/   # scan all
"""

import hashlib
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
ADRS_DIR = DOCS_DIR / "adrs"
TESTING_DIR = REPO_ROOT / "testing"


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from a Markdown file.

    Uses yaml.safe_load so nested maps and lists are parsed correctly (the
    previous hand-rolled parser only handled flat ``key: value`` lines and
    silently dropped nested ``enforcement:`` blocks).
    """
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1])
    return loaded if isinstance(loaded, dict) else {}


def check_adr_links(errors: list[str]) -> None:
    """Check ADR frontmatter linked_prd and linked_research references."""
    if not ADRS_DIR.exists():
        return
    for adr_file in sorted(ADRS_DIR.glob("[0-9]*.md")):
        if adr_file.name in ("CAS.md", "TEMPLATE.md"):
            continue
        fm = parse_frontmatter(adr_file.read_text(encoding="utf-8"))
        for field in ("linked_prd", "linked_research"):
            value = fm.get(field)
            # PyYAML returns typed values (None, list, str); normalize to a
            # string before the `in` check, otherwise `list in tuple` raises.
            if not value:  # None, "", [] → nothing to check
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            elif not isinstance(value, str):
                value = str(value)
            if value in ("null", "[]", ""):
                continue
            # Handle list syntax: [path1, path2]
            paths = re.findall(r"[\w./-]+\.md", value)
            for ref_path in paths:
                resolved = REPO_ROOT / ref_path
                if not resolved.exists():
                    errors.append(
                        f"{adr_file.relative_to(REPO_ROOT)}: {field} references missing file: {ref_path}"
                    )


def check_spec_tags(errors: list[str]) -> None:
    """Check acceptance spec @prd and @adr tags reference existing files."""
    specs_dir = TESTING_DIR / "specs" / "features"
    if not specs_dir.exists():
        return
    for feature_file in specs_dir.glob("*.feature"):
        text = feature_file.read_text(encoding="utf-8")
        # @prd path/to/prd.md
        for match in re.finditer(r"@prd\s+(\S+)", text):
            ref = match.group(1)
            resolved = REPO_ROOT / ref
            if not resolved.exists():
                errors.append(
                    f"{feature_file.relative_to(REPO_ROOT)}: @prd references missing file: {ref}"
                )
        # @adr path/to/adr.md
        for match in re.finditer(r"@adr\s+(\S+)", text):
            ref = match.group(1)
            resolved = REPO_ROOT / ref
            if not resolved.exists():
                errors.append(
                    f"{feature_file.relative_to(REPO_ROOT)}: @adr references missing file: {ref}"
                )


def check_markdown_links(errors: list[str], target_files: list[Path]) -> None:
    """Check markdown [text](path) links in docs/ resolve to existing files."""
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for md_file in target_files:
        text = md_file.read_text(encoding="utf-8")
        for match in link_pattern.finditer(text):
            link_text = match.group(1)
            href = match.group(2)
            # Skip external links and anchors
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # Strip anchor
            href = href.split("#")[0]
            if not href:
                continue
            resolved = md_file.parent / href
            if not resolved.exists():
                try:
                    rel = md_file.relative_to(REPO_ROOT)
                except ValueError:
                    rel = md_file
                errors.append(f"{rel}: link '[{link_text}]({href})' target not found")


def compute_adr_hash(adr_dir: Path) -> str:
    """Compute a deterministic hash of all accepted ADR contents.

    Hashing file *contents* (not mtimes) makes the freshness check stable
    across git clone/checkout, since git does not preserve modification times.
    The same logic is used by scripts/generate_cas.py to stamp CAS.md with a
    ``content_hash`` frontmatter field.
    """
    hasher = hashlib.sha256()
    for adr_file in sorted(adr_dir.glob("*.md")):
        if adr_file.name in ("TEMPLATE.md", "CAS.md"):
            continue
        content = adr_file.read_text(encoding="utf-8")
        hasher.update(content.encode())
    return hasher.hexdigest()[:16]


def check_cas_freshness(warnings: list[str]) -> None:
    """Warn if CAS.md content_hash doesn't match the current ADR contents.

    Reads the ``content_hash`` frontmatter field from CAS.md and compares it
    against a freshly computed hash of all ADR files. If they differ (or the
    field is absent), CAS is stale and must be regenerated.
    """
    cas_file = ADRS_DIR / "CAS.md"
    if not cas_file.exists():
        warnings.append("docs/adrs/CAS.md does not exist — run scripts/generate_cas.py")
        return
    if not ADRS_DIR.exists():
        return
    cas_fm = parse_frontmatter(cas_file.read_text(encoding="utf-8"))
    stored_hash = cas_fm.get("content_hash")
    if not stored_hash:
        warnings.append(
            "docs/adrs/CAS.md has no content_hash frontmatter — "
            "run scripts/generate_cas.py to regenerate"
        )
        return
    current_hash = compute_adr_hash(ADRS_DIR)
    if current_hash != stored_hash:
        warnings.append(
            "docs/adrs/CAS.md is stale — ADR contents changed since CAS was generated. "
            "Run: python scripts/generate_cas.py"
        )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # Determine target files
    if len(sys.argv) > 1:
        targets = []
        for arg in sys.argv[1:]:
            p = Path(arg)
            if p.is_dir():
                targets.extend(p.rglob("*.md"))
            else:
                targets.append(p)
    else:
        targets = list(DOCS_DIR.rglob("*.md"))

    # Run all checks
    check_adr_links(errors)
    check_spec_tags(errors)
    check_markdown_links(errors, targets)
    check_cas_freshness(warnings)

    # Report
    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")

    if errors:
        print(f"\n{len(errors)} error(s) found.")
        return 1
    if warnings:
        print(f"\n{len(warnings)} warning(s).")
    print("All document links valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
