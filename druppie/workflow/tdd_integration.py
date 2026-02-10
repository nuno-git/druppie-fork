"""
TDD Integration Module

This module provides integration points for TDD workflows into the main execution loop.
It can be imported and used without modifying existing code.
"""

from typing import Optional, Dict, Any
import structlog
from uuid import UUID

from .tdd_workflow import (
    parse_test_result,
    is_validation_step,
    determine_tdd_next_action,
    generate_builder_retry_step,
    validate_tdd_workflow_result,
    handle_tdd_workflow_step,
)
from ..config.tdd_config import get_tdd_settings, is_tdd_enabled

logger = structlog.get_logger()


class TDDIntegration:
    """TDD integration for main execution loop."""
    
    def __init__(self):
        self.settings = get_tdd_settings()
    
    def should_process_tdd(self, agent_id: str, step_type: str = "agent") -> bool:
        """Check if TDD processing should be applied.
        
        Args:
            agent_id: The agent ID (e.g., "tester", "builder")
            step_type: The step type (e.g., "agent", "tool")
            
        Returns:
            True if TDD processing should be applied
        """
        if not is_tdd_enabled():
            return False
        
        # Check if this is a tester validation step
        return is_validation_step(step_type, agent_id)
    
    def process_agent_output(
        self,
        agent_id: str,
        agent_output: str,
        step_data: Optional[Dict[str, Any]] = None,
        session_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Process agent output for TDD workflows.
        
        Args:
            agent_id: The agent ID that produced the output
            agent_output: The output from the agent
            step_data: Optional step data for context
            session_id: Optional session ID for logging
            
        Returns:
            Dict with TDD processing results
        """
        if not self.should_process_tdd(agent_id):
            return {
                "processed": False,
                "reason": "Not a TDD validation step",
            }
        
        logger.info(
            "tdd_processing_started",
            agent_id=agent_id,
            session_id=str(session_id) if session_id else None,
        )
        
        # Use the workflow configuration from settings
        workflow_config = {
            "max_retries": self.settings.retry.max_retries,
            "coverage_threshold": self.settings.coverage.default_threshold,
            "require_coverage": self.settings.coverage.require_coverage,
        }
        
        # Process the TDD workflow step
        step = step_data or {"type": "agent", "agent_id": agent_id}
        result = handle_tdd_workflow_step(step, agent_output, workflow_config)
        
        logger.info(
            "tdd_processing_completed",
            agent_id=agent_id,
            verdict=result["parsed_result"]["verdict"],
            next_action=result["next_action"],
            session_id=str(session_id) if session_id else None,
        )
        
        return {
            "processed": True,
            "tdd_result": result,
            "should_retry": result["next_action"] == "retry",
            "retry_step": result.get("retry_step"),
            "verdict": result["parsed_result"]["verdict"],
        }
    
    def create_test_result_event(
        self,
        parsed_result: Dict[str, Any],
        agent_run_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Create a test result event for the timeline.
        
        Args:
            parsed_result: Parsed test result from parse_test_result()
            agent_run_id: Optional agent run ID
            session_id: Optional session ID
            
        Returns:
            Dict with event data for the timeline
        """
        verdict = parsed_result.get("verdict", "UNKNOWN")
        
        event_data = {
            "event_type": "test_result",
            "title": f"Test Result: {verdict}",
            "status": "success" if verdict == "PASS" else "error",
            "data": {
                **parsed_result,
                "agent_run_id": str(agent_run_id) if agent_run_id else None,
                "session_id": str(session_id) if session_id else None,
            },
        }
        
        # Add framework if available
        if "framework" in parsed_result:
            event_data["data"]["framework"] = parsed_result["framework"]
        
        return event_data
    
    def get_retry_configuration(self) -> Dict[str, Any]:
        """Get TDD retry configuration.
        
        Returns:
            Dict with retry configuration
        """
        return {
            "max_retries": self.settings.retry.max_retries,
            "initial_delay": self.settings.retry.initial_delay,
            "max_delay": self.settings.retry.max_delay,
            "backoff_factor": self.settings.retry.backoff_factor,
            "retry_on_test_failure": self.settings.retry.retry_on_test_failure,
            "retry_on_low_coverage": self.settings.retry.retry_on_low_coverage,
            "retry_on_timeout": self.settings.retry.retry_on_timeout,
        }
    
    def validate_coverage(
        self,
        coverage: float,
        project_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate coverage against thresholds.
        
        Args:
            coverage: Coverage percentage
            project_type: Optional project type for specific threshold
            
        Returns:
            Dict with validation results
        """
        from ..config.tdd_config import ProjectType
        
        # Get threshold for project type
        if project_type:
            try:
                pt = ProjectType(project_type.lower())
                threshold = self.settings.get_coverage_threshold(pt)
            except ValueError:
                threshold = self.settings.coverage.default_threshold
        else:
            threshold = self.settings.coverage.default_threshold
        
        is_acceptable = coverage >= threshold
        meets_minimum = coverage >= 50.0  # Absolute minimum
        
        return {
            "coverage": coverage,
            "threshold": threshold,
            "is_acceptable": is_acceptable,
            "meets_minimum": meets_minimum,
            "message": f"Coverage {coverage:.1f}% {'meets' if is_acceptable else 'below'} threshold of {threshold}%",
        }


# Global instance for easy import
tdd_integration = TDDIntegration()


# Convenience functions for direct import
def process_tdd_output(
    agent_id: str,
    agent_output: str,
    step_data: Optional[Dict[str, Any]] = None,
    session_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Process TDD output (convenience function).
    
    Args:
        agent_id: The agent ID
        agent_output: Agent output string
        step_data: Optional step data
        session_id: Optional session ID
        
    Returns:
        Dict with processing results
    """
    return tdd_integration.process_agent_output(
        agent_id, agent_output, step_data, session_id
    )


def create_test_event(
    parsed_result: Dict[str, Any],
    agent_run_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Create test event (convenience function).
    
    Args:
        parsed_result: Parsed test result
        agent_run_id: Optional agent run ID
        session_id: Optional session ID
        
    Returns:
        Dict with event data
    """
    return tdd_integration.create_test_result_event(
        parsed_result, agent_run_id, session_id
    )


def get_tdd_retry_config() -> Dict[str, Any]:
    """Get TDD retry configuration (convenience function).
    
    Returns:
        Dict with retry configuration
    """
    return tdd_integration.get_retry_configuration()


__all__ = [
    "TDDIntegration",
    "tdd_integration",
    "process_tdd_output",
    "create_test_event",
    "get_tdd_retry_config",
]