"""Mermaid syntax validator for markdown documents.

Validates Mermaid code blocks in markdown content against common syntax errors
that LLMs frequently produce. Returns actionable error messages so the LLM
can fix and retry.
"""

import re
from dataclasses import dataclass


@dataclass
class MermaidError:
    line_number: int  # line number in the markdown document (1-based)
    line_content: str  # the offending line
    rule: str  # rule ID (e.g. "no-nested-delimiters")
    message: str  # fix instruction for the LLM


# Smart/curly quotes and their ASCII replacements
_SMART_QUOTES = {
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u00ab": '"',  # left-pointing double angle quotation mark
    "\u00bb": '"',  # right-pointing double angle quotation mark
}

# Unicode characters that should not appear in Mermaid
_BAD_UNICODE = {
    "\u2014": "--",  # em dash
    "\u2013": "-",  # en dash
    "\u2192": "-->",  # rightwards arrow
    "\u2190": "<--",  # leftwards arrow
    "\u21d2": "==>",  # rightwards double arrow
    "\u2026": "...",  # horizontal ellipsis
}


def _find_mermaid_blocks(markdown: str) -> list[tuple[int, int]]:
    """Find all Mermaid code blocks in markdown.

    Returns list of (start_line, end_line) tuples (1-based, inclusive).
    start_line is the line AFTER the opening fence, end_line is the line
    BEFORE the closing fence.
    """
    blocks = []
    lines = markdown.split("\n")
    in_block = False
    block_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_block and re.match(r"^```mermaid\s*$", stripped, re.IGNORECASE):
            in_block = True
            block_start = i + 1  # next line (0-based)
        elif in_block and stripped == "```":
            # block_start and i-1 are the content lines (0-based)
            if i > block_start:
                blocks.append((block_start + 1, i))  # convert to 1-based
            in_block = False

    return blocks


def _check_backslash_quotes(line: str, line_number: int) -> MermaidError | None:
    """Detect escaped quotes like \\\" in Mermaid."""
    if r'\"' in line:
        return MermaidError(
            line_number=line_number,
            line_content=line,
            rule="no-backslash-quotes",
            message=(
                f'Found \\" (backslash-escaped quote) which is invalid in Mermaid. '
                f"Mermaid uses plain double quotes. "
                f'Fix: remove the backslashes, use plain " instead of \\".'
            ),
        )
    return None


def _check_nested_delimiters(line: str, line_number: int) -> MermaidError | None:
    """Detect nested delimiter patterns that are invalid in Mermaid."""
    patterns = [
        (r'\[\(\(', '[((', 'The database shape is [("Label")] with one ( not two. Fix: replace [(( with [('),
        (r'\)\)\]', '))]', 'The database shape is [("Label")] with one ) not two. Fix: replace ))] with )]'),
        (r'\(\[\(', '([(', 'This nested delimiter combination is invalid. Use a single delimiter pair.'),
        (r'\(\[\[', '([[', 'This nested delimiter combination is invalid. Use ["Label"] for a rectangle or [("Label")] for a database.'),
    ]
    for pattern, found_text, fix_hint in patterns:
        match = re.search(pattern, line)
        if match:
            return MermaidError(
                line_number=line_number,
                line_content=line,
                rule="no-nested-delimiters",
                message=f"Found {found_text} which is invalid in Mermaid. {fix_hint}",
            )
    return None


def _check_single_dash_arrow(line: str, line_number: int) -> MermaidError | None:
    """Detect -> instead of --> in flowcharts."""
    # Match -> that is NOT part of -->, ==> , ~-> , -.-> or ->| or ->>
    if re.search(r'(?<![-.=~])->\s*(?![->|])', line):
        return MermaidError(
            line_number=line_number,
            line_content=line,
            rule="double-dash-arrows",
            message=(
                "Found -> which is not a valid Mermaid arrow. "
                "Use --> for a solid arrow or -.-> for a dotted arrow. "
                "Fix: replace -> with -->."
            ),
        )
    return None


def _check_reserved_end(line: str, line_number: int) -> MermaidError | None:
    """Detect 'end' used as a node ID."""
    if re.match(r'^\s*end\s*[\[\(\{]', line):
        return MermaidError(
            line_number=line_number,
            line_content=line,
            rule="reserved-end",
            message=(
                'Found "end" used as a node ID, but "end" is a reserved keyword in Mermaid. '
                "Fix: rename the node to something else, e.g. finish, done, or end_node."
            ),
        )
    return None


def _check_smart_quotes(line: str, line_number: int) -> MermaidError | None:
    """Detect smart/curly quotes."""
    for char, replacement in _SMART_QUOTES.items():
        if char in line:
            return MermaidError(
                line_number=line_number,
                line_content=line,
                rule="ascii-quotes-only",
                message=(
                    f"Found smart/curly quote character (U+{ord(char):04X}) which Mermaid cannot parse. "
                    f"Fix: replace all smart quotes with plain ASCII quotes ({replacement})."
                ),
            )
    return None


def _check_unicode_chars(line: str, line_number: int) -> MermaidError | None:
    """Detect em dashes, unicode arrows, and other problematic unicode."""
    for char, replacement in _BAD_UNICODE.items():
        if char in line:
            return MermaidError(
                line_number=line_number,
                line_content=line,
                rule="ascii-only",
                message=(
                    f"Found unicode character (U+{ord(char):04X}) which Mermaid cannot parse. "
                    f"Fix: replace with ASCII equivalent: {replacement}"
                ),
            )
    return None


# All checks to run on each line
_LINE_CHECKS = [
    _check_backslash_quotes,
    _check_nested_delimiters,
    _check_single_dash_arrow,
    _check_reserved_end,
    _check_smart_quotes,
    _check_unicode_chars,
]


def validate_mermaid_in_markdown(markdown: str) -> list[MermaidError]:
    """Validate all Mermaid code blocks in a markdown document.

    Args:
        markdown: Full markdown document content.

    Returns:
        List of MermaidError objects. Empty list means all Mermaid is valid.
    """
    errors: list[MermaidError] = []
    lines = markdown.split("\n")
    blocks = _find_mermaid_blocks(markdown)

    for block_start, block_end in blocks:
        for line_num in range(block_start, block_end + 1):
            line = lines[line_num - 1]  # convert 1-based to 0-based index
            for check in _LINE_CHECKS:
                error = check(line, line_num)
                if error:
                    errors.append(error)

    return errors
