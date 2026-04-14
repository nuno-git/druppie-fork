"""Layer 1: Result validators for tool call output.

Validators check the quality/correctness of a tool call's result string
after execution. Each validator is a simple function that takes a result
string and returns (passed: bool, message: str).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    validator: str
    passed: bool
    message: str


def validate_result(result: str | None, validators: list[str | dict]) -> list[ValidationResult]:
    """Run a list of validators against a tool call result.

    Validators can be:
    - A string name: "not_empty", "no_error", "json_parseable"
    - A dict with one key: {"contains": "some text"}, {"matches": "regex"}
    """
    results = []
    for v in validators:
        if isinstance(v, str):
            vr = _run_named_validator(v, result)
        elif isinstance(v, dict):
            key = next(iter(v))
            value = v[key]
            vr = _run_parameterized_validator(key, value, result)
        else:
            vr = ValidationResult(str(v), False, f"Unknown validator type: {type(v)}")
        results.append(vr)
    return results


def _run_named_validator(name: str, result: str | None) -> ValidationResult:
    """Run a named validator."""
    if name == "not_empty":
        if not result or not result.strip():
            return ValidationResult("not_empty", False, "Result is empty or whitespace")
        return ValidationResult("not_empty", True, "Result is non-empty")

    elif name == "no_error":
        if result and _looks_like_error(result):
            return ValidationResult("no_error", False, f"Result contains error indicator: {result[:200]}")
        return ValidationResult("no_error", True, "No error indicators found")

    elif name == "json_parseable":
        if not result:
            return ValidationResult("json_parseable", False, "Result is empty")
        try:
            json.loads(result)
            return ValidationResult("json_parseable", True, "Valid JSON")
        except json.JSONDecodeError as e:
            return ValidationResult("json_parseable", False, f"Invalid JSON: {e}")

    else:
        return ValidationResult(name, False, f"Unknown validator: {name}")


def _run_parameterized_validator(name: str, param: str, result: str | None) -> ValidationResult:
    """Run a parameterized validator."""
    if name == "contains":
        if not result:
            return ValidationResult(f"contains:{param}", False, "Result is empty")
        if param in result:
            return ValidationResult(f"contains:{param}", True, f"Result contains '{param}'")
        return ValidationResult(f"contains:{param}", False, f"Result does not contain '{param}'")

    elif name == "matches":
        if not result:
            return ValidationResult(f"matches:{param}", False, "Result is empty")
        try:
            compiled = re.compile(param, re.DOTALL)
        except re.error as e:
            return ValidationResult(f"matches:{param}", False, f"Invalid regex pattern: {e}")
        if compiled.search(result):
            return ValidationResult(f"matches:{param}", True, f"Result matches pattern '{param}'")
        return ValidationResult(f"matches:{param}", False, f"Result does not match pattern '{param}'")

    else:
        return ValidationResult(name, False, f"Unknown parameterized validator: {name}")


_ERROR_PATTERNS = [
    r"\berror\b",
    r"\bfailed\b",
    r"\bexception\b",
    r"\btraceback\b",
    r"\bfailure\b",
]
_ERROR_RE = re.compile("|".join(_ERROR_PATTERNS), re.IGNORECASE)

# Phrases that contain error-like words but indicate success
_FALSE_POSITIVE_PATTERNS = [
    r"\bno\s+errors?\b",
    r"\b0\s+(tests?\s+)?failed\b",
    r"\bwithout\s+errors?\b",
    r"\berror.?free\b",
    r"\bno\s+failures?\b",
    r"\b0\s+failures?\b",
    r"\berror\s*handl",
    r"\bexception\s*handl",
]
_FALSE_POSITIVE_RE = re.compile("|".join(_FALSE_POSITIVE_PATTERNS), re.IGNORECASE)


def _looks_like_error(text: str) -> bool:
    """Check if text looks like an error message.

    Excludes common false positives like "No errors found" or "0 tests failed".
    Only suppresses a false positive if ALL error-pattern matches are covered
    by a success phrase (prevents real errors being masked by unrelated success phrases).
    """
    error_matches = list(_ERROR_RE.finditer(text))
    if not error_matches:
        return False
    # Check each error match — if ANY is not covered by a false-positive phrase, it's a real error
    fp_matches = list(_FALSE_POSITIVE_RE.finditer(text))
    for em in error_matches:
        covered = any(
            fp.start() <= em.start() and em.end() <= fp.end()
            for fp in fp_matches
        )
        if not covered:
            return True
    return False
