"""Message compaction for the agent runtime.

When context pressure exceeds a threshold, the entire conversation body
is sent to the LLM for summarization. The summary replaces all messages
except the header (system + user prompt), giving the agent a clean slate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.types import AgentEvent

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    max_context_tokens: int = 150_000
    summarization_threshold: float = 0.70
    max_input_chars: int = 30_000
    max_output_tokens: int = 1024
    tool_result_max_chars: int = 15_000


@dataclass
class CompactionState:
    calibration_ratio: float = 4.0
    calibration_samples: int = 0


class MessageCompactor:

    def __init__(
        self,
        config: CompactionConfig | None = None,
        summary_llm: Callable | None = None,
    ):
        self.config = config or CompactionConfig()
        self.state = CompactionState()
        self._summary_llm = summary_llm

    def estimate_tokens(self, messages: list[dict]) -> int:
        total = 0
        ratio = self.state.calibration_ratio

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            chars = len(content) if isinstance(content, str) else len(str(content))

            tool_calls = msg.get("tool_calls")
            if role == "assistant" and tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    chars += len(func.get("name", ""))
                    chars += len(func.get("arguments", ""))

            total += int(chars / ratio) + 4

        return total

    def calibrate(self, actual_prompt_tokens: int, messages: list[dict]) -> None:
        if actual_prompt_tokens < 100:
            return

        total_chars = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total_chars += len(content) if isinstance(content, str) else len(str(content))
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    total_chars += len(func.get("name", ""))
                    total_chars += len(func.get("arguments", ""))

        real_ratio = total_chars / actual_prompt_tokens
        real_ratio = max(2.5, min(6.0, real_ratio))

        old = self.state.calibration_ratio
        self.state.calibration_ratio = 0.7 * old + 0.3 * real_ratio
        self.state.calibration_samples += 1

    async def compress(
        self,
        messages: list[dict],
        llm: Callable | None,
        agent: AgentDefinition,
        emitter: EventEmitter | None,
    ) -> list[dict]:
        token_count = self.estimate_tokens(messages)
        max_tokens = self.config.max_context_tokens
        threshold_tokens = int(max_tokens * self.config.summarization_threshold)

        if token_count <= threshold_tokens:
            return messages

        header, body = self._split_header_body(messages)
        if not body:
            return messages

        summarize_llm = self._summary_llm or llm
        if summarize_llm is not None:
            try:
                body_text = self._serialize_body(body)
                llm_summary = await self._summarize_with_llm(
                    body_text, summarize_llm, agent,
                )
                if llm_summary:
                    summary_msg = {
                        "role": "user",
                        "content": (
                            "[CONVERSATION SUMMARY]\n"
                            + llm_summary
                            + "\n[END SUMMARY]"
                        ),
                    }
                    result = header + [summary_msg]
                    tokens_after = self.estimate_tokens(result)

                    if emitter:
                        emitter.emit(AgentEvent.now("context_compressed", {
                            "phase": "summarized",
                            "tokens_before": token_count,
                            "tokens_after": tokens_after,
                            "turns_compressed": len(body),
                            "summary_text": llm_summary,
                        }))
                    return result
            except Exception as exc:
                logger.warning(
                    "context_llm_summary_failed", extra={"error": str(exc)},
                )

        fallback_msg = {
            "role": "user",
            "content": "[CONVERSATION SUMMARY \u2014 older turns dropped due to context limit]",
        }
        result = header + [fallback_msg]
        tokens_after = self.estimate_tokens(result)

        if emitter:
            emitter.emit(AgentEvent.now("context_compressed", {
                "phase": "summarized_fallback",
                "tokens_before": token_count,
                "tokens_after": tokens_after,
                "turns_compressed": len(body),
            }))
        return result

    @staticmethod
    def _split_header_body(messages: list[dict]) -> tuple[list[dict], list[dict]]:
        header = []
        body_start = 0
        for msg in messages:
            if msg.get("role") in ("system", "user"):
                header.append(msg)
                body_start += 1
            else:
                break
        return header, messages[body_start:]

    def _serialize_body(self, body: list[dict]) -> str:
        lines = []
        for msg in body:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            if isinstance(content, str):
                lines.append(f"[{role}] {content}")
            else:
                lines.append(f"[{role}] {json.dumps(content)}")
        return "\n".join(lines)[:self.config.max_input_chars]

    async def _summarize_with_llm(
        self,
        history_text: str,
        llm: Callable,
        agent: AgentDefinition,
    ) -> str:
        response = await llm(
            model=agent.llm_profile,
            messages=[
                {"role": "system", "content": (
                    "Summarize this coding agent conversation history. "
                    "Focus on files read/modified, tests run, errors, and current state. "
                    "Be specific with paths and function names. Max 300 words."
                )},
                {"role": "user", "content": history_text},
            ],
            tools=[],
            temperature=0.0,
            max_tokens=self.config.max_output_tokens,
        )
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    @staticmethod
    def truncate_tool_result(content: str, max_chars: int = 15_000) -> str:
        if len(content) <= max_chars:
            return content
        if len(content) > 50_000:
            head, tail = 3000, 1000
        else:
            head, tail = 5000, 2000
        return (
            content[:head]
            + f"\n\n... [output truncated: {len(content)} chars, "
            f"showing first {head} and last {tail}] ...\n\n"
            + content[-tail:]
        )
