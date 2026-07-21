"""Temporary throwaway probe (docs-gate-probe2).

This module exists solely to demonstrate that the mandatory-docs CI gate
can be skipped via a `docs-exempt:` directive in the PR description
(not via a label). It is intended to be deleted together with its PR.
"""


def probe() -> str:
    """Return a marker string identifying this throwaway probe."""
    return "docs-gate-probe2"
