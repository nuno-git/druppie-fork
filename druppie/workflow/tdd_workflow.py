"""
TDD Workflow Handler Module

This module provides standalone TDD workflow logic that can be imported
and used by the main execution loop without modifying existing code.
"""
from typing import Any, Optional
import re


def parse_test_result(result: str) -> dict:
    """Parse tester agent's test result output.

    Looks for:
    - ## TEST RESULT: PASS or FAIL
    - Verdict: **PASS** or **FAIL**
    - Retry count: "Current Attempt: X"
    - Summary stats (total, passed, failed)
    - Coverage percentage

    Args:
        result: String output from tester agent

    Returns:
        Dict with:
        - verdict: "PASS" or "FAIL"
        - retry_count: int (current attempt number)
        - should_retry: bool
        - summary: dict with test stats
        - coverage: float or None
        - feedback: str (if FAIL)
    """
    # Parse verdict from header
    verdict_match = re.search(r'## TEST RESULT:\s*(PASS|FAIL)', result, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"

    # Parse verdict from content (fallback)
    if not verdict_match:
        verdict_match = re.search(r'\*\*(PASS|FAIL)\*\*', result, re.IGNORECASE)
        verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"

    # Parse retry count
    retry_match = re.search(r'Current Attempt:\s*(\d+)', result)
    retry_count = int(retry_match.group(1)) if retry_match else 0

    # Parse summary stats
    total_match = re.search(r'Total:\s*(\d+)', result)
    passed_match = re.search(r'Passed:\s*(\d+)', result)
    failed_match = re.search(r'Failed:\s*(\d+)', result)

    summary = {
        "total": int(total_match.group(1)) if total_match else 0,
        "passed": int(passed_match.group(1)) if passed_match else 0,
        "failed": int(failed_match.group(1)) if failed_match else 0,
    }

    # Parse coverage
    coverage_match = re.search(r'Coverage:\s*([\d.]+)%', result)
    coverage = float(coverage_match.group(1)) if coverage_match else None

    # Extract feedback (if FAIL)
    feedback = ""
    if verdict == "FAIL":
        feedback_section = re.search(
            r'### Feedback for Builder.*?(?=### Retry|$)',
            result,
            re.DOTALL
        )
        if feedback_section:
            feedback = feedback_section.group(0).strip()

    # Determine if should retry
    should_retry = (verdict == "FAIL" and retry_count < 3)  # Default max_retries

    return {
        "verdict": verdict,
        "retry_count": retry_count,
        "should_retry": should_retry,
        "summary": summary,
        "coverage": coverage,
        "feedback": feedback,
    }


def is_validation_step(step_type: str, agent_id: str) -> bool:
    """Check if a workflow step is a tester validation step.

    Args:
        step_type: The type of step (e.g., "agent")
        agent_id: The agent ID for the step

    Returns:
        True if this is a tester validation step
    """
    return step_type == "agent" and agent_id == "tester"


def determine_tdd_next_action(
    verdict: str,
    retry_count: int,
    max_retries: int = 3,
    coverage_threshold: float = 80.0,
    coverage: Optional[float] = None,
) -> dict:
    """Determine next action based on TDD test results.

    Args:
        verdict: "PASS" or "FAIL"
        retry_count: Current retry attempt number
        max_retries: Maximum allowed retries
        coverage_threshold: Minimum acceptable coverage percentage
        coverage: Actual coverage percentage (if available)

    Returns:
        Dict with:
        - action: "continue", "retry", or "fail"
        - reason: str explaining the decision
        - should_increment_retry: bool
    """
    if verdict == "PASS":
        if coverage is not None and coverage < coverage_threshold:
            return {
                "action": "continue",
                "reason": f"Tests pass but coverage ({coverage:.1f}%) below threshold ({coverage_threshold}%)",
                "should_increment_retry": False,
            }
        return {
            "action": "continue",
            "reason": "All tests passed with acceptable coverage",
            "should_increment_retry": False,
        }

    # Verdict is FAIL
    if retry_count < max_retries:
        return {
            "action": "retry",
            "reason": f"Tests failed (attempt {retry_count + 1}/{max_retries})",
            "should_increment_retry": True,
        }
    else:
        return {
            "action": "fail",
            "reason": f"Tests failed after {max_retries} retry attempts",
            "should_increment_retry": False,
        }


def generate_builder_retry_step(
    original_step: dict,
    retry_count: int,
    max_retries: int,
    tester_feedback: str,
) -> dict:
    """Generate a builder retry step based on tester feedback.

    Args:
        original_step: The original builder step definition
        retry_count: Current retry attempt number
        max_retries: Maximum allowed retries
        tester_feedback: Feedback from tester agent

    Returns:
        Dict with retry step definition
    """
    return {
        "type": "agent",
        "agent_id": "builder",
        "mode": "retry",
        "retry_context": {
            "attempt": retry_count + 1,
            "max_attempts": max_retries,
            "tester_feedback": tester_feedback,
        },
        "prompt_template": f"""Previous implementation attempt failed. Fix the issues reported by the tester.

Tester feedback:
{tester_feedback}

Retry context:
- Attempt: {retry_count + 1} of {max_retries}

Fix requirements:
1. Read the specific test failures
2. Make targeted fixes (don't rewrite working code)
3. Address all issues in feedback
4. Re-run tests to verify fixes
5. Commit with message "Fix test failures (attempt {retry_count + 1})"
""",
        "expected_output": "Issues fixed, tests passing",
    }


def validate_tdd_workflow_result(test_result: dict, config: dict) -> tuple[bool, str]:
    """Validate TDD workflow result against thresholds.

    Args:
        test_result: Parsed test result from parse_test_result()
        config: Configuration dict with thresholds

    Returns:
        Tuple of (is_valid, message)
    """
    if test_result["verdict"] != "PASS":
        return False, "Tests did not pass"

    coverage = test_result.get("coverage")
    if coverage is None:
        require_coverage = config.get("require_coverage", True)
        if require_coverage:
            return False, "Coverage report not available but required"
        return True, "Tests passed, coverage not required"

    threshold = config.get("coverage_threshold", 80.0)
    if coverage < threshold:
        return False, f"Coverage {coverage:.1f}% below threshold {threshold}%"

    return True, "Tests passed with acceptable coverage"


# Convenience function for main loop integration
def handle_tdd_workflow_step(
    step: dict,
    agent_output: str,
    workflow_config: dict,
) -> dict:
    """Handle a TDD workflow step and return next action.

    This is the main entry point for the main loop to call.

    Args:
        step: The workflow step that was executed
        agent_output: Output from the agent (tester)
        workflow_config: Workflow configuration dict

    Returns:
        Dict with:
        - next_action: "continue", "retry", or "fail"
        - retry_step: dict (if action is "retry")
        - validation_result: dict with validation details
    """
    parsed = parse_test_result(agent_output)
    next_action_info = determine_tdd_next_action(
        verdict=parsed["verdict"],
        retry_count=parsed["retry_count"],
        max_retries=workflow_config.get("max_retries", 3),
        coverage_threshold=workflow_config.get("coverage_threshold", 80.0),
        coverage=parsed.get("coverage"),
    )

    is_valid, validation_message = validate_tdd_workflow_result(parsed, workflow_config)

    retry_step = None
    if next_action_info["action"] == "retry":
        retry_step = generate_builder_retry_step(
            original_step=step,
            retry_count=parsed["retry_count"],
            max_retries=workflow_config.get("max_retries", 3),
            tester_feedback=parsed.get("feedback", ""),
        )

    return {
        "next_action": next_action_info["action"],
        "reason": next_action_info["reason"],
        "should_increment_retry": next_action_info["should_increment_retry"],
        "retry_step": retry_step,
        "parsed_result": parsed,
        "is_valid": is_valid,
        "validation_message": validation_message,
    }