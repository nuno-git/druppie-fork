#!/usr/bin/env python3
"""
generate_cas.py — Generate the Current Architecture Specification (CAS.md)

Reads all accepted ADRs from docs/adrs/, extracts their metadata and decisions,
and produces docs/adrs/CAS.md — the single living document that agents and
developers reference instead of crawling individual ADRs.

Usage:
    python3 scripts/generate_cas.py

Uses PyYAML (yaml.safe_load) for frontmatter parsing.
"""

import glob
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# YAML frontmatter parser (PyYAML)
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter between --- delimiters, or None if absent."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    parsed = yaml.safe_load(m.group(1))
    if isinstance(parsed, dict):
        return parsed
    return {}


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------

def extract_body(text: str) -> str:
    """Return the markdown body (everything after frontmatter)."""
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    if m:
        return text[m.end():]
    return text


def extract_section(body: str, heading: str) -> str:
    """Extract the content under a ## heading until the next ## heading."""
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph from text."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for p in paragraphs:
        p = p.strip()
        if p:
            return p
    return ""


# ---------------------------------------------------------------------------
# Domain inference
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS = {
    "data": ["database", "column", "json", "jsonb", "table", "schema", "orm", "sqlalchemy", "migration", "repository"],
    "api": ["route", "http", "rest", "endpoint", "fastapi", "request", "response", "layered", "layer"],
    "agents": ["agent", "tool", "mcp", "llm", "runtime", "execution", "loop", "communication"],
    "infra": ["docker", "deploy", "infrastructure", "ci", "cd", "container", "compose"],
    "testing": ["test", "pytest", "playwright", "e2e", "integration"],
}


def infer_domain(frontmatter: dict, body: str) -> str:
    """Infer the domain of an ADR from its title and body content."""
    text = (str(frontmatter.get("title", "")) + " " + body).lower()
    best_domain = "general"
    best_score = 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain


# ---------------------------------------------------------------------------
# Content hash (kept in sync with scripts/validate_doc_links.py)
# ---------------------------------------------------------------------------

def compute_adr_hash(adr_dir: Path) -> str:
    """Compute a deterministic hash of all accepted ADR contents.

    This must be byte-for-byte identical to ``compute_adr_hash`` in
    ``scripts/validate_doc_links.py`` so the ``content_hash`` stamped into
    CAS.md frontmatter is recognized by the validator's freshness check.

    Hashes file *contents* (not mtimes) so the value is stable across git
    clone/checkout. Excludes TEMPLATE.md and CAS.md itself.
    """
    hasher = hashlib.sha256()
    for adr_file in sorted(adr_dir.glob("*.md")):
        if adr_file.name in ("TEMPLATE.md", "CAS.md"):
            continue
        content = adr_file.read_text(encoding="utf-8")
        hasher.update(content.encode())
    return hasher.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
ADRS_DIR = REPO_ROOT / "docs" / "adrs"
CAS_PATH = ADRS_DIR / "CAS.md"


def load_adrs() -> list[dict]:
    """Load all ADR files, parse frontmatter and extract key content."""
    pattern = str(ADRS_DIR / "[0-9]*.md")
    files = sorted(glob.glob(pattern))
    adrs = []
    for fpath in files:
        text = Path(fpath).read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm is None:
            print(f"WARNING: {fpath} — no frontmatter found, skipping", file=sys.stderr)
            continue
        body = extract_body(text)
        decision_text = extract_section(body, "Decision")
        decision_summary = first_paragraph(decision_text)
        enforcement_fm = fm.get("enforcement", {})
        if isinstance(enforcement_fm, dict):
            raw_lint = enforcement_fm.get("lint_rules", []) or []
            raw_ci = enforcement_fm.get("ci_checks", []) or []
            lint_rules = raw_lint if isinstance(raw_lint, list) else []
            ci_checks = raw_ci if isinstance(raw_ci, list) else []
        else:
            lint_rules = []
            ci_checks = []

        adrs.append({
            "id": fm.get("id", "???"),
            "title": fm.get("title", "Untitled"),
            "status": fm.get("status", "unknown"),
            "date": fm.get("date", "unknown"),
            "deciders": fm.get("deciders", []),
            "superseded_by": fm.get("superseded_by"),
            "lint_rules": lint_rules,
            "ci_checks": ci_checks,
            "decision_summary": decision_summary,
            "domain": infer_domain(fm, body),
            "filepath": fpath,
        })
    return adrs


def generate_cas(adrs: list[dict], adr_dir: Path = ADRS_DIR) -> str:
    """Generate the CAS.md content from a list of parsed ADRs."""
    accepted = [a for a in adrs if a["status"] == "accepted"]
    accepted.sort(key=lambda a: str(a["id"]))

    now = datetime.now(timezone.utc)
    now_display = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    content_hash = compute_adr_hash(adr_dir)

    lines = []
    # YAML frontmatter — read by scripts/validate_doc_links.py (content_hash
    # freshness check). Keep the keys stable; the validator parses this block.
    lines.append("---")
    lines.append(f"content_hash: {content_hash}")
    lines.append(f"last_generated: {now_iso}")
    lines.append("---")
    lines.append("")
    lines.append("# Current Architecture Specification (CAS)")
    lines.append("")
    lines.append("<!--")
    lines.append("  AUTO-GENERATED by scripts/generate_cas.py")
    lines.append("  Do NOT edit this file manually. Changes will be overwritten.")
    lines.append(f"  Last generated: {now_display}")
    lines.append("-->")
    lines.append("")
    lines.append(
        "This document is the **Current Architecture Specification** — a consolidated "
        "view of all *accepted* Architecture Decision Records (ADRs). It serves as the "
        "primary reference for agents and developers, summarizing the architectural "
        "rules that the Druppie platform currently follows."
    )
    lines.append("")
    lines.append("For the full rationale and context behind each decision, see the individual ADR files in `docs/adrs/`.")
    lines.append("")

    # --- Table of active ADRs ---
    lines.append("## Active ADRs")
    lines.append("")
    lines.append("| ADR | Title | Status | Enforcement |")
    lines.append("|-----|-------|--------|-------------|")
    for a in accepted:
        enforcement_parts = []
        if a["lint_rules"]:
            enforcement_parts.append("lint: " + ", ".join(str(r) for r in a["lint_rules"]))
        if a["ci_checks"]:
            enforcement_parts.append("CI: " + ", ".join(str(c) for c in a["ci_checks"]))
        enforcement_str = "; ".join(enforcement_parts) if enforcement_parts else "manual review"
        lines.append(f"| {a['id']} | {a['title']} | {a['status']} | {enforcement_str} |")
    lines.append("")

    # --- Group by domain ---
    DOMAIN_ORDER = ["data", "api", "agents", "infra", "testing", "general"]
    DOMAIN_LABELS = {
        "data": "Data Layer",
        "api": "API & Layered Architecture",
        "agents": "Agents & Runtime",
        "infra": "Infrastructure",
        "testing": "Testing",
        "general": "General",
    }

    grouped: dict[str, list[dict]] = {}
    for a in accepted:
        grouped.setdefault(a["domain"], []).append(a)

    lines.append("## Decisions by Domain")
    lines.append("")

    for domain in DOMAIN_ORDER:
        domain_adrs = grouped.get(domain, [])
        if not domain_adrs:
            continue
        label = DOMAIN_LABELS.get(domain, domain.title())
        lines.append(f"### {label}")
        lines.append("")
        for a in domain_adrs:
            lines.append(f"#### ADR-{a['id']}: {a['title']}")
            lines.append("")
            if a["decision_summary"]:
                lines.append(a["decision_summary"])
            else:
                lines.append("*(No decision summary available)*")
            lines.append("")
        # end for
    # end for

    # --- Supersession chain notes ---
    superseded = [a for a in adrs if a["status"] == "superseded"]
    if superseded:
        lines.append("## Superseded Decisions")
        lines.append("")
        lines.append("| ADR | Title | Superseded By |")
        lines.append("|-----|-------|---------------|")
        for a in superseded:
            lines.append(f"| {a['id']} | {a['title']} | {a['superseded_by'] or 'N/A'} |")
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated on {now_display} from {len(accepted)} accepted ADRs.*")
    lines.append("")

    return "\n".join(lines)


def main():
    adrs = load_adrs()
    if not adrs:
        print("ERROR: No ADR files found in docs/adrs/", file=sys.stderr)
        sys.exit(1)

    cas_content = generate_cas(adrs)
    CAS_PATH.write_text(cas_content, encoding="utf-8")
    accepted_count = sum(1 for a in adrs if a["status"] == "accepted")
    print(f"CAS.md generated: {len(adrs)} ADRs scanned, {accepted_count} accepted → {CAS_PATH}")


if __name__ == "__main__":
    main()
