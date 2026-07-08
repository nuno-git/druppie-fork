"""Message history reconstruction from stored LLM calls."""

import json

DISPLAY_ONLY_KEYS = {"user_answer"}


def _strip_display_fields(result):
    """Remove display-only fields from a tool result before feeding to agents.

    Tool results may contain user-language fields (e.g. user_answer)
    that are only for the frontend. Agents must see English only.
    """
    if not result:
        return result
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
        if isinstance(parsed, dict) and DISPLAY_ONLY_KEYS & parsed.keys():
            cleaned = {k: v for k, v in parsed.items() if k not in DISPLAY_ONLY_KEYS}
            return json.dumps(cleaned) if isinstance(result, str) else cleaned
    except (json.JSONDecodeError, TypeError):
        pass
    return result


def reconstruct_from_db(
    llm_calls: list,
    execution_repo,
) -> list[dict]:
    """Reconstruct message history from stored LLM calls.

    Uses the last LLM call's request_messages as the base — it already
    contains any compressed history from previous turns. Only appends
    the assistant response and tool results from that final call.

    Falls back to full replay if the last call has no request_messages.
    """
    if not llm_calls:
        return []

    last_call = llm_calls[-1]

    if last_call.request_messages and len(last_call.request_messages) > 0:
        messages = list(last_call.request_messages)
    else:
        messages = _full_replay(llm_calls)
        return messages

    if last_call.response_tool_calls and len(last_call.response_tool_calls) > 0:
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tc.get("id", f"call_last_{j}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                }
                for j, tc in enumerate(last_call.response_tool_calls)
            ],
        })

        for j, tool_call_db in enumerate(last_call.tool_calls):
            if tool_call_db.result or tool_call_db.error_message:
                tool_call_id = f"call_last_{j}"
                if j < len(last_call.response_tool_calls):
                    tool_call_id = last_call.response_tool_calls[j].get("id", tool_call_id)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_call_db.result or f"Error: {tool_call_db.error_message}",
                })

    elif last_call.response_content:
        messages.append({
            "role": "assistant",
            "content": last_call.response_content,
        })

    return messages


def _full_replay(llm_calls: list) -> list[dict]:
    """Full replay fallback — reconstruct from all LLM calls sequentially."""
    messages = []

    for i, llm_call in enumerate(llm_calls):
        if i == 0 and llm_call.request_messages:
            messages.extend(llm_call.request_messages)

        if llm_call.response_tool_calls and len(llm_call.response_tool_calls) > 0:
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

            for j, tool_call_db in enumerate(llm_call.tool_calls):
                if tool_call_db.result or tool_call_db.error_message:
                    tool_call_id = f"call_{i}_{j}"
                    if j < len(llm_call.response_tool_calls):
                        tool_call_id = llm_call.response_tool_calls[j].get("id", tool_call_id)

                    result_content = _strip_display_fields(tool_call_db.result) or f"Error: {tool_call_db.error_message}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result_content,
                    })

        elif llm_call.response_content:
            messages.append({
                "role": "assistant",
                "content": llm_call.response_content,
            })

    return messages
