#!/usr/bin/env python3
"""
validate_adr_status.py — Validate ADR frontmatter consistency

Checks every ADR markdown file in docs/adrs/ for:
  - Valid YAML frontmatter with required fields
  - Valid status values
  - Supersession consistency (superseded ADRs must reference existing ADRs)
  - Date format validity
  - ID/filename consistency
  - Optional JSON Schema validation against docs/adrs/adr.schema.json

Usage:
    python3 scripts/validate_adr_status.py

Exit 0 if all valid, exit 1 with error messages if not.
"""

import glob
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ADRS_DIR = REPO_ROOT / "docs" / "adrs"
SCHEMA_PATH = ADRS_DIR / "adr.schema.json"

VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded"}
SKIP_FILES = {"TEMPLATE.md", "CAS.md"}

REQUIRED_FIELDS = {"id", "title", "status", "date", "deciders", "superseded_by", "enforcement"}

# --- Optional JSON Schema support -------------------------------------------
try:
    from jsonschema import validate as jsonschema_validate
    from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_JSONSCHEMA = False

_SCHEMA_CACHE: dict | None = None


def _load_schema() -> dict | None:
    """Load the ADR frontmatter JSON Schema (cached).

    Returns the parsed schema dict, or ``None`` if the schema file is missing.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    if not SCHEMA_PATH.exists():
        return None
    _SCHEMA_CACHE = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


# --- Frontmatter parsing ----------------------------------------------------


def parse_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter between ``---`` delimiters.

    Uses :func:`yaml.safe_load` so nested maps (e.g. ``enforcement:``) and
    typed scalars are parsed correctly — replacing the previous hand-rolled
    flat parser which collapsed nested maps.

    Returns ``None`` when no ``---`` delimiters are present, or a (possibly
    empty) dict when the delimiters exist but the content is empty/invalid.
    """
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    parsed = yaml.safe_load(parts[1])
    if isinstance(parsed, dict):
        return _normalize_frontmatter(parsed)
    return {}


def _normalize_frontmatter(fm: dict) -> dict:
    """Normalize PyYAML-parsed values to the types the validator expects.

    PyYAML parses unquoted YAML scalars into native Python types, which
    breaks several existing checks:

    - ``id: 001`` (unquoted) → ``int(1)`` — normalized to ``"001"`` so the
      ``^\\d{3}$`` pattern holds.  This is the ``id: 001`` parsing bug.
    - ``date: 2026-06-09`` → ``datetime.date`` — normalized to an ISO string
      so the ``^\\d{4}-\\d{2}-\\d{2}$`` check passes.
    - ``superseded_by: 005`` (unquoted) → ``int(5)`` — normalized to ``"005"``
      so cross-reference lookups against ``known_ids`` succeed.

    Quoted values (``id: "001"``) are already strings and pass through
    unchanged.
    """
    raw_id = fm.get("id")
    if isinstance(raw_id, int):
        fm["id"] = str(raw_id).zfill(3)
    elif raw_id is not None:
        fm["id"] = str(raw_id)

    raw_date = fm.get("date")
    if isinstance(raw_date, (date, datetime)):
        fm["date"] = raw_date.isoformat()
    elif raw_date is not None:
        fm["date"] = str(raw_date)

    raw_sbid = fm.get("superseded_by")
    if isinstance(raw_sbid, int):
        fm["superseded_by"] = str(raw_sbid).zfill(3)
    elif raw_sbid is not None:
        fm["superseded_by"] = str(raw_sbid)

    return fm


# --- Validation -------------------------------------------------------------


def validate_adr(filepath: str, known_ids: set[str]) -> list[str]:
    """Validate a single ADR file. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []
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

    # JSON Schema validation (optional — skipped gracefully if jsonschema
    # is not installed or the schema file is missing).
    schema = _load_schema()
    if schema and HAS_JSONSCHEMA:
        try:
            jsonschema_validate(instance=fm, schema=schema)
        except JSONSchemaValidationError as exc:
            field_path = ".".join(str(p) for p in exc.absolute_path) or "(root)"
            errors.append(
                f"{filename}: Schema validation failed for '{field_path}': {exc.message}"
            )

    return errors


def main():
    all_errors: list[str] = []

    # Collect all ADR files (exclude TEMPLATE.md and CAS.md)
    pattern = str(ADRS_DIR / "*.md")
    adr_files = [f for f in sorted(glob.glob(pattern)) if Path(f).name not in SKIP_FILES]

    if not adr_files:
        print("ERROR: No ADR files found in docs/adrs/", file=sys.stderr)
        sys.exit(1)

    # First pass: collect all IDs for cross-reference validation
    known_ids: set[str] = set()
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
        schema_active = HAS_JSONSCHEMA and _load_schema() is not None
        schema_note = " + schema" if schema_active else ""
        print(
            f"ADR validation passed{schema_note}: {len(adr_files)} file(s) checked, all valid."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
