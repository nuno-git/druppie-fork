#!/usr/bin/env python3
"""
validate_prd_status.py — Validate PRD frontmatter consistency

Checks every PRD markdown file in docs/prds/ for:
  - Valid YAML frontmatter with required fields
  - Valid status values
  - Supersession consistency (superseded PRDs must reference existing PRDs)
  - Date format validity
  - ID/filename consistency
  - Optional JSON Schema validation against docs/prds/prd.schema.json

Usage:
    python3 scripts/validate_prd_status.py

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
PRDS_DIR = REPO_ROOT / "docs" / "prds"
SCHEMA_PATH = PRDS_DIR / "prd.schema.json"

VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded"}
SKIP_FILES = {"TEMPLATE.md"}

REQUIRED_FIELDS = {"id", "title", "status", "date", "author", "superseded_by"}

# --- Optional JSON Schema support -------------------------------------------
try:
    from jsonschema import validate as jsonschema_validate
    from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_JSONSCHEMA = False

_SCHEMA_CACHE: dict | None = None


def _load_schema() -> dict | None:
    """Load the PRD frontmatter JSON Schema (cached).

    Returns the parsed schema dict, or ``None`` if the schema file is missing.
    The schema is created by a separate step; the validator degrades gracefully
    (skips schema validation) when it is not present yet.
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

    Uses :func:`yaml.safe_load` so nested maps and typed scalars are parsed
    correctly — avoiding the pitfalls of a hand-rolled flat parser.

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
    breaks several checks:

    - ``id: 001`` (unquoted) → ``int(1)`` — normalized to ``"001"`` so the
      ``^\\d{3}$`` pattern holds.
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


def validate_prd(filepath: str, known_ids: set[str]) -> list[str]:
    """Validate a single PRD file. Returns a list of error messages (empty = valid)."""
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
                "Must reference the PRD that supersedes this one."
            )
        elif known_ids and str(superseded_by) not in known_ids:
            errors.append(
                f"{filename}: 'superseded_by' references PRD-{superseded_by}, "
                "but no PRD with that ID exists."
            )
    elif status == "accepted" and superseded_by is not None:
        errors.append(
            f"{filename}: Status is 'accepted' but 'superseded_by' is set to '{superseded_by}'. "
            "Accepted PRDs must have superseded_by: null."
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
    prd_id = fm.get("id")
    if prd_id is not None:
        id_str = str(prd_id)
        if not re.match(r"^\d{3}$", id_str):
            errors.append(
                f"{filename}: ID '{prd_id}' is not a 3-digit number. Expected format: NNN (e.g. 001)."
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

    # Collect all PRD files (exclude TEMPLATE.md)
    pattern = str(PRDS_DIR / "*.md")
    prd_files = [f for f in sorted(glob.glob(pattern)) if Path(f).name not in SKIP_FILES]

    if not prd_files:
        # No real PRD files yet (only the template, which is skipped). This is
        # a clean state — nothing to validate, so report success.
        schema_active = HAS_JSONSCHEMA and _load_schema() is not None
        schema_note = " + schema" if schema_active else ""
        print(f"PRD validation passed{schema_note}: 0 file(s) checked, all valid.")
        sys.exit(0)

    # First pass: collect all IDs for cross-reference validation
    known_ids: set[str] = set()
    for filepath in prd_files:
        text = Path(filepath).read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm and "id" in fm:
            known_ids.add(str(fm["id"]))

    # Second pass: validate each file
    for filepath in prd_files:
        errors = validate_prd(filepath, known_ids)
        all_errors.extend(errors)

    if all_errors:
        print("PRD validation FAILED:\n", file=sys.stderr)
        for err in all_errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print(f"\n{len(all_errors)} error(s) found.", file=sys.stderr)
        sys.exit(1)
    else:
        schema_active = HAS_JSONSCHEMA and _load_schema() is not None
        schema_note = " + schema" if schema_active else ""
        print(
            f"PRD validation passed{schema_note}: {len(prd_files)} file(s) checked, all valid."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
