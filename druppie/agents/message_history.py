"""Message history reconstruction from stored LLM calls."""

import json


def reconstruct_from_db(
    llm_calls: list,
    execution_repo,
) -> list[dict]:
    """Reconstruct message history from stored LLM calls.

    Walks the DB records and rebuilds the full messages list so
    the agent loop can resume from where it left off.

    For each LLM call:
    1. Add the request_messages (first call has system + user)
    2. Add the assistant response (with tool_calls if any)
    3. Add tool results for each tool call

    Args:
        llm_calls: Ordered list of LLM call DB records
        execution_repo: ExecutionRepository (used for tool call lookups)

    Returns:
        Reconstructed messages list ready for next LLM call
    """
    messages = []

    for i, llm_call in enumerate(llm_calls):
        # For first LLM call, use the full request_messages (system + user)
        if i == 0 and llm_call.request_messages:
            messages.extend(llm_call.request_messages)
        elif llm_call.request_messages:
            # For subsequent calls, skip system/user (already added)
            pass

        # Add assistant response with tool calls
        # Check for non-empty list (empty list [] is falsy in Python)
        if llm_call.response_tool_calls and len(llm_call.response_tool_calls) > 0:
            # Assistant made tool calls
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc.get("id", f"call_{i}_{j}"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name"),
                            "arguments": json.dumps(tc.get("args", {})),
                        },
                    }
                    for j, tc in enumerate(llm_call.response_tool_calls)
                ],
            })

            # Add tool results from the database
            for j, tool_call_db in enumerate(llm_call.tool_calls):
                if tool_call_db.result or tool_call_db.error_message:
                    tool_call_id = f"call_{i}_{j}"  # Default
                    if j < len(llm_call.response_tool_calls):
                        tool_call_id = llm_call.response_tool_calls[j].get("id", tool_call_id)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_call_db.result or f"Error: {tool_call_db.error_message}",
                    })

        elif llm_call.response_content:
            # Assistant gave text response (no tool calls)
            messages.append({
                "role": "assistant",
                "content": llm_call.response_content,
            })

    return messages
