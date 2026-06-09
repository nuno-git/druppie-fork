#!/usr/bin/env python3
"""
generate_cas.py — Generate the Current Architecture Specification (CAS.md)

Reads all accepted ADRs from docs/adrs/, extracts their metadata and decisions,
and produces docs/adrs/CAS.md — the single living document that agents and
developers reference instead of crawling individual ADRs.

Usage:
    python3 scripts/generate_cas.py

Requires only stdlib. Uses re for YAML frontmatter parsing (no PyYAML dependency).
"""

import glob
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# YAML frontmatter parser (minimal, stdlib-only)
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter between --- delimiters. Returns a dict or None."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    return _parse_yaml_block(raw.splitlines())


def _parse_yaml_block(lines: list[str], base_indent: int = 0) -> dict:
    """Parse a block of YAML lines into a dict. Handles nested maps and lists."""
    result = {}
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        # Determine indentation
        stripped = raw_line.lstrip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(raw_line) - len(stripped)
        if indent < base_indent:
            break
        # key: value
        kv = re.match(r"^(\w[\w_-]*):\s*(.*)", stripped)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip()
            # Check if value is empty — might be a nested map or list
            if val == "":
                # Look ahead for nested content
                nested_lines = []
                j = i + 1
                while j < len(lines):
                    next_raw = lines[j]
                    next_stripped = next_raw.lstrip()
                    if not next_stripped:
                        j += 1
                        continue
                    next_indent = len(next_raw) - len(next_stripped)
                    if next_indent <= indent:
                        break
                    nested_lines.append(next_raw)
                    j += 1
                if nested_lines:
                    # Determine if nested block is a list or map
                    first_nested = nested_lines[0].lstrip()
                    min_indent = min(len(l) - len(l.lstrip()) for l in nested_lines if l.lstrip())
                    if first_nested.startswith("- "):
                        # It's a list
                        items = []
                        for nl in nested_lines:
                            ns = nl.lstrip()
                            li_match = re.match(r"^-\s+(.*)", ns)
                            if li_match:
                                items.append(_parse_yaml_scalar(li_match.group(1).strip()))
                        result[key] = items
                    else:
                        # It's a nested map
                        result[key] = _parse_yaml_block(nested_lines, min_indent)
                    i = j
                    continue
                else:
                    result[key] = None
                    i += 1
                    continue
            result[key] = _parse_yaml_value(val)
            i += 1
            continue
        # list item
        li = re.match(r"^-\s+(.*)", stripped)
        if li and result:
            last_key = list(result.keys())[-1]
            if isinstance(result[last_key], list):
                result[last_key].append(_parse_yaml_scalar(li.group(1).strip()))
            i += 1
            continue
        i += 1
    return result


def _parse_yaml_value(val: str):
    """Parse a single YAML value."""
    if val is None:
        return None
    if val == "" :
        return []
    if val.lower() in ("null", "~", "none"):
        return None
    if val.lower() in ("true",):
        return True
    if val.lower() in ("false",):
        return False
    if val == "[]":
        return []
    try:
        return int(val)
    except ValueError:
        pass
    return _parse_yaml_scalar(val)


def _parse_yaml_scalar(val: str):
    if val.lower() in ("null", "~", "none"):
        return None
    if val.lower() in ("true",):
        return True
    if val.lower() in ("false",):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    # Strip quotes
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]
    return val


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


def generate_cas(adrs: list[dict]) -> str:
    """Generate the CAS.md content from a list of parsed ADRs."""
    accepted = [a for a in adrs if a["status"] == "accepted"]
    accepted.sort(key=lambda a: str(a["id"]))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    lines.append("# Current Architecture Specification (CAS)")
    lines.append("")
    lines.append("<!--")
    lines.append("  AUTO-GENERATED by scripts/generate_cas.py")
    lines.append("  Do NOT edit this file manually. Changes will be overwritten.")
    lines.append(f"  Last generated: {now}")
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
    lines.append(f"*Generated on {now} from {len(accepted)} accepted ADRs.*")
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
