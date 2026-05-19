"""Summary mode utilities for session inspection.

Provides truncation and summary-building functions for the session summary API.
"""

from __future__ import annotations

import json
from typing import Any


def truncate_text(text: str | None, max_words: int = 50) -> str | None:
    """Truncate text to max_words, appending a truncation notice if needed."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + f"... [truncated, {len(words)} words total]"


def truncate_value(value: Any, max_words: int = 50) -> str | None:
    """Truncate any value (str, dict, list) to max_words string representation."""
    if value is None:
        return None
    if isinstance(value, str):
        return truncate_text(value, max_words)
    # For dicts/lists, serialize to JSON first, then truncate
    text = json.dumps(value, default=str, ensure_ascii=False)
    return truncate_text(text, max_words)


def build_session_summary(detail: Any) -> "SessionSummaryView":
    """Build a summary view from a full SessionDetail.

    - Strips all IDs, timestamps, token usage
    - Strips LLM calls entirely
    - Extracts tool calls from LLM calls and lifts to agent_run level
    - Truncates tool arguments/results to 50 words
    - Keeps error messages
    """
    from druppie.domain.session import SessionSummaryView, TimelineEntrySummary
    from druppie.domain.agent_run import AgentRunSummaryView, ToolCallSummary

    summary_timeline = []
    for entry in detail.timeline:
        if entry.type.value == "message" or entry.message is not None:
            summary_timeline.append(
                TimelineEntrySummary(
                    type=entry.type,
                    message=entry.message,
                    agent_run=None,
                )
            )
        elif entry.agent_run is not None:
            ar = entry.agent_run

            # Extract tool calls from llm_calls
            tool_call_summaries = []
            if hasattr(ar, "llm_calls") and ar.llm_calls:
                for llm_call in ar.llm_calls:
                    if hasattr(llm_call, "tool_calls") and llm_call.tool_calls:
                        for tc in llm_call.tool_calls:
                            tool_call_summaries.append(
                                ToolCallSummary(
                                    name=tc.tool_name,
                                    server_name=tc.mcp_server,
                                    status=tc.status.value
                                    if hasattr(tc.status, "value")
                                    else str(tc.status),
                                    arguments=truncate_value(tc.arguments),
                                    result=truncate_value(tc.result),
                                    approval=tc.approval,
                                )
                            )

            summary_ar = AgentRunSummaryView(
                agent_id=ar.agent_id,
                status=ar.status.value
                if hasattr(ar.status, "value")
                else str(ar.status),
                error_message=ar.error_message,
                tool_calls=tool_call_summaries,
            )

            summary_timeline.append(
                TimelineEntrySummary(
                    type=entry.type,
                    message=None,
                    agent_run=summary_ar,
                )
            )
        else:
            summary_timeline.append(
                TimelineEntrySummary(
                    type=entry.type,
                )
            )

    return SessionSummaryView(
        title=detail.title,
        status=detail.status,
        project=detail.project,
        timeline=summary_timeline,
    )
