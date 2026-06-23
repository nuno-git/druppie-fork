"""Coding MCP Server - Security Module.

Contains the BLOCKED_COMMAND_PATTERNS used by the bash tool for command safety.
The sandbox orchestrator architecture moved all workspace/container management
directly into tools.py. This module retains the security patterns for reference
and potential reuse.
"""

import re

# =============================================================================
# SECURITY: COMMAND BLOCKLIST
# =============================================================================

BLOCKED_COMMAND_PATTERNS = [
    r"rm\s+(-[rf]+\s+)*\s*/\s*$",
    r"rm\s+(-[rf]+\s+)*\s*/\*",
    r"rm\s+(-[rf]+\s+)+\s*/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bsudo\b",
    r"\bsu\s+-",
    r"\bsu\s+root",
    r"\bchmod\s+777\b",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+.*\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[0-6]",
    r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|network)",
    r":\(\)\s*{\s*:\|\s*:&\s*}\s*;",
    r">\s*/dev/sd[a-z]",
    r">\s*/dev/null\s*2>&1\s*&",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
    r">\s*/etc/sudoers",
    r"\bnc\s+-[elp]",
    r"\bbash\s+-i\s+>&\s+/dev/tcp",
    r"\bcurl\s+.*\|\s*bash",
    r"\bwget\s+.*\|\s*bash",
    r"\bcurl\s+.*\|\s*sh",
    r"\bwget\s+.*\|\s*sh",
]

BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMAND_PATTERNS]
