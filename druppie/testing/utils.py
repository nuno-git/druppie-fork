"""Shared utilities for the testing framework."""
from __future__ import annotations

import json
import logging
import subprocess
import time

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


def call_judge_llm(
    prompt: str,
    model: str,
    provider: str,
    system_message: str = "You are an evaluation judge. Respond ONLY with valid JSON.",
    max_retries: int = 5,
) -> tuple[str, int, int]:
    """Call a judge LLM with retry on rate-limit.

    Returns:
        (response_text, duration_ms, tokens_used)

    Raises:
        Exception: when all retries are exhausted or a non-rate-limit error occurs.
    """
    from druppie.llm.litellm_provider import ChatLiteLLM

    llm = ChatLiteLLM(provider=provider, model=model, temperature=0.0)
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": prompt},
    ]

    for attempt in range(max_retries):
        try:
            start = time.time()
            response = llm.chat(messages=messages)
            duration_ms = int((time.time() - start) * 1000)
            tokens = response.total_tokens or 0
            return response.content, duration_ms, tokens
        except Exception as e:
            if "rate" in str(e).lower() and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("Judge rate limited, retrying in %ds (attempt %d)", wait, attempt + 1)
                time.sleep(wait)
            else:
                raise

    raise RuntimeError("Judge call failed after retries")
