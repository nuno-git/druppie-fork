"""Shared utilities for the testing framework."""
from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def git_info() -> tuple[str | None, str | None]:
    """Get current git commit hash and branch name.

    Returns:
        Tuple of (commit_hash, branch_name), both None if git is unavailable.
    """
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None


def parse_json_from_llm(response_text: str) -> dict | None:
    """Parse JSON from an LLM response, handling markdown code blocks.

    Strips leading/trailing markdown code fences (```json ... ```) and
    handles leading whitespace before the fence.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    text = response_text.strip()
    if text.startswith("```"):
        # Remove opening fence line (```json, ```, etc.)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        # Remove closing fence
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text.strip())
        if isinstance(data, dict):
            return data
        logger.warning("LLM response is not a JSON object: %s", response_text[:200])
        return None
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse LLM response as JSON: %s", response_text[:200])
        return None
