#!/usr/bin/env python3
"""
validate_adr_status.py — Validate ADR frontmatter consistency

Checks every ADR markdown file in docs/adrs/ for:
  - Valid YAML frontmatter with required fields
  - Valid status values
  - Supersession consistency (superseded ADRs must reference existing ADRs)
  - Date format validity
  - ID/filename consistency

Usage:
    python3 scripts/validate_adr_status.py

Exit 0 if all valid, exit 1 with error messages if not.
"""

import glob
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADRS_DIR = REPO_ROOT / "docs" / "adrs"

VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded"}
SKIP_FILES = {"TEMPLATE.md", "CAS.md"}

REQUIRED_FIELDS = {"id", "title", "status", "date", "deciders", "superseded_by", "enforcement"}


def parse_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter between --- delimiters."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kv = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            result[key] = _parse_yaml_value(val)
            continue
        li = re.match(r"^-\s+(.*)", line)
        if li and result:
            last_key = list(result.keys())[-1]
            if isinstance(result[last_key], list):
                result[last_key].append(_parse_yaml_scalar(li.group(1).strip()))
    return result


def _parse_yaml_value(val: str):
    if val == "" or val is None:
        return []
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
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]
    return val


def validate_adr(filepath: str, known_ids: set[str]) -> list[str]:
    """Validate a single ADR file. Returns a list of error messages (empty = valid)."""
    errors = []
    filename = Path(filepath).name

    text = Path(filepath).read_text(encoding="utf-8")
    fm = parse_frontmatter(text)

    if fm is None:
        return [f"{filename}: No valid YAML frontmatter found (missing --- delimiters?)"]

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"{filename}: Missing required field '{field}'")

    # Status validation
    status = fm.get("status")
    if status and status not in VALID_STATUSES:
        errors.append(
            f"{filename}: Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )

    # Supersession consistency
    superseded_by = fm.get("superseded_by")
    if status == "superseded":
        if superseded_by is None:
            errors.append(
                f"{filename}: Status is 'superseded' but 'superseded_by' is null. "
                "Must reference the ADR that supersedes this one."
            )
        elif known_ids and str(superseded_by) not in known_ids:
            errors.append(
                f"{filename}: 'superseded_by' references ADR-{superseded_by}, "
                "but no ADR with that ID exists."
            )
    elif status == "accepted" and superseded_by is not None:
        errors.append(
            f"{filename}: Status is 'accepted' but 'superseded_by' is set to '{superseded_by}'. "
            "Accepted ADRs must have superseded_by: null."
        )

    # Date format
    date_val = fm.get("date")
    if date_val and isinstance(date_val, str):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
            errors.append(f"{filename}: Invalid date format '{date_val}'. Expected YYYY-MM-DD.")
    elif date_val and not isinstance(date_val, str):
        # date might be parsed as int if it looks like a number — still wrong
        errors.append(f"{filename}: Invalid date value '{date_val}'. Expected YYYY-MM-DD string.")

    # ID is 3-digit number
    adr_id = fm.get("id")
    if adr_id is not None:
        id_str = str(adr_id)
        if not re.match(r"^\d{3}$", id_str):
            errors.append(
                f"{filename}: ID '{adr_id}' is not a 3-digit number. Expected format: NNN (e.g. 001)."
            )

        # ID matches filename
        expected_prefix = id_str + "-"
        if not filename.startswith(expected_prefix):
            errors.append(
                f"{filename}: ID '{id_str}' does not match filename prefix. "
                f"Expected filename to start with '{expected_prefix}'."
            )

    return errors


def main():
    all_errors = []

    # Collect all ADR files (exclude TEMPLATE.md and CAS.md)
    pattern = str(ADRS_DIR / "*.md")
    adr_files = [
        f for f in sorted(glob.glob(pattern))
        if Path(f).name not in SKIP_FILES
    ]

    if not adr_files:
        print("ERROR: No ADR files found in docs/adrs/", file=sys.stderr)
        sys.exit(1)

    # First pass: collect all IDs for cross-reference validation
    known_ids = set()
    for filepath in adr_files:
        text = Path(filepath).read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm and "id" in fm:
            known_ids.add(str(fm["id"]))

    # Second pass: validate each file
    for filepath in adr_files:
        errors = validate_adr(filepath, known_ids)
        all_errors.extend(errors)

    if all_errors:
        print("ADR validation FAILED:\n", file=sys.stderr)
        for err in all_errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(all_errors)} error(s) found.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"ADR validation passed: {len(adr_files)} file(s) checked, all valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
