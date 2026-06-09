#!/usr/bin/env python3
"""Validate cross-references between documentation files.

Checks that:
- ADR linked_prd/linked_research paths exist (if non-null)
- BDD @prd and @adr tags point to existing files
- CAS.md is up to date (warns if older than any accepted ADR)
- Markdown [links](./path) in docs/ point to existing files

Usage:
    python scripts/validate_doc_links.py [files...]
    python scripts/validate_doc_links.py docs/   # scan all
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
ADRS_DIR = DOCS_DIR / "adrs"
TESTING_DIR = REPO_ROOT / "testing"


def parse_frontmatter(filepath: Path) -> dict:
    """Parse YAML frontmatter from a markdown file. Returns dict of key-value pairs."""
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm_text = text[3:end]
    result = {}
    for line in fm_text.strip().splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def check_adr_links(errors: list[str]) -> None:
    """Check ADR frontmatter linked_prd and linked_research references."""
    if not ADRS_DIR.exists():
        return
    for adr_file in sorted(ADRS_DIR.glob("[0-9]*.md")):
        if adr_file.name in ("CAS.md", "TEMPLATE.md"):
            continue
        fm = parse_frontmatter(adr_file)
        for field in ("linked_prd", "linked_research"):
            value = fm.get(field)
            if not value or value in ("null", "[]", ""):
                continue
            # Handle list syntax: [path1, path2]
            paths = re.findall(r'[\w./-]+\.md', value)
            for ref_path in paths:
                resolved = REPO_ROOT / ref_path
                if not resolved.exists():
                    errors.append(f"{adr_file.relative_to(REPO_ROOT)}: {field} references missing file: {ref_path}")


def check_bdd_tags(errors: list[str]) -> None:
    """Check BDD feature file @prd and @adr tags reference existing files."""
    bdd_dir = TESTING_DIR / "bdd" / "features"
    if not bdd_dir.exists():
        return
    for feature_file in bdd_dir.glob("*.feature"):
        text = feature_file.read_text(encoding="utf-8")
        # @prd path/to/prd.md
        for match in re.finditer(r'@prd\s+(\S+)', text):
            ref = match.group(1)
            resolved = REPO_ROOT / ref
            if not resolved.exists():
                errors.append(f"{feature_file.relative_to(REPO_ROOT)}: @prd references missing file: {ref}")
        # @adr path/to/adr.md
        for match in re.finditer(r'@adr\s+(\S+)', text):
            ref = match.group(1)
            resolved = REPO_ROOT / ref
            if not resolved.exists():
                errors.append(f"{feature_file.relative_to(REPO_ROOT)}: @adr references missing file: {ref}")


def check_markdown_links(errors: list[str], target_files: list[Path]) -> None:
    """Check markdown [text](path) links in docs/ resolve to existing files."""
    link_pattern = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
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


def check_cas_freshness(warnings: list[str]) -> None:
    """Warn if CAS.md is older than any accepted ADR."""
    cas_file = ADRS_DIR / "CAS.md"
    if not cas_file.exists():
        warnings.append("docs/adrs/CAS.md does not exist — run scripts/generate_cas.py")
        return
    cas_mtime = cas_file.stat().st_mtime
    if not ADRS_DIR.exists():
        return
    for adr_file in sorted(ADRS_DIR.glob("[0-9]*.md")):
        if adr_file.name in ("CAS.md", "TEMPLATE.md"):
            continue
        fm = parse_frontmatter(adr_file)
        if fm.get("status") == "accepted" and adr_file.stat().st_mtime > cas_mtime:
            warnings.append(
                f"docs/adrs/CAS.md is stale — {adr_file.name} was modified after CAS was generated. "
                f"Run: python scripts/generate_cas.py"
            )
            break  # one warning is enough


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
    check_bdd_tags(errors)
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
