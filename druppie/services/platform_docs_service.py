"""Platform documentation service.

Reads the platform's own ``docs/`` directory and returns formal documentation
(ADRs, PRDs, Specs, Research notes, Guides) with parsed frontmatter so the
frontend can render a single filterable documentation portal.

This service is intentionally stateless and filesystem-only — no database or
cache layer is required. The docs/ tree is small (~60 files) and parses in a
few milliseconds, so we re-read on every request.

The docs root is resolved in this priority order:
  1. ``DRUPPIE_DOCS_PATH`` env var (test/dev override)
  2. ``/app/docs`` (inside the Docker container — WORKDIR is /app)
  3. ``<repo_root>/docs`` (local development host)

Inside the container the working directory is ``/app`` and the docs/ tree is
COPY'd into ``/app/docs`` (see Dockerfile) or bind-mounted (dev compose).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
import yaml

from ..domain import PlatformDocEntry

logger = structlog.get_logger()

# --- Configuration ---------------------------------------------------------

# File naming conventions documented in AGENTS.md / docs/guides/documentation-framework.md
DOC_SUBDIRS = {
    "adr": {"dir": "docs/adrs", "ext": ".md", "skip": {"TEMPLATE.md", "CAS.md"}},
    "prd": {"dir": "docs/prds", "ext": ".md", "skip": {"TEMPLATE.md"}},
    "research": {"dir": "docs/research", "ext": ".md", "skip": {"TEMPLATE.md"}},
    "guide": {"dir": "docs/guides", "ext": ".md", "skip": set()},
    "spec": {"dir": "docs/specs", "ext": ".feature", "skip": {"TEMPLATE.feature"}},
}

# Any filename matching one of these patterns is skipped regardless of subdir.
GLOBAL_SKIP_PATTERNS = (
    re.compile(r"^TEMPLATE\."),
    re.compile(r"\.schema\.json$"),
    re.compile(r"^CAS\.md$"),
)

_TYPE_ORDER = {"adr": 0, "prd": 1, "spec": 2, "research": 3, "guide": 4}

# Frontmatter delimiter: a line containing exactly three dashes.
_FM_OPEN = re.compile(r"^---\s*$")


# --- Path resolution -------------------------------------------------------


def _resolve_docs_root() -> Path:
    """Resolve the docs/ directory for the current runtime.

    Order:
      1. ``DRUPPIE_DOCS_PATH`` env var
      2. ``/app/docs`` (Docker container WORKDIR is /app)
      3. ``<cwd>/docs`` (local dev host — repo root is the cwd)
    """
    env_path = os.environ.get("DRUPPIE_DOCS_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_dir():
            return candidate
        logger.warning("platform_docs_env_path_missing", path=env_path)

    container_path = Path("/app/docs")
    if container_path.is_dir():
        return container_path

    cwd_path = Path.cwd() / "docs"
    return cwd_path


def _should_skip(filename: str, subdir_skip: set) -> bool:
    if filename in subdir_skip:
        return True
    return any(pat.match(filename) for pat in GLOBAL_SKIP_PATTERNS)


# --- Frontmatter parsing ---------------------------------------------------


def _split_frontmatter(text: str) -> tuple[Optional[Dict[str, Any]], str]:
    """Split a markdown file into (frontmatter_dict, body).

    Returns (None, text) if there is no leading ``---`` frontmatter block.
    The body is everything after the closing ``---`` delimiter (with the
    leading newline stripped). Frontmatter parse errors are logged and
    treated as "no frontmatter" so one malformed file can't 500 the route.
    """
    if not text.startswith("---"):
        return None, text

    lines = text.splitlines(keepends=True)
    # First line is the opening ---; find the closing --- line.
    close_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if _FM_OPEN.match(lines[i]):
            close_idx = i
            break

    if close_idx is None:
        return None, text

    fm_text = "".join(lines[1:close_idx])
    body = "".join(lines[close_idx + 1 :]).lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            return None, text
        return fm, body
    except yaml.YAMLError as e:
        logger.warning("platform_docs_frontmatter_parse_failed", error=str(e))
        return None, text


def _coerce_str(value: Any) -> Optional[str]:
    """Coerce YAML scalars to a clean string; None/empty → None."""
    if value is None:
        return None
    if isinstance(value, list):
        # Take the first non-empty entry (used for deciders lists).
        for item in value:
            s = _coerce_str(item)
            if s:
                return s
        return None
    s = str(value).strip()
    return s or None


def _coerce_str_list(value: Any) -> Optional[List[str]]:
    """Coerce a YAML value into a list of non-empty strings, or None."""
    if value is None:
        return None
    if isinstance(value, list):
        out = [str(v).strip() for v in value if v is not None and str(v).strip()]
        return out or None
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else None
    s = str(value).strip()
    return [s] if s else None


# --- Per-type parsers ------------------------------------------------------


def _parse_markdown_doc(
    doc_type: str, path: Path
) -> Optional[PlatformDocEntry]:
    """Parse an ADR/PRD/Research markdown file with YAML frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("platform_docs_read_failed", file=str(path), error=str(e))
        return None

    fm, body = _split_frontmatter(raw)

    if fm is None:
        # No frontmatter: best-effort fallback. Use first H1 as title,
        # filename stem as id (only meaningful for guides).
        title = _first_h1(body) or path.stem
        return PlatformDocEntry(
            type=doc_type,
            id=None,
            title=title,
            status=None,
            date=None,
            author_or_deciders=None,
            linked_adrs=None,
            linked_prd=None,
            linked_research=None,
            linked_specs=None,
            filename=path.name,
            content=raw,
        )

    title = _coerce_str(fm.get("title")) or _first_h1(body) or path.stem
    doc_id = _coerce_str(fm.get("id"))

    # author (PRD/Research) vs deciders[0] (ADR)
    if doc_type == "adr":
        author_or_deciders = _coerce_str(fm.get("deciders"))
    else:
        author_or_deciders = _coerce_str(fm.get("author"))

    return PlatformDocEntry(
        type=doc_type,
        id=doc_id,
        title=title,
        status=_coerce_str(fm.get("status")),
        date=_coerce_str(fm.get("date")),
        author_or_deciders=author_or_deciders,
        linked_adrs=_coerce_str_list(fm.get("linked_adrs")) if doc_type != "adr" else None,
        linked_prd=_coerce_str(fm.get("linked_prd")),
        linked_research=_coerce_str(fm.get("linked_research")),
        linked_specs=_coerce_str_list(fm.get("linked_specs")),
        filename=path.name,
        content=raw,
    )


def _parse_guide(path: Path) -> Optional[PlatformDocEntry]:
    """Parse a guide markdown file. Guides have no frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("platform_docs_read_failed", file=str(path), error=str(e))
        return None

    title = _first_h1(raw) or path.stem
    return PlatformDocEntry(
        type="guide",
        id=None,
        title=title,
        status=None,
        date=None,
        author_or_deciders=None,
        linked_adrs=None,
        linked_prd=None,
        linked_research=None,
        linked_specs=None,
        filename=path.name,
        content=raw,
    )


# Matches:  # @status active   |   # @adr 007-strict-layered-architecture.md
_SPEC_COMMENT_TAG = re.compile(r"^#\s*@(\w+)\s+(.*)$")
# Matches:  @prd docs/prds/006-...   |   @adr docs/adrs/006-...   (Cucumber-style tags)
_SPEC_CUCUMBER_TAG = re.compile(r"^@(\w+)\s+(.+)$")
# Matches:  Feature: <title>
_SPEC_FEATURE_LINE = re.compile(r"^Feature:\s*(.+)$")


def _parse_spec(path: Path) -> Optional[PlatformDocEntry]:
    """Parse a Gherkin ``.feature`` spec file.

    Specs use two tag conventions (often mixed in the same file):
      1. Hash comments at the top:  ``# @status active``, ``# @adr <file>``,
         ``# @prd <file>``, ``# @superseded_by <file|empty>``
      2. Cucumber tags on their own line:  ``@prd docs/prds/006-...``

    There is no YAML frontmatter. The title comes from ``Feature: <title>``.
    The id is derived from the filename stem (e.g. ``006-translation-subsystem``).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("platform_docs_read_failed", file=str(path), error=str(e))
        return None

    tags: Dict[str, str] = {}
    title: Optional[str] = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Feature: <title>  — title line; once we hit it we stop scanning tags.
        m = _SPEC_FEATURE_LINE.match(stripped)
        if m:
            title = m.group(1).strip()
            break

        # # @tag value
        m = _SPEC_COMMENT_TAG.match(stripped)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            if value:
                tags.setdefault(key, value)
            continue

        # @tag value  (Cucumber-style)
        m = _SPEC_CUCUMBER_TAG.match(stripped)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            if value:
                tags.setdefault(key, value)
            continue

    # Map spec status → canonical status names used elsewhere (accepted/implemented etc.)
    raw_status = tags.get("status")
    status = _normalize_spec_status(raw_status)

    # Linked PRD / ADR paths
    linked_prd = tags.get("prd")
    linked_adr = tags.get("adr")
    linked_adrs = [linked_adr] if linked_adr else None

    # Derive id from filename: "006-translation-subsystem" → "006"
    doc_id = _id_from_filename(path.name)

    if title is None:
        title = path.stem

    return PlatformDocEntry(
        type="spec",
        id=doc_id,
        title=title,
        status=status,
        date=None,
        author_or_deciders=None,
        linked_adrs=linked_adrs,
        linked_prd=linked_prd,
        linked_research=None,
        linked_specs=None,
        filename=path.name,
        content=raw,
    )


def _normalize_spec_status(raw: Optional[str]) -> Optional[str]:
    """Normalize a spec's status tag to the canonical names used across docs.

    Spec files historically use ``active`` / ``draft`` / ``superseded`` while
    ADRs/PRDs use ``accepted`` / ``implemented`` / ``proposed``. We map the
    spec terms into the ADR/PRD vocabulary so the frontend status filter
    shows consistent buckets.

    Specs without an explicit ``# @status`` tag default to ``accepted``
    (the spec is in effect) — historically the most common state for older
    spec files written before the tag convention was introduced.
    """
    if not raw:
        return "accepted"
    s = raw.strip().lower()
    if s in ("active", "accepted"):
        return "accepted"
    if s in ("implemented", "complete", "approved"):
        return "implemented"
    if s in ("draft", "proposed"):
        return "proposed"
    if s in ("superseded", "deprecated"):
        return "superseded"
    return s


def _id_from_filename(filename: str) -> Optional[str]:
    """Extract the numeric id from a filename like ``006-translation-subsystem.feature``.

    Returns ``"006"`` for that example. Returns ``None`` if there's no leading number
    (e.g. ``TEMPLATE.feature``, free-form guide names).
    """
    m = re.match(r"^(\d+)", filename)
    return m.group(1) if m else None


def _first_h1(body: str) -> Optional[str]:
    """Return the text of the first ``# <title>`` heading in body, or None."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    return None


# --- Public API ------------------------------------------------------------


def load_platform_docs(docs_root: Optional[Path] = None) -> List[PlatformDocEntry]:
    """Read every formal doc under ``docs_root`` and return a flat sorted list.

    Sorted by (type, numeric id, filename) so output is deterministic and
    grouped: ADRs first, then PRDs, Specs, Research, Guides.
    """
    root = docs_root if docs_root is not None else _resolve_docs_root()

    if not root.is_dir():
        logger.warning("platform_docs_root_missing", root=str(root))
        return []

    entries: List[PlatformDocEntry] = []

    for doc_type, cfg in DOC_SUBDIRS.items():
        subdir = root / cfg["dir"].split("/", 1)[-1]
        if not subdir.is_dir():
            logger.debug("platform_docs_subdir_missing", type=doc_type, dir=str(subdir))
            continue

        for path in sorted(subdir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() != cfg["ext"]:
                continue
            if _should_skip(path.name, cfg["skip"]):
                continue

            if doc_type == "spec":
                entry = _parse_spec(path)
            elif doc_type == "guide":
                entry = _parse_guide(path)
            else:
                entry = _parse_markdown_doc(doc_type, path)

            if entry is not None:
                entries.append(entry)

    entries.sort(key=_sort_key)
    return entries


def _sort_key(entry: PlatformDocEntry) -> tuple:
    type_rank = _TYPE_ORDER.get(entry.type, 99)
    # Numeric id first (None sorts after numbered docs), then string id, then filename.
    try:
        id_num = (0, int(entry.id)) if entry.id and entry.id.isdigit() else (1, 0)
    except (TypeError, ValueError):
        id_num = (1, 0)
    return (type_rank, id_num[0], id_num[1], entry.id or "", entry.filename)


class PlatformDocsService:
    """Stateless filesystem-backed service for platform formal docs.

    Wrapped in a class so it slots into the existing DI pattern used by
    ``druppie/api/deps.py``. The class is cheap to instantiate (no I/O on
    construction); the filesystem is read on each ``list()`` call.
    """

    def __init__(self, docs_root: Optional[Path] = None) -> None:
        # Allow injection (tests, env overrides) but default to runtime resolution.
        self._docs_root = docs_root

    def list(self) -> List[PlatformDocEntry]:
        return load_platform_docs(self._docs_root)
