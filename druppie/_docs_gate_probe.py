"""TEMPORARY probe — demonstrates that the docs mandatory-gate flags a code
change that ships without documentation (PBI 9744). This PR is a test and
will be closed; the file is throwaway.
"""


def _probe() -> str:
    return "docs-gate-probe"
