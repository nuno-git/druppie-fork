#!/usr/bin/env python3
"""Mandatory-docs gate (Check A) — PBI 9744.

Testable Python replica of the bash gate that used to live inline in
``.github/workflows/docs.yml``. The workflow now shells out to this script so
the exempt-detection and code/doc-gate logic can be unit-tested.

Interface (stable — the workflow depends on it):

    is_exempt(labels, pr_body) -> bool
    mandatory_gate(changed_files) -> (ok, reason)
    main() -> int   # reads env LABELS/PR_BODY, changed files from STDIN

Exit 0 when the gate passes (or is exempt/skipped), 1 when code changed
without documentation.
"""

import os
import re
import sys

# ---------------------------------------------------------------------------
# Exempt detection (replicates the 3 bash checks in docs.yml Check A).
# ---------------------------------------------------------------------------

# (b) A *checked* checkbox line mentioning docs-exempt: "- [x] ... docs-exempt".
#     Empty "[ ]" must NOT count. Case-insensitive.
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[xX]\].*docs-exempt", re.IGNORECASE)

# (c) An explicit directive line: "docs-exempt: <non-empty reason>".
_DIRECTIVE_RE = re.compile(r"^\s*docs-exempt:\s*\S", re.IGNORECASE)


def is_exempt(labels: str, pr_body: str) -> bool:
    """Return True if the PR is exempt from the mandatory-docs gate.

    Mirrors the three bash checks:
      (a) an exact ``docs-exempt`` label in the comma/newline-separated
          ``labels`` string;
      (b) a *checked* checkbox line ``- [x] ... docs-exempt`` in ``pr_body``
          (case-insensitive; an unchecked ``- [ ]`` does NOT count);
      (c) a directive line ``docs-exempt: <non-empty reason>`` in ``pr_body``.
    """
    labels = labels or ""
    pr_body = pr_body or ""

    # (a) label — split on both commas and newlines, match exactly.
    for label in re.split(r"[,\n]", labels):
        if label.strip() == "docs-exempt":
            return True

    # (b) checked checkbox / (c) directive — scan line by line.
    for line in pr_body.splitlines():
        if _CHECKBOX_RE.match(line):
            return True
        if _DIRECTIVE_RE.match(line):
            return True

    return False


# ---------------------------------------------------------------------------
# Mandatory-docs gate (code changed => docs must change too).
# ---------------------------------------------------------------------------

# Code paths that require documentation when changed.
_CODE_RE = re.compile(r"^(druppie/|frontend/src/)")

# Doc paths that satisfy the requirement.
_DOC_RE = re.compile(
    r"^(docs/(adrs|prds|research|specs|guides)/)"
)


def mandatory_gate(changed_files: list[str]) -> tuple[bool, str]:
    """Decide whether the set of changed files satisfies the docs gate.

    Returns ``(False, reason)`` if there is a code change but no doc change,
    otherwise ``(True, "OK")``.
    """
    code_changed = any(_CODE_RE.match(f.strip()) for f in changed_files if f.strip())
    doc_changed = any(_DOC_RE.match(f.strip()) for f in changed_files if f.strip())

    if code_changed and not doc_changed:
        return (
            False,
            "code changed without documentation",
        )
    return (True, "OK")


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

_ERROR_MESSAGE = (
    "::error::code changed without documentation. "
    "See docs/guides/documentation-framework.md for how to document your "
    "change, or mark the PR docs-exempt in one of three ways: "
    "(1) add the `docs-exempt` label; "
    "(2) tick a checkbox line `- [x] docs-exempt` in the PR description; "
    "(3) add a directive line `docs-exempt: <reason>` to the PR description."
)


def main() -> int:
    labels = os.environ.get("LABELS", "")
    pr_body = os.environ.get("PR_BODY", "")

    if is_exempt(labels, pr_body):
        print("docs-exempt is set -> mandatory-docs gate skipped.")
        return 0

    changed_files = [line.rstrip("\n") for line in sys.stdin]

    ok, reason = mandatory_gate(changed_files)
    if not ok:
        print(_ERROR_MESSAGE)
        return 1

    print("Mandatory-docs gate OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
